---
spec_id: 001-create-and-list-in-memory-tasks
title: Create and list in-memory tasks
status: building
priority: P1
shape: service-python
---

# 001 — Create and list in-memory tasks

## Problem

The taskboard10 task API has no tasks yet: it answers health, readiness and ping, but a client (the taskboard10 web front end or a script) cannot record a task or see the tasks recorded so far. Without that, nothing else in the system can be built or demonstrated. This first slice keeps tasks in the service's memory, so that the shape of a task and the create/list contract can be settled before storage is chosen.

## Stories

As a client of the task API, I want to create a task with a title and, if I like, a due date, so that it is recorded on the board.

As a client of the task API, I want to list all tasks created so far, so that I can show them to the user.

## Acceptance criteria

- **AC-001.1** Given the body `{"title": "Buy milk", "due_date": "2026-12-01"}`, when a client sends `POST /tasks`, then the response is 201 with a JSON body containing a non-empty string `id`, `"title": "Buy milk"` and `"due_date": "2026-12-01"`. (smoke)
- **AC-001.2** Given the body `{"title": "Buy milk"}` without a due date, when a client sends `POST /tasks`, then the response is 201 and the body contains `"due_date": null`.
- **AC-001.3** Given the body `{"title": "  Buy milk  "}`, when a client sends `POST /tasks`, then the created task's `title` is `"Buy milk"` (leading and trailing whitespace removed).
- **AC-001.4** Given task "A" was created and then task "B", when a client sends `GET /tasks`, then the response is 200 with a JSON array in which both tasks appear, "A" before "B", each with the same `id`, `title` and `due_date` the create response returned, and no two tasks share an `id`. (smoke)
- **AC-001.5** Given a freshly started service on which no task was created, when a client sends `GET /tasks`, then the response is 200 with the body `[]`.
- **AC-001.6** Given a body with no `title`, a `title` that is not a string, a `title` that is empty or whitespace only, or a `title` longer than 200 characters after trimming, when a client sends `POST /tasks`, then the response is 422 with a `detail` that names the field `title`, and a following `GET /tasks` shows no new task.
- **AC-001.7** Given a body whose `due_date` is not a calendar date in the form `YYYY-MM-DD` (for example `"2026-02-30"`, `"tomorrow"`, `"01.12.2026"` or `"2026-12-01T10:00:00"`), when a client sends `POST /tasks`, then the response is 422 with a `detail` that names the field `due_date`, and a following `GET /tasks` shows no new task.

## Non-goals

- Persistent storage: tasks are lost when the service restarts, and each running instance keeps its own list.
- Reading, updating, completing or deleting a single task.
- Filtering, sorting options, search and pagination of the list.
- Users, ownership, authentication and authorization: any caller that reaches the service may create and list tasks; access control is a later spec.
- Due times or time zones; a due date is a calendar date only.

## Assumptions

- **A1** The endpoints are `POST /tasks` and `GET /tasks`, with fields `id`, `title` and `due_date` (other option: other paths or field names such as `dueDate`; affects AC-001.1 to AC-001.7).
- **A2** `id` is a unique string assigned by the service; the client cannot choose it (other option: integer sequence; affects AC-001.1, AC-001.4).
- **A3** A due date is a calendar date `YYYY-MM-DD` and dates in the past are accepted (other option: full timestamp, or reject past dates; affects AC-001.1, AC-001.7).
- **A4** Titles are trimmed and must be 1 to 200 characters after trimming; duplicate titles are allowed (other option: no trimming, a different limit, unique titles; affects AC-001.3, AC-001.6).
- **A5** Invalid input is answered with 422 and a `detail` naming the offending field (other option: 400 with a custom error body; affects AC-001.6, AC-001.7).
- **A6** The list returns all tasks in creation order, oldest first, without a cap on the number of tasks (other option: newest first, or a maximum task count; affects AC-001.4).
- **A7** Unknown fields in the create body are ignored (other option: reject them with 422; affects AC-001.1).

## Open questions

- ~~May any caller that reaches the service create and list tasks without authentication in this slice, as with the existing endpoints?~~ Answered 2026-11-10: yes, no authentication in this slice; access control is a later spec, see Non-goals.

## Changelog

- 2026-11-10 created
- 2026-11-10 amended: open question on authentication answered (none in this slice), recorded under Non-goals; criteria unchanged
- 2026-11-10 approved
- 2026-11-10 building
