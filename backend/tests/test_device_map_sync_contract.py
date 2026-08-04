"""Contract checks for robot-facing map discovery and point-cloud download."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException, Response

from app.api import device_map
from app.api.device_map import (
    DeviceMapSnapshot,
    PointCloudMapSummary,
    _etag_matches,
    _manifest,
    _pointcloud_summary_statement,
    _validate_snapshot_frames,
    map_sync_revision,
    router,
)
from app.api.devices import GatewayRegistration, _require_device_key
from app.models.models import Device, MapAsset, MapPath, MapPoint, MapRegion, PointCloudMap, Project


NOW = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)


def _project(frame_id: str = "map") -> Project:
    return Project(
        id=uuid.UUID("10000000-0000-0000-0000-000000000001"),
        code="SITE-001",
        name="项目现场",
        map_frame=frame_id,
        is_active=True,
        created_at=NOW,
    )


def _point(code: str, x: float) -> MapPoint:
    return MapPoint(
        id=uuid.uuid5(uuid.NAMESPACE_DNS, f"point:{code}"),
        code=code,
        name=code,
        point_type="work",
        x=x,
        y=2.0,
        z=0.5,
        device_types=["agv"],
        color="#2FD7FF",
    )


def _region(code: str) -> MapRegion:
    polygon = [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]]
    return MapRegion(
        id=uuid.uuid5(uuid.NAMESPACE_DNS, f"region:{code}"),
        code=code,
        name=code,
        region_type="work",
        polygon=polygon,
        min_z=0.0,
        max_z=0.5,
        volumes=[{"polygon": polygon, "min_z": 0.0, "max_z": 0.5}],
        color="#2FD7FF",
        created_at=NOW,
    )


def _path(
    code: str,
    end_z: float = 0.5,
    *,
    start: list[float] | None = None,
    end: list[float] | None = None,
    direction: str = "bidirectional",
    status: str = "active",
) -> MapPath:
    return MapPath(
        id=uuid.uuid5(uuid.NAMESPACE_DNS, f"path:{code}"),
        code=code,
        name=code,
        points=[start or [0.0, 0.0, 0.0], end or [10.0, 0.0, end_z]],
        direction=direction,
        min_width_m=2.5,
        max_slope_percent=10.0,
        device_types=["agv"],
        status=status,
    )


def _asset(event_id: str, frame_id: str = "map") -> MapAsset:
    return MapAsset(
        id=uuid.uuid5(uuid.NAMESPACE_DNS, f"asset:{event_id}"),
        event_id=event_id,
        source_id="mapper-01",
        asset_type="octomap",
        asset_uri=f"https://maps.example.test/{event_id}.bt",
        checksum_sha256=hashlib.sha256(event_id.encode("utf-8")).hexdigest(),
        frame_id=frame_id,
        asset_metadata={"resolution": 0.1},
        observed_at=NOW,
        received_at=NOW,
    )


def _pointcloud(map_id: str = "map-001", frame_id: str = "map") -> PointCloudMap:
    return PointCloudMap(
        scope="current",
        map_id=map_id,
        source_id="slam-01",
        frame_id=frame_id,
        points=[[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]],
        map_metadata={"voxel_size": 0.1},
        observed_at=NOW,
        received_at=NOW,
    )


def _pointcloud_summary(map_id: str = "map-001", frame_id: str = "map") -> PointCloudMapSummary:
    return PointCloudMapSummary(
        map_id=map_id,
        source_id="slam-01",
        frame_id=frame_id,
        points_count=2,
        map_metadata={"voxel_size": 0.1},
        observed_at=NOW,
        received_at=NOW,
    )


def _device(enabled: bool = True) -> Device:
    return Device(
        id=uuid.UUID("20000000-0000-0000-0000-000000000001"),
        code="AGV-101",
        name="运输机器人 101",
        type="agv",
        gateway_enabled=enabled,
        gateway_key_hash=hashlib.sha256(b"device-secret").hexdigest(),
    )


def test_robot_map_sync_routes_are_exposed() -> None:
    routes = {(route.path, method) for route in router.routes for method in route.methods or set()}

    assert ("/devices/gateway/{device_code}/map-sync", "GET") in routes
    assert ("/devices/gateway/{device_code}/map-sync/pointcloud", "GET") in routes


def test_sync_revision_is_stable_for_query_order_and_changes_with_real_content() -> None:
    first = DeviceMapSnapshot(
        _project(),
        [_region("R-002"), _region("R-001")],
        [_point("P-002", 2.0), _point("P-001", 1.0)],
        [_asset("asset-002"), _asset("asset-001")],
        _pointcloud_summary(),
    )
    reordered = DeviceMapSnapshot(
        first.project,
        list(reversed(first.regions)),
        list(reversed(first.points)),
        list(reversed(first.assets)),
        first.pointcloud,
    )
    changed = DeviceMapSnapshot(
        first.project,
        first.regions,
        [_point("P-002", 20.0), _point("P-001", 1.0)],
        first.assets,
        first.pointcloud,
    )

    assert map_sync_revision(first) == map_sync_revision(reordered)
    assert map_sync_revision(first) != map_sync_revision(changed)


def test_sync_revision_includes_real_robot_paths() -> None:
    base = DeviceMapSnapshot(_project(), [], [], [], None)
    with_path = DeviceMapSnapshot(_project(), [], [], [], None, [_path("PATH-001")])
    changed_path = DeviceMapSnapshot(_project(), [], [], [], None, [_path("PATH-001", 0.8)])

    assert map_sync_revision(base) != map_sync_revision(with_path)
    assert map_sync_revision(with_path) != map_sync_revision(changed_path)
    assert _manifest(with_path, _device()).paths[0]["points"][-1] == [10.0, 0.0, 0.5]


def test_manifest_exposes_directed_road_edges_and_same_cell_junctions() -> None:
    first = _path(
        "PATH-A",
        start=[0.0, 0.0, 0.0],
        end=[1.0, 0.0, 0.0],
        direction="forward",
    )
    second = _path(
        "PATH-B",
        start=[1.0, 0.0, 0.0],
        end=[2.0, 0.0, 0.0],
        direction="reverse",
    )

    manifest = _manifest(DeviceMapSnapshot(_project(), [], [], [], None, [first, second]), _device())
    edges = {edge.id: edge for edge in manifest.road_network.edges}

    assert manifest.schema_version == "v2"
    assert manifest.road_network.voxel_cell_size_m == 0.05
    assert edges[f"road:{first.id}:forward"].from_node_id == f"road:{first.id}:start"
    assert edges[f"road:{first.id}:forward"].to_node_id == f"road:{first.id}:end"
    assert edges[f"road:{second.id}:reverse"].from_node_id == f"road:{second.id}:end"
    assert edges[f"road:{second.id}:reverse"].to_node_id == f"road:{second.id}:start"
    junctions = [edge for edge in edges.values() if edge.kind == "junction"]
    assert {(edge.from_node_id, edge.to_node_id) for edge in junctions} == {
        (f"road:{first.id}:end", f"road:{second.id}:start"),
        (f"road:{second.id}:start", f"road:{first.id}:end"),
    }


def test_manifest_connects_face_adjacent_road_endpoints() -> None:
    first = _path("PATH-A", start=[0.0, 0.0, 0.0], end=[0.05, 0.0, 0.0])
    second = _path("PATH-B", start=[0.1, 0.0, 0.0], end=[1.0, 0.0, 0.0])

    network = _manifest(DeviceMapSnapshot(_project(), [], [], [], None, [first, second]), _device()).road_network
    junctions = [edge for edge in network.edges if edge.kind == "junction"]

    assert {(edge.from_node_id, edge.to_node_id) for edge in junctions} == {
        (f"road:{first.id}:end", f"road:{second.id}:start"),
        (f"road:{second.id}:start", f"road:{first.id}:end"),
    }


def test_manifest_does_not_connect_diagonally_adjacent_road_endpoints() -> None:
    first = _path("PATH-A", start=[0.0, 0.0, 0.0], end=[0.05, 0.0, 0.0])
    second = _path("PATH-B", start=[0.1, 0.05, 0.0], end=[1.0, 1.0, 0.0])

    network = _manifest(DeviceMapSnapshot(_project(), [], [], [], None, [first, second]), _device()).road_network

    assert [edge for edge in network.edges if edge.kind == "junction"] == []


def test_disabled_roads_remain_in_records_but_not_in_traversable_network() -> None:
    disabled = _path("PATH-DISABLED", status="disabled")
    manifest = _manifest(DeviceMapSnapshot(_project(), [], [], [], None, [disabled]), _device())

    assert [path["code"] for path in manifest.paths] == ["PATH-DISABLED"]
    assert manifest.road_network.nodes == []
    assert manifest.road_network.edges == []


def test_manifest_exposes_real_semantic_map_without_embedding_point_array() -> None:
    snapshot = DeviceMapSnapshot(
        _project(),
        [_region("R-001")],
        [_point("P-001", 1.0)],
        [_asset("asset-001")],
        _pointcloud_summary(),
    )

    manifest = _manifest(snapshot, _device())

    assert manifest.device_code == "AGV-101"
    assert manifest.frame_id == "map"
    assert manifest.pointcloud.has_data is True
    assert manifest.pointcloud.points_count == 2
    assert "points" not in manifest.pointcloud.model_dump()
    assert manifest.pointcloud.download_path.endswith("/map-sync/pointcloud?map_id=map-001")
    assert manifest.assets[0]["checksum_sha256"] == _asset("asset-001").checksum_sha256


def test_empty_manifest_is_explicit_and_does_not_generate_map_data() -> None:
    manifest = _manifest(DeviceMapSnapshot(_project(), [], [], [], None), _device())

    assert manifest.regions == []
    assert manifest.points == []
    assert manifest.paths == []
    assert manifest.assets == []
    assert manifest.pointcloud.has_data is False
    assert manifest.pointcloud.points_count == 0
    assert manifest.pointcloud.download_path is None


def test_stored_frame_mismatch_is_rejected() -> None:
    snapshot = DeviceMapSnapshot(_project("site_map"), [], [], [_asset("asset-001", "map")], None)

    with pytest.raises(HTTPException) as exc_info:
        _validate_snapshot_frames(snapshot)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "stored_map_frame_mismatch"


def test_etag_matching_accepts_strong_weak_and_list_values() -> None:
    etag = '"map-sync-revision"'

    assert _etag_matches(etag, etag)
    assert _etag_matches(f'"other", W/{etag}', etag)
    assert _etag_matches("*", etag)
    assert not _etag_matches('"old"', etag)


def test_manifest_query_does_not_select_complete_point_array() -> None:
    selected_columns = set(_pointcloud_summary_statement().selected_columns.keys())

    assert "points" not in selected_columns
    assert "points_count" in selected_columns


def test_registration_rejects_path_unsafe_device_codes() -> None:
    with pytest.raises(ValueError):
        GatewayRegistration(code="AGV/101", name="运输机器人", type="agv")


@pytest.mark.asyncio
async def test_manifest_endpoint_returns_etag_and_304_after_device_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    class Result:
        def __init__(self, values):
            self.values = values

        def scalars(self):
            return self

        def all(self):
            return self.values

        def mappings(self):
            return self

        def one_or_none(self):
            return self.values

    class Session:
        def __init__(self):
            self.execute_values = [
                [_project()],
                [_region("R-001")],
                [_point("P-001", 1.0)],
                [_asset("asset-001")],
                {
                    "map_id": "map-001",
                    "source_id": "slam-01",
                    "frame_id": "map",
                    "points_count": 2,
                    "map_metadata": {"voxel_size": 0.1},
                    "observed_at": NOW,
                    "received_at": NOW,
                },
                [],
            ]

        async def connection(self, **_kwargs):
            return None

        async def execute(self, _statement):
            return Result(self.execute_values.pop(0))

    async def allow_device(_db, _device_code, _key):
        return _device()

    monkeypatch.setattr(device_map, "_require_device_key", allow_device)
    response = Response()
    manifest = await device_map.get_gateway_map_sync(
        "AGV-101", response, Session(), "device-secret", None
    )

    assert manifest.device_code == "AGV-101"
    etag = response.headers["etag"]
    assert etag.startswith('"map-sync-')
    assert response.headers["x-map-sync-revision"] == manifest.sync_revision

    not_modified = await device_map.get_gateway_map_sync(
        "AGV-101", Response(), Session(), "device-secret", etag
    )
    assert isinstance(not_modified, Response)
    assert not_modified.status_code == 304
    assert not_modified.body == b""


@pytest.mark.asyncio
async def test_current_pointcloud_download_returns_complete_real_points(monkeypatch: pytest.MonkeyPatch) -> None:
    class Session:
        def __init__(self):
            self.scalar_values = [_pointcloud("map-current")]

        async def connection(self, **_kwargs):
            return None

        async def execute(self, _statement):
            return type(
                "Result",
                (),
                {"scalars": lambda self: self, "all": lambda self: [_project()]},
            )()

        async def scalar(self, _statement):
            return self.scalar_values.pop(0)

    async def allow_device(_db, _device_code, _key):
        return _device()

    monkeypatch.setattr(device_map, "_require_device_key", allow_device)
    response = Response()
    result = await device_map.download_gateway_pointcloud(
        "AGV-101",
        response,
        "map-current",
        Session(),
        "device-secret",
        None,
    )

    assert result.map_id == "map-current"
    assert result.points == [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
    assert result.total_count == 2
    assert response.headers["etag"].startswith('"pointcloud-')


@pytest.mark.asyncio
async def test_device_key_auth_rejects_wrong_key_and_disabled_device() -> None:
    class Result:
        def __init__(self, device: Device):
            self.device = device

        def scalar_one_or_none(self) -> Device:
            return self.device

    class Session:
        def __init__(self, device: Device):
            self.device = device

        async def execute(self, _statement):
            return Result(self.device)

    with pytest.raises(HTTPException) as wrong_key:
        await _require_device_key(Session(_device()), "AGV-101", "bootstrap-or-other-device-key")
    assert wrong_key.value.status_code == 401

    with pytest.raises(HTTPException) as disabled:
        await _require_device_key(Session(_device(False)), "AGV-101", "device-secret")
    assert disabled.value.status_code == 403


@pytest.mark.asyncio
async def test_pointcloud_download_rejects_stale_map_id(monkeypatch: pytest.MonkeyPatch) -> None:
    class Session:
        def __init__(self):
            self.scalar_values = [_pointcloud("map-current")]

        async def connection(self, **_kwargs):
            return None

        async def execute(self, _statement):
            return type(
                "Result",
                (),
                {"scalars": lambda self: self, "all": lambda self: [_project()]},
            )()

        async def scalar(self, _statement):
            return self.scalar_values.pop(0)

    async def allow_device(_db, _device_code, _key):
        return _device()

    monkeypatch.setattr(device_map, "_require_device_key", allow_device)

    with pytest.raises(HTTPException) as exc_info:
        await device_map.download_gateway_pointcloud(
            "AGV-101",
            Response(),
            "map-old",
            Session(),
            "device-secret",
            None,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "map_version_changed"
    assert exc_info.value.detail["current_map_id"] == "map-current"
