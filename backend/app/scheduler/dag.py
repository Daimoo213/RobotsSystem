"""DAG (Directed Acyclic Graph) for task dependency management."""

from __future__ import annotations

import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class DAGNode:
    task_id: str
    process_id: str
    name: str
    status: str = "pending"  # pending/assigned/running/paused/completed/failed
    dependencies: list[str] = field(default_factory=list)
    device_id: str | None = None
    priority: int = 50
    map_point_id: str | None = None
    estimated_duration: int = 60
    progress: float = 0.0
    stage: str = "earthwork"
    planned_start: datetime | None = None


class TaskDAG:
    """Manages task dependencies and determines which tasks are ready to execute."""

    def __init__(self):
        self._nodes: dict[str, DAGNode] = {}
        self._dependents: dict[str, list[str]] = defaultdict(list)  # task_id -> tasks that depend on it

    def add_node(self, node: DAGNode) -> None:
        self._nodes[node.task_id] = node
        for dep in node.dependencies:
            self._dependents[dep].append(node.task_id)

    def remove_node(self, task_id: str) -> None:
        node = self._nodes.pop(task_id, None)
        if node:
            for dep in node.dependencies:
                if task_id in self._dependents.get(dep, []):
                    self._dependents[dep].remove(task_id)

    def mark_completed(self, task_id: str) -> list[str]:
        """Mark a task as completed and return newly-unlocked task IDs."""
        node = self._nodes.get(task_id)
        if node:
            node.status = "completed"
            node.progress = 100.0
        unlocked = []
        for dependent_id in self._dependents.get(task_id, []):
            dep_node = self._nodes.get(dependent_id)
            if dep_node and dep_node.status == "pending":
                if self._all_deps_completed(dependent_id):
                    unlocked.append(dependent_id)
        return unlocked

    def mark_failed(self, task_id: str) -> None:
        node = self._nodes.get(task_id)
        if node:
            node.status = "failed"

    def update_status(self, task_id: str, status: str, progress: float | None = None,
                      device_id: str | None = None) -> None:
        node = self._nodes.get(task_id)
        if node:
            node.status = status
            if progress is not None:
                node.progress = progress
            if device_id is not None:
                node.device_id = device_id

    def update_task(
        self,
        task_id: str,
        *,
        name: str | None = None,
        priority: int | None = None,
        planned_start: datetime | None = None,
    ) -> None:
        """Keep mutable scheduling fields aligned with the database record."""

        node = self._nodes.get(task_id)
        if node is None:
            return
        if name is not None:
            node.name = name
        if priority is not None:
            node.priority = priority
        node.planned_start = planned_start

    def get_ready_tasks(self) -> list[DAGNode]:
        """Return all pending tasks whose dependencies are all completed, sorted by priority."""
        ready = [
            n for n in self._nodes.values()
            if n.status == "pending" and self._all_deps_completed(n.task_id)
        ]
        ready.sort(key=lambda n: n.priority, reverse=True)
        return ready

    def get_running_tasks(self) -> list[DAGNode]:
        return [n for n in self._nodes.values() if n.status in ("assigned", "running")]

    def get_all_nodes(self) -> list[DAGNode]:
        return list(self._nodes.values())

    def _all_deps_completed(self, task_id: str) -> bool:
        node = self._nodes.get(task_id)
        if not node:
            return True
        for dep in node.dependencies:
            dep_node = self._nodes.get(dep)
            if not dep_node or dep_node.status != "completed":
                return False
        return True

    def clear(self) -> None:
        self._nodes.clear()
        self._dependents.clear()
