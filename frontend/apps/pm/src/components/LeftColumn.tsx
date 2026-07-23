/** PM端 Left column — robot count, resource load (API), stage overview (computed).
 * 所有数据从 API 获取或从 tasks 聚合计算，无硬编码。
 */

import { useEffect } from 'react';
import { Panel, DonutChart, ProgressBar } from '@robots/ui';
import { usePmStore } from '../stores/pmStore';
import { DEVICE_TYPE_LABELS, DEVICE_STATUS_LABELS, STAGES, COLORS, STATUS_COLORS, formatDisplayValue } from '@robots/utils';
import { getResourceLoad, getTrend, getCameras } from '@robots/api-client';

export function LeftColumn() {
  const { devices, tasks, setResourceLoad, resourceLoad, setTrendData, setCameras } = usePmStore();

  // 获取资源负载数据和趋势数据
  useEffect(() => {
    const fetchData = async () => {
      try {
        const [load, trend, cams] = await Promise.all([getResourceLoad(), getTrend(7), getCameras()]);
        setResourceLoad(load);
        setTrendData(trend);
        setCameras(cams);
      } catch (e) { console.error(e); }
    };
    fetchData();
    const interval = setInterval(fetchData, 15000);
    return () => clearInterval(interval);
  }, [setResourceLoad, setTrendData, setCameras]);

  // 机器人数量按类型统计（从 devices 计算）
  const typeData = Object.entries(DEVICE_TYPE_LABELS).map(([type, label]) => {
    const count = devices.filter((d) => d.type === type).length;
    const colors: Record<string, string> = { agv: '#2FD7FF', excavator: '#FFB33D', crane: '#B56CFF', masonry: '#34DF9A', inspect: '#3D8CFF' };
    return { label, value: count, color: colors[type] || '#687988' };
  }).filter((d) => d.value > 0);

  // 设备状态分布（从 devices 计算）
  const statusData = Object.entries(DEVICE_STATUS_LABELS).map(([status, label]) => {
    const count = devices.filter((d) => d.status === status).length;
    return { label, value: count, color: STATUS_COLORS[status] || '#687988' };
  }).filter((d) => d.value > 0);

  // 阶段进度（从 tasks 聚合计算）
  // 当前阶段 = 第一个"尚未全部完成"的阶段（按阶段顺序）
  const stageProgressRaw = STAGES.map((s) => {
    const stageTasks = tasks.filter((t) => t.stage === s.value);
    const done = stageTasks.filter((t) => t.status === 'completed').length;
    const total = stageTasks.length;
    const pct = total > 0 ? Math.round((done / total) * 100) : 0;
    return { ...s, pct, total, done };
  });
  const currentStageValue = stageProgressRaw.find((s) => s.total > 0 && s.pct < 100)?.value
    || stageProgressRaw.find((s) => s.total > 0)?.value
    || null;
  const stageProgress = stageProgressRaw.map((s) => ({ ...s, isCurrent: s.value === currentStageValue }));

  return (
    <div className="flex min-h-0 h-full flex-col gap-2 overflow-y-auto">
      <Panel title="机器人投入分布" className="shrink-0">
        {typeData.length > 0 ? (
          <DonutChart data={typeData} centerValue={devices.length} centerLabel="台" />
        ) : (
          <div className="py-8 text-center text-[12px] text-[#5A7A92]">加载中...</div>
        )}
      </Panel>

      <Panel title="设备状态分布" className="shrink-0">
        {statusData.length > 0 ? (
          <DonutChart data={statusData} size={130} thickness={18} />
        ) : (
          <div className="py-4 text-center text-[12px] text-[#5A7A92]">加载中...</div>
        )}
      </Panel>

      <Panel title="资源负载" className="shrink-0">
        <div className="space-y-1.5">
          {resourceLoad.length > 0 ? (
            resourceLoad.map((item) => (
              <div key={item.type} className="flex items-center gap-2">
                <span className="w-16 text-[11px] text-[#aecce0]">{formatDisplayValue(item.label, '未知设备类型')}</span>
                <div className="flex-1">
                  <ProgressBar
                    value={item.load_rate}
                    color={item.load_rate > 90 ? COLORS.red : item.load_rate > 70 ? COLORS.amber : COLORS.green}
                    height={6}
                  />
                </div>
                <span className="w-14 text-right font-mono text-[10px] text-[#E6F6FF]">{item.active}/{item.total}</span>
              </div>
            ))
          ) : (
            <div className="py-2 text-center text-[12px] text-[#5A7A92]">加载中...</div>
          )}
        </div>
      </Panel>

      <Panel title="施工阶段总览" className="shrink-0">
        <div className="space-y-2">
          {stageProgress.map((s) => (
            <div key={s.value} className={s.isCurrent ? 'rounded border border-[#2FD7FF] p-1.5' : 'p-1.5'}>
              <div className="mb-1 flex items-center justify-between">
                <span className={`text-[12px] ${s.isCurrent ? 'text-[#2FD7FF]' : s.pct === 100 && s.total > 0 ? 'text-[#34DF9A]' : 'text-[#5A7A92]'}`}>
                  {s.isCurrent && <span className="mr-1 inline-block h-1.5 w-1.5 rounded-full bg-[#2FD7FF]" style={{ animation: 'blink 1.5s infinite' }} />}
                  {s.label}
                </span>
                <span className="font-mono text-[11px] text-[#aecce0]">
                  {s.total > 0 ? `${s.pct}% (${s.done}/${s.total})` : '无任务'}
                </span>
              </div>
              <ProgressBar
                value={s.pct}
                color={s.pct === 100 && s.total > 0 ? COLORS.green : s.isCurrent ? COLORS.cyan : COLORS.gray}
                height={4}
              />
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}
