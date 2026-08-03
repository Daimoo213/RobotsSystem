/** PM端 Right column — todo tasks, camera (API), trend (API), events.
 * 所有数据从 API/store 获取，无硬编码。
 */

import { useEffect, useRef, useState } from 'react';
import { Plus, Camera, TrendingUp, Loader2, Trash2 } from 'lucide-react';
import { Panel, EventFeed, ProgressBar } from '@robots/ui';
import { usePmStore } from '../stores/pmStore';
import { COLORS, DISPATCH_REASON_LABELS, DISPATCH_STATE_LABELS, formatDateTime, formatDisplayValue, formatUnit, STAGE_LABELS, TASK_STATUS_LABELS } from '@robots/utils';
import { createTask, getPoints } from '@robots/api-client';
import type { MapPoint, ProcessOption } from '@robots/shared-types';

export function RightColumn() {
  const { tasks, events, processes, cameras, trendData, addTask } = usePmStore();
  const [showAddTask, setShowAddTask] = useState(false);

  // 待办 = pending(未开始) + running(进行中) + paused(已暂停)
  // 与甘特图中"未完成"任务对应：新增任务(pending)会同时出现在两边
  const todoTasks = tasks
    .filter((t) => ['pending', 'assigned', 'running', 'paused', 'reassign_pending', 'cancel_requested'].includes(t.status))
    .sort((a, b) => b.priority - a.priority);

  // 获取第一个摄像头（展示用）
  const camera = cameras[0];

  return (
    <div className="flex h-full min-h-0 flex-col gap-2 overflow-y-auto">
      {/* 待办任务 */}
      <Panel
        title={`待办任务 (${todoTasks.length})`}
        className="shrink-0"
        actions={
          <button onClick={() => setShowAddTask(true)} className="flex items-center gap-1 rounded text-[11px] text-[#2FD7FF] hover:text-[#34DF9A]">
            <Plus size={12} /> 新增
          </button>
        }
      >
        <div className="thin-scroll max-h-64 space-y-1 overflow-y-auto pr-1">
          {todoTasks.length === 0 && <div className="py-3 text-center text-[12px] text-[#5A7A92]">暂无待办任务</div>}
          {todoTasks.map((t) => (
            <div key={t.id} className="flex items-center gap-2 rounded border border-[rgba(91,183,255,0.15)] p-1.5 hover:border-[#2FD7FF]">
              <div className="w-1 h-8 rounded" style={{ backgroundColor: t.priority > 80 ? COLORS.red : t.priority > 60 ? COLORS.amber : COLORS.blue }} />
              <div className="flex-1 min-w-0">
                <div className="text-[12px] text-[#E6F6FF] truncate">{t.name}</div>
                <div className="flex items-center gap-1 mt-0.5">
                  <span className="text-[9px] font-mono text-[#5A7A92]">{t.code}</span>
                  {t.priority > 80 && <span className="rounded bg-[rgba(255,92,109,0.2)] px-1 text-[9px] text-[#FF5C6D]">紧急</span>}
                  {t.status === 'running' && <span className="rounded bg-[rgba(47,215,255,0.2)] px-1 text-[9px] text-[#2FD7FF]">进行中</span>}
                  {t.status === 'paused' && <span className="rounded bg-[rgba(255,179,61,0.2)] px-1 text-[9px] text-[#FFB33D]">已暂停</span>}
                  {t.status === 'cancel_requested' && <span className="rounded bg-[rgba(255,179,61,0.2)] px-1 text-[9px] text-[#FFB33D]">取消请求中</span>}
                  {t.dispatch_state === 'waiting_device' && <span className="rounded bg-[rgba(255,179,61,0.15)] px-1 text-[9px] text-[#FFB33D]">等待设备</span>}
                  {t.deliverable_qty && (
                    <span className="text-[9px] text-[#79A3BF]">交付：{t.deliverable_qty}{formatUnit(t.deliverable_unit)}</span>
                  )}
                </div>
                {t.planned_start && (
                  <div className="text-[9px] text-[#5A7A92] mt-0.5">
                    {formatDateTime(t.planned_start)} → {formatDateTime(t.planned_end)}
                  </div>
                )}
                {t.status === 'pending' && (
                  <div className="mt-0.5 truncate text-[9px] text-[#79A3BF]" title={DISPATCH_REASON_LABELS[t.dispatch_reason || ''] || t.dispatch_reason || ''}>
                    {DISPATCH_STATE_LABELS[t.dispatch_state] || '等待调度'}：{DISPATCH_REASON_LABELS[t.dispatch_reason || ''] || '等待条件满足'}
                  </div>
                )}
                {t.resource_plan && (
                  <div className={`mt-0.5 text-[9px] ${t.resource_plan.coverage_ratio >= 1 ? 'text-[#34DF9A]' : 'text-[#FFB33D]'}`}>
                    集群产能覆盖 {Math.round(t.resource_plan.coverage_ratio * 100)}%
                  </div>
                )}
              </div>
              <span className="font-mono text-[10px] text-[#aecce0]">{Math.round(t.progress)}%</span>
            </div>
          ))}
        </div>
      </Panel>

      {/* 摄像头 AI 检测摘要 */}
      <Panel title="摄像头人工智能检测" className="shrink-0" actions={<span className="text-[10px] text-[#5A7A92]">{camera?.code || '无摄像头'}</span>}>
        <div className="relative h-32 overflow-hidden rounded border border-[rgba(91,183,255,0.15)] bg-[#0A1521]">
          <div className="flex h-full items-center justify-center text-[#5A7A92]">
            <Camera size={32} />
          </div>
          {/* 位置 */}
          {camera && (
            <div className="absolute left-2 bottom-2 text-[9px] text-[#79A3BF]">{camera.location}</div>
          )}
          {/* AI识别浮窗 */}
          {camera?.latest_detection ? (
            <div className="absolute right-2 bottom-2 rounded border border-[rgba(47,215,255,0.3)] bg-[rgba(9,25,41,0.8)] p-1.5 text-[9px]">
              <div className="text-[#2FD7FF] font-medium mb-0.5">人工智能识别</div>
              <div className="text-[#aecce0]">挖机: {camera.latest_detection.excavator_count}</div>
              <div className="text-[#aecce0]">渣土车: {camera.latest_detection.truck_count}</div>
              <div className="text-[#aecce0]">人员: {camera.latest_detection.person_count}</div>
              <div className="text-[#34DF9A]">扬尘：{formatDisplayValue(camera.latest_detection.dust_level, '无数据')}</div>
              <div className="text-[#aecce0]">边坡：{formatDisplayValue(camera.latest_detection.slope_risk, '无数据')}</div>
            </div>
          ) : (
            <div className="absolute right-2 bottom-2 text-[9px] text-[#5A7A92]">无识别数据</div>
          )}
        </div>
      </Panel>

      {/* 完成趋势 — 从 API 获取 */}
      <Panel title="任务完成趋势" className="shrink-0" actions={<TrendingUp size={14} className="text-[#2FD7FF]" />}>
        {trendData && trendData.labels.length > 0 ? (
          <TrendChart trendData={trendData} />
        ) : (
          <div className="flex h-24 items-center justify-center text-[12px] text-[#5A7A92]">加载趋势数据...</div>
        )}
      </Panel>

      {/* 实时事件 */}
      <Panel title="实时事件" className="flex min-h-0 flex-1">
        <div className="min-h-0 flex-1">
          <EventFeed events={events} maxItems={15} />
        </div>
      </Panel>

      {/* 任务发布弹窗 */}
      {showAddTask && (
        <TaskPublishModal
          processes={processes}
          onClose={() => setShowAddTask(false)}
          onCreated={() => setShowAddTask(false)}
        />
      )}
    </div>
  );
}

