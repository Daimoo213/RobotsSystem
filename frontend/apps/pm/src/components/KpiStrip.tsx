/** PM端 KPI strip — 8项指标全部从 /dashboard/kpi 获取，无硬编码。 */

import { useEffect } from 'react';
import { TrendingUp, Truck, Activity, ClipboardList, AlertTriangle, Gauge, Package, ScanEye } from 'lucide-react';
import { usePmStore } from '../stores/pmStore';
import { getKpi, type KpiData } from '@robots/api-client';

const KPIS = [
  { key: 'overall_progress', label: '总体进度', icon: TrendingUp, color: '#2FD7FF', unit: '%' },
  { key: 'earthwork_rate', label: '土方完成率', icon: Truck, color: '#34DF9A', unit: '%' },
  { key: 'running_tasks', label: '进行中任务', icon: Activity, color: '#2FD7FF', unit: '' },
  { key: 'pending_tasks', label: '待闭环事项', icon: ClipboardList, color: '#FFB33D', unit: '' },
  { key: 'delay_risk', label: '延期风险', icon: AlertTriangle, color: '#FF5C6D', unit: '' },
  { key: 'resource_load', label: '资源负载率', icon: Gauge, color: '#3D8CFF', unit: '%' },
  { key: 'spoil_trips', label: '渣土外运量', icon: Package, color: '#B56CFF', unit: 'm³' },
  { key: 'ai_compliance', label: 'AI识别合规率', icon: ScanEye, color: '#34DF9A', unit: '%' },
] as const;

export function KpiStrip() {
  const { kpiData, setKpiData } = usePmStore();

  useEffect(() => {
    const fetchKpi = async () => {
      try {
        const data = await getKpi();
        setKpiData(data);
      } catch (e) { console.error(e); }
    };
    fetchKpi();
    const interval = setInterval(fetchKpi, 5000); // 每5秒刷新
    return () => clearInterval(interval);
  }, [setKpiData]);

  return (
    <div className="grid grid-cols-8 gap-2">
      {KPIS.map((kpi) => {
        const Icon = kpi.icon;
        const val = kpiData?.[kpi.key as keyof KpiData];
        const displayVal = val !== undefined && val !== null ? val : '--';
        return (
          <div
            key={kpi.key}
            className="flex items-center gap-2 rounded-lg border border-[rgba(91,183,255,0.22)] bg-[rgba(9,25,41,0.86)] px-3 py-2"
          >
            <Icon size={20} style={{ color: kpi.color }} />
            <div>
              <div className="font-mono text-[20px] font-bold leading-tight" style={{ color: kpi.color }}>
                {displayVal}{typeof val === 'number' ? kpi.unit : ''}
              </div>
              <div className="text-[10px] text-[#79A3BF]">{kpi.label}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
