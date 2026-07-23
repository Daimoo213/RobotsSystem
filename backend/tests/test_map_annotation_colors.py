"""Map annotation color request-contract checks."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.map import MapPointInput, MapRegionInput


def test_map_annotation_colors_default_to_the_grid_accent() -> None:
    region = MapRegionInput(
        code="REGION-1",
        name="作业区",
        region_type="work",
        polygon=[[0, 0], [2, 0], [0, 2]],
    )
    point = MapPointInput(
        code="POINT-1",
        name="装载点",
        point_type="loading",
        x=1,
        y=1,
    )

    assert region.color == "#2FD7FF"
    assert point.color == "#2FD7FF"


@pytest.mark.parametrize("color", ["cyan", "2FD7FF", "#2FD7F", "#GGGGGG"])
def test_map_annotation_colors_require_six_digit_hex(color: str) -> None:
    with pytest.raises(ValidationError):
        MapPointInput(
            code="POINT-1",
            name="装载点",
            point_type="loading",
            x=1,
            y=1,
            color=color,
        )
