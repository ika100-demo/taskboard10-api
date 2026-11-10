"""Ordered, thread-safe in-memory task store."""

import threading
import uuid
from datetime import date

from taskboard10_api.tasks.models import Task


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


_default_store = TaskStore()


def get_task_store() -> TaskStore:
    return _default_store
