# Device Gateway API

The backend is a database-backed control plane. Physical robots and Gazebo
bridges connect through this HTTP contract; this repository contains no ROS,
firmware, SLAM, navigation, or Gazebo world code.

## 地图坐标系方向约定（Map Frame）

所有设备位置、定位校准、点云、地图点位、区域和地图资产必须使用当前项目的 `map_frame`，默认名称为 `map`。该坐标系是固定的右手笛卡尔坐标系，单位为米：

- 原点 `(0,0,0)` 是现场联调时确定的固定地图基准点，更新完整地图时不得改变。
- `+X` 沿项目选定的现场基准方向。
- 观察者位于 `+Z` 一侧俯视地图时，`+Y` 是从 `+X` 逆时针旋转 90° 的方向。
- `+Z` 竖直向上，`Z=0` 是项目约定的高程基准面。
- 若项目采用 ENU 地理对齐，推荐 `+X=东`、`+Y=北`、`+Z=上`；否则以现场坐标基准记录为准。

```text
             +Y
              ^
              |
原点 (0,0,0)  +------------> +X

+Z 垂直地图平面向上。
```

设备侧必须先完成来源坐标到项目地图坐标的变换 `p_map = R_map_source * p_source + t_map_source`，再填写数值和 `frame_id`。平台不提供 ROS TF 或厂商坐标转换服务。`frame_id` 与项目配置不一致时，遥测、校准、完整点云和地图资产接口返回 HTTP 422。

位置对象使用 `{x,y,z}`，点云点使用 `[x,y,z]`，区域多边形使用 `[x,y]`。栅格 `origin_x/origin_y/origin_z` 只是栅格最小角，不会重新定义地图原点。当前 v1 不定义 `yaw`、欧拉角或四元数。

O&M 内部渲染转换为 `(x_three,y_three,z_three)=(x_map,z_map,-y_map)`，设备不得提前转换。`mesh_gltf` 导出轴应为 `X_gltf=X_map`、`Y_gltf=Z_map`、`Z_gltf=-Y_map`，而 `metadata.origin=[x,y,z]` 仍使用项目地图坐标。完整说明见 [设备开发与接入规范](./设备开发与接入规范.md#31-map-坐标系方向约定)。

## 初始化与凭据

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
  "protocol_version": "v2",
  "capabilities": {
    "processes": ["material_transport"],
    "camera": {
      "stream_url": "https://media.example.test/AGV-101/index.m3u8",
      "stream_protocol": "hls"
    }
  },
  "work_capacities": [
    {
      "capability_code": "material_transport",
      "output_unit": "t",
      "rate_per_hour": 18.5,
      "source": "field_calibrated",
      "evidence_ref": "CAL-AGV-101-20260731",
      "reported_at": "2026-07-31T16:00:00+08:00",
      "valid_until": "2026-10-31T23:59:59+08:00"
    }
  ],
  "section_tags": {"section": "A"},
  "permissions": {"travel": true, "work": true}
}
```

首次注册响应只返回一次 `device_gateway_key`。机器人或桥接程序必须将它保存到本机密钥存储；后续遥测、命令、ACK、校正和地图同步均使用该设备专属密钥，共享初始化密钥不能替代。

`protocol_version` 只接受 `v1` 或 `v2`。`v1` 保留基础目标任务兼容；需要接收结构化作业参数、执行阶段和作业后返航计划的设备必须注册为 `v2`。平台不会把 v2 任务派发给 v1 设备。

`DEVICE_GATEWAY_API_KEY` 是系统级共享接入密钥，只用于首次创建设备，以及没有设备身份的独立建图、地图资产和视觉网关写入接口。它不得下发给普通机器人作为长期运行凭据。机器人同步地图时必须使用首次注册获得的设备专属 `device_gateway_key`。

`work_capacities` 是集群资源规划的真实数据源，每条记录必须提供能力编码、工作量单位、大于 0 的每小时产能、来源、证据编号和上报时间。来源只接受 `manufacturer_rated`、`field_calibrated`、`telemetry_observed`、`contract_verified`。缺少有效产能声明的设备不会被用于覆盖任务交付量，平台不会以设备类型、速度或前端数据推测产能。

设备编码同时用于 URL 路径，当前只允许字母、数字、点、下划线、冒号和连字符，并且必须以字母或数字开头。

`capabilities.camera` declares an operator-controllable robot camera. Its
`stream_url` must be a browser-playable HLS manifest or MP4 URL, and
`stream_protocol` is `hls` or `mp4`. Do not register RTSP URLs here: browsers
cannot play RTSP directly. Expose RTSP through an authenticated media gateway
that produces HLS before providing its URL to the control plane.

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
  "camera": {
    "enabled": true,
    "is_online": true,
    "stream_url": "https://media.example.test/AGV-101/index.m3u8",
    "stream_protocol": "hls"
  },
  "mission": {
    "execution_id": "gateway-execution-id-from-mission-start",
    "state": "running",
    "phase": "navigating_to_target",
    "phase_sequence": 3,
    "phase_progress": 45.0,
    "progress": 32.5,
    "completed_qty": 18.0
  }
}
```

