# 01 · 软件设计文档

> 机器人集群智能调度系统 · 软件设计与架构方案
> 阶段：第四步（软件设计 + 用户场景设计），待用户确认方案可行性
> 日期：2026-07-14

---

## 一、系统总体架构

### 1.1 四层架构（落实 CODEBUDDY.md 定义）

```
┌─────────────────────────────────────────────────────────────┐
│  应用层（前端双端大屏）                                       │
│  ┌──────────────────────┐    ┌──────────────────────────┐  │
│  │  PM 端（指挥）        │    │  O&M 端（运维 3D 调度）   │  │
│  │  - KPI 指标条         │    │  - 3D 点云场景            │  │
│  │  - 甘特图             │    │  - 设备状态分布           │  │
│  │  - 摄像头视角         │    │  - 运维操作台             │  │
│  │  - 待办任务           │    │  - 集群拓扑/告警          │  │
│  │  - 完成趋势/事件流    │    │  - 底部设备卡片条         │  │
│  └──────────┬───────────┘    └──────────┬───────────────┘  │
│             │      REST + WebSocket       │                  │
└─────────────┼─────────────────────────────┼─────────────────┘
              │                             │
┌─────────────┼─────────────────────────────┼─────────────────┐
│  调度层（后端核心大脑）                      │                  │
│  ┌──────────▼─────────────────────────────▼──────────────┐  │
│  │  调度引擎（DAG + 市场机制 + 重规划循环）               │  │
│  │  - 任务编排  - 协同控制  - 能耗维保  - 安全管控        │  │
│  │  - 监控告警  - 地图感知                                 │  │
│  └──────────┬─────────────────────────────┬──────────────┘  │
│             │                             │                  │
│  ┌──────────▼──────────┐    ┌─────────────▼──────────────┐  │
│  │  点云源（混合模式）  │    │  设备适配层（Adapter）      │  │
│  │  - 仿真生成器        │    │  - SimulatedAdapter（默认）│  │
│  │  - 真实接收器        │    │  - Ros2Adapter（未来）     │  │
│  └─────────────────────┘    └────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
              │
┌─────────────┼─────────────────────────────────────────────┐
│  数据层      │                                              │
│  ┌──────────▼─────────┐  ┌──────────────┐  ┌────────────┐  │
│  │  PostgreSQL 16     │  │  TimescaleDB │  │   Redis    │  │
│  │  关系数据          │  │  时序事件流   │  │  热缓存/   │  │
│  │  - 设备/任务/剧本  │  │  - 遥测/告警  │  │  pub/sub   │  │
│  └────────────────────┘  └──────────────┘  └────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 后端模块划分（FastAPI 应用结构）

```
backend/app/
├── main.py                      # FastAPI 入口
├── core/
│   ├── config.py                # pydantic-settings 配置
│   ├── database.py              # SQLAlchemy 异步引擎 + Session
│   ├── redis.py                 # Redis 连接 + pub/sub
│   ├── security.py              # 权限校验（PM/O&M 两级）
│   └── logging.py               # 结构化日志
│
├── api/                         # REST 路由（按模块分文件）
│   ├── devices.py               # 设备注册/查询/控制命令
│   ├── tasks.py                 # 任务 CRUD/改派/插单
│   ├── scripts.py               # 剧本切换/列表
│   ├── map.py                   # 地图/点位/区域
│   ├── alerts.py                # 告警查询/处置
│   ├── reports.py               # 报表导出（Excel）
│   ├── pointcloud.py            # 点云配置/状态
│   └── auth.py                  # 登录/角色
│
├── ws/                          # WebSocket handlers
│   ├── hub.py                   # 连接管理 + Redis 广播
│   ├── channels.py              # 频道定义
│   └── handlers.py              # 消息分发
│
├── adapters/                    # 设备适配层
│   ├── base.py                  # DeviceAdapter 抽象基类
│   ├── simulated.py             # 仿真设备适配器（默认）
│   ├── ros2.py                  # ROS2 适配器（未来扩展，占位）
│   ├── mqtt_bridge.py           # MQTT 订阅桥（真实设备遥测）
│   └── registry.py              # 适配器注册与切换
│
├── scheduler/                   # 调度引擎核心
│   ├── engine.py                # 调度主循环（asyncio）
│   ├── dag.py                   # DAG 解析与依赖校验
│   ├── strategy.py              # SchedulerStrategy 抽象接口
│   ├── market.py                # 市场机制策略（招标/竞价）
│   ├── allocator.py             # 任务分配器（调用策略）
│   ├── replanner.py             # 异常重规划
│   └── priority.py              # 优先级体系
│
├── coordination/                # 协同作业控制
│   ├── formation.py             # 编队同步
│   ├── collision.py             # 碰撞联锁检测
│   └── group_cmd.py             # 群组指令下发
│
├── pointcloud/                  # 点云源（混合模式）
│   ├── base.py                  # PointCloudSource 抽象
│   ├── simulator.py             # 仿真点云生成器
│   ├── real_receiver.py         # 真实点云接收器
│   ├── processor.py             # 聚合/坐标变换/降采样
│   └── manager.py               # 源切换管理
│
├── map/                         # 地图与环境感知
│   ├── grid.py                  # 2D 网格 + 高度层
│   ├── regions.py               # 区域划分
│   ├── points.py                # 施工点位
│   ├── obstacles.py             # 动态障碍物
│   └── scene_config.py          # 3D 场景配置
│
├── energy/                      # 能耗与维保
├── safety/                      # 安全管控
├── monitor/                     # 监控与告警
├── reports/                     # 报表统计
├── models/                      # SQLAlchemy 模型
├── services/                    # 业务服务层
├── scripts_data/                # 剧本配置文件（YAML）
└── alembic/                     # 数据库迁移
```

### 1.3 前端 Monorepo 结构（详细）

```
frontend/
├── pnpm-workspace.yaml
├── apps/
│   ├── pm/                          # PM 端
│   │   └── src/
│   │       ├── sections/
│   │       │   ├── TopBar/          # 顶部状态栏
│   │       │   ├── KpiStrip/        # 8项KPI指标条
│   │       │   ├── LeftColumn/      # 左栏
│   │       │   ├── GanttColumn/     # 中栏甘特图
│   │       │   └── RightColumn/     # 右栏
│   │       ├── hooks/
│   │       └── stores/
│   │
│   └── om/                          # O&M 端
│       └── src/
│           ├── sections/
│           │   ├── TopBar/
│           │   ├── LeftColumn/
│           │   ├── Scene3D/         # @react-three/fiber 3D 场景
│           │   ├── RightColumn/
│           │   └── DeviceDeck/      # 底部设备卡片
│           ├── views/               # 调度/能耗/安全三视图
│           ├── hooks/
│           └── stores/
│
└── packages/
    ├── ui/                          # 共用组件库
    │   └── src/components/
    │       ├── DeviceCard/
    │       ├── AlertBar/
    │       ├── StatusBadge/
    │       ├── Gantt/               # 自研甘特图
    │       ├── DonutChart/
    │       ├── TrendChart/
    │       └── EventFeed/
    ├── three-scene/                 # 3D 场景封装
    │   └── src/
    │       ├── Scene.tsx
    │       ├── PointCloud.tsx
    │       ├── TransparentBlocks/
    │       ├── DeviceMarkers/
    │       └── HudOverlay/
    ├── api-client/                  # REST + WebSocket 客户端
    ├── shared-types/                # 共用 TS 类型
    └── utils/                       # 共用工具
