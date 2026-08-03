"""Durable scheduling-window helpers for construction tasks."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

from app.models.models import Task


def automatic_schedule_window(
    dependencies: Iterable[Task],
    estimated_duration: int,
    at: datetime,
) -> tuple[datetime, datetime]:
    """Calculate an automatic task window from real predecessor records.

    A completed predecessor contributes its actual completion time. An
    incomplete predecessor contributes its persisted forecast, allowing PM to
    inspect a provisional window without making the task dispatchable early.
    """

    start_candidates = [at]
    for dependency in dependencies:
        if dependency.status == "completed" and dependency.completed_at is not None:
            start_candidates.append(dependency.completed_at)
        elif dependency.planned_end is not None:
            start_candidates.append(dependency.planned_end)
    planned_start = max(start_candidates)
    return planned_start, planned_start + timedelta(minutes=estimated_duration)


def completed_dependency_anchor(dependencies: Iterable[Task]) -> datetime | None:
    """Return the true finish anchor only when all predecessors completed."""

    items = list(dependencies)
    if not items or any(item.status != "completed" or item.completed_at is None for item in items):
        return None
    return max(item.completed_at for item in items if item.completed_at is not None)
