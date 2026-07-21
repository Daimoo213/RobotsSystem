"""Reports router — Excel export."""

from __future__ import annotations

import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require
from app.models.models import Alert, Device, MissionExecution, Task

router = APIRouter(prefix="/reports", tags=["reports"])


def _parse_date(value: str | None, field: str) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{field} must be ISO-8601") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@router.post("/export")
async def export_report(
    report_type: str = "summary",
    date_from: str | None = None,
    date_to: str | None = None,
    db: AsyncSession = Depends(get_db),
    _role=Depends(require("report.export")),
) -> StreamingResponse:
    """Export an Excel report from actual persisted records for the requested interval."""
    start = _parse_date(date_from, "date_from")
    end = _parse_date(date_to, "date_to")
    if start and end and end < start:
        raise HTTPException(status_code=422, detail="date_to must not precede date_from")
    wb = Workbook()

    # ── Sheet 1: Device summary ─────────────────────────
    ws1 = wb.active
    ws1.title = "设备维度"
    ws1.append(["设备编码", "名称", "类型", "状态", "电量", "所属标段"])
    device_statement = select(Device)
    if start:
        device_statement = device_statement.where(Device.registered_at >= start)
    if end:
        device_statement = device_statement.where(Device.registered_at <= end)
    result = await db.execute(device_statement.order_by(Device.code))
    for d in result.scalars().all():
        ws1.append([d.code, d.name, d.type, d.status, d.battery, d.section_id])

    # ── Sheet 2: Task summary ───────────────────────────
    ws2 = wb.create_sheet("任务维度")
    ws2.append(["任务编码", "名称", "工序", "状态", "进度", "优先级", "阶段"])
    task_statement = select(Task)
    if start:
        task_statement = task_statement.where(Task.created_at >= start)
    if end:
        task_statement = task_statement.where(Task.created_at <= end)
    result = await db.execute(task_statement.order_by(Task.created_at))
    for t in result.scalars().all():
        ws2.append([t.code, t.name, t.process_id, t.status, t.progress, t.priority, t.stage])

    # ── Sheet 3: Alerts ─────────────────────────────────
    ws3 = wb.create_sheet("告警维度")
    ws3.append(["告警ID", "设备ID", "等级", "分类", "消息", "状态", "创建时间"])
    alert_statement = select(Alert)
    if start:
        alert_statement = alert_statement.where(Alert.created_at >= start)
    if end:
        alert_statement = alert_statement.where(Alert.created_at <= end)
    result = await db.execute(alert_statement.order_by(Alert.created_at.desc()).limit(500))
    for a in result.scalars().all():
        ws3.append([str(a.id), str(a.device_id) if a.device_id else "",
                    a.level, a.category, a.message, a.status,
                    a.created_at.isoformat() if a.created_at else ""])

    # ── Sheet 4: Progress ───────────────────────────────
    ws4 = wb.create_sheet("进度维度")
    progress_statement = select(Task.stage, func.count(), func.avg(Task.progress)).where(Task.status == "completed")
    if start:
        progress_statement = progress_statement.where(Task.completed_at >= start)
    if end:
        progress_statement = progress_statement.where(Task.completed_at <= end)
    result = await db.execute(progress_statement.group_by(Task.stage))
    ws4.append(["阶段", "已完成任务数", "平均进度"])
    for row in result.all():
        ws4.append([row[0], row[1], round(row[2] or 0, 2)])

    # ── Sheet 5: Energy ─────────────────────────────────
    ws5 = wb.create_sheet("能耗维度")
    result = await db.execute(
        select(Device.type, func.count(), func.avg(Device.battery))
        .group_by(Device.type)
    )
    ws5.append(["设备类型", "数量", "平均电量"])
    for row in result.all():
        ws5.append([row[0], row[1], round(row[2] or 0, 2)])

    # Mission attempts are the source of truth for device-side execution.
    ws6 = wb.create_sheet("任务执行明细")
    ws6.append(["执行ID", "任务编码", "设备ID", "状态", "进度", "失败码", "下发时间", "开始时间", "结束时间"])
    execution_statement = select(MissionExecution, Task).join(Task, Task.id == MissionExecution.task_id)
    if start:
        execution_statement = execution_statement.where(MissionExecution.dispatched_at >= start)
    if end:
        execution_statement = execution_statement.where(MissionExecution.dispatched_at <= end)
    executions = await db.execute(execution_statement.order_by(MissionExecution.dispatched_at.desc()))
    for execution, task in executions.all():
        ws6.append([
            execution.gateway_execution_id,
            task.code,
            str(execution.device_id),
            execution.state,
            execution.progress,
            execution.failure_code,
            execution.dispatched_at.isoformat(),
            execution.started_at.isoformat() if execution.started_at else None,
            execution.completed_at.isoformat() if execution.completed_at else None,
        ])

    for sheet in wb.worksheets:
        sheet.freeze_panes = "A2"
        for column in sheet.columns:
            sheet.column_dimensions[column[0].column_letter].width = min(
                max((len(str(cell.value or "")) for cell in column), default=8) + 2,
                42,
            )

    # Write to buffer
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = f"report_{report_type}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/export-pdf")
async def export_pdf_report(
    date_from: str | None = None,
    date_to: str | None = None,
    db: AsyncSession = Depends(get_db),
    _role=Depends(require("report.export")),
) -> StreamingResponse:
    """Export a concise PDF from persisted project, task, device, and alert totals."""

    start = _parse_date(date_from, "date_from")
    end = _parse_date(date_to, "date_to")
    if start and end and end < start:
        raise HTTPException(status_code=422, detail="date_to must not precede date_from")
    task_statement = select(func.count(Task.id), func.count(Task.id).filter(Task.status == "completed"))
    alert_statement = select(func.count(Alert.id), func.count(Alert.id).filter(Alert.status.in_(["open", "ack"])))
    if start:
        task_statement = task_statement.where(Task.created_at >= start)
        alert_statement = alert_statement.where(Alert.created_at >= start)
    if end:
        task_statement = task_statement.where(Task.created_at <= end)
        alert_statement = alert_statement.where(Alert.created_at <= end)
    task_totals = (await db.execute(task_statement)).one()
    alert_totals = (await db.execute(alert_statement)).one()
    device_count = await db.scalar(select(func.count(Device.id)))

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setTitle("Robots Cluster Scheduler Report")
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(48, 800, "Robots Cluster Scheduler Report")
    pdf.setFont("Helvetica", 10)
    rows = [
        ("Generated at", datetime.now(timezone.utc).isoformat()),
        ("Date from", start.isoformat() if start else "all retained records"),
        ("Date to", end.isoformat() if end else "all retained records"),
        ("Registered devices", str(device_count or 0)),
        ("Tasks", str(task_totals[0] or 0)),
        ("Completed tasks", str(task_totals[1] or 0)),
        ("Alerts", str(alert_totals[0] or 0)),
        ("Open or acknowledged alerts", str(alert_totals[1] or 0)),
    ]
    y = 760
    for label, value in rows:
        pdf.drawString(48, y, f"{label}: {value}")
        y -= 24
    pdf.showPage()
    pdf.save()
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=robots_scheduler_report.pdf"},
    )
