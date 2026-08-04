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
import { COLORS, DEVICE_TYPE_LABELS, DISPATCH_REASON_LABELS, DISPATCH_STATE_LABELS, formatDateTime, formatUnit, MISSION_PHASE_LABELS, PROCESSES, STAGE_LABELS, TASK_STATUS_LABELS } from '@robots/utils';
import type { Task } from '@robots/shared-types';
import { exportReport } from '@robots/api-client';
import { cancelTask, deleteTask, pauseTask, recalculateTaskResourcePlan, resumeTask } from '@robots/api-client';

type Granularity = 'day' | 'week' | 'month' | 'quarter';

const STATUS_FILL: Record<string, string> = {
  completed: COLORS.green, running: COLORS.cyan, pending: COLORS.blue,
  paused: COLORS.amber, failed: COLORS.red, assigned: COLORS.cyan, reassign_pending: COLORS.amber,
  cancel_requested: COLORS.amber, cancelled: COLORS.gray,
};

const STATUS_LABELS = TASK_STATUS_LABELS;

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
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const selectedTask = tasks.find((task) => task.id === selectedTaskId) || null;
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
      link.download = '机器人调度系统报表.xlsx';
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
                  onClick={() => setSelectedTaskId(t.id)}
                  className="flex cursor-pointer items-center justify-between border-l-2 py-1 pl-2 pr-1 text-[11px] hover:bg-[rgba(47,215,255,0.08)]"
                  style={{ height: ROW_H, borderColor: STATUS_FILL[t.status] || COLORS.gray }}
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-1">
                      <span className="font-mono text-[9px] text-[#5A7A92]">{t.code}</span>
                      <span className="truncate text-[#aecce0]">{t.name}</span>
                    </div>
                    {t.deliverable_qty ? (
                      <span className="text-[9px] text-[#5A7A92]">交付 {t.deliverable_qty}{formatUnit(t.deliverable_unit)}</span>
                    ) : null}
                  </div>
                      <span className="ml-1 shrink-0 text-[9px]" style={{ color: STATUS_FILL[t.status] }}>{STATUS_LABELS[t.status] || '未知状态'}</span>
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
                    onClick={() => setSelectedTaskId(t.id)}
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
        <TaskDetailModal task={selectedTask} onClose={() => setSelectedTaskId(null)} />
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
       push(dd, `第${i + 1}周`);
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
       push(dd, `${dd.getFullYear()}年第${Math.floor(dd.getMonth() / 3) + 1}季度`);
    }
  }
  return ticks;
}