任务状态为 `accepted`、`running`、`paused`、`completed`、`failed`、`cancelled`。任务只有在遥测被平台接受后才改变。暂停、恢复、取消命令入队不代表动作已经完成；平台分别等待设备报告 `paused`、`running`、`cancelled`。改派必须先收到旧设备的 `cancelled`。

v2 执行阶段固定为：

```text
preparing -> navigating_to_target -> arrived_at_target -> working
          -> work_completed -> returning -> returned
```

不需要返回的任务在 `work_completed` 后可以结束；要求返回的任务必须继续到 `returned`。`phase_sequence` 从 0 开始连续递增；阶段未变化但阶段进度发生变化时也必须递增。相同序号只允许完全相同的幂等重传，序号回退、同序号不同内容、阶段回退或跳过关键阶段均返回 409。暂停和恢复可保持相同阶段与序号。

返航任务提交 `state=completed` 时还必须提交：

```json
{
  "phase": "returned",
  "result": {
    "return_completed": true,
    "return_point_id": "mission_start 中 return.target.point_id"
  }
}
```

缺少以上证据或返回点不匹配时，平台不会完成任务或解锁后续任务。同一 `boot_id` 中遥测 `sequence` 必须递增；重复 `event_id` 幂等返回，旧序列会被拒绝。平台不推算未上报的能耗、里程、运行时长或漂移值。

## 设备主动下线

正常关机、计划维护、网络切换或本机安全停车完成后，设备必须在停止心跳前调用：

```http
POST /api/devices/gateway/{device_code}/offline
X-Device-Gateway-Key: <device_gateway_key>
Content-Type: application/json
```

```json
{
  "event_id": "offline-20260804-0001",
  "reason_code": "maintenance",
  "note": "计划更换驱动轮",
  "observed_at": "2026-08-04T12:00:00Z",
  "expected_reconnect_at": "2026-08-04T16:00:00Z"
}
```

`event_id` 是独立于遥测序列的幂等事件标识。`reason_code` 只能是 `shutdown`（正常关机）、`maintenance`（计划维护）、`network_change`（网络切换）、`safety_stop`（安全停机）、`operator_requested`（人工请求）或 `other`。`expected_reconnect_at` 早于 `observed_at` 时会返回 422。

成功后设备连接状态立即变为 `planned_offline`（O&M 显示“主动离线”），设备不再参与新任务规划，现有心跳超时告警会被关闭。该状态不是任务终态：若仍有执行单元，平台保留最后一次真实任务遥测，不会自行伪造暂停、取消或完成。设备必须先按本机安全流程处理活动任务，再报告主动下线。

下一次成功的 `POST /telemetry` 或已注册设备的 `POST /register` 会清除主动下线记录并恢复在线。没有主动下线报告且超过心跳阈值时，连接状态仍为 `offline`，会按异常失联处理。

## Calibration

`POST /api/devices/gateway/{device_code}/calibration` records an outcome from
the bridge after it has performed a real QR/AprilTag or manual localization
correction. It is an audit API, not a ROS/EKF implementation.

```json
{
  "event_id": "calibration-20260720-0001",
  "frame_id": "map",
  "qrcode_id": "A-START-01",
  "source": "automatic",
  "observed_at": "2026-07-20T12:01:00Z",
  "success": true,
  "position": {"x": 83.2, "y": 132.8, "z": 0},
  "drift_meters": 0.06
}
```

## 地图资产、点云与机器人同步

### 地图生产端上传

