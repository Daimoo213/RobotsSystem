"""Contract checks for persistent robot traversable-path APIs."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.map import MapPathInput, _path_dict, create_paths_batch, router
from app.models.models import MapPath


def _path_request(**overrides) -> MapPathInput:
    values = {
        "code": "PATH-001",
        "name": "北侧坡道",
        "points": [[0.0, 0.0, 0.0], [10.0, 0.0, 0.5]],
        "direction": "forward",
        "min_width_m": 2.5,
        "max_slope_percent": 8.0,
        "device_types": ["agv", "hauler"],
        "status": "active",
    }
    values.update(overrides)
    return MapPathInput(**values)


def test_robot_path_routes_are_exposed_with_standard_map_crud() -> None:
    routes = {(route.path, method) for route in router.routes for method in route.methods or set()}

    assert ("/map/paths", "GET") in routes
    assert ("/map/paths", "POST") in routes
    assert ("/map/paths/batch", "POST") in routes
    assert ("/map/paths/{path_id}", "PUT") in routes
    assert ("/map/paths/{path_id}", "DELETE") in routes


def test_path_accepts_ordered_three_dimensional_endpoints_and_constraints() -> None:
    path = _path_request()

    assert path.points[1] == [10.0, 0.0, 0.5]
    assert path.direction == "forward"
    assert path.min_width_m == 2.5
    assert path.max_slope_percent == 8.0
    assert path.device_types == ["agv", "hauler"]


@pytest.mark.parametrize(
    ("points", "max_slope_percent", "message"),
    [
        ([[0, 0, 0], [1, 1]], 8.0, "三个有限"),
        ([[0, 0, 0], [1, 0, 0], [2, 0, 0]], 8.0, "at most 2"),
        ([[0, 0, 0], [0, 0, 1]], 8.0, "水平位置不能重合"),
        ([[0, 0, 0], [10, 0, 2]], 10.0, "实际坡度超过"),
    ],
)
def test_path_rejects_invalid_or_unusable_geometry(points, max_slope_percent, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        _path_request(points=points, max_slope_percent=max_slope_percent)


def test_path_rejects_repeated_device_type_codes() -> None:
    with pytest.raises(ValidationError, match="不能重复"):
        _path_request(device_types=["agv", "agv"])


def test_path_response_preserves_only_persisted_route_information() -> None:
    path = MapPath(
        id=uuid.UUID("30000000-0000-0000-0000-000000000001"),
        **_path_request().model_dump(),
    )

    assert _path_dict(path) == {
        "id": "30000000-0000-0000-0000-000000000001",
        "code": "PATH-001",
        "name": "北侧坡道",
        "points": [[0.0, 0.0, 0.0], [10.0, 0.0, 0.5]],
        "start": [0.0, 0.0, 0.0],
        "end": [10.0, 0.0, 0.5],
        "direction": "forward",
        "min_width_m": 2.5,
        "max_slope_percent": 8.0,
        "device_types": ["agv", "hauler"],
        "status": "active",
    }


@pytest.mark.asyncio
async def test_batch_create_persists_all_paths_in_request_order() -> None:
    class Result:
        def scalars(self):
            return self

        def all(self):
            return []

    class Session:
        def __init__(self) -> None:
            self.added: list[MapPath] = []

        async def execute(self, _statement):
            return Result()

        def add_all(self, paths: list[MapPath]) -> None:
            self.added.extend(paths)

        async def flush(self) -> None:
            for index, path in enumerate(self.added, start=1):
                path.id = uuid.UUID(f"30000000-0000-0000-0000-{index:012d}")

    session = Session()
    created = await create_paths_batch(
        [_path_request(), _path_request(code="PATH-002", name="东侧坡道")],
        session,
        None,
    )

    assert [item["code"] for item in created] == ["PATH-001", "PATH-002"]
    assert [item["id"] for item in created] == [
        "30000000-0000-0000-0000-000000000001",
        "30000000-0000-0000-0000-000000000002",
    ]


@pytest.mark.asyncio
async def test_batch_create_rejects_duplicate_codes_before_writing() -> None:
    class Session:
        def add_all(self, _paths: list[MapPath]) -> None:
            raise AssertionError("重复编码的批量请求不能写入数据库")

    with pytest.raises(HTTPException) as exc_info:
        await create_paths_batch([_path_request(), _path_request()], Session(), None)

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "duplicate_path_code_in_batch"
