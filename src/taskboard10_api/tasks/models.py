"""Request and response models for tasks."""

import re
from datetime import date
from typing import Annotated, Any

from pydantic import BaseModel, StringConstraints, field_validator

Title = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=200),
]

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class TaskCreate(BaseModel):
    """Body of POST /tasks. Unknown fields (including a client id) are ignored."""

    title: Title
    due_date: date | None = None

    @field_validator("due_date", mode="before")
    @classmethod
    def _strict_iso_date(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str) and _DATE_RE.fullmatch(value):
            return value
        raise ValueError("due_date must be a calendar date in the form YYYY-MM-DD")


class Task(BaseModel):
    """A stored task; due_date serialises as null when absent."""

    id: str
    title: str
    due_date: date | None
