---
spec_id: 002-store-tasks-in-postgres-so-they-survive
shape: service-python
spec_hash: 199db89b3144
summary: Postgres-backed TaskStore (psycopg 3 pool, lazy, app-owned schema) behind get_task_store, 503 when the database is unavailable, app factory for multi-instance tests, devbox Postgres test harness
tasks:
  - id: t1
    title: Add devbox Postgres and the pytest Postgres harness
    files: [devbox.json, tests/postgres_harness.py, tests/conftest.py]
    covers: [AC-002.4, AC-002.5]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: Add PostgresTaskStore with lazy pool, schema bootstrap and unavailability errors
    files: [src/taskboard10_api/tasks/pg_store.py, pyproject.toml, uv.lock, tests/test_pg_store_unit.py]
    covers: [AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.5]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t3
    title: Wire the Postgres store into an app factory and answer 503 when it is unavailable
    files: [src/taskboard10_api/tasks/store.py, src/taskboard10_api/tasks/api.py, src/taskboard10_api/main.py, tests/test_task_store_unit.py, docs/env-vars.md]
    covers: [AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.5]
    parallel_safe: true
    depends_on: [t2]
    done: true
---

# Plan — 002 Store tasks in Postgres so they survive restarts and every instance sees the same list

The contract, the pool settings, the table, and the fixtures the acceptance tests use are all in [design.md](design.md). The plan has two levels:

- **Level 1, in parallel.** t1 builds the test infrastructure: devbox Postgres and the fixtures. t2 builds the Postgres store and adds its dependencies. They share no files, and neither imports the other's work.
- **Level 2.** t3 depends on t2, because `store.py`, `api.py` and `main.py` import `PostgresTaskStore` and `TaskStoreUnavailable`. It switches the app over and adds the 503.

The acceptance tests need t1's fixtures and pass once all three tasks are merged.

No gitops task: the system plan's gitops part already wires `uses: postgres` (`DATABASE_URL`, `PG*`) for this component (spec, Provided by the system).

## t1 — Add devbox Postgres and the pytest Postgres harness

**Files:** devbox.json, tests/postgres_harness.py, tests/conftest.py
**Covers:** AC-002.4, AC-002.5
**Goal:** Give `devbox run test` a real, throwaway Postgres that tests can stop and restart, through the fixtures named in design.md (Test hooks): `postgres`, `database_url` and `unreachable_database_url`. Add local recipes so developers can run the service against a database.

**Implementation notes:**
- `devbox.json`:
  - Add the package `postgresql@16`.
  - Add the recipes `db-up` and `db-down` for local runs. `db-up` runs `initdb -U postgres --auth=trust --no-locale -E UTF8` into `$PGDATA` when `$PGDATA/PG_VERSION` is missing, then `devbox services start postgresql`. `db-down` runs `devbox services stop postgresql`.
  - Do not change the template recipes (`test`, `ci`, ...).
- `tests/postgres_harness.py`, class `PostgresServer(base_dir: Path)`:
  - `initdb -D <dir>/data -U postgres --auth=trust --no-locale -E UTF8`.
  - Pick a free port by binding a socket to `127.0.0.1:0`.
  - `start()`: `pg_ctl -D <data> -l <dir>/pg.log -w -t 30 -o "-c listen_addresses=127.0.0.1 -c port=<port> -c unix_socket_directories='' -c fsync=off" start`. `stop()`: `pg_ctl -D <data> -w -m fast stop`.
  - `running`: `pg_ctl status` exit code.
  - `url(dbname)` → `postgresql://postgres@127.0.0.1:<port>/<dbname>`.
  - `create_database()`: `createdb -h 127.0.0.1 -p <port> -U postgres t_<uuid hex>`, returning its URL. Use binaries only, no psycopg, so t1 does not need t2.
- Pass every location explicitly (`-D`, `-h`, `-p`, `-U`). Clear `PGHOST`, `PGPORT`, `PGDATA`, `PGUSER` and `PGDATABASE` from the subprocess env, because devbox's postgresql plugin sets them in the shell.
- If `shutil.which("initdb")` is `None`, call `pytest.fail("initdb not on PATH: run the tests through devbox run test (devbox.json provides postgresql)")`, raised lazily inside the session fixture. Never skip, and never break collection for tests that do not use Postgres.
- `tests/conftest.py`:
  - Keep `client`.
  - Add the session fixture `postgres`: start under `tmp_path_factory.mktemp("pg")`, stop at session end.
  - Add the function fixture `database_url`: `if not postgres.running: postgres.start()`, then `create_database()`, then `monkeypatch.setenv("DATABASE_URL", url)`. At teardown, restart the server if it is stopped.
  - Add the function fixture `unreachable_database_url`: a free port that nobody listens on, set into env.
- Subprocess calls use list args with no shell, `check=True` and a timeout, so bandit only scans `src/` and the code stays clean anyway.

**Done when:**
- A throwaway test that uses `database_url` can stop and start `postgres` and create two databases.
- `devbox run test` still passes every existing test.
- `devbox run quality` is green.

## t2 — Add PostgresTaskStore with lazy pool, schema bootstrap and unavailability errors

**Files:** src/taskboard10_api/tasks/pg_store.py, pyproject.toml, uv.lock, tests/test_pg_store_unit.py
**Covers:** AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.5
**Goal:** Build `PostgresTaskStore` and `TaskStoreUnavailable` exactly as design.md specifies (interfaces, pool settings table, pseudocode, Data). The store persists tasks in creation order, creates its own table, maps every database failure to `TaskStoreUnavailable`, and recovers without a restart.

