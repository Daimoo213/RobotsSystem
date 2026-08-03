from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.scheduler.scheduling import automatic_schedule_window, completed_dependency_anchor


def _task(*, status: str, completed_at: datetime | None, planned_end: datetime | None) -> SimpleNamespace:
    return SimpleNamespace(status=status, completed_at=completed_at, planned_end=planned_end)


def test_automatic_schedule_starts_now_without_dependencies() -> None:
    current_time = datetime(2026, 7, 31, 9, 0, tzinfo=timezone.utc)

    planned_start, planned_end = automatic_schedule_window([], 90, current_time)

    assert planned_start == current_time
    assert planned_end == current_time + timedelta(minutes=90)


def test_automatic_schedule_uses_latest_dependency_forecast() -> None:
    current_time = datetime(2026, 7, 31, 9, 0, tzinfo=timezone.utc)
    first_end = current_time + timedelta(minutes=30)
    second_end = current_time + timedelta(minutes=50)
    dependencies = [
        _task(status="pending", completed_at=None, planned_end=first_end),
        _task(status="running", completed_at=None, planned_end=second_end),
    ]

    planned_start, planned_end = automatic_schedule_window(dependencies, 120, current_time)

    assert planned_start == second_end
    assert planned_end == second_end + timedelta(minutes=120)
    assert completed_dependency_anchor(dependencies) is None


def test_completed_dependency_anchor_uses_real_completion_time() -> None:
    current_time = datetime(2026, 7, 31, 9, 0, tzinfo=timezone.utc)
    first_completed = current_time + timedelta(minutes=10)
    second_completed = current_time + timedelta(minutes=25)
    dependencies = [
        _task(status="completed", completed_at=first_completed, planned_end=current_time + timedelta(minutes=30)),
        _task(status="completed", completed_at=second_completed, planned_end=current_time + timedelta(minutes=60)),
    ]

    assert completed_dependency_anchor(dependencies) == second_completed
