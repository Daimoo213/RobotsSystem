"""Project map-frame contract tests."""

import pytest
from fastapi import HTTPException

from app.api.devices import GatewayCalibrationReport, GatewayPosition
from app.core.coordinates import MAP_FRAME_CONVENTION, ensure_map_frame


def test_map_coordinate_convention_is_right_handed_and_z_up() -> None:
    assert "右手" in MAP_FRAME_CONVENTION
    assert "+Z 竖直向上" in MAP_FRAME_CONVENTION
    assert "逆时针 90 度" in MAP_FRAME_CONVENTION


def test_gateway_position_openapi_describes_axis_directions() -> None:
    properties = GatewayPosition.model_json_schema()["properties"]
    assert "+X" in properties["x"]["description"]
    assert "+Y" in properties["y"]["description"]
    assert "+Z" in properties["z"]["description"]


def test_calibration_defaults_to_map_frame() -> None:
    report = GatewayCalibrationReport.model_validate(
        {
            "event_id": "calibration-001",
            "source": "automatic",
            "observed_at": "2026-07-30T12:00:00Z",
            "success": True,
        }
    )
    assert report.frame_id == "map"


def test_mismatched_map_frame_is_rejected() -> None:
    ensure_map_frame("map", "map")
    with pytest.raises(HTTPException) as exc_info:
        ensure_map_frame("odom", "map")
    assert exc_info.value.status_code == 422
    assert "map" in exc_info.value.detail