独立建图桥接器使用共享 `DEVICE_GATEWAY_API_KEY` 调用 `POST /api/map/gateway/assets` 登记外部地图资产。请求包含不可变 `event_id`、`source_id`、`asset_type`（`mesh_gltf`、`octomap` 或 `geojson`）、`asset_uri`、项目 `frame_id`、元数据、观测时间和可选 SHA-256。平台只保存资产引用和元数据，不保存对象存储中的文件内容。

建图桥接器使用同一共享密钥调用 `POST /api/pointcloud/gateway/map` 上传一份已经在建图端完成融合和抽样的完整点云。O&M 必须先通过 `PATCH /api/ops/mapping` 开启建图模式。新的 `map_id` 替换当前地图；相同 `map_id` 仅作为幂等重试，内容必须保持不变。平台不合并多个快照，也不再次抽样。

操作员页面继续使用 JWT 调用 `GET /api/pointcloud/map` 和地图管理接口。机器人不得保存或使用操作员 JWT。

### 机器人获取地图同步清单

```http
GET /api/devices/gateway/{device_code}/map-sync
X-Device-Gateway-Key: <device_gateway_key>
If-None-Match: "<上一次响应的 ETag>"   # 首次请求省略
```

只有 `{device_code}` 对应的有效设备专属密钥可以调用。共享 `DEVICE_GATEWAY_API_KEY`、其他设备的密钥和操作员 JWT 均不能替代。设备被禁用时返回 403，项目未初始化时返回 409。

当前 v2 是严格单项目控制平面：所有已注册且启用的设备都视为当前项目成员，可以读取当前项目的完整区域、点位、道路网络、资产引用和点云。若某台设备不应再访问现场地图，O&M 必须禁用其网关凭据。数据库出现多个项目记录或没有唯一活动项目时，接口返回 409 `project_scope_ambiguous`，不会猜测地图归属。地图资产 `metadata` 不得存放对象存储密钥、设备密钥或其他秘密。

200 响应包含：

| 字段 | 含义 |
| --- | --- |
| `schema_version` | 当前固定为 `v2` |
| `device_code` | 已通过鉴权的设备编码 |
| `project_code` / `project_name` | 当前活动项目标识和名称 |
| `frame_id` | 所有区域、点位、资产和点云共同使用的项目地图坐标系 |
| `coordinate_system` | 固定为右手坐标系、单位米、`+Z` 向上 |
| `sync_revision` | 对当前持久化地图语义内容做规范化序列化后计算的 SHA-256 |
| `regions` | 按编码排序的真实三维业务区域及体积组件 |
| `points` | 按编码排序的真实业务点位、二维码和设备适用信息 |
| `paths` | 按编码排序的真实机器人道路段；每条道路恰有 `[起点,终点]` 两个 `[x,y,z]` 端点，并含方向、净宽、坡度、适用设备类型与状态 |
| `road_network` | 启用道路推导出的节点与有向边；包含道路方向边和端点自动接驳边，是设备侧道路连通关系的唯一事实源 |
| `assets` | 外部资产 URI、类型、坐标系、元数据和可选 SHA-256 |
| `pointcloud` | `has_data`、`map_id`、来源、坐标系、点数、元数据、时间和下载路径；不包含完整点数组 |

`sync_revision` 覆盖项目编码和 `frame_id`、区域、点位、道路段、由道路推导的连通拓扑、资产引用以及当前点云摘要。数据库查询顺序不会影响该值，任一受覆盖的真实内容变化都会产生新修订号。完整点数组不重复参与整图哈希，因为上传契约保证 `map_id` 不可变且相同 `map_id` 不会覆盖内容。

### 机器人道路网络

道路由 O&M 通过 `/api/map/paths` 和批量 `/api/map/paths/batch` 维护，设备不能创建、修改或删除道路。每条道路固定只有起点和终点；分支、路口和连续道路必须保存为多条道路，不能使用一个多点路径臆造连接。同步清单中的每项道路具有以下约束：

```json
{
  "id": "路径 UUID",
  "code": "PATH-001",
  "name": "现场路径名称",
  "points": [[0.0, 0.0, 0.0], [10.0, 0.0, 0.5]],
  "start": [0.0, 0.0, 0.0],
  "end": [10.0, 0.0, 0.5],
  "direction": "bidirectional",
  "min_width_m": 2.5,
  "max_slope_percent": 8.0,
  "device_types": ["agv"],
  "status": "active"
}
```

