"""PostgreSQL-backed task store with a lazy pool and self-created schema."""

import os
import threading
import uuid
from collections.abc import Callable
from datetime import date
from typing import Any, TypeVar, cast

import structlog
from psycopg_pool import ConnectionPool

from taskboard10_api.tasks.models import Task

_SCHEMA_LOCK_KEY = 0x7461736B73
_UNAVAILABLE = "Task store is unavailable"
_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS tasks (
    seq      bigserial PRIMARY KEY,
    id       text      NOT NULL UNIQUE,
    title    text      NOT NULL,
    due_date date      NULL
)
"""

T = TypeVar("T")


class TaskStoreUnavailable(Exception):  # noqa: N818 - name fixed by the contract
    """The database cannot be used; the message never contains the URL."""


class PostgresTaskStore:
    """Persists tasks in creation order; connects lazily and recovers by itself."""

    def __init__(self, database_url: str | None) -> None:
        self._url = database_url or None
        self._pool: ConnectionPool[Any] | None = None
        self._pool_lock = threading.Lock()
        self._schema_ready = False

    @classmethod
    def from_env(cls) -> "PostgresTaskStore":
        return cls(os.environ.get("DATABASE_URL") or None)

    def _get_pool(self) -> "ConnectionPool[Any]":
        with self._pool_lock:
            if self._pool is None:
                pool: ConnectionPool[Any] = ConnectionPool(
                    conninfo=self._url or "",
                    min_size=1,
                    max_size=5,
                    timeout=2.0,
                    reconnect_timeout=2.0,
                    check=ConnectionPool.check_connection,
                    open=False,
                    kwargs={
                        "connect_timeout": 2,
                        "options": "-c statement_timeout=2000",
                        "application_name": "taskboard10-api",
                    },
                )
                pool.open(wait=False)
                self._pool = pool
            return self._pool

    def _ensure_schema(self, conn: Any) -> None:
        with conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (_SCHEMA_LOCK_KEY,))
            conn.execute(_CREATE_TABLE)
        self._schema_ready = True

    def _run(self, operation: str, fn: Callable[[Any], T]) -> T:
        log = structlog.get_logger()
        if self._url is None:
            log.error(
                "task_store_unavailable",
                operation=operation,
                error_type="MissingDatabaseUrl",
            )
            raise TaskStoreUnavailable(_UNAVAILABLE)
        try:
            pool = self._get_pool()
            with pool.connection() as conn:
                if not self._schema_ready:
                    self._ensure_schema(conn)
                return fn(conn)
        except Exception as exc:
            log.error(
                "task_store_unavailable",
                operation=operation,
                error_type=type(exc).__name__,
            )
            raise TaskStoreUnavailable(_UNAVAILABLE) from exc

    def create(self, title: str, due_date: date | None) -> Task:
        task_id = str(uuid.uuid4())

        def _insert(conn: Any) -> Task:
            conn.execute(
                "INSERT INTO tasks (id, title, due_date) VALUES (%s, %s, %s)",
                (task_id, title, due_date),
            )
            return Task(id=task_id, title=title, due_date=due_date)

        return self._run("create", _insert)

    def list_all(self) -> list[Task]:
        def _select(conn: Any) -> list[Task]:
            rows = conn.execute("SELECT id, title, due_date FROM tasks ORDER BY seq").fetchall()
            result: list[Task] = []
            for row in rows:
                tid, title, due = cast("tuple[str, str, date | None]", row)
                result.append(Task(id=tid, title=title, due_date=due))
            return result

        return self._run("list", _select)

    def close(self) -> None:
        with self._pool_lock:
            pool, self._pool = self._pool, None
        if pool is not None:
            pool.close(timeout=2)