```

---

## 二、数据模型设计

### 2.1 关系数据（PostgreSQL）

**devices（设备注册表）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | 设备唯一ID |
| code | VARCHAR(32) UNIQUE | 设备编码（如 T-03） |
| name | VARCHAR(64) | 设备名称 |
| type | VARCHAR(32) | agv/excavator/crane/masonry/inspect |
| model | VARCHAR(64) | 型号 |
| capabilities | JSONB | 能力标签（适配工序列表） |
| section_tags | JSONB | 标段/车型/工序三维标签 |
| permissions | JSONB | 通行/施工权限 |
| status | VARCHAR(16) | idle/charging/moving/working/maintenance/occupancy/fault |
| battery | FLOAT | 电量百分比 |
| position_x/y/z | FLOAT | 当前坐标 |
| section_id | VARCHAR(32) | 所属标段 |
| last_heartbeat | TIMESTAMPTZ | 最后心跳 |

**tasks（任务表）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | |
| code | VARCHAR(32) | 任务编码 |
| name | VARCHAR(128) | 任务名称（工序名） |
| process_id | VARCHAR(32) | 关联的29项工序ID |
| script_id | UUID FK | 所属剧本 |
| device_id | UUID FK NULL | 分配的设备（NULL=未分配） |
| status | VARCHAR(16) | pending/assigned/running/paused/completed/failed |
| priority | INT | 优先级 |
| target_point_id | UUID FK | 目标施工点位 |
| progress | FLOAT | 进度0-100 |
| dependencies | JSONB | 前置任务ID列表（DAG边） |
| params | JSONB | 动作参数 |
| estimated_duration | INT | 预估工期（秒） |

**scripts（剧本表）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | |
| name | VARCHAR(64) | 剧本名称 |
| description | TEXT | |
| config | JSONB | 完整剧本配置（DAG+设备映射+节奏） |
| is_active | BOOL | 当前激活剧本 |

**alerts（告警表）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | |
| device_id | UUID FK NULL | |
| level | VARCHAR(16) | critical/warning/info |
| category | VARCHAR(32) | offline/timeout/low_battery/path_conflict/boundary |
| message | TEXT | |
| status | VARCHAR(16) | open/acknowledged/resolved |

**users（用户表）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | |
| username | VARCHAR(64) UNIQUE | |
| role | VARCHAR(16) | pm / om |
| display_name | VARCHAR(64) | |

### 2.2 时序数据（TimescaleDB）

**device_events（设备遥测事件流，hypertable）**

| 字段 | 类型 | 说明 |
|------|------|------|
| time | TIMESTAMPTZ | 事件时间（分区键） |
| device_id | UUID | |
| event_type | VARCHAR(32) | telemetry/status_change/task_event/alert |
| payload | JSONB | 事件负载（位置/电量/状态/任务进度等） |

按 `time` 自动分区，7天前数据启用压缩。

### 2.3 Redis 缓存策略

| Key 模式 | 用途 | TTL |
|----------|------|-----|
| `device:{id}:state` | 设备最新状态 | 5s |
| `device:online` | 在线设备集合 | — |
| `ws:broadcast:{channel}` | WebSocket 广播 pub/sub | — |
| `estop:status` | 全局急停状态 | — |
| `script:active` | 当前激活剧本ID | — |

---

## 三、核心流程设计

### 3.1 调度主流程

```
1. 系统启动 → 加载激活剧本 → 解析为 DAG
2. DAG 拓扑排序 → 产出可执行任务队列（前置已满足的任务）
3. 调度循环（每 1s tick）：
   a. 扫描可执行任务队列
   b. 对每个任务，查询可调度设备（类型适配+电量+标段权限+非禁行区）
   c. 市场机制：可调度设备对任务"投标"（基于距离/电量/负载成本）
   d. 调度器定标 → 生成派单 → 下发设备（通过 adapter）
   e. 设备执行 → 实时上报进度 → 更新任务状态
   f. 任务完成 → 标记 DAG 节点完成 → 解锁后继任务
