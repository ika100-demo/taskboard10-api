# Design — 001 Create and list in-memory tasks

## Decisions

- **One feature package `taskboard10_api/tasks/`** (models, store, router), included into the existing `main.app` with `app.include_router`. `main.py` keeps only wiring. Later task specs (read one, update, delete) extend this package.
- **Storage goes behind a `TaskStore` class that is injected with a FastAPI dependency (`get_task_store`).** The default is one process-wide instance (spec non-goal: no persistence, one list per instance). Using a dependency gives the tests a fresh, empty store per test (AC-001.5) through `app.dependency_overrides`, without a reset endpoint or reloading the module. A persistent store in a later spec replaces the class behind the same two methods.
- **Validation is done by the Pydantic request model, and errors use FastAPI's default 422 body**, with nothing custom (A5). `loc` names the field, which is what AC-001.6 and AC-001.7 test.
- **`title` is strict**: it must be a JSON string (no number-to-string coercion). It is stripped of leading and trailing whitespace first, then must be 1 to 200 characters long (A4).
- **`due_date` is strict `YYYY-MM-DD`**: a `mode="before"` validator accepts only `null` or a string matching `^\d{4}-\d{2}-\d{2}$`, and Pydantic then parses that string into a `datetime.date`. This rejects what Pydantic's lax `date` parsing would otherwise accept: unix-timestamp numbers, `"2026-12-01T00:00:00"`, and `"20261201"`. Pydantic's own date check rejects impossible dates such as `"2026-02-30"`. Past dates are accepted (A3).
- **`id` is `str(uuid.uuid4())`**, assigned by the store. It is unique, and the client cannot set it (A2): a client `id` in the body is ignored like any other unknown field (A7, Pydantic's default `extra="ignore"`).
- **Thread safety**: the endpoints are sync `def`, so FastAPI runs them in its thread pool. `TaskStore` guards its list with a `threading.Lock` and returns a copy from `list_all()`.

No ADR: in-memory storage is explicitly temporary (spec Problem, Non-goals), and the package and dependency layout follow existing FastAPI practice. Both are local to this feature.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `src/taskboard10_api/tasks/__init__.py` | package marker, re-exports `router` | new |
| `src/taskboard10_api/tasks/models.py` | `TaskCreate` (request) and `Task` (response) Pydantic models and their validation | new |
| `src/taskboard10_api/tasks/store.py` | `TaskStore` (in-memory, ordered, thread-safe), `get_task_store()` dependency | new |
| `src/taskboard10_api/tasks/api.py` | `APIRouter` with `POST /tasks` and `GET /tasks` | new |
| `src/taskboard10_api/main.py` | `app.include_router(tasks.router)` | changed |

### Public interfaces (Python)

```python
# tasks/models.py
Title = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=200)]

class TaskCreate(BaseModel):          # extra fields ignored
    title: Title
    due_date: date | None = None      # before-validator: None or str matching ^\d{4}-\d{2}-\d{2}$, else ValueError

class Task(BaseModel):
    id: str
    title: str
    due_date: date | None             # serialised as "YYYY-MM-DD" or null (never omitted)

# tasks/store.py
class TaskStore:
    def create(self, title: str, due_date: date | None) -> Task: ...   # assigns uuid4 id, appends
    def list_all(self) -> list[Task]: ...                              # copy, creation order, oldest first

def get_task_store() -> TaskStore: ...   # returns the process-wide default instance
```

## Contract

There is no authentication (spec Non-goals). Bodies are `application/json`.

### `POST /tasks`

Request body:

| Field | Type | Required | Rule |
|---|---|---|---|
| `title` | string | yes | Leading and trailing whitespace is trimmed; must then be 1 to 200 characters. Duplicates are allowed. |
| `due_date` | string `YYYY-MM-DD` or `null` | no (default `null`) | Must be a real calendar date; past dates are accepted. |
| any other field | – | – | Ignored, including `id`. |

Responses:

- `201 Created`: `{"id": "<uuid4 string>", "title": "<trimmed title>", "due_date": "YYYY-MM-DD" | null}`. All three keys are always present (AC-001.1, AC-001.2, AC-001.3).
- `422 Unprocessable Entity`: FastAPI's default validation body. Nothing is stored (AC-001.6, AC-001.7):

  ```json
  {"detail": [{"type": "<pydantic error type>", "loc": ["body", "title"], "msg": "<text>", "input": "<value>"}]}
  ```

  `detail` is a list with one entry per failing field. The entry for a field has `loc == ["body", "<field>"]`. Tests check `"title"` or `"due_date"` in `loc` and do not check `type` or `msg`. Cases:

  | Input | `loc` |
  |---|---|
  | `title` missing, not a string (number, bool, list, object, null), empty or whitespace-only, longer than 200 characters after trimming | `["body", "title"]` |
  | `due_date` not `null` and not a string matching `YYYY-MM-DD` (`"tomorrow"`, `"01.12.2026"`, `"2026-12-01T10:00:00"`, numbers), or an impossible date (`"2026-02-30"`) | `["body", "due_date"]` |

  A body that is not a JSON object (or not valid JSON) also gets FastAPI's default 422, with `loc` starting with `"body"`. No criterion covers this case.

### `GET /tasks`

- `200 OK`: a JSON array of `Task` objects (the shape above), in creation order with the oldest first. It has no cap and no pagination (AC-001.4, A6).
- On a fresh process, or with a fresh `TaskStore`, the body is `[]` (AC-001.5).

### Test hooks (for the acceptance tests)

- In-process tests get an isolated, empty store per test with:

  ```python
  store = TaskStore()
  app.dependency_overrides[get_task_store] = lambda: store
  yield
  app.dependency_overrides.pop(get_task_store, None)
  ```

  Import `app` from `taskboard10_api.main`, and `TaskStore` and `get_task_store` from `taskboard10_api.tasks.store`.
- The smoke tests for AC-001.1 and AC-001.4 run against a shared deployed instance:
  - They create data, so they are marked `@pytest.mark.writes`, and their titles are `smoke-<uuid>`.
  - For AC-001.4 they check that the two created tasks appear in the list in order with matching fields, not that the list equals exactly those two tasks.
  - A read-only smoke check (`GET /tasks` → 200 and a JSON array) keeps the list covered in staging and prod.

## Data

There is no persistent data. Each process holds a `list[Task]` in memory, and it is lost on restart.

**Operational note:** each replica keeps its own list (spec non-goal). With more than one replica in an environment, a create followed by a list can reach different pods. The AC-001.4 smoke test in dev then only holds if dev runs one replica.
