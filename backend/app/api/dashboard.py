"""Dashboard API — 所有派生指标从数据库实时聚合计算，不存储冗余字段。

KPI 计算逻辑：
- 总体进度 = completed_tasks / total_tasks * 100
- 土方完成率 = earthwork阶段 completed_tasks / earthwork total_tasks * 100
- 进行中任务数 = status='running' 的任务数
- 待闭环事项数 = status='pending' 的任务数
- 延期风险数 = planned_end < now 且 status != 'completed' 的任务数
- 资源负载率 = working_devices / total_devices * 100
- 渣土外运车次 = spoil_export 工序的 completed_qty 之和
- AI合规率 = 最近一次 camera_detection 的 ai_compliance_rate
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user, require
from app.models.models import (
    Alert,
    Camera,
    CameraDetection,
    Device,
    DeviceEvent,
    MaintenanceWorkOrder,
    Project,
    SafetyState,
    Task,
    User,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get(
    "/project",
    summary="查询当前项目概况",
    description="读取最近创建的启用项目；未初始化时明确返回 configured=false，不生成默认项目信息。",
    response_description="当前项目编码、名称、地点、坐标系、时区和配置状态。",
)
async def get_project(
    db: AsyncSession = Depends(get_db),
    _role=Depends(require("read")),
) -> dict:
    project = await db.scalar(select(Project).where(Project.is_active == True).order_by(Project.created_at.desc()))
    if project is None:
        return {"configured": False}
    return {
        "configured": True,
        "code": project.code,
        "name": project.name,
        "location": project.location,
        "map_frame": project.map_frame,
        "timezone": project.timezone,
    }


@router.get(
    "/kpi",
    summary="查询项目 KPI",
    description="从任务、设备和告警等数据库记录实时聚合项目进度、设备利用率、安全及质量指标。",
    response_description="八项 KPI 的当前值、单位和变化信息。",
)
async def get_kpi(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """8项KPI指标——全部从数据库聚合计算。"""

    now = datetime.now(timezone.utc)

    # 1. 总体进度 = completed / total
    total_tasks = await db.scalar(select(func.count(Task.id)))
    completed_tasks = await db.scalar(
        select(func.count(Task.id)).where(Task.status == "completed")
    )
    overall_progress = round((completed_tasks / total_tasks * 100) if total_tasks > 0 else 0, 1)

    # 2. 土方完成率
    earthwork_total = await db.scalar(
        select(func.count(Task.id)).where(Task.stage == "earthwork")
    )
    earthwork_completed = await db.scalar(
        select(func.count(Task.id)).where(Task.stage == "earthwork", Task.status == "completed")
    )
    earthwork_rate = round((earthwork_completed / earthwork_total * 100) if earthwork_total > 0 else 0, 1)

    # 3. 进行中任务数
    running_tasks = await db.scalar(
        select(func.count(Task.id)).where(Task.status == "running")
    )

    # 4. 待闭环事项数
    pending_tasks = await db.scalar(
        select(func.count(Task.id)).where(Task.status == "pending")
    )

    # 5. 延期风险数 = planned_end < now 且未完成
    delay_risk = await db.scalar(
        select(func.count(Task.id)).where(
            Task.planned_end < now,
            Task.status != "completed",
        )
    )

    # 6. 资源负载率 = working_devices / total_devices * 100
    total_devices = await db.scalar(select(func.count(Device.id)))
    working_devices = await db.scalar(
        select(func.count(Device.id)).where(
            Device.status.in_(["working", "moving"])
        )
    )
    resource_load = round((working_devices / total_devices * 100) if total_devices > 0 else 0, 1)

    # 7. 渣土外运车次 = spoil_export 工序的 completed_qty 之和
    spoil_trips = await db.scalar(
        select(func.coalesce(func.sum(Task.completed_qty), 0)).where(
            Task.process_id == "spoil_export"
        )
    )

    # 8. AI合规率 = 最近一次摄像头识别的 ai_compliance_rate
    latest_detection = await db.execute(
        select(CameraDetection)
        .order_by(CameraDetection.detected_at.desc())
        .limit(1)
    )
    ai_rate = latest_detection.scalar_one_or_none()
    ai_compliance = round(ai_rate.ai_compliance_rate, 1) if ai_rate else 0.0

    return {
        "overall_progress": overall_progress,
        "earthwork_rate": earthwork_rate,
        "running_tasks": running_tasks or 0,
        "pending_tasks": pending_tasks or 0,
        "delay_risk": delay_risk or 0,
        "resource_load": resource_load,
        "spoil_trips": int(spoil_trips or 0),
        "ai_compliance": ai_compliance,
        "total_tasks": total_tasks or 0,
        "completed_tasks": completed_tasks or 0,
        "total_devices": total_devices or 0,
        "working_devices": working_devices or 0,
    }


@router.get(
    "/trend",
    summary="查询任务完成趋势",
    description="按日聚合指定天数内任务的计划完成数、实际完成数和预测走势。",
    response_description="日期序列及 planned、actual、predicted 三组趋势数据。",
)
async def get_trend(
    days: int = Query(7, ge=1, le=90, description="向前统计的自然日数量，范围 1 至 90。"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """完成趋势——从 tasks 表按日聚合（计划完成数 vs 实际完成数 vs 预测）。

    返回三线数据：planned / actual / predicted
    """
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)

    # 计划完成数：按 planned_end 日期分组
    planned_result = await db.execute(
        select(
            func.date_trunc("day", Task.planned_end).label("day"),
            func.count(Task.id).label("count"),
        )
        .where(Task.planned_end >= start, Task.planned_end <= now + timedelta(days=3))
        .group_by("day")
        .order_by("day")
    )
    planned_data = {row.day.date().isoformat(): row.count for row in planned_result}

    # 实际完成数：按 completed_at 日期分组
    actual_result = await db.execute(
        select(
            func.date_trunc("day", Task.completed_at).label("day"),
            func.count(Task.id).label("count"),
        )
        .where(Task.completed_at >= start)
        .group_by("day")
        .order_by("day")
    )
    actual_data = {row.day.date().isoformat(): row.count for row in actual_result}

    # 构建三线数据
    labels = []
    planned_line = []
    actual_line = []
    predicted_line = []

    for i in range(days):
        day = (start + timedelta(days=i)).date()
        day_str = day.isoformat()
        labels.append(day_str)
        planned_line.append(planned_data.get(day_str, 0))
        actual_line.append(actual_data.get(day_str, 0))
        # 预测线：最近3天实际平均 + 趋势
        recent_actuals = [actual_line[j] for j in range(max(0, i - 2), i + 1) if j < len(actual_line)]
        avg = sum(recent_actuals) / len(recent_actuals) if recent_actuals else 0
        predicted_line.append(round(avg, 1))

    return {
        "labels": labels,
        "planned": planned_line,
        "actual": actual_line,
        "predicted": predicted_line,
    }


@router.get(
    "/resource-load",
    summary="查询设备资源负载",
    description="按设备类型统计设备总数、工作数量和真实负载率；无设备时返回空列表。",
    response_description="各设备类型的数量和负载率。",
)
async def get_resource_load(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """资源负载——从 devices 表按设备类型分组计算实际负载率。

    负载率 = (working + moving) / total * 100
    """
    result = await db.execute(
        select(
            Device.type,
            func.count(Device.id).label("total"),
            func.count(Device.id).filter(
                Device.status.in_(["working", "moving"])
            ).label("active"),
            func.count(Device.id).filter(
                Device.status == "idle"
            ).label("idle"),
            func.count(Device.id).filter(
                Device.status == "charging"
            ).label("charging"),
            func.count(Device.id).filter(
                Device.status.in_(["fault", "maintenance"])
            ).label("fault"),
        ).group_by(Device.type)
    )

    TYPE_LABELS = {
        "excavator": "挖机",
        "agv": "渣土车队",
        "crane": "吊车",
        "masonry": "砌筑机器人",
        "inspect": "巡检班组",
    }

    loads = []
    for row in result:
        load_rate = round((row.active / row.total * 100) if row.total > 0 else 0, 1)
        loads.append({
            "type": row.type,
            "label": TYPE_LABELS.get(row.type, row.type),
            "total": row.total,
            "active": row.active,
            "idle": row.idle,
            "charging": row.charging,
            "fault": row.fault,
            "load_rate": load_rate,
        })

    return loads


@router.get(
    "/energy",
    summary="查询真实能耗数据",
    description="只聚合设备遥测实际上报的功率和累计能耗；缺失指标不会被估算或补值。",
    response_description="能耗数据可用性、汇总值和设备级明细。",
)
async def get_energy_view(
    db: AsyncSession = Depends(get_db),
    _role=Depends(require("read")),
) -> dict:
    """Aggregate only externally reported energy values; never estimate absent telemetry."""

    devices = (await db.execute(select(Device).order_by(Device.code))).scalars().all()
    energy_devices = [device for device in devices if (device.operational_metrics or {}).get("energy_kwh_total") is not None]
    power_devices = [device for device in devices if (device.operational_metrics or {}).get("power_kw") is not None]
    return {
        "has_data": bool(energy_devices or power_devices),
        "total_energy_kwh": round(sum(float(device.operational_metrics["energy_kwh_total"]) for device in energy_devices), 3) if energy_devices else None,
        "current_power_kw": round(sum(float(device.operational_metrics["power_kw"]) for device in power_devices), 3) if power_devices else None,
        "devices_reporting_energy": len(energy_devices),
        "devices": [
            {
                "id": str(device.id), "code": device.code, "type": device.type,
                "battery": device.battery, "status": device.status,
                "power_kw": (device.operational_metrics or {}).get("power_kw"),
                "energy_kwh_total": (device.operational_metrics or {}).get("energy_kwh_total"),
                "mileage_km_total": (device.operational_metrics or {}).get("mileage_km_total"),
                "runtime_hours_total": (device.operational_metrics or {}).get("runtime_hours_total"),
            }
            for device in devices
        ],
    }


@router.get(
    "/safety",
    summary="查询安全状态",
    description="读取数据库中的全局急停锁存状态以及仍处于 open 或 ack 的真实告警。",
    response_description="全局安全状态、急停信息和活动告警列表。",
)
async def get_safety_view(
    db: AsyncSession = Depends(get_db),
    _role=Depends(require("read")),
) -> dict:
    """Return the persisted safety latch and currently active database alerts."""

    safety = await db.get(SafetyState, "global")
    result = await db.execute(
        select(Alert).where(Alert.status.in_(["open", "ack"])).order_by(Alert.created_at.desc()).limit(100)
    )
    alerts = result.scalars().all()
    return {
        "global_estop": {
            "active": bool(safety and safety.active),
            "cycle_id": safety.cycle_id if safety else None,
            "source": safety.source if safety else None,
            "updated_at": safety.updated_at.isoformat() if safety else None,
        },
        "open_alert_count": len(alerts),
        "critical_alert_count": sum(1 for alert in alerts if alert.level == "critical"),
        "alerts": [
            {
                "id": str(alert.id), "device_id": str(alert.device_id) if alert.device_id else None,
                "level": alert.level, "category": alert.category, "message": alert.message,
                "status": alert.status, "created_at": alert.created_at.isoformat(),
            }
            for alert in alerts
        ],
    }


@router.get(
    "/maintenance",
    summary="查询维护工单",
    description="查询由设备实际累计运行时长或里程阈值触发的维护工单，可按工单状态筛选。",
    response_description="维护工单及关联设备信息列表。",
)
async def get_maintenance_view(
    status_filter: str | None = Query(default=None, alias="status", description="工单状态，例如 open、ack 或 resolved。"),
    db: AsyncSession = Depends(get_db),
    _role=Depends(require("read")),
) -> list[dict]:
    statement = select(MaintenanceWorkOrder, Device).join(Device, Device.id == MaintenanceWorkOrder.device_id)
    if status_filter:
        statement = statement.where(MaintenanceWorkOrder.status == status_filter)
    result = await db.execute(statement.order_by(MaintenanceWorkOrder.created_at.desc()))
    return [
        {
            "id": str(work_order.id), "device_id": str(device.id), "device_code": device.code,
            "trigger_type": work_order.trigger_type, "threshold": work_order.threshold,
            "observed_value": work_order.observed_value, "status": work_order.status,
            "note": work_order.note, "created_at": work_order.created_at.isoformat(),
            "closed_at": work_order.closed_at.isoformat() if work_order.closed_at else None,
        }
        for work_order, device in result.all()
    ]


@router.get(
    "/environment",
    summary="查询最新环境观测",
    description="读取设备事件中最新一条 environment 记录；无真实观测时返回 has_data=false。",
    response_description="环境数据可用性、观测时间和实际指标。",
)
async def get_environment(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """环境数据——从 device_events 中 event_type='environment' 的最新记录提取。

    如果没有环境数据则返回默认值（明确标识无数据）。
    """
    result = await db.execute(
        select(DeviceEvent)
        .where(DeviceEvent.event_type == "environment")
        .order_by(DeviceEvent.time.desc())
        .limit(1)
    )
    event = result.scalar_one_or_none()

    if event and event.payload:
        return {
            "has_data": True,
            "dust_level": event.payload.get("dust_level", "未知"),
            "temperature": event.payload.get("temperature"),
            "humidity": event.payload.get("humidity"),
            "noise": event.payload.get("noise"),
            "updated_at": event.time.isoformat(),
        }

    # 从摄像头识别数据中提取扬尘
    cam_result = await db.execute(
        select(CameraDetection)
        .order_by(CameraDetection.detected_at.desc())
        .limit(1)
    )
    detection = cam_result.scalar_one_or_none()
    if detection:
        return {
            "has_data": True,
            "dust_level": detection.dust_level,
            "temperature": None,
            "humidity": None,
            "noise": None,
            "updated_at": detection.detected_at.isoformat(),
            "source": "camera_detection",
        }

    return {
        "has_data": False,
        "dust_level": "无数据",
        "temperature": None,
        "humidity": None,
        "noise": None,
        "updated_at": None,
    }


@router.get(
    "/health-score",
    summary="查询设备集群健康分",
    description="根据数据库中设备在线状态和健康字段计算当前集群健康比例。",
    response_description="健康分、设备总数、健康设备数和数据可用性。",
)
async def get_health_score(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """系统健康分——从设备健康状态聚合计算。

    健康分 = 在线且无故障设备数 / 总设备数 * 100
    """
    total = await db.scalar(select(func.count(Device.id)))
    healthy = await db.scalar(
        select(func.count(Device.id)).where(
            Device.status.notin_(["fault", "maintenance"])
        )
    )
    score = round((healthy / total * 100) if total > 0 else 0)

    # 告警统计
    open_alerts = await db.scalar(
        select(func.count(Alert.id)).where(Alert.status == "open")
    )
    critical_alerts = await db.scalar(
        select(func.count(Alert.id)).where(Alert.status == "open", Alert.level == "critical")
    )

    return {
        "score": score,
        "total_devices": total or 0,
        "healthy_devices": healthy or 0,
        "open_alerts": open_alerts or 0,
        "critical_alerts": critical_alerts or 0,
    }


@router.get(
    "/cameras",
    summary="查询摄像头看板数据",
    description="返回已注册摄像头及各摄像头最新一条外部视觉检测结果，不生成检测数据。",
    response_description="摄像头基本信息和最新检测结果列表。",
)
async def get_cameras(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """摄像头列表 + 最新识别结果。"""
    cameras = await db.execute(select(Camera).order_by(Camera.code))
    result = []
    for cam in cameras.scalars():
        # 获取最新识别记录
        det_result = await db.execute(
            select(CameraDetection)
            .where(CameraDetection.camera_id == cam.id)
            .order_by(CameraDetection.detected_at.desc())
            .limit(1)
        )
        det = det_result.scalar_one_or_none()
        result.append({
            "id": str(cam.id),
            "code": cam.code,
            "name": cam.name,
            "location": cam.location,
            "stream_url": cam.stream_url,
            "is_online": cam.is_online,
            "latest_detection": {
                "excavator_count": det.excavator_count if det else 0,
                "truck_count": det.truck_count if det else 0,
                "person_count": det.person_count if det else 0,
                "dust_level": det.dust_level if det else "无数据",
                "slope_risk": det.slope_risk if det else "无数据",
                "ai_compliance_rate": det.ai_compliance_rate if det else 0,
                "detected_at": det.detected_at.isoformat() if det and det.detected_at else None,
            } if det else None,
        })
    return result