`points` 必须是当前项目 `map_frame` 中按 `[起点,终点]` 顺序排列的两个 `[x,y,z]` 坐标，单位均为米；`z` 是高程。`start` 和 `end` 是对应端点的冗余显式字段。`forward` 仅允许从起点到终点，`reverse` 仅允许从终点到起点，`bidirectional` 允许双向。`min_width_m` 是净宽门槛，`max_slope_percent` 是道路端点间允许的最大坡度；`status=disabled` 的道路保留几何供审计，但设备不得作为可通行道路使用。空 `device_types` 表示平台不按设备类型限制，设备仍必须自行执行本体尺寸、坡度、定位、避障和安全校验。

`road_network` 的结构如下：

```json
{
  "voxel_cell_size_m": 0.05,
  "origin": [-30.0, -30.0, 0.0],
  "nodes": [{
    "id": "road:<道路 UUID>:start",
    "path_id": "道路 UUID",
    "path_code": "PATH-001",
    "endpoint": "start",
    "position": [0.0, 0.0, 0.0],
    "cell": [600, 600, 0]
  }],
  "edges": [{
    "id": "road:<道路 UUID>:forward",
    "kind": "road",
    "from_node_id": "road:<道路 UUID>:start",
    "to_node_id": "road:<道路 UUID>:end",
    "direction": "forward",
    "path_id": "道路 UUID",
    "path_code": "PATH-001"
  }]
}
```

`nodes` 仅包含启用道路的端点。`edges.kind=road` 表示按该道路方向允许通行，`edges.kind=junction` 表示两条不同道路端点的自动双向接驳，后者的 `direction` 为 `connector`，且不含 `path_id` 与 `path_code`。平台按固定 `0.05m` 体素及 `origin` 计算端点 `cell`：端点同格，或三轴曼哈顿距离为 1（共享一个体素面）时生成两条反向 `junction` 边。设备只能在本机设备类型、净宽、坡度和安全校验均满足的 `road` 边上通行，并可用 `junction` 边在道路间转接。平台只下发真实道路和拓扑，不实现机器人侧寻路或运动控制。

成功响应包含：

```http
ETag: "map-sync-<完整响应内容的 SHA-256>"
Cache-Control: private, no-cache
X-Map-Sync-Revision: <sync_revision>
```

当 `If-None-Match` 与当前 ETag 相同时，接口在完成设备鉴权后返回 304 和空响应体。没有区域、点位、资产或点云时返回真实空数组及 `pointcloud.has_data=false`，不会生成占位地图。

### 机器人下载完整点云

清单中 `pointcloud.has_data=true` 时，设备调用其 `download_path`：

```http
GET /api/devices/gateway/{device_code}/map-sync/pointcloud?map_id={map_id}
X-Device-Gateway-Key: <device_gateway_key>
If-None-Match: "<上一次点云响应的 ETag>"   # 可省略
```

200 响应返回 `map_id`、`source_id`、`frame_id`、完整真实 `points`、`total_count`、建图元数据和观测/接收时间。点云成功响应也包含 ETag；命中时返回 304。

- 当前尚无完整点云时返回 404。
- 请求的 `map_id` 已被新地图替换时返回 409，`detail.code=map_version_changed`，并在 `current_map_id` 中给出当前版本。设备必须重新获取清单。
- 已保存点云或资产的 `frame_id` 与项目不一致时返回 409，平台不会向机器人下发混合坐标数据。

### 设备侧安全切换顺序

1. 获取清单并比较 `sync_revision`；未变化时不下载。
2. 将清单和点云下载到临时文件或临时数据库，不覆盖正在使用的地图。
3. 校验 `frame_id`、`map_id`、点数、点结构以及设备实际使用资产的 SHA-256。资产缺少校验值时不得自动作为可信运行地图激活，应由建图端重新登记带校验值的新资产事件。
4. 下载完成后使用旧 ETag 再次请求清单；返回 304 才表示整套地图未在下载期间变化。返回 200 时丢弃临时结果并按新修订号重新同步。
5. 全部验证通过后由机器人本地地图管理程序原子切换；失败时保留上一份已验证地图，并按本体安全策略停车或限制运行。

`asset_uri` 为 HTTPS 时设备可按自身网络策略下载；为 `s3`、`gs`、`oss` 时设备必须配置对应对象存储客户端和权限。短期签名 URL 到期或资产内容变化时，建图端必须使用新的 `event_id` 重新登记，不能复用旧事件覆盖。平台不代理外部资产文件，也不在本仓库实现 ROS 地图加载、SLAM 或导航。

