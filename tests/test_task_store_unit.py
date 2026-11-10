from datetime import date
from types import SimpleNamespace
from typing import cast

from fastapi import Request

from taskboard10_api.main import create_app
from taskboard10_api.tasks.store import TaskStore, get_task_store


def test_empty_store_lists_nothing() -> None:
    assert TaskStore().list_all() == []


def test_insertion_order_and_unique_ids() -> None:
    store = TaskStore()
    a = store.create("A", None)
    b = store.create("B", date(2026, 12, 1))
    assert store.list_all() == [a, b]
    assert a.id != b.id
    assert b.due_date == date(2026, 12, 1)


def test_returned_list_is_a_copy() -> None:
    store = TaskStore()
    store.create("A", None)
    listed = store.list_all()
    listed.clear()
    assert len(store.list_all()) == 1


def test_get_task_store_returns_app_state_store() -> None:
    app = create_app()
    request = SimpleNamespace(app=app)
    assert get_task_store(cast(Request, request)) is app.state.task_store
