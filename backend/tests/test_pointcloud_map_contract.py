"""Contract checks for the complete point-cloud map API."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.pointcloud import PointCloudMapIn, router


def test_routes_use_complete_map_contract() -> None:
    routes = {(route.path, method) for route in router.routes for method in route.methods or set()}

    assert ("/pointcloud/gateway/map", "POST") in routes
    assert ("/pointcloud/map", "GET") in routes
    assert ("/pointcloud/gateway/snapshots", "POST") not in routes
    assert ("/pointcloud/latest", "GET") not in routes


def test_complete_map_accepts_more_than_the_old_snapshot_limit() -> None:
    points = [[float(index), 0.0, 0.0] for index in range(50_001)]
    pointcloud_map = PointCloudMapIn(
        map_id="site-map-20260728-001",
        source_id="slam-gateway-01",
        observed_at="2026-07-28T08:00:00Z",
        points=points,
    )

    assert len(pointcloud_map.points) == 50_001


def test_complete_map_rejects_invalid_coordinates() -> None:
    with pytest.raises(ValidationError):
        PointCloudMapIn(
            map_id="invalid-map",
            source_id="slam-gateway-01",
            observed_at="2026-07-28T08:00:00Z",
            points=[[1.0, 2.0], [float("nan"), 2.0, 3.0]],
        )