4. 异常重规划：
   - 设备离线/故障 → 任务回退到队列 → 重新分配
   - 低电量 → 降权或派充电任务
   - 路径冲突 → 碰撞联锁触发 → 减速/停车/重规划
5. 全程事件写入 device_events（TimescaleDB）+ 推送 WebSocket
```

### 3.2 设备接入流程（仿真模式）

```
1. 系统启动 → SimulatedAdapter 初始化 N 台虚拟设备
2. 每台设备独立 asyncio 协程：
   a. 每 1s 上报心跳 + 遥测（位姿沿预设路径移动、电量缓慢下降）
   b. 接收派单 → 状态切到 working → 沿路径移动到目标点 → 执行工序 → 上报进度
   c. 任务完成 → 状态切回 idle
3. 遥测数据 → 更新 Redis → 推送 WebSocket → 前端大屏实时刷新
```

### 3.3 点云渲染流程（混合模式）

```
1. 启动时读取配置：pointcloud.source = simulated | real
2. 仿真模式：
   a. 加载沙盘预建模型（楼栋/基坑/道路的占位几何）
   b. 模拟"扫描机器人"沿预设轨迹移动
   c. 每帧生成扫描覆盖区域的点云片段（带噪声）
   d. 后端聚合 + 体素降采样（目标 < 50万点）
   e. 通过 WebSocket 增量推送点云到前端
3. 真实模式：
   a. 通过 ROS2/MQTT 订阅设备点云主题
   b. 接收 PointCloud2 → 解析为 (x,y,z,rgb) 数组
   c. 同样聚合 + 降采样 + WebSocket 推送
4. 前端 Three.js：
   a. <Points> 渲染点云，随扫描进度逐渐显示
   b. 点云与透明方块模型叠加（点云=实时建图，方块=预建参考）
   c. 支持点云密度/透明度调节
```

### 3.4 急停流程

```
触发（PM端应急 或 O&M端）：
  → 后端 estop.py 设置 Redis estop:status = active
  → Redis pub/sub 广播到所有 WebSocket 连接
  → SimulatedAdapter 立即停止所有设备移动
  → 前端大屏全局显示急停态（红色闪烁）

恢复（仅 O&M 端）：
  → 后端校验角色 = om
  → 清除 Redis estop:status
  → 广播恢复信号
  → 设备恢复到急停前状态（或重新调度）
