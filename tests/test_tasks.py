"""Acceptance tests for spec 001 (create and list in-memory tasks)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient


class _LazyTasksClient:
    """TestClient on an isolated empty store, set up on first use.

    The imports happen at first request so a missing module fails the test, not collection.
    """

    def __init__(self) -> None:
        self._client: TestClient | None = None
        self._app: Any = None
        self._dep: Any = None

    def _ensure(self) -> TestClient:
        if self._client is None:
            from taskboard10_api.tasks.store import TaskStore, get_task_store

            from taskboard10_api.main import app

            store = TaskStore()
            app.dependency_overrides[get_task_store] = lambda: store
            self._app, self._dep = app, get_task_store
            self._client = TestClient(app)
        return self._client

    def post(self, body: Any) -> Any:
        return self._ensure().post("/tasks", json=body)

    def list(self) -> Any:
        return self._ensure().get("/tasks")

    def close(self) -> None:
        if self._app is not None:
            self._app.dependency_overrides.pop(self._dep, None)


@pytest.fixture()
def tasks() -> Iterator[_LazyTasksClient]:
    lazy = _LazyTasksClient()
    try:
        yield lazy
    finally:
        lazy.close()


def _assert_422_names(response: Any, field: str) -> None:
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any(field in entry["loc"] for entry in detail)


def test_create_with_due_date_returns_201():  # AC-001.1
    c = _LazyTasksClient()
    try:
        response = c.post({"title": "Buy milk", "due_date": "2026-12-01"})
        assert response.status_code == 201
        body = response.json()
        assert isinstance(body["id"], str) and body["id"]
        assert body["title"] == "Buy milk"
        assert body["due_date"] == "2026-12-01"
    finally:
        c.close()


def test_create_without_due_date_is_null(tasks):  # AC-001.2
    response = tasks.post({"title": "Buy milk"})
    assert response.status_code == 201
    assert response.json()["due_date"] is None


def test_title_is_trimmed(tasks):  # AC-001.3
    response = tasks.post({"title": "  Buy milk  "})
    assert response.status_code == 201
    assert response.json()["title"] == "Buy milk"


def test_list_returns_tasks_in_creation_order(tasks):  # AC-001.4
    a = tasks.post({"title": "A", "due_date": "2026-12-01"}).json()
    b = tasks.post({"title": "B"}).json()
    response = tasks.list()
    assert response.status_code == 200
    listed = response.json()
    assert [t["id"] for t in listed] == [a["id"], b["id"]]
    assert listed[0] == a
    assert listed[1] == b
    assert len({t["id"] for t in listed}) == len(listed)


def test_list_is_empty_on_fresh_store(tasks):  # AC-001.5
    response = tasks.list()
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"title": 5},
        {"title": True},
        {"title": ["x"]},
        {"title": {"a": 1}},
        {"title": None},
        {"title": ""},
        {"title": "   "},
        {"title": "x" * 201},
        {"title": "  " + "x" * 201 + "  "},
    ],
)
def test_invalid_title_is_422_and_stores_nothing(tasks, body):  # AC-001.6
    _assert_422_names(tasks.post(body), "title")
    assert tasks.list().json() == []


def test_title_of_200_characters_is_accepted(tasks):  # AC-001.6
    response = tasks.post({"title": "x" * 200})
    assert response.status_code == 201


@pytest.mark.parametrize(
    "due",
    ["2026-02-30", "tomorrow", "01.12.2026", "2026-12-01T10:00:00", 20261201, True],
)
def test_invalid_due_date_is_422_and_stores_nothing(tasks, due):  # AC-001.7
    _assert_422_names(tasks.post({"title": "Buy milk", "due_date": due}), "due_date")
    assert tasks.list().json() == []


# Smoke tests (AC-001.1, AC-001.4): reach the service only through SMOKE_BASE_URL.


@pytest.mark.smoke
@pytest.mark.writes
def test_smoke_ac_001_1_create_task(smoke_base_url: str) -> None:  # AC-001.1
    import uuid

    import httpx

    title = f"smoke-{uuid.uuid4()}"
    response = httpx.post(
        smoke_base_url + "/tasks",
        json={"title": title, "due_date": "2026-12-01"},
        timeout=10,
    )
    assert response.status_code == 201
    body = response.json()
    assert isinstance(body["id"], str) and body["id"]
    assert body["title"] == title
    assert body["due_date"] == "2026-12-01"


@pytest.mark.smoke
@pytest.mark.writes
def test_smoke_ac_001_4_list_keeps_creation_order(smoke_base_url: str) -> None:  # AC-001.4
    import uuid

    import httpx

    first = httpx.post(
        smoke_base_url + "/tasks", json={"title": f"smoke-{uuid.uuid4()}"}, timeout=10
    ).json()
    second = httpx.post(
        smoke_base_url + "/tasks",
        json={"title": f"smoke-{uuid.uuid4()}", "due_date": "2026-12-01"},
        timeout=10,
    ).json()
    response = httpx.get(smoke_base_url + "/tasks", timeout=10)
    assert response.status_code == 200
    listed = response.json()
    ids = [t["id"] for t in listed]
    assert len(set(ids)) == len(ids)
    assert ids.index(first["id"]) < ids.index(second["id"])
    assert first in listed
    assert second in listed


@pytest.mark.smoke
def test_smoke_ac_001_4_list_is_readable(smoke_base_url: str) -> None:  # AC-001.4
    import httpx

    response = httpx.get(smoke_base_url + "/tasks", timeout=10)
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.smoke
def test_smoke_ac_001_1_rejects_missing_title(smoke_base_url: str) -> None:  # AC-001.6
    import httpx

    response = httpx.post(smoke_base_url + "/tasks", json={}, timeout=10)
    assert response.status_code == 422