Camera/vision gateways use `POST /api/cameras/gateway/register` and
`POST /api/cameras/gateway/{camera_code}/detections`. The platform never
generates camera detections itself.

## 命令拉取、任务接收与回执

### 投递模型

机器人侧没有服务端反向推送接口。设备接入程序需要在本机持续轮询：

```http
GET /api/devices/gateway/{device_code}/commands
X-Device-Gateway-Key: <device_gateway_key>
```

接口立即返回当前未终结命令，不是保持连接的长轮询。建议以约 1 秒周期轮询；发生网络或服务错误后采用有上限的指数退避。设备在空闲、执行任务和暂停状态都必须持续轮询，才能接收启动、取消、急停和摄像头控制。

平台采用至少一次投递。在 ACK 成功前，同一 `command.id` 会重复返回；设备必须将命令处理记录持久化，按 ID 去重。已处理过的命令不再执行动作，只重发本地保存的相同 ACK。命令列表还包含 `global_estop_active`：为 `true` 时设备必须保持本地安全停止，并优先处理对应 `estop`。

### 设备端闭环

收到命令后的正确闭环为：

```text
拉取命令 -> 本地持久化并去重 -> 校验安全和执行条件 -> 调用本机控制器
         -> 持久化处理结果 -> ACK 命令 -> 遥测上报真实状态/进度/结果
```

对 `mission_start`，设备先持久化 `execution_id`、`workflow`、`allocation` 和执行上下文；通过遥测报告 `accepted`，实际开始后报告 `running`。命令 ACK 表示控制器已接受或明确拒绝启动，不表示任务结束。运行、暂停、完成、失败、取消、工作量和返航阶段只能通过遥测中的 `mission` 对象更新。

同一业务任务由多台设备协作时，设备必须只执行并上报自己的 `execution_id` 和 `allocation.assigned_qty`，不能上报或重复执行其他设备的份额。设备端实际导航、避障、作业、返航和本机安全控制由机器人软件或厂商控制器实现，平台仅提供命令契约。

ACK 的发送也需要本地持久化：成功响应后才清除待发 ACK；超时或 5xx 时用同一个终态重试。相同终态 ACK 可幂等重试，不同终态会返回 409。

### 命令类别

Commands include `mission_start`, `mission_pause`, `mission_resume`,
`mission_cancel`, `pause`, `resume`, `estop`, `reset`, `release`,
`camera_enable`, and `camera_disable`. Camera commands carry
`{"sensor":"camera","enabled":true|false}`. The bridge must ACK the command
only after the sensor power state changes, then report the confirmed `camera`
state in its next telemetry message. The dashboard treats a queued command as
pending and only permits live viewing after that confirmation.

v2 `mission_start` 的关键载荷如下。顶层 `process_id`、`target` 和 `constraints` 为 v1 兼容字段；v2 设备以 `workflow` 为执行依据：

```json
{
  "schema_version": "v2",
  "execution_id": "唯一执行标识",
  "task_id": "平台任务 UUID",
  "task_code": "T-12345678",
  "map_frame": "map",
  "process_id": "material_transport",
  "target": {
    "point_id": "作业点 UUID",
    "point_code": "WORK-01",
    "frame_id": "map",
    "x": 12.5,
    "y": 8.0,
    "z": 0.0
  },
  "workflow": {
    "outbound": {"target": {"point_id": "作业点 UUID", "frame_id": "map", "x": 12.5, "y": 8.0, "z": 0.0}},
    "operation": {
      "process_id": "material_transport",
      "parameters": {},
      "instructions": "现场录入的作业要求",
      "deliverable_qty": 5,
      "deliverable_unit": "车次"
    },
    "return": {
      "required": true,
      "policy": "return_to_point",
      "target": {"point_id": "返回点 UUID", "point_code": "PARK-01", "frame_id": "map", "x": 2.0, "y": 3.0, "z": 0.0}
    }
  },
  "allocation": {
    "allocation_id": "资源分配 UUID",
    "requirement_id": "资源需求 UUID",
    "role_code": "transport",
    "assigned_qty": 5,
    "output_unit": "车次",
    "work_scope": {"mode": "shared_queue", "map_point_id": "作业点 UUID"},
    "predicted_finish_at": "2026-07-20T12:35:00Z"
  },
  "constraints": {},
  "completion_policy": "after_return"
}
```

