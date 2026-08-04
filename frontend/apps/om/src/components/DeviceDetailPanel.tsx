/** O&M device drill-down backed by the persisted telemetry and alert history. */

import { useEffect, useState } from 'react';
import { Play, RotateCcw, X } from 'lucide-react';
import { useOmStore } from '../stores/omStore';
import { CameraSensorPanel } from './CameraSensorPanel';
import { ALERT_STATUS_LABELS, DEVICE_TYPE_LABELS, DEVICE_STATUS_LABELS, HEALTH_KEYS, HEALTH_STATUS_LABELS, MISSION_PHASE_LABELS, MISSION_STATE_LABELS, formatPosition, formatUserMessage, getDeviceDisplayStatus, getHealthColor, getStatusColor } from '@robots/utils';
import { getDeviceDetail, requestManualCalibration, sendCommand } from '@robots/api-client';
import type { DeviceDetail } from '@robots/api-client';

export function DeviceDetailPanel() {
  const { devices, selectedDeviceId, selectDevice } = useOmStore();
  const device = devices.find((item) => item.id === selectedDeviceId);
  const [detail, setDetail] = useState<DeviceDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [showTrajectory, setShowTrajectory] = useState(false);

  useEffect(() => {
    if (!device) return;
    setLoading(true);
    setDetail(null);
    getDeviceDetail(device.id)
      .then(setDetail)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [device?.id]);

  if (!device) return null;
  const displayStatus = getDeviceDisplayStatus(device.status, device.connection_status);
  const statusColor = getStatusColor(displayStatus);
  const trajectory = detail?.trajectory || [];

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/40" onClick={() => selectDevice(null)}>
      <div className="h-full w-full max-w-[480px] overflow-y-auto rounded-l-xl border-l border-[rgba(91,183,255,0.3)] bg-[rgba(9,25,41,0.95)] p-5" onClick={(event) => event.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-[16px] font-bold text-[#E6F6FF]">设备详情: {device.code}</h3>
          <button onClick={() => selectDevice(null)} className="text-[#79A3BF] hover:text-[#FF5C6D]" title="关闭"><X size={18} /></button>
        </div>

        <Section title="基本信息">
          <Row label="编码" value={device.code} mono />
          <Row label="名称" value={device.name} />
           <Row label="类型" value={DEVICE_TYPE_LABELS[device.type] || '未知设备类型'} />
           <Row label="连接状态" value={DEVICE_STATUS_LABELS[displayStatus] || '未知状态'} color={statusColor} />
           {(displayStatus === 'offline' || displayStatus === 'planned_offline') && <Row label="最后运行状态" value={DEVICE_STATUS_LABELS[device.status] || '未知状态'} color={getStatusColor(device.status)} />}
           {device.offline?.reason_code && <Row label="主动下线原因" value={formatOfflineReason(device.offline.reason_code)} color="#FFB33D" />}
           {device.offline?.expected_reconnect_at && <Row label="预计恢复时间" value={new Date(device.offline.expected_reconnect_at).toLocaleString()} />}
           {device.offline?.note && <Row label="下线说明" value={device.offline.note} />}
          <Row label="标段" value={device.section_id || '-'} />
        </Section>

        <Section title="实时状态">
          <Row label="位置" value={formatPosition(device.position)} mono />
          <Row label="电量" value={`${Math.round(device.battery)}%`} color={device.battery < 20 ? '#FF5C6D' : '#34DF9A'} />
          <Row label="上报时间" value={device.last_heartbeat ? new Date(device.last_heartbeat).toLocaleString() : '未上报'} />
           {device.operational_metrics?.power_kw !== undefined && <Row label="功率" value={`${device.operational_metrics.power_kw} 千瓦`} />}
           {device.operational_metrics?.energy_kwh_total !== undefined && <Row label="累计能耗" value={`${device.operational_metrics.energy_kwh_total} 千瓦时`} />}
           {typeof device.operational_metrics?.mission_phase === 'string' && <Row label="当前任务阶段" value={MISSION_PHASE_LABELS[device.operational_metrics.mission_phase] || '未知执行阶段'} color="#2FD7FF" />}
        </Section>

        <Section title="体检指标">
          <div className="flex justify-between">
            {HEALTH_KEYS.map(({ key, label }) => {
              const value = device.health?.[key as keyof typeof device.health] || 'unknown';
               return <div key={key} className="text-center"><div className="text-[11px] text-[#5A7A92]">{label}</div><div className="text-[12px] font-mono font-bold" style={{ color: getHealthColor(value) }}>{HEALTH_STATUS_LABELS[value] || '未知'}</div></div>;
            })}
          </div>
        </Section>

        <CameraSensorPanel deviceId={device.id} />

        <Section title={`历史告警 (${detail?.alerts.length ?? 0})`}>
          {loading && <div className="text-[12px] text-[#5A7A92]">读取历史记录...</div>}
          {!loading && !detail?.alerts.length && <div className="text-[12px] text-[#5A7A92]">暂无已上报告警</div>}
           {detail?.alerts.slice(0, 5).map((alert) => <div key={alert.id} className="border-b border-[rgba(91,183,255,0.1)] py-1 text-[11px]"><div className="text-[#aecce0]">{formatUserMessage(alert.message)}</div><div className="text-[#5A7A92]">{new Date(alert.created_at).toLocaleString()} · {ALERT_STATUS_LABELS[alert.status] || '未知状态'}</div></div>)}
        </Section>

        <Section title={`轨迹回放 (${trajectory.length})`}>
          <button onClick={() => setShowTrajectory((value) => !value)} disabled={trajectory.length === 0} className="flex items-center gap-1 rounded border border-[rgba(91,183,255,0.3)] px-3 py-1 text-[12px] text-[#2FD7FF] hover:border-[#2FD7FF] disabled:opacity-40"><Play size={12} /> {showTrajectory ? '隐藏轨迹' : '查看轨迹'}</button>
          {showTrajectory && trajectory.map((point) => <div key={point.time} className="mt-1 flex justify-between text-[11px] text-[#aecce0]"><span>{new Date(point.time).toLocaleTimeString()}</span><span className="font-mono">{point.position ? formatPosition(point.position) : '--'}</span></div>)}
        </Section>

        <Section title={`任务执行 (${detail?.executions.length ?? 0})`}>
          {!detail?.executions.length && <div className="text-[12px] text-[#5A7A92]">暂无任务执行记录</div>}
           {detail?.executions.slice(0, 4).map((execution) => <div key={execution.id} className="border-b border-[rgba(91,183,255,0.1)] py-1 text-[11px]"><div className="text-[#aecce0]">{execution.task_code} · {execution.task_name}</div><div className="text-[#5A7A92]">{MISSION_STATE_LABELS[execution.state] || '未知状态'} · {MISSION_PHASE_LABELS[execution.phase] || '未知执行阶段'} · {Math.round(execution.progress)}%</div></div>)}
        </Section>

        <div className="mt-4 flex gap-2">
          <button onClick={() => sendCommand(device.id, 'pause').catch(console.error)} className="flex flex-1 items-center justify-center gap-1 rounded border border-[rgba(255,179,61,0.4)] py-1.5 text-[12px] text-[#FFB33D] hover:bg-[rgba(255,179,61,0.1)]">暂停</button>
          <button onClick={() => requestManualCalibration(device.id).catch(console.error)} className="flex flex-1 items-center justify-center gap-1 rounded border border-[rgba(47,215,255,0.4)] py-1.5 text-[12px] text-[#2FD7FF] hover:bg-[rgba(47,215,255,0.1)]">校准</button>
          <button onClick={() => sendCommand(device.id, 'reset').catch(console.error)} className="flex flex-1 items-center justify-center gap-1 rounded border border-[rgba(181,108,255,0.4)] py-1.5 text-[12px] text-[#B56CFF] hover:bg-[rgba(181,108,255,0.1)]"><RotateCcw size={12} /> 重置</button>
        </div>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <div className="mb-3 rounded-lg border border-[rgba(91,183,255,0.15)] p-2.5"><div className="mb-1.5 text-[12px] font-medium text-[#2FD7FF]">{title}</div>{children}</div>;
}

function Row({ label, value, mono, color }: { label: string; value: string; mono?: boolean; color?: string }) {
  return <div className="flex justify-between py-0.5 text-[12px]"><span className="text-[#79A3BF]">{label}</span><span className={mono ? 'font-mono' : ''} style={{ color: color || '#E6F6FF' }}>{value}</span></div>;
}

function formatOfflineReason(reason: string): string {
  const labels: Record<string, string> = {
    shutdown: '正常关机', maintenance: '计划维护', network_change: '网络切换',
    safety_stop: '安全停机', operator_requested: '人工请求', other: '其他原因',
  };
  return labels[reason] || '其他原因';
}