// ── 完成趋势图（从 API 数据渲染）─────────────────────────
function TrendChart({ trendData }: { trendData: { labels: string[]; planned: number[]; actual: number[]; predicted: number[] } }) {
  const maxVal = Math.max(...trendData.planned, ...trendData.actual, ...trendData.predicted, 1);
  const width = 300;
  const height = 80;
  const step = width / Math.max(trendData.labels.length - 1, 1);

  const toPoints = (data: number[]) =>
    data.map((v, i) => `${i * step},${height - (v / maxVal) * height * 0.85}`).join(' ');

  return (
    <div>
      <div className="h-24">
        <svg width="100%" height="100%" viewBox={`0 0 ${width} ${height}`}>
          {[0, 20, 40, 60, 80, 100].map((y) => (
            <line key={y} x1="0" y1={y * 0.8} x2={width} y2={y * 0.8} stroke="rgba(91,183,255,0.08)" strokeWidth="1" />
          ))}
          <polyline points={toPoints(trendData.planned)} fill="none" stroke="#3D8CFF" strokeWidth="1.5" strokeDasharray="4 3" />
          <polyline points={toPoints(trendData.actual)} fill="none" stroke="#2FD7FF" strokeWidth="2" />
          <polyline points={toPoints(trendData.predicted)} fill="none" stroke="#34DF9A" strokeWidth="1.5" strokeDasharray="3 2" />
        </svg>
      </div>
      <div className="flex justify-center gap-3 text-[10px]">
        <span className="text-[#3D8CFF]">- - 计划</span>
        <span className="text-[#2FD7FF]">— 实际</span>
        <span className="text-[#34DF9A]">- - 预测</span>
      </div>
    </div>
  );
}

