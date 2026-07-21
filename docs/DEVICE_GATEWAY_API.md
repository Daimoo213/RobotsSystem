# Device Gateway API

The backend is a database-backed control plane. Physical robots and Gazebo
bridges connect through this HTTP contract; this repository contains no ROS,
firmware, SLAM, navigation, or Gazebo world code.

## Bootstrap and Credentials

Set `DEVICE_GATEWAY_API_KEY` for the bootstrap endpoint. Send it as
`X-Device-Gateway-Key` when registering a new device:

```http
POST /api/devices/gateway/register
X-Device-Gateway-Key: <bootstrap-secret>
```

```json
{
  "code": "AGV-101",
  "name": "Material AGV 101",
  "type": "agv",
  "model": "VENDOR-AGV-3",
  "protocol_version": "v1",
  "capabilities": {"processes": ["material_transport"]},
  "section_tags": {"section": "A"},
  "permissions": {"travel": true, "work": true}
}
```

The one-time response includes `device_gateway_key`. Store it in the robot or
bridge secret store. All subsequent gateway calls, including any registration
metadata refresh, require that per-device key; the shared bootstrap key is not
accepted as a substitute.

## Telemetry and Mission State

`POST /api/devices/gateway/{device_code}/telemetry` requires the per-device
`X-Device-Gateway-Key`. Events are idempotent by `event_id` and retain the
gateway's boot/session and ordering information.

```json
{
  "event_id": "0fa85f64-5717-4562-b3fc-2c963f66afa6",
  "boot_id": "controller-boot-2026-07-20T12:00:00Z",
  "sequence": 42,
  "frame_id": "map",
  "schema_version": "v1",
  "observed_at": "2026-07-20T12:00:05Z",
  "status": "moving",
  "battery": 76.5,
  "position": {"x": 83.2, "y": 132.8, "z": 0},
  "health": {"location": "ok", "battery": "ok", "task": "ok", "safety": "ok"},
  "metrics": {
    "power_kw": 4.2,
    "energy_kwh_total": 18.7,
    "mileage_km_total": 4.8,
    "runtime_hours_total": 12.3,
    "localization_drift_meters": 0.08
  },
  "mission": {
    "execution_id": "gateway-execution-id-from-mission-start",
    "state": "running",
    "progress": 32.5,
    "completed_qty": 18.0
  }
}
```

Mission states are `accepted`, `running`, `paused`, `completed`, `failed`, and
`cancelled`. A mission only changes a task after this telemetry is accepted.
When the platform queues `mission_pause`, `mission_resume`, or
`mission_cancel`, its dashboard keeps the last confirmed task state until the
bridge reports `paused`, `running`, or `cancelled` respectively. A reassignment
is not dispatched to the new device until that `cancelled` report arrives.
Within the same `boot_id`, `sequence` must increase monotonically; duplicated
`event_id` values are returned idempotently and an older sequence is rejected.
The control plane does not infer omitted energy, mileage, runtime, or drift
values.

## Calibration

`POST /api/devices/gateway/{device_code}/calibration` records an outcome from
the bridge after it has performed a real QR/AprilTag or manual localization
correction. It is an audit API, not a ROS/EKF implementation.

```json
{
  "event_id": "calibration-20260720-0001",
  "qrcode_id": "A-START-01",
  "source": "automatic",
  "observed_at": "2026-07-20T12:01:00Z",
  "success": true,
  "position": {"x": 83.2, "y": 132.8, "z": 0},
  "drift_meters": 0.06
}
```

## Map Assets And Point Clouds

Mapping bridges register external mesh/occupancy-map artifacts with
`POST /api/map/gateway/assets` using the bootstrap gateway key. Payloads use
an immutable `event_id`, `source_id`, `asset_type` (`mesh_gltf`, `octomap`, or
`geojson`), `asset_uri`, optional SHA-256 checksum, map `frame_id`, metadata,
and observed timestamp. The API stores metadata and a reference only; the
artifact remains in the configured object store or mapping pipeline. The O&M
browser renders `mesh_gltf` assets only from a browser-accessible HTTPS `.gltf`
or `.glb` URL in the `map` frame; use a time-bounded, CORS-enabled object-store
URL for a private bucket.

Point-cloud snapshots use `POST /api/pointcloud/gateway/snapshots`, again with
the bootstrap gateway key. Each payload must carry an immutable `event_id`, a
source ID, frame ID, observation timestamp, and real `[x,y,z]` points. Latest
snapshots are exposed to authenticated dashboards at `/api/pointcloud/latest`.

Camera/vision gateways use `POST /api/cameras/gateway/register` and
`POST /api/cameras/gateway/{camera_code}/detections`. The platform never
generates camera detections itself.

## Commands

`GET /api/devices/gateway/{device_code}/commands` returns non-expired durable
commands in priority order. Delivery is at-least-once, so the client must
deduplicate by the command `id`, persist its outcome across reconnects, and
repeat the ACK until the HTTP request succeeds.

Commands include `mission_start`, `mission_pause`, `mission_resume`,
`mission_cancel`, `pause`, `resume`, `estop`, `reset`, and `release`.

`POST /api/devices/gateway/{device_code}/commands/{command_id}/ack` records
the command outcome. Repeating an identical terminal acknowledgement is safe;
a contradictory acknowledgement is rejected.

```json
{"status": "acknowledged", "message": "controller accepted command"}
```

## Operating Guarantees

- Tasks require a persisted map point and are dispatched only to registered,
  heartbeat-valid, capability-matching devices.
- Global emergency stop and alert holds are durable commands for every target
  device. Recovery queues a `release` command for every gateway device and
  requires the physical controller to ACK that it is safe. The robot must still
  enforce its own hardware and local fail-safe.
- Empty projects return empty lists and zero metrics. The API does not create
  devices, map data, tasks, point clouds, camera detections, or task progress.