**Implementation notes:**
- Dependencies: add `psycopg[binary]>=3.2` and `psycopg-pool>=3.2` to `[project].dependencies` by editing `pyproject.toml`, then let `devbox run test` (`uv run`) relock `uv.lock`. Do not use `uv add` (CLAUDE.md). The binary wheel bundles libpq, so the slim runtime image needs no apt package.
- `__init__(database_url)` does no I/O. `from_env()` treats `""` as `None`.
- `_get_pool()`, under a `threading.Lock`:
  - Build `ConnectionPool(conninfo=url, min_size=1, max_size=5, timeout=2.0, reconnect_timeout=2.0, check=ConnectionPool.check_connection, open=False, kwargs={"connect_timeout": 2, "options": "-c statement_timeout=2000", "application_name": "taskboard10-api"})`.
  - Then call `pool.open(wait=False)`, once only.
- `_ensure_schema(conn)`, in one transaction: `SELECT pg_advisory_xact_lock(%s)` with `_SCHEMA_LOCK_KEY`, then the `CREATE TABLE IF NOT EXISTS tasks` from design.md. Set `_schema_ready = True` only after it commits.
- `create`: `id = str(uuid.uuid4())`, then `INSERT ... VALUES (%s, %s, %s)` inside `with pool.connection() as conn:`, which commits on exit. Return `Task(id=..., title=..., due_date=...)`.
- `list_all`: `SELECT id, title, due_date FROM tasks ORDER BY seq`. Map rows to `Task`. `due_date` comes back as `datetime.date` or `None`.
- Errors:
  - When the URL is missing, log and raise with `error_type="MissingDatabaseUrl"` without touching psycopg.
  - Otherwise wrap pool construction and every call in `except Exception`. Log `structlog.get_logger().error("task_store_unavailable", operation=..., error_type=type(exc).__name__)` exactly once, then `raise TaskStoreUnavailable("Task store is unavailable") from exc`.
  - Never log `str(exc)` or the URL.
- `close()`: `pool.close(timeout=2)` if a pool exists. Idempotent.
- `tests/test_pg_store_unit.py`, no database needed:
  - Without a URL, `list_all` and `create` raise `TaskStoreUnavailable`.
  - `from_env` with `DATABASE_URL=""` behaves as unset.
  - The logged event carries no URL (use structlog's `capture_logs`).
  - `close()` without a pool is a no-op.
- mypy strict: type the row access (for example `conn.execute(...).fetchall()` with `tuple[str, str, date | None]` casts) and give every method a return type.

**Done when:**
- The new unit tests and `devbox run quality` pass.
- `uv.lock` contains psycopg and psycopg-pool.
- `devbox run security` (pip-audit, bandit) is green.

## t3 — Wire the Postgres store into an app factory and answer 503 when it is unavailable

**Files:** src/taskboard10_api/tasks/store.py, src/taskboard10_api/tasks/api.py, src/taskboard10_api/main.py, tests/test_task_store_unit.py, docs/env-vars.md
**Covers:** AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.5
**Goal:** Make the Postgres store the default for every app instance through `create_app()`, keep the in-memory `TaskStore` as an override-able double, and answer `503 {"detail": "Task store is unavailable"}` on both task endpoints when the store is unavailable. 422 still wins, and `/health` and `/ready` are unaffected.

**Implementation notes:**
- `store.py`:
  - Add `class TaskRepository(Protocol)` with `create` and `list_all`.
  - Keep `TaskStore` unchanged.
  - Remove `_default_store`.
  - Add `def get_task_store(request: Request) -> TaskRepository: return cast(TaskRepository, request.app.state.task_store)`.
- `api.py`:
  - Type the dependency as `Annotated[TaskRepository, Depends(get_task_store)]`.
  - Wrap each store call in `try/except TaskStoreUnavailable: raise HTTPException(status_code=503, detail="Task store is unavailable") from None`.
  - Log `task_created` only on success.
  - Keep the sync `def` handlers. Body validation runs before the handler, so the 422 is unchanged even when the database is down.
- `main.py`:
  - Keep `configure_logging` and tracing at module level, so they run once.
  - Add `def create_app() -> FastAPI`. It builds `FastAPI(title=..., version=..., lifespan=_lifespan)`, adds `MetricsMiddleware` and the tasks router, registers `/health`, `/ready`, `/ping` and `/metrics` (moved inside unchanged, with the same response bodies), and sets `app.state.task_store = PostgresTaskStore.from_env()`.
  - `_lifespan` yields, then calls `app.state.task_store.close()` when the object has `close`.
  - End the module with `app = create_app()`. The Prometheus metrics stay module-global, so several apps in one test process share them without registering twice.
- `tests/test_task_store_unit.py`: replace `test_default_store_is_shared` with a test that `get_task_store` returns `app.state.task_store` of a `create_app()` instance (call it with a stub request object, or go through a route with `TestClient`). Keep the in-memory tests.
- `docs/env-vars.md`: add a "Database" section with `DATABASE_URL` (default unset, which means the task endpoints answer 503; `PG*` are ignored), as in design.md, Configuration.
- Make sure the spec-001 suite (`tests/test_tasks.py`, which overrides `get_task_store` on `main.app`), the health tests and the metrics tests still pass unchanged.

**Done when:**
- The acceptance tests for AC-002.1 to AC-002.5 pass against the harness Postgres.
- The spec-001 acceptance tests, the health tests and the metrics tests still pass.
- `devbox run ci` is green, with coverage at 80% or more.
