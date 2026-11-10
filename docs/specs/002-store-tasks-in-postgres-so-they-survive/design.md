# Design — 002 Store tasks in Postgres so they survive restarts and every instance sees the same list

## Decisions

- **A Postgres store goes behind the existing `get_task_store` dependency; the routes keep their shape.** `tasks/pg_store.py` adds `PostgresTaskStore`, which has the same two methods as the in-memory `TaskStore` (`create`, `list_all`). A `TaskRepository` Protocol in `tasks/store.py` names that interface. The in-memory `TaskStore` stays unchanged and is now only a unit-test double. The spec-001 tests still swap it in through `app.dependency_overrides[get_task_store]` (spec notes).
- **One store per app instance, built by an app factory.** `main.create_app()` builds a fresh FastAPI app and puts `PostgresTaskStore.from_env()` on `app.state.task_store`. `get_task_store(request)` returns `request.app.state.task_store`. The module-level `app = create_app()` stays the uvicorn entry point (Dockerfile unchanged). The factory is the acceptance tests' hook. "Stopped and started again" (AC-002.1) is one app's lifespan ending and a new `create_app()` starting. "Two instances" (AC-002.3) is two apps, each with its own pool, on the same database.
- **psycopg 3 with a small `psycopg_pool.ConnectionPool`, created and opened lazily on the first task request.** Nothing connects at import or startup. The service therefore starts, and `/health` and `/ready` answer 200, while the database is down, so there is no crash loop (AC-002.4). The pool also bounds how long a request waits for a connection (2 s), whatever the background connect is doing (refused port, unresolvable host, black-holed host). Pool settings, and the reason for each:

  | Setting | Value | Why |
  |---|---|---|
  | `conninfo` | `DATABASE_URL` as given (libpq URI) | contract |
  | `min_size` / `max_size` | 1 / 5 | small; one warm connection per replica |
  | `timeout` | 2.0 | pool wait 2 s → `PoolTimeout` → 503 (Timeouts table) |
  | `reconnect_timeout` | 2.0 | a failed background connect gives up after about 2 s instead of backing off for up to 5 minutes, so the first request after the database is back gets a fresh attempt (AC-002.5) |
  | `check` | `ConnectionPool.check_connection` | a connection that died while the database was down is dropped when it is checked out, not handed to a request, so the first request after recovery does not 503 (AC-002.5) |
  | `open` | `False`, then `pool.open(wait=False)` on first use | never block or crash at startup |
  | `kwargs` | `{"connect_timeout": 2, "options": "-c statement_timeout=2000", "application_name": "taskboard10-api"}` | connect 2 s, one statement 2 s (Timeouts table) |

- **Every database failure becomes `TaskStoreUnavailable`, and the route turns it into 503.** This covers any `psycopg.Error` (including `PoolTimeout`, `PoolClosed` and `OperationalError`), a failure while the pool is built, and an unset or empty `DATABASE_URL`. The store logs the failure once, at `error`, with only the exception type, and raises `TaskStoreUnavailable`. The handler catches it and raises `HTTPException(503, "Task store is unavailable")`. There is no retry inside a request (contract, Errors). When `DATABASE_URL` is unset or empty, the store never builds a pool and never falls back to `PG*` variables or libpq defaults: that case must answer 503 (contract, Database wiring).
- **The app creates its own schema, once per process, on the first successful connection.** This runs in one transaction: `SELECT pg_advisory_xact_lock(<const>)`, then `CREATE TABLE IF NOT EXISTS tasks (...)`, then commit. The lock serialises two replicas that start at once: concurrent `CREATE TABLE IF NOT EXISTS` can otherwise fail on the `pg_type` unique index. A process-local flag skips the step after the first success. A failure leaves the flag unset, so the next request tries again (AC-002.2, AC-002.5). No migration tool is added yet. See the ADR.
- **Inserts commit before the response is sent.** `with pool.connection() as conn:` commits when the block exits, and that happens before the handler returns, so any instance's next `GET` sees the row (AC-002.3). If the insert fails or times out, the block rolls back, nothing is stored, and the request gets a 503 (AC-002.4).
- **Acceptance tests run against a real Postgres from devbox, started by a pytest fixture.** There is no Docker and no mock. `devbox.json` gains `postgresql@16`. A session fixture runs `initdb` and `pg_ctl` in a temp dir on a free 127.0.0.1 port, so `devbox run test` brings its own database locally and in the CI `test` job, and `ci.yml` stays untouched (it is a skeleton file). The fixture can stop and restart that server for AC-002.4 and AC-002.5.