当任务由多个设备协同执行时，`allocation.assigned_qty` 和 `workflow.operation.deliverable_qty` 是本设备执行单元的配额，不是整个业务任务总量；`task_total_qty` 仅用于界面和机端参考。设备必须只上报自己 `execution_id` 的累计 `completed_qty`，不得替其他设备填报完成量。平台按资源需求聚合所有执行单元，所有完成门槛达标且需要返航的执行单元均确认返航后，业务任务才完成。

设备 ACK `mission_start` 只表示命令已被控制器接收，不能替代任务遥测。若设备在尚未接受执行时以 `failed` ACK 明确拒绝启动，平台终结本次执行并把任务恢复为等待设备；设备必须随后真实上报自身 `idle/ready` 状态，平台不会根据任务终态推测设备已经空闲。

`POST /api/devices/gateway/{device_code}/commands/{command_id}/ack` records
the command outcome. Repeating an identical terminal acknowledgement is safe;
a contradictory acknowledgement is rejected.

```json
{"status": "acknowledged", "message": "controller accepted command"}
```

## 摄像头与视觉数据

视频流和视觉检测结果走不同的通道，平台没有接收视频帧、录像文件或图像二进制的 API。

### 机器人机载摄像头

机器人登记时可在 `capabilities.camera` 说明摄像头能力。设备在遥测中上报真实的 `camera.enabled`、`camera.is_online`、`camera.stream_url` 与 `camera.stream_protocol`。`stream_protocol` 仅允许 `hls` 或 `mp4`；`stream_url` 必须是 O&M 浏览器实际可访问的播放地址。RTSP、MJPEG 和厂商私有流需要在设备侧或现场媒体网关转换为 HLS/MP4 后才可提供给 O&M。

视频不经过平台后端转发，实际链路为：

```text
机器人摄像头 -> 设备侧媒体服务/现场媒体网关 -> HLS 或 MP4 -> O&M 浏览器播放器
```

O&M 的开启/关闭操作会生成 `camera_enable` 或 `camera_disable` 命令。设备在物理开关已经完成后 ACK，并在下一次遥测中确认状态和可用播放地址。媒体服务需自行提供网络可达性、HTTPS/CORS 和观看鉴权；不得把设备网关密钥、用户名或密码放到 `stream_url` 中。

### 独立摄像头与视觉网关

独立摄像头/视觉网关使用系统级 `DEVICE_GATEWAY_API_KEY` 调用：

```http
POST /api/cameras/gateway/register
POST /api/cameras/gateway/{camera_code}/detections
X-Device-Gateway-Key: <DEVICE_GATEWAY_API_KEY>
```

登记接口记录摄像头编码、名称、位置、实际流地址及二维地图位置。视觉网关在本地完成真实采集和识别后，上传一条结构化统计：

```json
{
  "detected_at": "<带时区的真实检测完成时间>",
  "excavator_count": 0,
  "truck_count": 0,
  "person_count": 0,
  "dust_level": "<实际检测等级>",
  "slope_risk": "<实际检测等级>",
  "ai_compliance_rate": 0
}
```

上例中的零值只代表真实检测到零个目标或零合规率，不能作为演示数据。检测上报当前不含 `event_id`，服务端也不做请求去重；HTTP 超时后应记录发送结果未知，不能无条件重试。平台保存检测统计供 PM/O&M 展示，不生成识别结果，也不从视频流推断统计数据。

## Operating Guarantees

- 任务必须关联真实地图点位。资源规划仅选择已启用、心跳有效、空闲、电量达标、无其他活动执行、明确声明对应能力和有效单位产能、且兼容作业点/返回点的设备。
- 一个业务任务可包含多个资源需求和多个设备执行单元；数据库只限制同一设备同时最多一个活动执行。调度器按每个需求的剩余交付量、计划窗口和真实单位产能选择实际设备类型与数量，并向每台设备下发自身配额。
- 任一完成门槛资源需求产能不足时，任务保持 `pending` 并持久化等待原因；调度器每个周期从数据库重新发现任务，设备后来上线、空闲或更新有效产能后自动重新规划和派发，不生成虚构设备或虚构完成量。
- Global emergency stop and alert holds are durable commands for every target
  device. Recovery queues a `release` command for every gateway device and
  requires the physical controller to ACK that it is safe. The robot must still
  enforce its own hardware and local fail-safe.
- Empty projects return empty lists and zero metrics. The API does not create
  devices, map data, tasks, point clouds, camera detections, or task progress.
