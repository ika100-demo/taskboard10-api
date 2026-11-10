"""Unit tests for PostgresTaskStore that need no database."""

import pytest
from structlog.testing import capture_logs

from taskboard10_api.tasks.pg_store import PostgresTaskStore, TaskStoreUnavailable


def test_list_without_url_raises_unavailable() -> None:
    with capture_logs() as logs, pytest.raises(TaskStoreUnavailable, match="unavailable"):
        PostgresTaskStore(None).list_all()
    assert logs[0]["error_type"] == "MissingDatabaseUrl"
    assert logs[0]["operation"] == "list"


def test_create_without_url_raises_unavailable() -> None:
    with pytest.raises(TaskStoreUnavailable):
        PostgresTaskStore(None).create("x", None)


def test_from_env_empty_counts_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "")
    with pytest.raises(TaskStoreUnavailable):
        PostgresTaskStore.from_env().list_all()


def test_logged_event_carries_no_url() -> None:
    url = "postgresql://user:s3cret@127.0.0.1:1/db"  # pragma: allowlist secret
    store = PostgresTaskStore(url)
    with capture_logs() as logs, pytest.raises(TaskStoreUnavailable) as info:
        store.list_all()
    store.close()
    assert "s3cret" not in str(info.value)
    assert "s3cret" not in repr(logs)
    assert logs[0]["event"] == "task_store_unavailable"


def test_close_without_pool_is_noop() -> None:
    store = PostgresTaskStore(None)
    store.close()
    store.close()
