/** O&M端 Right column — topology (from devices), type distribution, alerts, system overview.
 * 所有数据从 store/API 获取，无硬编码。
 */

import { useCallback, useEffect, useState } from 'react';
import { Panel, AlertList, ProgressBar } from '@robots/ui';
import { useOmStore } from '../stores/omStore';
import { DEVICE_TYPE_LABELS, COLORS, formatDisplayValue } from '@robots/utils';
import { acknowledgeAlert, getEnvironment, getHealthScore, getKpi } from '@robots/api-client';
import type { EnvironmentData, HealthScore, KpiData } from '@robots/api-client';

export function RightColumn() {
  const { devices, alerts, upsertAlert } = useOmStore();
  const [health, setHealth] = useState<HealthScore | null>(null);
  const [env, setEnv] = useState<EnvironmentData | null>(null);
  const [kpi, setKpi] = useState<KpiData | null>(null);
  const [acknowledgingId, setAcknowledgingId] = useState<string | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [h, e, dashboardKpi] = await Promise.all([getHealthScore(), getEnvironment(), getKpi()]);
        setHealth(h);
        setEnv(e);
        setKpi(dashboardKpi);
      } catch (e) { console.error(e); }
    };
    fetchData();
    const interval = setInterval(fetchData, 10000);
    return () => clearInterval(interval);
  }, []);

  const handleAcknowledge = useCallback(async (alertId: string) => {
    setAcknowledgingId(alertId);
    try {
      await acknowledgeAlert(alertId);
      const alert = alerts.find((item) => item.id === alertId);
      if (alert) upsertAlert({ ...alert, status: 'ack' });
    } catch (error) {
      console.error(error);
    } finally {
      setAcknowledgingId(null);
    }
  }, [alerts, upsertAlert]);

  // 设备类型分布（从 devices 计算）
  const typeData = Object.entries(DEVICE_TYPE_LABELS).map(([type, label]) => ({
    label, value: devices.filter((d) => d.type === type).length,
  })).filter((d) => d.value > 0);

  // 集群拓扑节点（从 devices 数据渲染）
  const topologyNodes = devices.slice(0, 20).map((d, i) => ({
    id: d.id,
    code: d.code,
    isOnline: d.status !== 'fault' && d.status !== 'maintenance',
  }));

  return (
    <div className="flex h-full flex-col gap-2 overflow-y-auto">
      <Panel title={`集群协同拓扑 (${topologyNodes.length})`}>
        <div className="relative h-32 flex items-center justify-center">
          <svg width="100%" height="100%" viewBox="0 0 200 120">
            {/* Center node */}
            <circle cx="100" cy="60" r="10" fill="#2FD7FF" opacity="0.3" />
            <circle cx="100" cy="60" r="6" fill="#2FD7FF" />
            <text x="100" y="80" textAnchor="middle" className="fill-[#aecce0]" style={{ fontSize: 8 }}>调度中心</text>
            {/* Device nodes */}
            {topologyNodes.map((node, i) => {
              const angle = (i / topologyNodes.length) * Math.PI * 2;
              const x = 100 + Math.cos(angle) * 45;
              const y = 60 + Math.sin(angle) * 35;
              return (
                <g key={node.id}>
                  <line x1="100" y1="60" x2={x} y2={y} stroke={node.isOnline ? 'rgba(52,223,154,0.3)' : 'rgba(255,92,109,0.3)'} strokeWidth="0.5" />
                  <circle cx={x} cy={y} r="3" fill={node.isOnline ? '#34DF9A' : '#FF5C6D'} opacity="0.8" />
                </g>
              );
            })}
          </svg>
        </div>
      </Panel>

      <Panel title="设备类型分布">
        <div className="space-y-1">
          {typeData.map((d) => (
            <div key={d.label} className="flex items-center gap-2">
              <span className="w-20 text-[11px] text-[#aecce0]">{d.label}</span>
              <div className="flex-1"><ProgressBar value={(d.value / Math.max(devices.length, 1)) * 100} color={COLORS.cyan} height={6} /></div>
              <span className="w-6 text-right font-mono text-[11px] text-[#E6F6FF]">{d.value}</span>
            </div>
          ))}
          {typeData.length === 0 && <div className="py-2 text-center text-[12px] text-[#5A7A92]">加载中...</div>}
        </div>
      </Panel>

      <Panel title="实时告警" className="flex-1 min-h-[100px]">
        <AlertList
          alerts={alerts}
          maxItems={15}
          onAcknowledge={handleAcknowledge}
          acknowledgingId={acknowledgingId}
        />
      </Panel>

      <Panel title="系统概览">
        <div className="space-y-1.5">
          <div>
            <div className="mb-0.5 flex justify-between text-[11px]">
              <span className="text-[#aecce0]">节点在线率</span>
              <span className="font-mono" style={{ color: (health?.score ?? 0) > 80 ? '#34DF9A' : '#FFB33D' }}>{health?.score ?? '--'}%</span>
            </div>
            <ProgressBar value={health?.score ?? 0} color={COLORS.green} height={4} />
          </div>
          <div>
            <div className="mb-0.5 flex justify-between text-[11px]">
              <span className="text-[#aecce0]">任务完成率</span>
              <span className="font-mono text-[#2FD7FF]">{kpi ? `${kpi.overall_progress}%` : '--'}</span>
            </div>
            <ProgressBar value={kpi?.overall_progress ?? 0} color={COLORS.cyan} height={4} />
          </div>
          <div className="flex justify-between text-[11px]">
            <span className="text-[#aecce0]">未处理告警</span>
            <span className="font-mono" style={{ color: (health?.open_alerts ?? 0) > 0 ? '#FFB33D' : '#34DF9A' }}>{health?.open_alerts ?? '--'}</span>
          </div>
          <div className="flex justify-between text-[11px]">
            <span className="text-[#aecce0]">遥测更新时间</span>
            <span className="font-mono text-[#aecce0]">
              {env?.updated_at ? new Date(env.updated_at).toLocaleTimeString() : '--'}
            </span>
          </div>
          {env?.has_data && (
            <div className="flex justify-between text-[11px]">
              <span className="text-[#aecce0]">扬尘等级</span>
              <span style={{ color: ['优', '良'].includes(formatDisplayValue(env.dust_level)) ? '#34DF9A' : '#FFB33D' }}>{formatDisplayValue(env.dust_level)}</span>
            </div>
          )}
        </div>
      </Panel>
    </div>
  );
}
