# Verification — 001 Create and list in-memory tasks

**Result:** pass
**Commit:** deb7ae8 · **Base:** 2d02371 · **Trace:** 7/7 criteria named by tests (smoke: AC-001.1, AC-001.4)

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-001.1 | met | `tests/test_tasks.py::test_create_with_due_date_returns_201`, smoke `test_smoke_ac_001_1_create_task` | `src/taskboard10_api/tasks/api.py:16-24`, `src/taskboard10_api/tasks/store.py:17-21`, `src/taskboard10_api/main.py:24` | Asserts 201, non-empty string `id`, `title == "Buy milk"`, `due_date == "2026-12-01"` on the parsed body. Smoke test is `@smoke @writes` with a `smoke-<uuid>` title. |
| AC-001.2 | met | `tests/test_tasks.py::test_create_without_due_date_is_null` | `src/taskboard10_api/tasks/models.py:21` (default `None`), `models.py:38` (`Task.due_date` required, serialised as `null`) | Asserts 201 and `due_date is None` (key present, else `KeyError`). |
| AC-001.3 | met | `tests/test_tasks.py::test_title_is_trimmed` | `src/taskboard10_api/tasks/models.py:9-12` (`strip_whitespace=True`) | Asserts 201 and `title == "Buy milk"` for `"  Buy milk  "`. |
| AC-001.4 | met | `tests/test_tasks.py::test_list_returns_tasks_in_creation_order`, smoke `test_smoke_ac_001_4_list_keeps_creation_order`, `test_smoke_ac_001_4_list_is_readable` | `src/taskboard10_api/tasks/api.py:27-32`, `src/taskboard10_api/tasks/store.py:23-25` (copy under lock, insertion order), `store.py:18` (uuid4 id) | Asserts 200, ids in order `[A, B]`, each listed object equal to its create response (id, title, due_date), ids unique. Smoke checks order and equality within a shared list, per design. |
| AC-001.5 | met | `tests/test_tasks.py::test_list_is_empty_on_fresh_store` | `src/taskboard10_api/tasks/store.py:13-15`, `store.py:28` (default store starts empty) | Asserts 200 and body `== []`. "Freshly started" is modelled by a fresh `TaskStore` via `dependency_overrides`, the test hook `design.md` defines. |
| AC-001.6 | met | `tests/test_tasks.py::test_invalid_title_is_422_and_stores_nothing` (10 cases), `test_title_of_200_characters_is_accepted` | `src/taskboard10_api/tasks/models.py:9-12` (`strict`, strip, `min_length=1`, `max_length=200`), `models.py:20`; FastAPI default 422 handler | Cases: missing, int, bool, list, object, null, `""`, `"   "`, 201 chars, 201 chars padded. Each asserts 422, `"title"` in some `detail[].loc`, and a following `GET /tasks == []`. 200 chars accepted (boundary). |
| AC-001.7 | met | `tests/test_tasks.py::test_invalid_due_date_is_422_and_stores_nothing` (6 cases) | `src/taskboard10_api/tasks/models.py:23-30` (before-validator, `^\d{4}-\d{2}-\d{2}$` fullmatch), `models.py:21` (Pydantic `date` rejects `2026-02-30`) | All four examples from the criterion plus `20261201` (int) and `True`. Each asserts 422, `"due_date"` in `loc`, and a following `GET /tasks == []`. |

## Non-goals

- No persistence: the store is a process-local list (`store.py:14`, `store.py:28`). ✔
- No read/update/complete/delete of a single task: only `POST /tasks` and `GET /tasks` are registered (`api.py:16`, `api.py:27`). ✔
- No filtering, sorting options, search or pagination: `list_tasks` takes no query parameters (`api.py:28-32`). ✔
- No authentication or authorization added. ✔
- No due times or time zones: `due_date` is a `date`, and datetime strings are rejected (`models.py:28-30`). ✔
- No template-owned code changed beyond wiring: `main.py` gains one import and one `include_router` line; health, ready, ping and metrics untouched. ✔

## Deviations from the plan

- `tests/test_tasks.py` changed in commit `19db0ee` (task t1), but it is in no task's `files`: a single `# noqa: I001` on line 25. Acceptable: a rule-named, line-level suppression that test-diff allows; no assertion changed (see below).
- Smoke test `test_smoke_ac_001_1_rejects_missing_title` (red commit) carries `ac_001_1` in its name but tests AC-001.6 (its comment says so). Acceptable, cosmetic: an extra read-only smoke check; it does not weaken either criterion.
- Both tasks t1 and t2 are `done: true`. Every other changed file is listed in a task's `files`.

## Contract

Matches `design.md`. ✔ `TaskCreate`, `Task` and `Title` match the public interfaces (`models.py:9-38`); `TaskStore.create`/`list_all` and `get_task_store` match (`store.py:10-32`), with a `threading.Lock` and a copy from `list_all`. The router uses full `/tasks` paths with sync handlers, `status_code=201` and `response_model` as planned (`api.py:13-32`). It logs `task_created` with the id only (`api.py:23`). There is no custom exception handler, so the default 422 body has `loc == ["body", "<field>"]`. Unknown fields such as `id` are ignored (default `extra="ignore"`; unit test `test_unknown_fields_ignored`).

## Suppressions in acceptance tests

| File | Line | Rule | False positive |
|---|---|---|---|
| `tests/test_tasks.py` | 25 | `noqa: I001` | yes: import order only, inside the lazy-import helper. In the red commit `taskboard10_api.tasks` did not exist yet, so isort sorted it into a separate section. Once the package existed, ruff wanted the two in-function imports merged and reordered, which would change the red test's parsed code. Order has no effect on what the test asserts. |

## Mutation check (report only)

11 of 13 mutants of the changed code were caught by the acceptance tests (85 %; spec 152, report only).

Survived (a test that names the criterion would fail if it checked this):
- `src/taskboard10_api/tasks/models.py:11 True → False`
- `src/taskboard10_api/tasks/store.py:32 return value → None`
