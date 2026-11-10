"""Acceptance tests for spec 002 (store tasks in Postgres so they survive)."""

from __future__ import annotations

import time
from typing import Any

import pytest

UNAVAILABLE = {"detail": "Task store is unavailable"}


def _new_client() -> Any:
    from fastapi.testclient import TestClient

    from taskboard10_api.main import create_app

    return TestClient(create_app())


def _table_exists(url: str) -> bool:
    import psycopg

    with psycopg.connect(url) as conn:
        row = conn.execute("select to_regclass('public.tasks')").fetchone()
    return bool(row and row[0])


def _stored_count(url: str) -> int:
    import psycopg

    with psycopg.connect(url) as conn:
        row = conn.execute("select count(*) from tasks").fetchone()
    assert row is not None
    return int(row[0])


def test_tasks_survive_restart(database_url):  # AC-002.1
    with _new_client() as api:
        a = api.post("/tasks", json={"title": "A", "due_date": "2030-01-02"})
        b = api.post("/tasks", json={"title": "B"})
    assert a.status_code == 201
    assert b.status_code == 201
    with _new_client() as api:
        response = api.get("/tasks")
    assert response.status_code == 200
    assert response.json() == [a.json(), b.json()]


def test_table_created_and_empty_list(database_url):  # AC-002.2
    assert not _table_exists(database_url)
    with _new_client() as api:
        response = api.get("/tasks")
    assert response.status_code == 200
    assert response.json() == []
    assert _table_exists(database_url)


def test_create_contract_unchanged_against_database(database_url):  # AC-002.2
    with _new_client() as api:
        created = api.post("/tasks", json={"title": "  Write  ", "due_date": "2031-05-06"})
        assert created.status_code == 201
        body = created.json()
        assert set(body) == {"id", "title", "due_date"}
        assert body["title"] == "Write"
        assert body["due_date"] == "2031-05-06"
        assert api.post("/tasks", json={"title": "   "}).status_code == 422
        assert api.post("/tasks", json={"title": "x" * 201}).status_code == 422
        assert api.post("/tasks", json={}).status_code == 422
        assert api.post("/tasks", json={"title": "t", "due_date": "nope"}).status_code == 422
        assert api.get("/tasks").json() == [body]
    assert _stored_count(database_url) == 1


def test_two_instances_see_each_others_tasks(database_url):  # AC-002.3
    with _new_client() as one, _new_client() as two:
        first = one.post("/tasks", json={"title": "one-1"})
        assert first.status_code == 201
        for i in range(10):
            client = one if i % 2 == 0 else two
            response = client.get("/tasks")
            assert response.status_code == 200
            assert first.json() in response.json()
        second = two.post("/tasks", json={"title": "two-1"})
        third = one.post("/tasks", json={"title": "one-2"})
        expected = [first.json(), second.json(), third.json()]
        assert one.get("/tasks").json() == expected
        assert two.get("/tasks").json() == expected


def test_stopped_database_answers_503(postgres, database_url):  # AC-002.4
    with _new_client() as api:
        assert api.post("/tasks", json={"title": "before"}).status_code == 201
        postgres.stop()
        started = time.monotonic()
        got = api.get("/tasks")
        assert time.monotonic() - started < 3
        assert got.status_code == 503
        assert got.json() == UNAVAILABLE
        started = time.monotonic()
        posted = api.post("/tasks", json={"title": "during"})
        assert time.monotonic() - started < 3
        assert posted.status_code == 503
        assert posted.json() == UNAVAILABLE
        assert api.get("/health").status_code == 200
        assert api.get("/ready").status_code == 200
        postgres.start()
    assert _stored_count(database_url) == 1


def test_unreachable_url_answers_503(unreachable_database_url):  # AC-002.4
    with _new_client() as api:
        started = time.monotonic()
        got = api.get("/tasks")
        assert time.monotonic() - started < 3
        assert got.status_code == 503
        assert got.json() == UNAVAILABLE
        started = time.monotonic()
        posted = api.post("/tasks", json={"title": "x"})
        assert time.monotonic() - started < 3
        assert posted.status_code == 503
        assert posted.json() == UNAVAILABLE
        assert api.get("/health").json() == {"status": "ok"}
        assert api.get("/ready").json() == {"status": "ready"}


def test_unset_url_answers_503(monkeypatch):  # AC-002.4
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with _new_client() as api:
        got = api.get("/tasks")
        assert got.status_code == 503
        assert got.json() == UNAVAILABLE
        posted = api.post("/tasks", json={"title": "x"})
        assert posted.status_code == 503
        assert posted.json() == UNAVAILABLE
        assert api.get("/health").status_code == 200
        assert api.get("/ready").status_code == 200


def test_invalid_post_is_422_when_database_down(unreachable_database_url):  # AC-002.4
    with _new_client() as api:
        assert api.post("/tasks", json={"title": "   "}).status_code == 422


def test_recovers_when_database_returns(postgres, database_url):  # AC-002.5
    with _new_client() as api:
        assert api.get("/tasks").status_code == 200
        postgres.stop()
        assert api.get("/tasks").status_code == 503
        assert api.post("/tasks", json={"title": "lost"}).status_code == 503
        postgres.start()
        assert postgres.running
        deadline = time.monotonic() + 15
        got = api.get("/tasks")
        while got.status_code != 200 and time.monotonic() < deadline:
            time.sleep(0.5)
            got = api.get("/tasks")
        assert got.status_code == 200
        assert got.json() == []
        created = api.post("/tasks", json={"title": "after"})
        assert created.status_code == 201
        assert api.get("/tasks").json() == [created.json()]


@pytest.mark.parametrize("path", ["/health", "/ready"])
def test_probes_ok_without_database(monkeypatch, path):  # AC-002.4
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with _new_client() as api:
        assert api.get(path).status_code == 200