// ── 任务详情弹窗 ──────────────────────────────────────────
function TaskDetailModal({ task, onClose }: { task: Task; onClose: () => void }) {
  const removeTask = usePmStore((state) => state.removeTask);
  const updateTask = usePmStore((state) => state.updateTask);
  const color = STATUS_FILL[task.status] || COLORS.gray;
  const procName = PROCESSES[task.process_id]?.name || '未知工序';
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const hasExecutionHistory = task.resource_allocations.some((allocation) => allocation.execution_id !== null);
  const pauseRequested = task.resource_allocations.some((allocation) => allocation.state === 'pause_requested');
  const resumeRequested = task.resource_allocations.some((allocation) => allocation.state === 'resume_requested');
  const canPause = ['assigned', 'running'].includes(task.status);
  const canCancel = ['assigned', 'running', 'paused', 'reassign_pending'].includes(task.status)
    || (task.status === 'pending' && hasExecutionHistory);
  const canDelete = task.status === 'pending' && !hasExecutionHistory;

  const execute = async (action: () => Promise<unknown>) => {
    setBusy(true); setError(''); setNotice('');
    try { await action(); onClose(); } catch (reason) { setError(reason instanceof Error ? reason.message : '操作失败'); } finally { setBusy(false); }
  };

  const submitControl = async (
    action: () => Promise<{ ok: boolean; task?: Task }>,
    successNotice: string,
    failureMessage: string,
  ) => {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const result = await action();
      if (!result.ok) {
        setError(failureMessage);
        return;
      }
      if (result.task) updateTask(result.task);
      setNotice(successNotice);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : failureMessage);
    } finally {
      setBusy(false);
    }
  };

  const handlePause = () => submitControl(
    () => pauseTask(task.id),
    '暂停请求已下发，正在等待设备遥测确认。',
    '提交任务暂停请求失败，请刷新后确认任务状态',
  );

  const handleResume = () => submitControl(
    () => resumeTask(task.id),
    '恢复请求已下发，正在等待设备遥测确认。',
    '提交任务恢复请求失败，请刷新后确认任务状态',
  );

  const handleCancel = async () => {
    const confirmation = hasExecutionHistory
      ? `确认取消任务“${task.name}”吗？平台会停止后续调度；存在活动设备时会下发取消命令并等待遥测确认。`
      : `确认取消任务“${task.name}”吗？任务将不再参与后续调度，但会保留取消审计记录。`;
    if (!window.confirm(confirmation)) return;
    await submitControl(
      () => cancelTask(task.id),
      '取消请求已提交，正在等待任务状态更新。',
      '提交任务取消请求失败，请刷新后确认任务状态',
    );
  };

  const handleDelete = async () => {
    if (!window.confirm(`确认删除尚未派发的任务“${task.name}”吗？此操作不可恢复。`)) return;

    setBusy(true);
    setError('');
    setNotice('');
    try {
      const result = await deleteTask(task.id);
      if (!result.ok) {
        setError('任务删除未完成，请刷新后确认任务状态');
        return;
      }
      removeTask(task.id);
      onClose();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '取消或删除任务失败');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div className="max-h-[90vh] w-[440px] overflow-y-auto rounded-xl border border-[rgba(91,183,255,0.3)] bg-[rgba(9,25,41,0.95)] p-5" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-[16px] font-bold text-[#E6F6FF]">任务详情</h3>
          <button onClick={onClose} className="text-[#79A3BF] hover:text-[#FF5C6D]">✕</button>
        </div>
        <div className="space-y-1.5 text-[13px]">
          <Row label="任务编码" value={task.code} mono />
          <Row label="任务名称" value={task.name} />
          <Row label="工序" value={procName} />
           <Row label="状态" value={STATUS_LABELS[task.status] || '未知状态'} color={color} />
          <Row label="调度状态" value={DISPATCH_STATE_LABELS[task.dispatch_state] || '未知调度状态'} />
          {task.dispatch_reason && <Row label="等待原因" value={DISPATCH_REASON_LABELS[task.dispatch_reason] || task.dispatch_reason} color={COLORS.amber} />}
          {task.current_phase && <Row label="执行阶段" value={MISSION_PHASE_LABELS[task.current_phase] || '未知执行阶段'} color={COLORS.cyan} />}
          <Row label="优先级" value={String(task.priority)} />
          <Row label="阶段" value={STAGE_LABELS[task.stage] || '未知阶段'} />
          {task.planned_start && <Row label="计划开始" value={formatDateTime(task.planned_start)} />}
          {task.planned_end && <Row label="计划结束" value={formatDateTime(task.planned_end)} />}
          {task.started_at && <Row label="实际开始" value={formatDateTime(task.started_at)} />}
          {task.completed_at && <Row label="实际完成" value={formatDateTime(task.completed_at)} />}
          <Row label="预估工期" value={`${task.estimated_duration}分钟 (${Math.round(task.estimated_duration / 60 * 10) / 10}小时)`} />
           {task.deliverable_qty ? <Row label="交付总量" value={`${task.deliverable_qty} ${formatUnit(task.deliverable_unit)}`} color={COLORS.cyan} /> : null}
           {task.completed_qty > 0 ? <Row label="已完成量" value={`${task.completed_qty} ${formatUnit(task.deliverable_unit)}`} color={COLORS.green} /> : null}
          {task.map_point_name ? <Row label="目标点位" value={`${task.map_point_code} ${task.map_point_name}`} /> : null}
          <Row label="作业后处置" value={task.return_policy === 'return_to_point' ? '返回指定点位' : '原地结束'} />
          {task.return_point_name ? <Row label="返回点位" value={`${task.return_point_code} ${task.return_point_name}`} /> : null}
          {Object.keys(task.work_parameters || {}).length > 0 ? <Row label="结构化作业参数" value={`${Object.keys(task.work_parameters).length} 项`} /> : null}
          {task.dependencies?.length ? <Row label="前置依赖" value={task.dependencies.length + ' 项'} /> : null}
        </div>
        <ResourcePlanSection task={task} />
        <div className="mt-3 mb-2">
          <div className="mb-1 flex justify-between text-[11px]">
            <span className="text-[#aecce0]">执行进度</span>
            <span className="font-mono text-[#E6F6FF]">{Math.round(task.progress)}%</span>
          </div>
          <ProgressBar value={task.progress} color={color} />
        </div>
        <div className="mt-4 flex gap-2">
          <button disabled={busy || ['completed', 'cancel_requested', 'cancelled'].includes(task.status)} onClick={() => execute(() => recalculateTaskResourcePlan(task.id))} className="flex-1 rounded border border-[rgba(47,215,255,0.42)] py-1.5 text-[12px] text-[#2FD7FF] hover:bg-[rgba(47,215,255,0.1)] disabled:opacity-40">重新规划资源</button>
          {canPause ? (
            <button disabled={busy || pauseRequested} onClick={handlePause} className="flex-1 rounded border border-[rgba(255,179,61,0.4)] py-1.5 text-[12px] text-[#FFB33D] hover:bg-[rgba(255,179,61,0.1)] disabled:opacity-40">{pauseRequested ? '暂停请求中' : '暂停'}</button>
          ) : task.status === 'paused' ? (
            <button disabled={busy || resumeRequested} onClick={handleResume} className="flex-1 rounded border border-[rgba(52,223,154,0.4)] py-1.5 text-[12px] text-[#34DF9A] hover:bg-[rgba(52,223,154,0.1)] disabled:opacity-40">{resumeRequested ? '恢复请求中' : '恢复'}</button>
          ) : null}
          {canCancel && <button disabled={busy} onClick={handleCancel} className="flex-1 rounded border border-[rgba(255,92,109,0.48)] py-1.5 text-[12px] text-[#FF5C6D] hover:bg-[rgba(255,92,109,0.12)] disabled:opacity-40">取消任务</button>}
          {canDelete && <button disabled={busy} onClick={handleDelete} className="flex-1 rounded border border-[rgba(255,92,109,0.48)] py-1.5 text-[12px] text-[#FF5C6D] hover:bg-[rgba(255,92,109,0.12)] disabled:opacity-40">删除任务</button>}
          <button onClick={onClose} className="flex-1 rounded bg-[rgba(91,183,255,0.15)] py-1.5 text-[12px] text-[#2FD7FF]">关闭</button>
        </div>
        {error && <div className="mt-2 text-[11px] text-[#FF5C6D]">{error}</div>}
        {notice && <div className="mt-2 text-[11px] text-[#FFB33D]">{notice}</div>}
      </div>
    </div>
  );
}

