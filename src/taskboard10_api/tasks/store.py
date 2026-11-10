"""Ordered, thread-safe in-memory task store and the repository protocol."""

import threading
import uuid
from datetime import date
from typing import Protocol, cast

from fastapi import Request

from taskboard10_api.tasks.models import Task


class TaskRepository(Protocol):
    """What the task endpoints need from a store."""

    def create(self, title: str, due_date: date | None) -> Task: ...

    def list_all(self) -> list[Task]: ...


class TaskStore:
    """Holds tasks in creation order."""

    def __init__(self) -> None:
        self._tasks: list[Task] = []
        self._lock = threading.Lock()

    def create(self, title: str, due_date: date | None) -> Task:
        task = Task(id=str(uuid.uuid4()), title=title, due_date=due_date)
        with self._lock:
            self._tasks.append(task)
        return task

    def list_all(self) -> list[Task]:
        with self._lock:
            return list(self._tasks)


def get_task_store(request: Request) -> TaskRepository:
    return cast(TaskRepository, request.app.state.task_store)