ADR: [docs/adr/001-postgres-task-store.md](../../adr/001-postgres-task-store.md) (Postgres via psycopg 3, app-owned idempotent schema, devbox Postgres for tests).

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `src/taskboard10_api/tasks/pg_store.py` | `PostgresTaskStore` (lazy pool, schema bootstrap, create, list, close), `TaskStoreUnavailable` | new |
| `src/taskboard10_api/tasks/store.py` | `TaskRepository` Protocol, in-memory `TaskStore` (unchanged), `get_task_store(request)` | changed |
| `src/taskboard10_api/tasks/api.py` | routes typed against `TaskRepository`; `TaskStoreUnavailable` → 503 | changed |
| `src/taskboard10_api/main.py` | `create_app()` factory with lifespan (closes the store); `app = create_app()` | changed |
| `tests/postgres_harness.py` | `PostgresServer`: initdb, start, stop, createdb via the devbox binaries | new (test support, not an acceptance test) |
| `tests/conftest.py` | fixtures `postgres`, `database_url`, `unreachable_database_url` (plus the existing `client`) | changed |
| `devbox.json` | package `postgresql@16`; recipes `db-up`, `db-down` for local runs | changed |
| `pyproject.toml`, `uv.lock` | `psycopg[binary]>=3.2`, `psycopg-pool>=3.2` | changed |
| `docs/env-vars.md` | `DATABASE_URL` | changed |

### Public interfaces (Python)

```python
# tasks/pg_store.py
class TaskStoreUnavailable(Exception): ...          # message never contains the URL or password

class PostgresTaskStore:
    def __init__(self, database_url: str | None) -> None: ...   # no I/O
    @classmethod
    def from_env(cls) -> "PostgresTaskStore": ...   # os.environ.get("DATABASE_URL") or None ("" counts as unset)
    def create(self, title: str, due_date: date | None) -> Task: ...  # uuid4 id, INSERT, commit; raises TaskStoreUnavailable
    def list_all(self) -> list[Task]: ...           # SELECT ... ORDER BY seq; raises TaskStoreUnavailable
    def close(self) -> None: ...                    # closes the pool if one was opened; idempotent

# tasks/store.py
class TaskRepository(Protocol):
    def create(self, title: str, due_date: date | None) -> Task: ...
    def list_all(self) -> list[Task]: ...

class TaskStore: ...                                # in-memory, unchanged; satisfies TaskRepository

def get_task_store(request: Request) -> TaskRepository: ...   # request.app.state.task_store

# main.py
def create_app() -> FastAPI: ...                    # reads DATABASE_URL at call time; no DB I/O
app: FastAPI                                        # = create_app()
```

Pseudocode of one store call:

```
def _run(op, fn):
    if url is None: log.error("task_store_unavailable", operation=op, error_type="MissingDatabaseUrl"); raise TaskStoreUnavailable
    try:
        pool = self._get_pool()                     # build + open(wait=False) once, under a threading.Lock
        with pool.connection() as conn:             # waits <= 2 s; check_connection drops dead conns
            if not self._schema_ready: ensure_schema(conn); self._schema_ready = True
            return fn(conn)                         # commit on block exit
    except Exception as exc:                        # psycopg.Error, PoolTimeout, pool construction errors
        log.error("task_store_unavailable", operation=op, error_type=type(exc).__name__)
        raise TaskStoreUnavailable from exc
```

## Contract

