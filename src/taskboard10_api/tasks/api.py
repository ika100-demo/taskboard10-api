"""HTTP routes for tasks."""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException

from .models import Task, TaskCreate
from .pg_store import TaskStoreUnavailable
from .store import TaskRepository, get_task_store

router = APIRouter(tags=["tasks"])


def _unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail="Task store is unavailable")


@router.post("/tasks", status_code=201, response_model=Task)
def create_task(
    body: TaskCreate,
    store: Annotated[TaskRepository, Depends(get_task_store)],
) -> Task:
    """Create a task."""
    try:
        task = store.create(body.title, body.due_date)
    except TaskStoreUnavailable:
        raise _unavailable() from None
    structlog.get_logger().info("task_created", task_id=task.id)
    return task


@router.get("/tasks", response_model=list[Task])
def list_tasks(
    store: Annotated[TaskRepository, Depends(get_task_store)],
) -> list[Task]:
    """List all tasks, oldest first."""
    try:
        return store.list_all()
    except TaskStoreUnavailable:
        raise _unavailable() from None
