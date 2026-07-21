/** PM端 Gantt chart — 任务调度甘特图。
 *
 * 功能（参照开源甘特图，如 frappe-gantt）：
 * - 真实时间轴：日/周/月/季度切换改变单位长度与刻度，任务条随之缩放并可横向滚动
 * - 阶段分组汇总条 + 任务行
 * - 依赖关系连线（前置→后继，带箭头）
 * - 里程碑菱形标记（阶段关键节点）
 * - 任务条进度填充 + 延期风险标识
 * - 今日线
 * 所有数据来自 tasks（DB），无硬编码。
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { Download, Layers, Filter, AlertTriangle, Milestone } from 'lucide-react';
import { Panel, ProgressBar } from '@robots/ui';
import { usePmStore } from '../stores/pmStore';
import { COLORS, formatDateTime } from '@robots/utils';
import type { Task } from '@robots/shared-types';
import { exportReport } from '@robots/api-client';
import { listDevices, pauseTask, reassignTask, resumeTask } from '@robots/api-client';
import type { Device } from '@robots/shared-types';

type Granularity = 'day' | 'week' | 'month' | 'quarter';

const STATUS_FILL: Record<string, string> = {
  completed: COLORS.green, running: COLORS.cyan, pending: COLORS.blue,
  paused: COLORS.amber, failed: COLORS.red, assigned: COLORS.cyan,
};

const STATUS_LABELS: Record<string, string> = {
  completed: '已完成', running: '进行中', pending: '待开始',
  paused: '已暂停', failed: '失败', assigned: '已分配',
};

const STAGE_LABELS: Record<string, string> = {
  earthwork: '土方开发', foundation: '基础施工', main: '主体施工',
  mep: '机电安装', finishing: '装修施工', landscape: '室外景观', completion: '竣工',
};

// 每个粒度对应的"每天像素数"——切换会改变任务条宽度与可滚动性
const PX_PER_DAY: Record<Granularity, number> = {
  day: 90, week: 42, month: 14, quarter: 5,
};

const ROW_H = 28;            // 任务行高
const STAGE_ROW_H = 22;      // 阶段汇总行高
const AXIS_H = 28;           // 时间轴高度

export function GanttColumn() {
  const { tasks, activeStage } = usePmStore();
  const [granularity, setGranularity] = useState<Granularity>('month');
  const [filter, setFilter] = useState<'all' | 'risk' | 'running'>('all');
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);
  const [exporting, setExporting] = useState(false);

  // 横向滚动同步：右列内部横向滚动 ↔ 底部常驻滚动条
  const hScrollRef = useRef<HTMLDivElement>(null);   // 右列横向滚动容器
  const bottomScrollRef = useRef<HTMLDivElement>(null); // 底部常驻滚动条容器
  const syncing = useRef(false);
  const onHScroll = () => {
    if (syncing.current) return;
    syncing.current = true;
    if (bottomScrollRef.current && hScrollRef.current)
      bottomScrollRef.current.scrollLeft = hScrollRef.current.scrollLeft;
    syncing.current = false;
  };
  const onBottomScroll = () => {
    if (syncing.current) return;
    syncing.current = true;
    if (hScrollRef.current && bottomScrollRef.current)
      hScrollRef.current.scrollLeft = bottomScrollRef.current.scrollLeft;
    syncing.current = false;
  };

  // Alt+滚轮 → 横向滚动；普通滚轮放行给外层纵向滚动。
  // 用原生捕获监听（passive:false）在事件到达外层纵向容器前拦截，避免竖向同时滚动。
  useEffect(() => {
    const el = hScrollRef.current;
    if (!el) return;
    const onWheelCapture = (e: WheelEvent) => {
      if (e.altKey && el.scrollWidth > el.clientWidth + 1) {
        el.scrollLeft += e.deltaY;
        e.preventDefault();
        e.stopPropagation();
      }
    };
    el.addEventListener('wheel', onWheelCapture, { capture: true, passive: false });
    return () => el.removeEventListener('wheel', onWheelCapture, { capture: true });
  }, []);

  // ── 过滤 ───────────────────────────────────────────────
  const filtered = useMemo(() => tasks.filter((t) => {
    if (filter === 'risk') return t.status !== 'completed' && (t.progress < 30 || (t.planned_end && new Date(t.planned_end).getTime() < Date.now()));
    if (filter === 'running') return t.status === 'running' || t.status === 'assigned';
    return true;
  }), [tasks, filter]);

  // ── 时间范围（数据驱动）─────────────────────────────────
  const { minTime, maxTime, totalDays } = useMemo(() => {
    const times = filtered
      .flatMap((t) => [t.planned_start, t.planned_end].filter(Boolean))
      .map((t) => new Date(t as string).getTime());
    const fallback = Date.now();
    const min = times.length ? Math.min(...times) : fallback;
    const max = times.length ? Math.max(...times) : fallback + 86400000 * 30;
    // 留白：前后各扩 3 天
    const m0 = min - 3 * 86400000;
    const m1 = max + 3 * 86400000;
    return { minTime: m0, maxTime: m1, totalDays: Math.max((m1 - m0) / 86400000, 1) };
  }, [filtered]);

  const pxPerDay = PX_PER_DAY[granularity];
  const chartWidth = Math.max(totalDays * pxPerDay, 600);

  const xOf = (ms: number) => ((ms - minTime) / 86400000) * pxPerDay;
  const now = Date.now();
  const todayX = xOf(now);

  // ── 阶段分组 ───────────────────────────────────────────
  const stageOrder = ['earthwork', 'foundation', 'main', 'mep', 'finishing', 'landscape', 'completion'];
  const knownStages = new Set(stageOrder);
  // 未知/缺失 stage 的任务归入当前激活阶段，确保新增任务一定能显示
  const effStage = (t: Task) => (t.stage && knownStages.has(t.stage)) ? t.stage : activeStage;
  const stagesPresent = stageOrder.filter((s) => filtered.some((t) => effStage(t) === s));

  // 构建布局：阶段行 + 任务行，记录每行索引与 x 位置（供依赖连线与里程碑）
  interface RowInfo { key: string; type: 'stage' | 'task'; task?: Task; top: number; }
  const rows: RowInfo[] = [];
  const rowIndexByTaskId: Record<string, number> = {};
  let top = 0;
  for (const stage of stagesPresent) {
    const stTasks = filtered.filter((t) => effStage(t) === stage);
    if (stTasks.length === 0) continue;
    rows.push({ key: `stage:${stage}`, type: 'stage', top });
    top += STAGE_ROW_H;
    for (const t of stTasks) {
      rowIndexByTaskId[t.id] = rows.length;
      rows.push({ key: `task:${t.id}`, type: 'task', task: t, top });
      top += ROW_H;
    }
  }
  const bodyHeight = top;

  // 任务条几何
  const geom = (t: Task) => {
    const s = t.planned_start ? new Date(t.planned_start).getTime() : minTime;
    const e = t.planned_end ? new Date(t.planned_end).getTime() : s + 86400000;
    const left = xOf(s);
    const width = Math.max((e - s) / 86400000 * pxPerDay, 6);
    return { left, width };
  };

  // ── 依赖连线 ───────────────────────────────────────────
  const edges = useMemo(() => {
    const lines: { x1: number; y1: number; x2: number; y2: number; key: string }[] = [];
    for (const t of filtered) {
      for (const depId of t.dependencies || []) {
        const from = filtered.find((d) => d.id === depId);
        if (!from || !(depId in rowIndexByTaskId) || !(t.id in rowIndexByTaskId)) continue;
        const fg = geom(from);
        const tg = geom(t);
        const x1 = fg.left + fg.width;
        const y1 = rows[rowIndexByTaskId[depId]].top + ROW_H / 2;
        const x2 = tg.left;
        const y2 = rows[rowIndexByTaskId[t.id]].top + ROW_H / 2;
        lines.push({ x1, y1, x2, y2, key: `${depId}->${t.id}` });
      }
    }
    return lines;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtered, minTime, maxTime, granularity]);

  // ── 里程碑（阶段关键节点 = 阶段内最晚 planned_end）───────
  const milestones = useMemo(() => {
    return stagesPresent.map((stage) => {
      const stTasks = filtered.filter((t) => effStage(t) === stage);
      const maxEnd = stTasks.reduce((mx, t) => {
        const e = t.planned_end ? new Date(t.planned_end).getTime() : 0;
        return Math.max(mx, e);
      }, 0);
      const idx = rows.findIndex((r) => r.key === `stage:${stage}`);
      return {
        x: xOf(maxEnd),
        y: (idx >= 0 ? rows[idx].top : 0) + STAGE_ROW_H / 2,
        label: `${STAGE_LABELS[stage] || stage}节点`,
      };
    }).filter((m) => m.x >= 0 && m.x <= chartWidth);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtered, minTime, maxTime, granularity]);

  // ── 时间轴刻度 ─────────────────────────────────────────
  const ticks = useMemo(() => buildTicks(minTime, maxTime, granularity), [minTime, maxTime, granularity]);

  const downloadReport = async () => {
    setExporting(true);
    try {
      const blob = await exportReport({});
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'robots-scheduler-report.xlsx';
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      console.error(error);
    } finally {
      setExporting(false);
    }
  };

  return (
    <Panel
      title="任务调度甘特图"
      className="flex h-full min-w-0 flex-col"
      actions={
        <div className="flex items-center gap-1">
          {(['day', 'week', 'month', 'quarter'] as Granularity[]).map((g) => (
            <button
              key={g}
              onClick={() => setGranularity(g)}
              className={`rounded px-2 py-0.5 text-[11px] ${granularity === g ? 'bg-[#2FD7FF] text-[#050B13]' : 'text-[#79A3BF] hover:text-[#2FD7FF]'}`}
            >
              {g === 'day' ? '日' : g === 'week' ? '周' : g === 'month' ? '月' : '季度'}
            </button>
          ))}
          <span className="mx-1 text-[#5A7A92]">|</span>
          <button onClick={() => setFilter('running')} className={`flex items-center gap-1 rounded px-2 py-0.5 text-[11px] ${filter === 'running' ? 'bg-[#2FD7FF] text-[#050B13]' : 'text-[#79A3BF]'}`}>
            进行中
          </button>
          <button onClick={() => setFilter('risk')} className={`flex items-center gap-1 rounded px-2 py-0.5 text-[11px] ${filter === 'risk' ? 'bg-[#FF5C6D] text-[#050B13]' : 'text-[#79A3BF]'}`}>
            <AlertTriangle size={11} /> 仅风险
          </button>
          <button onClick={() => setFilter('all')} className={`rounded px-2 py-0.5 text-[11px] ${filter === 'all' ? 'bg-[#2FD7FF] text-[#050B13]' : 'text-[#79A3BF]'}`}>全部</button>
          <button onClick={downloadReport} disabled={exporting} title="导出数据库报表" className="rounded px-2 py-0.5 text-[11px] text-[#79A3BF] hover:text-[#2FD7FF] disabled:opacity-40"><Download size={11} /></button>
          <button className="rounded px-2 py-0.5 text-[11px] text-[#79A3BF] hover:text-[#2FD7FF]"><Layers size={11} /></button>
        </div>
      }
    >
      <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden">
        {/* Left + Right share one vertical scroll so rows stay aligned */}
        <div className="flex min-w-0">
        {/* Left: task list (fixed) */}
        <div className="w-[260px] shrink-0 border-r border-[rgba(91,183,255,0.15)]">
          <div className="sticky top-0 z-10 bg-[rgba(9,25,41,0.96)]" style={{ height: AXIS_H }}>
            <div className="flex h-full items-end px-2 pb-1 text-[10px] text-[#5A7A92]">任务 / 阶段</div>
          </div>
          {stagesPresent.map((stage) => (
            <div key={stage}>
              <div className="bg-[rgba(47,215,255,0.08)] px-2 py-1 text-[12px] font-medium text-[#2FD7FF]" style={{ height: STAGE_ROW_H }}>
                {STAGE_LABELS[stage] || stage}
              </div>
              {filtered.filter((t) => effStage(t) === stage).map((t) => (
                <div
                  key={t.id}
                  onClick={() => setSelectedTask(t)}
                  className="flex cursor-pointer items-center justify-between border-l-2 py-1 pl-2 pr-1 text-[11px] hover:bg-[rgba(47,215,255,0.08)]"
                  style={{ height: ROW_H, borderColor: STATUS_FILL[t.status] || COLORS.gray }}
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-1">
                      <span className="font-mono text-[9px] text-[#5A7A92]">{t.code}</span>
                      <span className="truncate text-[#aecce0]">{t.name}</span>
                    </div>
                    {t.deliverable_qty ? (
                      <span className="text-[9px] text-[#5A7A92]">交付 {t.deliverable_qty}{t.deliverable_unit}</span>
                    ) : null}
                  </div>
                  <span className="ml-1 shrink-0 text-[9px]" style={{ color: STATUS_FILL[t.status] }}>{STATUS_LABELS[t.status]}</span>
                </div>
              ))}
            </div>
          ))}
          {filtered.length === 0 && (
            <div className="py-8 text-center text-[12px] text-[#5A7A92]">暂无任务，点击右栏"新增"发布任务</div>
          )}
        </div>

        {/* Right: scrollable timeline + bars (horizontal scroll driven by bottom bar / wheel) */}
        <div
          ref={hScrollRef}
          onScroll={onHScroll}
          className="gantt-hide-x min-h-0 min-w-0 flex-1 overflow-x-auto overflow-y-hidden"
        >
          <div style={{ width: chartWidth, position: 'relative' }}>
            {/* Time axis */}
            <div className="sticky top-0 z-10 bg-[rgba(9,25,41,0.96)]" style={{ height: AXIS_H, width: chartWidth }}>
              {ticks.map((tk, i) => (
                <div key={i} className="absolute top-0 flex h-full items-end border-l border-[rgba(91,183,255,0.12)] pb-1 pl-1 text-[9px] text-[#5A7A92]" style={{ left: tk.x }}>
                  {tk.label}
                </div>
              ))}
            </div>

            {/* Bars + stage summary rows */}
            <div style={{ height: bodyHeight, position: 'relative' }}>
              {/* Stage summary bars */}
              {stagesPresent.map((stage) => {
                const stTasks = filtered.filter((t) => effStage(t) === stage);
                const idx = rows.findIndex((r) => r.key === `stage:${stage}`);
                if (idx < 0) return null;
                const starts = stTasks.map((t) => (t.planned_start ? new Date(t.planned_start).getTime() : minTime));
                const ends = stTasks.map((t) => (t.planned_end ? new Date(t.planned_end).getTime() : minTime));
                const gs = Math.min(...starts), ge = Math.max(...ends);
                const sw = Math.max((ge - gs) / 86400000 * pxPerDay, 4);
                const done = stTasks.filter((t) => t.status === 'completed').length;
                const pct = stTasks.length ? Math.round(done / stTasks.length * 100) : 0;
                return (
                  <div key={stage} className="absolute left-0 right-0 rounded bg-[rgba(47,215,255,0.06)]" style={{ top: rows[idx].top, height: STAGE_ROW_H - 4 }}>
                    <div
                      className="absolute top-1/2 flex h-3 -translate-y-1/2 items-center rounded"
                      style={{ left: xOf(gs), width: sw, backgroundColor: 'rgba(47,215,255,0.15)', border: '1px solid rgba(47,215,255,0.4)' }}
                    >
                      <div className="h-full rounded-l" style={{ width: `${pct}%`, backgroundColor: 'rgba(47,215,255,0.45)' }} />
                      <span className="absolute left-1.5 text-[9px] text-[#2FD7FF]">{pct}%</span>
                    </div>
                  </div>
                );
              })}

              {/* Dependency edges (SVG overlay) */}
              <svg className="pointer-events-none absolute inset-0" width={chartWidth} height={bodyHeight} style={{ zIndex: 5 }}>
                <defs>
                  <marker id="arrow" markerWidth="7" markerHeight="7" refX="6" refY="3" orient="auto">
                    <path d="M0,0 L6,3 L0,6 Z" fill="#5A7A92" />
                  </marker>
                </defs>
                {edges.map((e) => {
                  const midX = Math.max(e.x1 + 8, e.x2 - 8);
                  return (
                    <path
                      key={e.key}
                      d={`M ${e.x1} ${e.y1} C ${midX} ${e.y1}, ${midX} ${e.y2}, ${e.x2} ${e.y2}`}
                      fill="none"
                      stroke="#5A7A92"
                      strokeWidth="1"
                      strokeDasharray="3 2"
                      markerEnd="url(#arrow)"
                    />
                  );
                })}
              </svg>

              {/* Task bars */}
              {filtered.map((t) => {
                const g = geom(t);
                const idx = rowIndexByTaskId[t.id];
                if (idx === undefined) return null;
                const topPos = rows[idx].top;
                const color = STATUS_FILL[t.status] || COLORS.gray;
                const isDelay = t.status !== 'completed' && t.planned_end && new Date(t.planned_end).getTime() < now;
                return (
                  <div
                    key={t.id}
                    className="absolute flex items-center"
                    style={{ top: topPos, left: g.left, width: g.width, height: ROW_H }}
                    onClick={() => setSelectedTask(t)}
                  >
                    <div
                      className="relative flex h-4 w-full items-center rounded"
                      style={{ backgroundColor: `${color}22`, border: `1px solid ${color}`, cursor: 'pointer' }}
                      title={`${t.code} ${t.name}`}
                    >
                      <div className="h-full rounded-l" style={{ width: `${t.progress}%`, backgroundColor: `${color}aa` }} />
                      <span className="absolute left-1 truncate text-[9px] font-mono" style={{ color }}>{t.code}</span>
                    </div>
                    {isDelay && (
                      <span className="absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full bg-[#FF5C6D]" title="延期风险" />
                    )}
                  </div>
                );
              })}

              {/* Milestones */}
              {milestones.map((m, i) => (
                <div key={i} className="absolute z-10" style={{ left: m.x, top: m.y - 6 }} title={m.label}>
                  <Milestone size={12} className="text-[#FFB33D]" />
                </div>
              ))}

              {/* Today line */}
              {todayX >= 0 && todayX <= chartWidth && (
                <div className="absolute top-0 z-20 h-full w-px bg-[#FF5C6D]" style={{ left: todayX }}>
                  <div className="absolute -top-0 left-1/2 -translate-x-1/2 whitespace-nowrap rounded bg-[#FF5C6D] px-1 text-[9px] text-white">
                    今天 {new Date().toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
        </div>
      </div>

      {/* 常驻底部横向滚动条：始终可见，随右列横向滚动同步，可拖拽滑块 */}
      <div className="flex shrink-0 items-center">
        <div className="w-[260px] shrink-0 border-r border-[rgba(91,183,255,0.15)]" />
        <div className="min-w-0 flex-1">
          <div
            ref={bottomScrollRef}
            onScroll={onBottomScroll}
            className="gantt-hbar h-2.5 overflow-x-auto overflow-y-hidden"
            style={{ scrollbarWidth: 'thin', scrollbarColor: '#2FD7FF rgba(47,215,255,0.08)' }}
          >
            <div style={{ width: chartWidth, height: 1 }} />
          </div>
        </div>
      </div>

      {/* Legend */}
      <div className="mt-2 flex flex-wrap items-center gap-4 border-t border-[rgba(91,183,255,0.1)] pt-2 text-[10px] text-[#5A7A92]">
        <span className="flex items-center gap-1"><span className="inline-block h-2 w-2 bg-[#34DF9A]" /> 已完成</span>
        <span className="flex items-center gap-1"><span className="inline-block h-2 w-2 bg-[#2FD7FF]" /> 进行中</span>
        <span className="flex items-center gap-1"><span className="inline-block h-2 w-2 bg-[#3D8CFF]" /> 待开始</span>
        <span className="flex items-center gap-1"><span className="inline-block h-2 w-2 bg-[#FFB33D]" /> 里程碑</span>
        <span className="flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-full bg-[#FF5C6D]" /> 延期风险</span>
        <span className="flex items-center gap-1 text-[#5A7A92]"><svg width="14" height="6"><path d="M0,3 C5,3 5,3 10,3" stroke="#5A7A92" strokeWidth="1" strokeDasharray="3 2" fill="none" /></svg> 依赖关系</span>
      </div>

      {selectedTask && (
        <TaskDetailModal task={selectedTask} onClose={() => setSelectedTask(null)} />
      )}
    </Panel>
  );
}

// ── 时间轴刻度构建 ────────────────────────────────────────
function buildTicks(minTime: number, maxTime: number, g: Granularity): { x: number; label: string }[] {
  const start = new Date(minTime);
  const ticks: { x: number; label: string }[] = [];
  const pxPerDay = PX_PER_DAY[g];
  const push = (d: Date, label: string) => {
    const x = ((d.getTime() - minTime) / 86400000) * pxPerDay;
    if (x >= 0 && x <= (maxTime - minTime) / 86400000 * pxPerDay) ticks.push({ x, label });
  };
  if (g === 'day') {
    for (let h = 0; h <= 24; h += 3) {
      const d = new Date(start); d.setHours(h, 0, 0, 0);
      push(d, `${String(h).padStart(2, '0')}:00`);
    }
  } else if (g === 'week') {
    const d = new Date(minTime);
    for (let i = 0; i < 12; i++) {
      const dd = new Date(d); dd.setDate(d.getDate() + i * 7);
      push(dd, `D${i + 1}`);
    }
  } else if (g === 'month') {
    const d = new Date(minTime);
    for (let i = 0; i < 12; i++) {
      const dd = new Date(d); dd.setMonth(d.getMonth() + i);
      push(dd, `${dd.getFullYear()}-${String(dd.getMonth() + 1).padStart(2, '0')}`);
    }
  } else {
    const d = new Date(minTime);
    for (let i = 0; i < 8; i++) {
      const dd = new Date(d); dd.setMonth(d.getMonth() + i * 3);
      push(dd, `${dd.getFullYear()}Q${Math.floor(dd.getMonth() / 3) + 1}`);
    }
  }
  return ticks;
}

// ── 任务详情弹窗 ──────────────────────────────────────────
function TaskDetailModal({ task, onClose }: { task: Task; onClose: () => void }) {
  const color = STATUS_FILL[task.status] || COLORS.gray;
  const procName = task.process_id;
  const [devices, setDevices] = useState<Device[]>([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    listDevices().then(setDevices).catch((reason) => setError(reason instanceof Error ? reason.message : '读取设备失败'));
  }, []);

  const execute = async (action: () => Promise<unknown>) => {
    setBusy(true); setError('');
    try { await action(); onClose(); } catch (reason) { setError(reason instanceof Error ? reason.message : '操作失败'); } finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div className="w-96 rounded-xl border border-[rgba(91,183,255,0.3)] bg-[rgba(9,25,41,0.95)] p-5" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-[16px] font-bold text-[#E6F6FF]">任务详情</h3>
          <button onClick={onClose} className="text-[#79A3BF] hover:text-[#FF5C6D]">✕</button>
        </div>
        <div className="space-y-1.5 text-[13px]">
          <Row label="任务编码" value={task.code} mono />
          <Row label="任务名称" value={task.name} />
          <Row label="工序" value={procName} />
          <Row label="状态" value={STATUS_LABELS[task.status] || task.status} color={color} />
          <Row label="优先级" value={String(task.priority)} />
          <Row label="阶段" value={STAGE_LABELS[task.stage] || task.stage} />
          {task.planned_start && <Row label="计划开始" value={formatDateTime(task.planned_start)} />}
          {task.planned_end && <Row label="计划结束" value={formatDateTime(task.planned_end)} />}
          {task.started_at && <Row label="实际开始" value={formatDateTime(task.started_at)} />}
          {task.completed_at && <Row label="实际完成" value={formatDateTime(task.completed_at)} />}
          <Row label="预估工期" value={`${task.estimated_duration}分钟 (${Math.round(task.estimated_duration / 60 * 10) / 10}小时)`} />
          {task.deliverable_qty ? <Row label="交付总量" value={`${task.deliverable_qty} ${task.deliverable_unit || ''}`} color={COLORS.cyan} /> : null}
          {task.completed_qty > 0 ? <Row label="已完成量" value={`${task.completed_qty} ${task.deliverable_unit || ''}`} color={COLORS.green} /> : null}
          {task.map_point_name ? <Row label="目标点位" value={`${task.map_point_code} ${task.map_point_name}`} /> : null}
          {task.dependencies?.length ? <Row label="前置依赖" value={task.dependencies.length + ' 项'} /> : null}
        </div>
        <div className="mt-3 mb-2">
          <div className="mb-1 flex justify-between text-[11px]">
            <span className="text-[#aecce0]">执行进度</span>
            <span className="font-mono text-[#E6F6FF]">{Math.round(task.progress)}%</span>
          </div>
          <ProgressBar value={task.progress} color={color} />
        </div>
        <div className="mt-4 flex gap-2">
          <select value={selectedDeviceId} onChange={(event) => setSelectedDeviceId(event.target.value)} className="min-w-0 flex-1 border border-[rgba(91,183,255,0.3)] bg-[#0A1521] px-1 text-[11px] text-[#E6F6FF]">
            <option value="">选择设备改派</option>
            {devices.filter((device) => device.status === 'idle').map((device) => <option key={device.id} value={device.id}>{device.code}</option>)}
          </select>
          <button disabled={!selectedDeviceId || busy} onClick={() => execute(() => reassignTask(task.id, selectedDeviceId))} className="rounded border border-[rgba(91,183,255,0.3)] px-2 text-[12px] text-[#aecce0] hover:border-[#2FD7FF] disabled:opacity-40">改派</button>
          {task.status === 'running' ? (
            <button disabled={busy} onClick={() => execute(() => pauseTask(task.id))} className="flex-1 rounded border border-[rgba(255,179,61,0.4)] py-1.5 text-[12px] text-[#FFB33D] hover:bg-[rgba(255,179,61,0.1)] disabled:opacity-40">暂停</button>
          ) : task.status === 'paused' ? (
            <button disabled={busy} onClick={() => execute(() => resumeTask(task.id))} className="flex-1 rounded border border-[rgba(52,223,154,0.4)] py-1.5 text-[12px] text-[#34DF9A] hover:bg-[rgba(52,223,154,0.1)] disabled:opacity-40">恢复</button>
          ) : null}
          <button onClick={onClose} className="flex-1 rounded bg-[rgba(91,183,255,0.15)] py-1.5 text-[12px] text-[#2FD7FF]">关闭</button>
        </div>
        {error && <div className="mt-2 text-[11px] text-[#FF5C6D]">{error}</div>}
      </div>
    </div>
  );
}

function Row({ label, value, mono, color }: { label: string; value: string; mono?: boolean; color?: string }) {
  return (
    <div className="flex justify-between">
      <span className="text-[#79A3BF]">{label}</span>
      <span className={mono ? 'font-mono' : ''} style={{ color: color || '#E6F6FF' }}>{value}</span>
    </div>
  );
}