function ResourcePlanSection({ task }: { task: Task }) {
  const plan = task.resource_plan;
  const summaries = plan?.summary.requirements || [];
  const allocations = task.resource_allocations || [];

  return (
    <section className="mt-4 border-t border-[rgba(91,183,255,0.18)] pt-3">
      <div className="mb-2 flex items-center justify-between">
        <h4 className="text-[13px] font-medium text-[#E6F6FF]">集群资源计划</h4>
        <span className={`text-[11px] ${plan?.coverage_ratio === 1 ? 'text-[#34DF9A]' : 'text-[#FFB33D]'}`}>
          {plan ? `产能覆盖 ${Math.round(plan.coverage_ratio * 100)}%` : '待计算'}
        </span>
      </div>
      {!plan ? <div className="text-[11px] text-[#5A7A92]">任务尚未具备资源规划结果。</div> : (
        <>
          <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px]">
            <span className="text-[#79A3BF]">计划状态</span><span className="text-right text-[#aecce0]">{DISPATCH_STATE_LABELS[plan.state] || '未知状态'}</span>
            <span className="text-[#79A3BF]">需求产能</span><span className="text-right font-mono text-[#aecce0]">{plan.required_rate_per_hour?.toFixed(2) || '-'} /小时</span>
            <span className="text-[#79A3BF]">计划产能</span><span className="text-right font-mono text-[#2FD7FF]">{plan.planned_rate_per_hour.toFixed(2)} /小时</span>
            {plan.predicted_completion_at && <><span className="text-[#79A3BF]">预计完成</span><span className="text-right text-[#aecce0]">{formatDateTime(plan.predicted_completion_at)}</span></>}
          </div>
          {plan.reason && <div className="mt-1 text-[11px] text-[#FFB33D]">{DISPATCH_REASON_LABELS[plan.reason] || '计划条件待补充'}</div>}
          {plan.summary.message && <div className="mt-1 text-[11px] text-[#FFB33D]">{plan.summary.message}</div>}
          {summaries.map((summary) => (
            <div key={summary.requirement_id} className="mt-2 border border-[rgba(91,183,255,0.15)] bg-[#0A1521] px-2 py-1.5 text-[11px]">
              <div className="flex justify-between text-[#aecce0]"><span>{summary.role_code === 'primary' ? '主作业' : '协同作业'}：{PROCESSES[summary.capability_code]?.name || '未登记工序'}</span><span>{summary.completed_qty}/{summary.required_qty}{formatUnit(summary.output_unit)}</span></div>
              {summary.device_types.map((type) => (
                <div key={type.device_type} className="mt-1 flex justify-between text-[#79A3BF]">
                  <span>{DEVICE_TYPE_LABELS[type.device_type] || '未登记设备类型'}</span>
                  <span>计划 {type.planned_count} 台，可用 {type.available_count} 台，{type.planned_rate_per_hour.toFixed(2)}/小时</span>
                </div>
              ))}
            </div>
          ))}
          {allocations.length > 0 && <div className="mt-2 space-y-1">
            <div className="text-[11px] text-[#79A3BF]">执行单元</div>
            {allocations.map((allocation) => <div key={allocation.id} className="flex justify-between text-[11px] text-[#aecce0]">
              <span>{allocation.device_code || '设备待确认'} {allocation.device_type ? `(${DEVICE_TYPE_LABELS[allocation.device_type] || '未登记设备类型'})` : ''}</span>
              <span>{allocation.completed_qty}/{allocation.planned_qty}{formatUnit(allocation.output_unit)} {MISSION_PHASE_LABELS[allocation.execution_phase || ''] || '等待设备确认'}</span>
            </div>)}
          </div>}
        </>
      )}
    </section>
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
