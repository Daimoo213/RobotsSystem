from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.devices import (
    GatewayCommandAck,
    GatewayCameraTelemetry,
    GatewayRegistration,
    GatewayTelemetry,
    _camera_state,
    require_gateway_api_key,
    router,
)
from app.api.map import MapAssetIn
from app.core.config import Settings, settings
from app.models.models import DeviceCommand
from app.services.device_connectivity import connection_health, connection_status


def test_gateway_routes_are_exposed() -> None:
    routes = {(route.path, method) for route in router.routes for method in route.methods or set()}

    assert ("/devices/gateway/register", "POST") in routes
    assert ("/devices/gateway/{device_code}/telemetry", "POST") in routes
    assert ("/devices/gateway/{device_code}/commands", "GET") in routes
    assert ("/devices/gateway/{device_code}/commands/{command_id}/ack", "POST") in routes
    assert ("/devices/{device_id}/camera", "GET") in routes
    assert ("/devices/{device_id}/camera/control", "POST") in routes


def test_gateway_payloads_preserve_operational_data() -> None:
    registration = GatewayRegistration(code="AGV-101", name="Material AGV 101", type="agv")
    telemetry = GatewayTelemetry.model_validate(
        {
            "event_id": "event-001",
            "boot_id": "boot-001",
            "sequence": 1,
            "status": "moving",
            "battery": 76.5,
            "position": {"x": 21.2, "y": 18.4},
            "vendor_fault_code": "MOTOR_TEMP_WARN",
        }
    )
    acknowledgement = GatewayCommandAck.model_validate(
        {"status": "acknowledged", "message": "brake applied", "controller_time": "2026-07-20T12:00:00Z"}
    )

    assert registration.capabilities == {}
    assert telemetry.model_dump()["vendor_fault_code"] == "MOTOR_TEMP_WARN"
    assert acknowledgement.model_dump()["controller_time"] == "2026-07-20T12:00:00Z"
    assert {column.name for column in DeviceCommand.__table__.columns} >= {
        "id",
        "device_id",
        "command",
        "status",
        "acknowledgement",
        "idempotency_key",
        "mission_execution_id",
    }


def test_camera_state_requires_sensor_enablement_before_exposing_stream() -> None:
    camera = GatewayCameraTelemetry.model_validate(
        {
            "enabled": True,
            "is_online": True,
            "stream_url": "https://media.example.test/robot-101/index.m3u8",
            "stream_protocol": "hls",
        }
    )
    device = type("DeviceStub", (), {
        "capabilities": {"camera": {"stream_url": camera.stream_url, "stream_protocol": "hls"}},
        "operational_metrics": {"camera": {"enabled": False, "is_online": True}},
    })()

    disabled_state = _camera_state(device)
    assert disabled_state["available"] is True
    assert disabled_state["enabled"] is False
    assert disabled_state["stream_url"] is None

    device.operational_metrics = {"camera": camera.model_dump(exclude_none=True)}
    enabled_state = _camera_state(device)
    assert enabled_state == {
        "available": True,
        "enabled": True,
        "is_online": True,
        "stream_url": "https://media.example.test/robot-101/index.m3u8",
        "stream_protocol": "hls",
    }


@pytest.mark.asyncio
async def test_gateway_key_is_required_in_every_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "debug", True)
    monkeypatch.setattr(settings, "device_gateway_api_key", "gateway-secret")
    with pytest.raises(HTTPException) as debug_missing_key:
        await require_gateway_api_key(None)
    assert debug_missing_key.value.status_code == 401

    monkeypatch.setattr(settings, "debug", False)
    monkeypatch.setattr(settings, "device_gateway_api_key", None)
    with pytest.raises(HTTPException) as missing_key:
        await require_gateway_api_key(None)
    assert missing_key.value.status_code == 503

    monkeypatch.setattr(settings, "device_gateway_api_key", "gateway-secret")
    with pytest.raises(HTTPException) as invalid_key:
        await require_gateway_api_key("wrong-key")
    assert invalid_key.value.status_code == 401

    await require_gateway_api_key("gateway-secret")


@pytest.mark.asyncio
async def test_existing_registration_uses_device_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.devices import register_gateway_device

    device = type("DeviceStub", (), {
        "id": "device-id", "code": "AGV-101", "gateway_key_hash": __import__("hashlib").sha256(b"device-secret").hexdigest(),
        "gateway_enabled": True, "name": "old", "type": "agv", "model": None, "capabilities": {},
        "section_tags": {}, "permissions": {}, "section_id": None, "health": {}, "last_heartbeat": None,
    })()

    class Session:
        async def execute(self, _statement):
            return type("Result", (), {"scalar_one_or_none": lambda self: device})()

        async def flush(self):
            return None

        def add(self, _record):
            return None

        async def commit(self):
            return None

    monkeypatch.setattr("app.api.devices._publish_device_snapshot", lambda _db: __import__("asyncio").sleep(0))
    request = GatewayRegistration(code="AGV-101", name="Material AGV", type="agv")
    with pytest.raises(HTTPException) as denied:
        await register_gateway_device(request, Session(), "bootstrap-secret")
    assert denied.value.status_code == 401


def test_production_settings_require_gateway_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEVICE_GATEWAY_API_KEY", raising=False)
    with pytest.raises(ValueError, match="device_gateway_api_key"):
        Settings(_env_file=None, debug=False)


def test_map_asset_requires_external_absolute_uri() -> None:
    asset = MapAssetIn.model_validate(
        {
            "event_id": "mesh-001", "source_id": "mapper-001", "asset_type": "mesh_gltf",
            "asset_uri": "https://maps.example.test/site/mesh.glb", "observed_at": "2026-07-20T12:00:00Z",
        }
    )
    assert asset.asset_uri.startswith("https://")
    with pytest.raises(ValueError, match="asset_uri"):
        MapAssetIn.model_validate(
            {
                "event_id": "mesh-002", "source_id": "mapper-001", "asset_type": "mesh_gltf",
                "asset_uri": "/static/mesh.glb", "observed_at": "2026-07-20T12:00:00Z",
            }
        )


def test_connection_status_expires_after_the_heartbeat_window() -> None:
    from datetime import datetime, timedelta, timezone

    now = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
    assert connection_status(now - timedelta(seconds=15), now) == "online"
    assert connection_status(now - timedelta(seconds=16), now) == "offline"
    assert connection_status(None, now) == "offline"
    assert connection_health(now - timedelta(seconds=16), now) == "fail"