```

### 3.5 WebSocket 频道设计

| 频道 | 推送内容 | 频率 |
|------|---------|------|
| `devices` | 所有设备位姿/状态/电量 | 1Hz |
| `tasks` | 任务状态变更 | 事件驱动 |
| `alerts` | 新告警 | 事件驱动 |
| `pointcloud` | 点云增量 | 5Hz（扫描中） |
| `events` | 实时事件流（日志） | 事件驱动 |
| `estop` | 急停状态变更 | 事件驱动 |
| `script` | 剧本切换通知 | 事件驱动 |

---

## 四、API 设计概要

### 4.1 REST API

```
# 设备
GET    /api/devices                 # 设备列表（支持筛选）
GET    /api/devices/{id}            # 设备详情
POST   /api/devices/{id}/command    # 下发控制命令（O&M权限）

# 任务
GET    /api/tasks                   # 任务列表
POST   /api/tasks                   # 新建任务（PM权限）
PATCH  /api/tasks/{id}              # 编辑/改派（PM权限）
POST   /api/tasks/{id}/pause        # 暂停
POST   /api/tasks/{id}/resume       # 恢复

# 剧本
GET    /api/scripts                 # 剧本列表
POST   /api/scripts/{id}/activate   # 激活剧本（PM权限）

# 地图
GET    /api/map/regions             # 区域列表
GET    /api/map/points              # 施工点位
GET    /api/map/scene-config        # 3D场景配置

# 告警
GET    /api/alerts                  # 告警列表
POST   /api/alerts/{id}/acknowledge # 确认告警

# 报表
POST   /api/reports/export          # 导出Excel

# 点云
GET    /api/pointcloud/status       # 点云源状态
POST   /api/pointcloud/config       # 切换源（simulated/real）

# 急停
POST   /api/estop                   # 触发急停（PM应急 或 O&M）
DELETE /api/estop                   # 恢复（仅O&M）

# 运维快捷指令（8个，O&M权限）
POST   /api/ops/self-check          # 设备自检
POST   /api/ops/force-charge        # 强制充电
POST   /api/ops/mode-switch         # 模式切换
POST   /api/ops/diagnostics         # 系统诊断
POST   /api/ops/backup              # 数据备份
POST   /api/ops/firmware-upgrade    # 固件升级
POST   /api/ops/network-check       # 网络检测
POST   /api/ops/safety-inspect      # 安全巡检
```

### 4.2 WebSocket

```
WS /ws?role=pm|om&channels=devices,tasks,alerts,pointcloud,events,estop

# 客户端→服务端
{ "type": "subscribe", "channel": "devices" }
{ "type": "unsubscribe", "channel": "pointcloud" }

# 服务端→客户端
{ "type": "devices", "data": [{ id, code, x, y, z, status, battery }, ...] }
{ "type": "alert", "data": { id, level, message, ... } }
{ "type": "pointcloud", "data": { points: [[x,y,z,r,g,b], ...], progress: 0.65 } }
{ "type": "estop", "data": { active: true, source: "pm" } }
```

---

## 五、剧本配置示例

```yaml
# earthwork-focused.yaml（土方主导剧本）
name: 土方主导演示
description: 重点展示土方开挖与渣土外运的集群协同
devices:
  - code: EX-01
    type: excavator
    start: { x: 120, y: 80, z: 0 }
    battery: 95
  - code: AGV-01
    type: agv
    start: { x: 50, y: 50, z: 0 }
    battery: 88
dag:
  nodes:
    - id: site_prep
      process: 场地平整
      target_point: P-AREA-01
      required_device_type: excavator
      estimated_duration: 60
    - id: pit_excavation
      process: 基坑土方清运
      target_point: P-PIT-01
      required_device_type: excavator
      estimated_duration: 120
      depends_on: [site_prep]
    - id: spoil_export
      process: 渣土外运
      target_point: P-EXIT-01
      required_device_type: agv
      estimated_duration: 90
      depends_on: [pit_excavation]
tempo:
  tick_interval: 1s
  speed_factor: 1.0
```

---

## 六、关键技术风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| 点云渲染性能卡顿 | O&M端3D卡顿 | 后端体素降采样 < 50万点；前端 BufferGeometry + Points |
| 甘特图自研工作量 | PM端延期 | 先实现核心（阶段行+任务行+今日线），里程碑/筛选二期补 |
| 多设备并发遥测导致 WebSocket 风暴 | 前端卡顿 | 后端合并 1Hz 推送；前端 Zustand 批量更新 |
| 仿真设备行为不真实 | 演示效果差 | 仿真器按真实物理参数建模 |
| 剧本切换时状态不一致 | 调度错乱 | 切换前停止所有任务、重置 DAG、原子操作 |
