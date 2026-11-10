from datetime import date
from typing import Any

import pytest
from pydantic import ValidationError

from taskboard10_api.tasks.models import Task, TaskCreate


def test_title_is_trimmed() -> None:
    assert TaskCreate(title="  Buy milk  ").title == "Buy milk"  # type: ignore[call-arg]


def test_title_boundaries_after_trimming() -> None:
    assert len(TaskCreate(title="a" * 200).title) == 200  # type: ignore[call-arg]
    assert len(TaskCreate(title=" " * 5 + "a" * 200 + " " * 5).title) == 200  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        TaskCreate(title="a" * 201)  # type: ignore[call-arg]


@pytest.mark.parametrize("title", ["", "   "])
def test_empty_title_rejected(title: str) -> None:
    with pytest.raises(ValidationError):
        TaskCreate(title=title)  # type: ignore[call-arg]


@pytest.mark.parametrize("title", [1, True, None, ["a"]])
def test_non_string_title_rejected(title: Any) -> None:
    with pytest.raises(ValidationError):
        TaskCreate(title=title)


def test_missing_title_rejected() -> None:
    with pytest.raises(ValidationError):
        TaskCreate.model_validate({})


def test_due_date_defaults_to_none() -> None:
    assert TaskCreate(title="x").due_date is None  # type: ignore[call-arg]


def test_valid_and_past_due_date_accepted() -> None:
    assert TaskCreate.model_validate({"title": "x", "due_date": "2026-12-01"}).due_date == date(
        2026, 12, 1
    )
    assert TaskCreate.model_validate({"title": "x", "due_date": "1999-01-01"}).due_date == date(
        1999, 1, 1
    )


@pytest.mark.parametrize(
    "value",
    ["2026-02-30", "tomorrow", "01.12.2026", "2026-12-01T10:00:00", "20261201", 1796083200, ""],
)
def test_bad_due_date_rejected(value: Any) -> None:
    with pytest.raises(ValidationError) as exc:
        TaskCreate.model_validate({"title": "x", "due_date": value})
    assert exc.value.errors()[0]["loc"] == ("due_date",)


def test_unknown_fields_ignored() -> None:
    model = TaskCreate.model_validate({"title": "x", "id": "client", "extra": 1})
    assert not hasattr(model, "id")


def test_task_serialises_null_due_date() -> None:
    assert Task(id="1", title="x", due_date=None).model_dump(mode="json") == {
        "id": "1",
        "title": "x",
        "due_date": None,
    }
