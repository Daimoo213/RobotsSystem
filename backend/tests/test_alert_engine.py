from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.services.alert_engine import AlertEngine


def _state(
    *,
    device_id: uuid.UUID,
    code: str,
    x: float,
    y: float,
    status: str = "moving",
    battery: float = 80.0,
    health: dict[str, str] | None = None,
) -> dict:
    return {
        "id": str(device_id),
        "code": code,
        "status": status,
        "battery": battery,
        "position": {"x": x, "y": y},
        "health": health or {"task": "ok"},
    }


def test_derive_violations_detects_collision_and_geofence() -> None:
    first_id = uuid.uuid4()
    second_id = uuid.uuid4()
    region = SimpleNamespace(
        id=uuid.uuid4(),
        code="R-RESTRICT-01",
        polygon=[[0, 0], [5, 0], [5, 5], [0, 5]],
    )

    violations = AlertEngine().derive_violations(
        [
            _state(device_id=first_id, code="AGV-01", x=1.0, y=1.0),
            _state(device_id=second_id, code="AGV-02", x=2.0, y=1.0),
        ],
        [region],
    )

    categories = {violation.category for violation in violations}
    assert categories == {"collision_risk", "geofence_breach"}
    collision = next(violation for violation in violations if violation.category == "collision_risk")
    assert set(collision.safety_hold_device_ids) == {first_id, second_id}


def test_derive_violations_detects_low_battery_and_fault() -> None:
    device_id = uuid.uuid4()

    violations = AlertEngine().derive_violations(
        [
            _state(
                device_id=device_id,
                code="EX-01",
                x=20.0,
                y=20.0,
                status="fault",
                battery=10.0,
                health={"task": "fail"},
            )
        ],
        [],
    )

    by_category = {violation.category: violation for violation in violations}
    assert set(by_category) == {"low_battery", "device_fault"}
    assert by_category["low_battery"].level == "warning"
    assert by_category["device_fault"].level == "critical"