The endpoints and the Task model are those of spec 001, unchanged (see [001 design](../001-create-and-list-in-memory-tasks/design.md#contract)). This spec adds the 503 answer and the database wiring. There is no authentication. Bodies are `application/json`.

Task: `{"id": "<uuid4 string>", "title": "<trimmed, 1-200 chars>", "due_date": "YYYY-MM-DD" | null}`. All three keys are always present.

### `GET /tasks`

| Status | Body | When |
|---|---|---|
| `200` | JSON array of Task, every stored task, ordered by `seq` (creation order, oldest first, across all instances); `[]` when empty | database reachable (AC-002.1, AC-002.2, AC-002.3, AC-002.5) |
| `503` | `{"detail": "Task store is unavailable"}` | `DATABASE_URL` unset or empty, no connection within 2 s, the connection fails, or the query exceeds 2 s; answered within 3 s (AC-002.4) |

### `POST /tasks`

| Status | Body | When |
|---|---|---|
| `201` | the created Task, committed before the response | valid body, database reachable (AC-002.2, AC-002.5) |
| `422` | FastAPI's default `{"detail": [{"loc": ["body", "title" \| "due_date"], "msg": ..., "type": ..., "input": ...}]}` | spec-001 validation rules; checked **before** any database access, so it is also the answer when the database is down; nothing stored (AC-002.2) |
| `503` | `{"detail": "Task store is unavailable"}` | as for `GET`; nothing stored (AC-002.4) |

`GET /health` → `200 {"status": "ok"}` and `GET /ready` → `200 {"status": "ready"}`, whether or not the database is reachable or configured (AC-002.4).

### Configuration

| Variable | Default | Effect |
|---|---|---|
| `DATABASE_URL` | unset | libpq URI, e.g. `postgresql://user:pass@host:5432/db`. Unset or empty: the service starts and both task endpoints answer 503. `PG*` variables are ignored by the app. |

### Logging

- One `error` event per failed request: `event="task_store_unavailable"`, `operation="list" | "create"`, `error_type="<exception class name>"` (`"MissingDatabaseUrl"` when the URL is unset). It never logs the URL, password or exception message.
- `info` `task_created` with `task_id` (unchanged).

## Data

Table `tasks`, created by the app (see Decisions):

```sql
CREATE TABLE IF NOT EXISTS tasks (
    seq      bigserial PRIMARY KEY,   -- creation order across instances
    id       text      NOT NULL UNIQUE, -- uuid4 string assigned by the API
    title    text      NOT NULL,
    due_date date      NULL
);
```

- Advisory lock key: one fixed bigint constant in `pg_store.py` (`_SCHEMA_LOCK_KEY = 0x7461736B73`, "tasks").
- Insert: `INSERT INTO tasks (id, title, due_date) VALUES (%s, %s, %s)`. List: `SELECT id, title, due_date FROM tasks ORDER BY seq`. Both use bound parameters only.
- Existing data: none. Spec 001 stored nothing persistently, so there is nothing to migrate.

## Test hooks (for the acceptance tests)

The fixtures come from `tests/conftest.py` and `tests/postgres_harness.py`, which plan task t1 builds. Acceptance tests use them and do not set up Postgres themselves. They live in their own files (for example `tests/test_tasks_postgres.py`) and leave `conftest.py` and `postgres_harness.py` alone.

| Fixture | Scope | Gives |
|---|---|---|
| `postgres` | session | a running `PostgresServer`: `.url(dbname="postgres") -> str`, `.create_database() -> str` (URL of a new empty database, no `tasks` table), `.stop()` (`pg_ctl stop -m fast`), `.start()` (same port and data dir), `.running -> bool` |
| `database_url` | function | URL of a fresh empty database, also set as env `DATABASE_URL` (monkeypatch). It makes sure the server is running before the test, and restarts it at teardown if the test stopped it. |
| `unreachable_database_url` | function | `postgresql://postgres@127.0.0.1:<port nobody listens on>/postgres`, set as env `DATABASE_URL` |

- Start a service instance with `with TestClient(create_app()) as api:` (`from taskboard10_api.main import create_app`). The `with` runs the lifespan. Leaving the block closes that instance's pool, which is the "stop" of AC-002.1. Create the app **after** the env is set.
- Use two `TestClient(create_app())` blocks open at once for AC-002.3.
- For AC-002.4 and AC-002.5, call `postgres.stop()`, then `postgres.start()`, inside a test that uses `database_url`. For the unset case, call `monkeypatch.delenv("DATABASE_URL", raising=False)` before `create_app()`. Measure the 3 s bound around one request with `time.monotonic()`.
- To check that there is no table, or that nothing was stored, connect to `database_url` directly with `psycopg` (available after plan t2).
- The server has trust auth on 127.0.0.1 only, no Unix socket, and `fsync=off`. If `initdb` is not on `PATH`, the fixture fails (it does not skip) with: run the tests through `devbox run test`.
- Smoke (deployed dev and staging): the existing spec-001 smoke tests keep working once the database is wired. Adding a read-only `GET /tasks` → 200 smoke check (not 503) confirms the database wiring in every environment.
