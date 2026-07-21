"""Market-based scheduler strategy — devices bid on tasks."""

from __future__ import annotations

import math
from typing import Protocol


class SchedulerStrategy(Protocol):
    """Abstract scheduler strategy interface."""

    async def allocate(self, task: dict, candidates: list[dict]) -> dict | None:
        """Select the best device for a task from candidates.

        Returns the winning device dict, or None if no suitable device.
        """
        ...


class MarketSchedulerStrategy:
    """Market mechanism: devices 'bid' on tasks based on cost.

    Cost = distance_cost + battery_cost + load_cost
    Lowest cost wins.
    """

    async def allocate(self, task: dict, candidates: list[dict]) -> dict | None:
        if not candidates:
            return None

        task_x = task.get("target_position", {}).get("x", 0)
        task_y = task.get("target_position", {}).get("y", 0)

        best_device = None
        best_cost = float("inf")

        for dev in candidates:
            dev_x = dev["position"]["x"]
            dev_y = dev["position"]["y"]
            distance = math.hypot(task_x - dev_x, task_y - dev_y)
            distance_cost = distance * 0.5

            # Battery cost: lower battery = higher cost
            battery_cost = (100 - dev["battery"]) * 0.3

            # Load cost: penalize devices already near capacity (simplified)
            load_cost = 0  # idle devices have 0 load

            total_cost = distance_cost + battery_cost + load_cost

            if total_cost < best_cost:
                best_cost = total_cost
                best_device = dev

        return best_device