// ── 任务发布弹窗 ──────────────────────────────────────
interface TaskPublishModalProps {
  processes: ProcessOption[];
  onClose: () => void;
  onCreated: () => void;
}

interface CollaborativeRequirementDraft {
  id: number;
  processId: string;
  quantity: string;
}

function TaskPublishModal({ processes, onClose, onCreated }: TaskPublishModalProps) {
  const addTask = usePmStore((state) => state.addTask);
  const tasks = usePmStore((state) => state.tasks);
  const [name, setName] = useState('');
  const [processId, setProcessId] = useState(processes[0]?.id || 'pit_excavation');
  const [points, setPoints] = useState<MapPoint[]>([]);
  const [mapPointId, setMapPointId] = useState('');
  const [returnAfterWork, setReturnAfterWork] = useState(false);
  const [returnPointId, setReturnPointId] = useState('');
  const [priority, setPriority] = useState(50);
  const [scheduleMode, setScheduleMode] = useState<'auto' | 'fixed'>('auto');
  const [plannedStart, setPlannedStart] = useState('');
  const [duration, setDuration] = useState(120);
  const [deliverableQty, setDeliverableQty] = useState('');
  const [dependencyIds, setDependencyIds] = useState<string[]>([]);
  const [collaborativeRequirements, setCollaborativeRequirements] = useState<CollaborativeRequirementDraft[]>([]);
  const collaborativeRequirementSequence = useRef(0);
  const [description, setDescription] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const selectedProcess = processes.find((p) => p.id === processId);
  const deliverableUnit = selectedProcess?.unit || '';
  const currentStage = selectedProcess?.stage || 'earthwork';
  const returnPoints = points.filter((point) => ['parking', 'standby', 'charge'].includes(point.point_type));
  const workPoints = points.filter((point) => !['parking', 'standby', 'charge'].includes(point.point_type));
  const dependencyCandidates = tasks
    .filter((task) => ['pending', 'assigned', 'running', 'paused', 'reassign_pending'].includes(task.status))
    .sort((a, b) => b.priority - a.priority || a.name.localeCompare(b.name, 'zh-CN'));
  const plannedEnd = plannedStart && Number.isFinite(duration) && duration > 0
    ? new Date(new Date(plannedStart).getTime() + duration * 60_000).toISOString()
    : null;

  useEffect(() => {
    getPoints().then((result) => {
      setPoints(result);
      const firstWorkPoint = result.find((point) => !['parking', 'standby', 'charge'].includes(point.point_type));
      const firstReturnPoint = result.find((point) => ['parking', 'standby', 'charge'].includes(point.point_type));
      if (firstWorkPoint) setMapPointId(firstWorkPoint.id);
      if (firstReturnPoint) setReturnPointId(firstReturnPoint.id);
    }).catch((requestError) => setError(requestError instanceof Error ? requestError.message : '加载施工点位失败'));
  }, []);

  const handleProcessChange = (id: string) => {
    setProcessId(id);
    const proc = processes.find((p) => p.id === id);
    if (proc) {
      setDuration(proc.duration);
      if (!name) setName(proc.name);
    }
  };

  const toggleDependency = (taskId: string) => {
    setDependencyIds((current) => (
      current.includes(taskId) ? current.filter((id) => id !== taskId) : [...current, taskId]
    ));
  };

  const addCollaborativeRequirement = () => {
    const auxiliaryProcess = processes.find((process) => process.id !== processId);
    if (!auxiliaryProcess) {
      setError('当前没有可添加的协同工序');
      return;
    }
    collaborativeRequirementSequence.current += 1;
    setCollaborativeRequirements((items) => [
      ...items,
      { id: collaborativeRequirementSequence.current, processId: auxiliaryProcess.id, quantity: '' },
    ]);
  };

  const updateCollaborativeRequirement = (id: number, patch: Partial<CollaborativeRequirementDraft>) => {
    setCollaborativeRequirements((items) => items.map((item) => (item.id === id ? { ...item, ...patch } : item)));
  };

  const removeCollaborativeRequirement = (id: number) => {
    setCollaborativeRequirements((items) => items.filter((item) => item.id !== id));
  };

  const handleSubmit = async () => {
    if (!name.trim()) { setError('请填写任务名称'); return; }
    if (!processId) { setError('请选择工序'); return; }
    if (!mapPointId) { setError('请选择已标注的施工点位'); return; }
    if (!Number.isFinite(duration) || duration <= 0) { setError('请填写大于 0 的预计工期'); return; }
    if (scheduleMode === 'fixed' && !plannedStart) { setError('指定开始时间模式下，请填写计划开始时间'); return; }
    if (!deliverableQty || !Number.isFinite(Number(deliverableQty)) || Number(deliverableQty) <= 0) { setError('请填写大于 0 的真实交付量，系统不会估造设备产能'); return; }
    if (returnAfterWork && !returnPointId) { setError('请先在运维地图中创建并选择停车点、待机点或充电点'); return; }
    const selectedAuxiliaryProcesses = new Set<string>();
    for (const requirement of collaborativeRequirements) {
      const process = processes.find((item) => item.id === requirement.processId);
      if (!process) { setError('协同作业的工序无效，请重新选择'); return; }
      if (process.id === processId || selectedAuxiliaryProcesses.has(process.id)) {
        setError('协同作业不能重复主工序或彼此重复');
        return;
      }
      if (!requirement.quantity || !Number.isFinite(Number(requirement.quantity)) || Number(requirement.quantity) <= 0) {
        setError(`请填写“${process.name}”的大于 0 真实交付量`);
        return;
      }
      selectedAuxiliaryProcesses.add(process.id);
    }
    const resourceRequirements = [
      {
        role_code: 'primary',
        capability_code: processId,
        required_qty: Number(deliverableQty),
        output_unit: deliverableUnit,
        is_completion_gate: true,
        work_scope: { mode: 'shared_queue', map_point_id: mapPointId },
      },
      ...collaborativeRequirements.map((requirement, index) => {
        const process = processes.find((item) => item.id === requirement.processId)!;
        return {
          role_code: `assist_${index + 1}`,
          capability_code: process.id,
          required_qty: Number(requirement.quantity),
          output_unit: process.unit,
          is_completion_gate: true,
          work_scope: { mode: 'shared_queue', map_point_id: mapPointId },
        };
      }),
    ];
    setLoading(true);
    setError('');
    try {
      const task = await createTask({
        name: name.trim(),
        process_id: processId,
        schedule_mode: scheduleMode,
        map_point_id: mapPointId,
        priority,
        estimated_duration: duration,
        planned_start: scheduleMode === 'fixed' && plannedStart ? new Date(plannedStart).toISOString() : undefined,
        deliverable_qty: deliverableQty ? parseFloat(deliverableQty) : undefined,
        deliverable_unit: deliverableUnit || undefined,
        stage: currentStage,
        description: description || undefined,
        dependencies: dependencyIds,
        return_policy: returnAfterWork ? 'return_to_point' : 'stay',
        return_point_id: returnAfterWork ? returnPointId : undefined,
        resource_requirements: resourceRequirements,
      });
      addTask(task);
      onCreated();
    } catch (e) {
      setError(e instanceof Error ? e.message : '发布失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div className="w-[480px] max-h-[90vh] overflow-y-auto rounded-xl border border-[rgba(91,183,255,0.3)] bg-[rgba(9,25,41,0.95)] p-5" onClick={(e) => e.stopPropagation()}>
        <h3 className="mb-4 text-[16px] font-bold text-[#E6F6FF]">发布施工任务</h3>
        <div className="space-y-3 text-[13px]">
          <div>
            <label className="block mb-1 text-[#79A3BF]">任务名称 *</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="如：A区基坑土方清运"
              className="w-full rounded border border-[rgba(91,183,255,0.3)] bg-[#0A1521] px-3 py-1.5 text-[#E6F6FF] outline-none focus:border-[#2FD7FF]"
            />
          </div>
          <div>
            <label className="block mb-1 text-[#79A3BF]">施工工序 *</label>
            <select
              value={processId}
              onChange={(e) => handleProcessChange(e.target.value)}
              className="w-full rounded border border-[rgba(91,183,255,0.3)] bg-[#0A1521] px-3 py-1.5 text-[#E6F6FF] outline-none focus:border-[#2FD7FF]"
            >
              {processes.length === 0 && <option value="">加载中...</option>}
              {processes.map((p) => (
                <option key={p.id} value={p.id}>{p.name}（{STAGE_LABELS[p.stage] || '未知阶段'}）</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block mb-1 text-[#79A3BF]">施工点位 *</label>
            <select value={mapPointId} onChange={(e) => setMapPointId(e.target.value)} className="w-full rounded border border-[rgba(91,183,255,0.3)] bg-[#0A1521] px-3 py-1.5 text-[#E6F6FF] outline-none focus:border-[#2FD7FF]">
              {workPoints.length === 0 && <option value="">请先在运维地图中创建施工点位</option>}
              {workPoints.map((point) => <option key={point.id} value={point.id}>{point.code} {point.name}</option>)}
            </select>
          </div>
          <div className="rounded border border-[rgba(91,183,255,0.2)] p-2.5">
            <label className="flex items-center gap-2 text-[#aecce0]">
              <input type="checkbox" checked={returnAfterWork} onChange={(event) => setReturnAfterWork(event.target.checked)} disabled={returnPoints.length === 0} />
              作业完成后返回指定点位
            </label>
            {returnAfterWork && (
              <select value={returnPointId} onChange={(event) => setReturnPointId(event.target.value)} className="mt-2 w-full rounded border border-[rgba(91,183,255,0.3)] bg-[#0A1521] px-3 py-1.5 text-[#E6F6FF] outline-none focus:border-[#2FD7FF]">
                {returnPoints.map((point) => <option key={point.id} value={point.id}>{point.code} {point.name}</option>)}
              </select>
            )}
            {returnPoints.length === 0 && <div className="mt-1 text-[10px] text-[#FFB33D]">需先在运维地图创建停车点、待机点或充电点</div>}
          </div>
          <div>
            <label className="block mb-1 text-[#79A3BF]">优先级</label>
            <div className="flex items-center gap-2">
              <input type="range" min={0} max={100} value={priority} onChange={(e) => setPriority(Number(e.target.value))} className="flex-1" />
              <span className="w-12 text-right font-mono text-[#2FD7FF]">{priority}</span>
              {priority > 80 && <span className="text-[10px] text-[#FF5C6D]">紧急</span>}
              {priority > 60 && priority <= 80 && <span className="text-[10px] text-[#FFB33D]">高</span>}
            </div>
          </div>
          <div>
            <label className="block mb-1 text-[#79A3BF]">预估工期（分钟）</label>
            <input type="number" value={duration} onChange={(e) => setDuration(Number(e.target.value))}
              className="w-full rounded border border-[rgba(91,183,255,0.3)] bg-[#0A1521] px-3 py-1.5 text-[#E6F6FF] outline-none focus:border-[#2FD7FF]" />
            {duration > 0 && <span className="text-[10px] text-[#5A7A92]">≈ {Math.round(duration / 60)}小时{duration % 60}分钟</span>}
          </div>
          <section className="rounded border border-[rgba(91,183,255,0.2)] p-2.5">
            <div className="mb-2 flex items-center justify-between gap-2">
              <div>
                <h4 className="text-[12px] font-medium text-[#E6F6FF]">排期方式</h4>
                <p className="mt-0.5 text-[10px] text-[#5A7A92]">自动排期会在前置任务完成后，结合实际资源可用性安排执行。</p>
              </div>
              <div className="flex shrink-0 overflow-hidden rounded border border-[rgba(91,183,255,0.3)] text-[11px]">
                <button type="button" onClick={() => setScheduleMode('auto')} className={`px-2 py-1 ${scheduleMode === 'auto' ? 'bg-[#2FD7FF] text-[#050B13]' : 'text-[#aecce0]'}`}>自动排期</button>
                <button type="button" onClick={() => setScheduleMode('fixed')} className={`border-l border-[rgba(91,183,255,0.3)] px-2 py-1 ${scheduleMode === 'fixed' ? 'bg-[#2FD7FF] text-[#050B13]' : 'text-[#aecce0]'}`}>指定开始</button>
              </div>
            </div>
            {scheduleMode === 'fixed' && (
              <div className="grid grid-cols-2 gap-2">
                <label className="block text-[10px] text-[#79A3BF]">
                  计划开始时间 *
                  <input type="datetime-local" value={plannedStart} onChange={(event) => setPlannedStart(event.target.value)} className="mt-1 w-full rounded border border-[rgba(91,183,255,0.3)] bg-[#0A1521] px-2 py-1.5 text-[12px] text-[#E6F6FF] outline-none focus:border-[#2FD7FF]" />
                </label>
                <div className="text-[10px] text-[#79A3BF]">
                  预计结束时间
                  <div className="mt-1 min-h-8 rounded border border-[rgba(91,183,255,0.16)] bg-[#0A1521] px-2 py-1.5 text-[12px] text-[#aecce0]">
                    {plannedEnd ? formatDateTime(plannedEnd) : '填写开始时间后按工期计算'}
                  </div>
                </div>
              </div>
            )}
          </section>
          <section className="border-t border-[rgba(91,183,255,0.18)] pt-3">
            <div className="mb-2 flex items-center justify-between gap-2">
              <div>
                <h4 className="text-[12px] font-medium text-[#E6F6FF]">前置任务</h4>
                <p className="mt-0.5 text-[10px] text-[#5A7A92]">选中的任务全部完成后，本任务才会进入资源规划和派发。</p>
              </div>
              <span className="shrink-0 text-[10px] text-[#2FD7FF]">已选 {dependencyIds.length} 项</span>
            </div>
            {dependencyCandidates.length === 0 ? (
              <div className="text-[10px] text-[#5A7A92]">当前没有可作为前置条件的未完成任务。</div>
            ) : (
              <div className="thin-scroll max-h-32 space-y-1 overflow-y-auto pr-1">
                {dependencyCandidates.map((task) => (
                  <label key={task.id} className="flex cursor-pointer items-center gap-2 rounded border border-[rgba(91,183,255,0.14)] px-2 py-1.5 text-[11px] hover:border-[rgba(47,215,255,0.48)]">
                    <input type="checkbox" checked={dependencyIds.includes(task.id)} onChange={() => toggleDependency(task.id)} />
                    <span className="min-w-0 flex-1 truncate text-[#E6F6FF]" title={task.name}>{task.name}</span>
                    <span className="font-mono text-[10px] text-[#79A3BF]">{task.code}</span>
                    <span className="text-[10px] text-[#79A3BF]">{TASK_STATUS_LABELS[task.status] || '未完成'}</span>
                  </label>
                ))}
              </div>
            )}
          </section>
          <div>
            <label className="block mb-1 text-[#79A3BF]">交付结果量化 *</label>
            <div className="flex items-center gap-2">
              <input type="number" value={deliverableQty} onChange={(e) => setDeliverableQty(e.target.value)} placeholder="如：500"
                className="flex-1 rounded border border-[rgba(91,183,255,0.3)] bg-[#0A1521] px-3 py-1.5 text-[#E6F6FF] outline-none focus:border-[#2FD7FF]" />
               <span className="w-16 text-[#aecce0]">{formatUnit(deliverableUnit)}</span>
            </div>
            <span className="text-[10px] text-[#5A7A92]">用于计算真实设备产能覆盖和所需数量</span>
          </div>
          <section className="border-t border-[rgba(91,183,255,0.18)] pt-3">
            <div className="mb-2 flex items-center justify-between">
              <div>
                <h4 className="text-[12px] font-medium text-[#E6F6FF]">协同作业需求</h4>
                <p className="mt-0.5 text-[10px] text-[#5A7A92]">按实际工法补充辅助工序，系统按真实产能规划设备类型和数量</p>
              </div>
              <button
                type="button"
                onClick={addCollaborativeRequirement}
                disabled={processes.length < 2}
                title="添加协同作业需求"
                className="flex items-center gap-1 text-[11px] text-[#2FD7FF] hover:text-[#34DF9A] disabled:opacity-40"
              >
                <Plus size={13} /> 添加
              </button>
            </div>
            {collaborativeRequirements.length === 0 ? (
              <div className="text-[10px] text-[#5A7A92]">未添加协同作业时，系统只规划主作业所需的设备集群。</div>
            ) : (
              <div className="space-y-2">
                {collaborativeRequirements.map((requirement) => {
                  const selectedRequirementProcess = processes.find((process) => process.id === requirement.processId);
                  return (
                    <div key={requirement.id} className="grid grid-cols-[minmax(0,1fr)_84px_28px] items-end gap-2">
                      <label className="block text-[10px] text-[#79A3BF]">
                        协同工序
                        <select
                          value={requirement.processId}
                          onChange={(event) => updateCollaborativeRequirement(requirement.id, { processId: event.target.value })}
                          className="mt-1 w-full rounded border border-[rgba(91,183,255,0.3)] bg-[#0A1521] px-2 py-1.5 text-[12px] text-[#E6F6FF] outline-none focus:border-[#2FD7FF]"
                        >
                          {processes.filter((process) => process.id !== processId).map((process) => (
                            <option key={process.id} value={process.id}>{process.name}</option>
                          ))}
                        </select>
                      </label>
                      <label className="block text-[10px] text-[#79A3BF]">
                        交付量
                        <div className="relative mt-1">
                          <input
                            type="number"
                            min="0"
                            value={requirement.quantity}
                            onChange={(event) => updateCollaborativeRequirement(requirement.id, { quantity: event.target.value })}
                            className="w-full rounded border border-[rgba(91,183,255,0.3)] bg-[#0A1521] px-2 py-1.5 pr-7 text-[12px] text-[#E6F6FF] outline-none focus:border-[#2FD7FF]"
                          />
                          <span className="pointer-events-none absolute inset-y-0 right-2 flex items-center text-[10px] text-[#79A3BF]">{formatUnit(selectedRequirementProcess?.unit || '')}</span>
                        </div>
                      </label>
                      <button
                        type="button"
                        onClick={() => removeCollaborativeRequirement(requirement.id)}
                        title="移除协同作业需求"
                        className="mb-0.5 flex h-8 w-7 items-center justify-center rounded border border-[rgba(255,92,109,0.36)] text-[#FF5C6D] hover:bg-[rgba(255,92,109,0.12)]"
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  );
                })}
              </div>
            )}
          </section>
          <div>
            <label className="block mb-1 text-[#79A3BF]">任务描述</label>
            <textarea value={description} onChange={(e) => setDescription(e.target.value)} placeholder="补充说明..." rows={2}
              className="w-full rounded border border-[rgba(91,183,255,0.3)] bg-[#0A1521] px-3 py-1.5 text-[#E6F6FF] outline-none focus:border-[#2FD7FF]" />
          </div>
          {error && (
            <div className="rounded border border-[#FF5C6D] bg-[rgba(255,92,109,0.1)] px-3 py-1.5 text-[12px] text-[#FF5C6D]">{error}</div>
          )}
        </div>
        <div className="mt-4 flex gap-2">
          <button onClick={onClose} className="flex-1 rounded border border-[rgba(91,183,255,0.3)] py-2 text-[13px] text-[#aecce0] hover:border-[#2FD7FF]">取消</button>
          <button onClick={handleSubmit} disabled={loading}
            className="flex flex-1 items-center justify-center gap-2 rounded bg-[#2FD7FF] py-2 text-[13px] font-medium text-[#050B13] hover:bg-[#34DF9A] disabled:opacity-50">
            {loading && <Loader2 size={14} className="animate-spin" />}
            {loading ? '发布中...' : '发布任务'}
          </button>
        </div>
      </div>
    </div>
  );
}
