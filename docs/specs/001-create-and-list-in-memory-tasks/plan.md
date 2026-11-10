---
spec_id: 001-create-and-list-in-memory-tasks
shape: service-python
spec_hash: 5c267c6f3800
summary: POST /tasks and GET /tasks backed by an injected in-memory TaskStore, with strict title and due_date validation
tasks:
  - id: t1
    title: Add task models and in-memory TaskStore
    files: [src/taskboard10_api/tasks/__init__.py, src/taskboard10_api/tasks/models.py, src/taskboard10_api/tasks/store.py, tests/test_task_models_unit.py, tests/test_task_store_unit.py]
    covers: [AC-001.2, AC-001.3, AC-001.4, AC-001.5, AC-001.6, AC-001.7]
    parallel_safe: true
    depends_on: []
  - id: t2
    title: Add /tasks router and wire it into the app
    files: [src/taskboard10_api/tasks/__init__.py, src/taskboard10_api/tasks/api.py, src/taskboard10_api/main.py]
    covers: [AC-001.1, AC-001.2, AC-001.3, AC-001.4, AC-001.5, AC-001.6, AC-001.7]
    parallel_safe: true
    depends_on: [t1]
---

# Plan — 001 Create and list in-memory tasks

The contract, the validation rules and the test hooks are in [design.md](design.md). The plan has two serial levels: t1 builds the domain layer (models and store), and t2 exposes it over HTTP. t2 imports `Task`, `TaskCreate`, `TaskStore` and `get_task_store` from t1 and extends the package `__init__.py` that t1 creates.

## t1 — Add task models and in-memory TaskStore

**Files:** src/taskboard10_api/tasks/__init__.py, src/taskboard10_api/tasks/models.py, src/taskboard10_api/tasks/store.py, tests/test_task_models_unit.py, tests/test_task_store_unit.py
**Covers:** AC-001.2, AC-001.3, AC-001.4, AC-001.5, AC-001.6, AC-001.7
**Goal:** Build the request and response models with all of the spec's validation, plus the ordered, thread-safe in-memory store and its FastAPI dependency. These have no HTTP surface yet; t2 adds it.

**Implementation notes:**
- `tasks/__init__.py`: a module docstring only, so `tasks` is a regular package. t2 adds the router re-export.
- `models.py`:
  - `Title = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=200)]`. Stripping runs before the length checks, so `"   "` fails and a 205-character title of which 10 characters are padding passes.
  - `TaskCreate(BaseModel)`: `title: Title` and `due_date: date | None = None`. Keep the default `extra="ignore"`, so unknown fields and a client `id` are dropped.
  - Add `@field_validator("due_date", mode="before")`. It returns `None` for `None`. For a `str` that fully matches `^\d{4}-\d{2}-\d{2}$` it returns the string unchanged, and Pydantic then parses it to `date`, which rejects `2026-02-30`. Anything else raises `ValueError`: numbers, datetimes, other formats.
  - `Task(BaseModel)`: `id: str`, `title: str`, `due_date: date | None`. Make no field optional-and-omitted: `null` must serialise as `null`.
- `store.py`:
  - `TaskStore` holds a `list[Task]` and a `threading.Lock`.
  - `create(title, due_date) -> Task` assigns `str(uuid.uuid4())` and appends under the lock.
  - `list_all() -> list[Task]` returns a copy taken under the lock, in insertion order.
  - Add a module-level `_default_store = TaskStore()` and `def get_task_store() -> TaskStore: return _default_store`.
- Unit tests:
  - Models: trimming, the 200 and 201 character boundaries after trimming, non-string titles (int, bool, null, list), each bad `due_date` example from AC-001.7 plus a unix-timestamp int and `"20261201"`, a past date accepted, and an unknown field ignored.
  - Store: an empty store lists `[]`, insertion order holds, ids are unique, and mutating the returned list does not change the store.
- Keep mypy strict clean: use `typing.Annotated` and give every function a return type.

**Done when:** `devbox run quality` and the new unit tests pass. The acceptance tests still fail, since there is no route yet.

## t2 — Add /tasks router and wire it into the app

**Files:** src/taskboard10_api/tasks/__init__.py, src/taskboard10_api/tasks/api.py, src/taskboard10_api/main.py
**Covers:** AC-001.1, AC-001.2, AC-001.3, AC-001.4, AC-001.5, AC-001.6, AC-001.7
**Goal:** Expose `POST /tasks` (201) and `GET /tasks` (200) exactly as the contract in design.md specifies, using the injected store, and register the router on the existing app.

**Implementation notes:**
- `api.py`: `router = APIRouter(tags=["tasks"])`. Declare the full paths `"/tasks"` and do not use a prefix with `""`, so FastAPI adds no slash redirect.
- `POST /tasks`:
  - `@router.post("/tasks", status_code=201, response_model=Task)`.
  - `def create_task(body: TaskCreate, store: Annotated[TaskStore, Depends(get_task_store)]) -> Task`.
  - The body returns `store.create(body.title, body.due_date)`.
  - It logs `structlog.get_logger().info("task_created", task_id=...)` with the id only and no title.
- `GET /tasks`: `@router.get("/tasks", response_model=list[Task])` with `def list_tasks(store: ...) -> list[Task]`, returning `store.list_all()`.
- Use sync `def` handlers, which run in the thread pool. The store's lock covers concurrency.
- Add no custom exception handler. FastAPI's default `RequestValidationError` handler produces the 422 `{"detail": [...]}` body with `loc: ["body", "<field>"]`. Validation fails before the handler runs, so nothing is stored on a 422.
- `tasks/__init__.py`: add `from .api import router` with `__all__ = ["router"]`.
- `main.py`: `from .tasks import router as tasks_router` and `app.include_router(tasks_router)` after `add_middleware`. Leave the health, ready, ping and metrics endpoints unchanged.

**Done when:**
- All acceptance tests for AC-001.1 to AC-001.7 pass in-process, using the `dependency_overrides` hook from design.md.
- The existing health and metrics tests still pass.
- `devbox run ci` is green, including coverage at 80% or more.
