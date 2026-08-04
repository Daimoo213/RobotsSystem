"""Contract checks for persistent 3D map-grid configuration."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.map import VOXEL_CELL_SIZE_M, VOXEL_CELL_VOLUME_M3, MapGridConfig, MapRegionInput, router


def test_3d_grid_routes_are_exposed() -> None:
    routes = {(route.path, method) for route in router.routes for method in route.methods or set()}

    assert ("/map/grid-config", "GET") in routes
    assert ("/map/grid-config", "PUT") in routes


def test_region_defaults_to_one_half_meter_volume() -> None:
    region = MapRegionInput(
        code="REGION-3D-01",
        name="空间作业区",
        region_type="work",
        polygon=[[0, 0], [2, 0], [0, 2]],
    )

    assert region.min_z == 0.0
    assert region.max_z == 0.5


def test_region_requires_positive_vertical_extent() -> None:
    with pytest.raises(ValidationError, match="顶部高度"):
        MapRegionInput(
            code="REGION-3D-02",
            name="无效区域",
            region_type="work",
            polygon=[[0, 0], [2, 0], [0, 2]],
            min_z=1,
            max_z=1,
        )


def test_region_accepts_multiple_volume_components() -> None:
    region = MapRegionInput(
        code="REGION-3D-03",
        name="多区域作业面",
        region_type="work",
        polygon=[[0, 0], [1, 0], [0, 1]],
        volumes=[
            {"polygon": [[0, 0], [1, 0], [1, 1], [0, 1]], "min_z": 0, "max_z": 0.5},
            {"polygon": [[2, 0], [3, 0], [3, 1], [2, 1]], "min_z": 0.5, "max_z": 1},
        ],
    )

    assert len(region.volumes) == 2
    assert region.volumes[1].min_z == 0.5


def test_region_accepts_more_than_the_legacy_component_limit() -> None:
    component = {"polygon": [[0, 0], [1, 0], [1, 1], [0, 1]], "min_z": 0, "max_z": 0.5}
    region = MapRegionInput(
        code="REGION-3D-04",
        name="多次框选区域",
        region_type="work",
        polygon=component["polygon"],
        volumes=[component] * 129,
    )

    assert len(region.volumes) == 129


def test_grid_configuration_limits_rendered_line_count() -> None:
    config = MapGridConfig(extent_length=10, extent_width=10, vertical_layers=8)

    assert config.line_color == "#5BB7FF"
    assert config.cell_volume_m3 == VOXEL_CELL_VOLUME_M3
    assert config.cell_length == VOXEL_CELL_SIZE_M
    assert config.cell_width == VOXEL_CELL_SIZE_M
    assert config.cell_height == VOXEL_CELL_SIZE_M
    assert config.display_voxel_multiplier == 1
    with pytest.raises(ValidationError, match="64"):
        MapGridConfig(extent_length=1000, extent_width=1000)


def test_grid_rejects_dimensions_that_do_not_match_the_fixed_cell_size() -> None:
    with pytest.raises(ValidationError, match="0.05"):
        MapGridConfig(cell_length=0.1)


def test_grid_rejects_display_extent_that_cuts_through_a_minimum_voxel() -> None:
    with pytest.raises(ValidationError, match="整数倍"):
        MapGridConfig(extent_length=10.03)


def test_grid_limits_display_voxel_aggregation_without_changing_real_voxels() -> None:
    config = MapGridConfig(display_voxel_multiplier=8)

    assert config.display_voxel_multiplier == 8
    assert config.cell_length == VOXEL_CELL_SIZE_M
    with pytest.raises(ValidationError):
        MapGridConfig(display_voxel_multiplier=33)


def test_default_grid_keeps_the_map_origin_at_its_center() -> None:
    config = MapGridConfig()

    assert config.origin_x + config.extent_length / 2 == 0
    assert config.origin_y + config.extent_width / 2 == 0
