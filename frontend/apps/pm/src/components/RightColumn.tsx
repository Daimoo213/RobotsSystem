/** PM端 Right column — todo tasks, camera (API), trend (API), events.
 * 所有数据从 API/store 获取，无硬编码。
 */

import { useEffect, useState } from 'react';
import { Plus, Camera, TrendingUp, Loader2 } from 'lucide-react';
import { Panel, EventFeed, ProgressBar } from '@robots/ui';
import { usePmStore } from '../stores/pmStore';
import { COLORS, formatDateTime, formatDisplayValue, formatUnit, STAGE_LABELS } from '@robots/utils';
import { createTask, getPoints } from '@robots/api-client';
import type { MapPoint, ProcessOption } from '@robots/shared-types';

export function RightColumn() {
  const { tasks, events, processes, cameras, trendData, addTask } = usePmStore();
  const [showAddTask, setShowAddTask] = useState(false);

  // 待办 = pending(未开始) + running(进行中) + paused(已暂停)
  // 与甘特图中"未完成"任务对应：新增任务(pending)会同时出现在两边
  const todoTasks = tasks
    .filter((t) => t.status === 'pending' || t.status === 'running' || t.status === 'paused')
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
                  {t.deliverable_qty && (
                    <span className="text-[9px] text-[#79A3BF]">交付：{t.deliverable_qty}{formatUnit(t.deliverable_unit)}</span>
                  )}
                </div>
                {t.planned_start && (
                  <div className="text-[9px] text-[#5A7A92] mt-0.5">
                    {formatDateTime(t.planned_start)} → {formatDateTime(t.planned_end)}
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

function TaskPublishModal({ processes, onClose, onCreated }: TaskPublishModalProps) {
  const [name, setName] = useState('');
  const [processId, setProcessId] = useState(processes[0]?.id || 'pit_excavation');
  const [points, setPoints] = useState<MapPoint[]>([]);
  const [mapPointId, setMapPointId] = useState('');
  const [priority, setPriority] = useState(50);
  const [plannedStart, setPlannedStart] = useState('');
  const [plannedEnd, setPlannedEnd] = useState('');
  const [duration, setDuration] = useState(120);
  const [deliverableQty, setDeliverableQty] = useState('');
  const [description, setDescription] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const selectedProcess = processes.find((p) => p.id === processId);
  const deliverableUnit = selectedProcess?.unit || '';
  const currentStage = selectedProcess?.stage || 'earthwork';

  useEffect(() => {
    getPoints().then((result) => {
      setPoints(result);
      if (result.length) setMapPointId(result[0].id);
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

  const handleStartChange = (val: string) => {
    setPlannedStart(val);
    if (val && duration) {
      const start = new Date(val);
      const end = new Date(start.getTime() + duration * 60000);
      setPlannedEnd(end.toISOString().slice(0, 16));
    }
  };

  const handleSubmit = async () => {
    if (!name.trim()) { setError('请填写任务名称'); return; }
    if (!processId) { setError('请选择工序'); return; }
    if (!mapPointId) { setError('请选择已标注的施工点位'); return; }
    setLoading(true);
    setError('');
    try {
      const task = await createTask({
        name: name.trim(),
        process_id: processId,
        map_point_id: mapPointId,
        priority,
        estimated_duration: duration,
        planned_start: plannedStart ? new Date(plannedStart).toISOString() : undefined,
        planned_end: plannedEnd ? new Date(plannedEnd).toISOString() : undefined,
        deliverable_qty: deliverableQty ? parseFloat(deliverableQty) : undefined,
        deliverable_unit: deliverableUnit || undefined,
        stage: currentStage,
        description: description || undefined,
      });
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
              {points.length === 0 && <option value="">请先在运维地图中创建施工点位</option>}
              {points.map((point) => <option key={point.id} value={point.id}>{point.code} {point.name}</option>)}
            </select>
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
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="block mb-1 text-[#79A3BF]">计划开始时间</label>
              <input type="datetime-local" value={plannedStart} onChange={(e) => handleStartChange(e.target.value)}
                className="w-full rounded border border-[rgba(91,183,255,0.3)] bg-[#0A1521] px-2 py-1.5 text-[#E6F6FF] outline-none focus:border-[#2FD7FF]" />
            </div>
            <div>
              <label className="block mb-1 text-[#79A3BF]">计划结束时间</label>
              <input type="datetime-local" value={plannedEnd} onChange={(e) => setPlannedEnd(e.target.value)}
                className="w-full rounded border border-[rgba(91,183,255,0.3)] bg-[#0A1521] px-2 py-1.5 text-[#E6F6FF] outline-none focus:border-[#2FD7FF]" />
            </div>
          </div>
          <div>
            <label className="block mb-1 text-[#79A3BF]">预估工期（分钟）</label>
            <input type="number" value={duration} onChange={(e) => setDuration(Number(e.target.value))}
              className="w-full rounded border border-[rgba(91,183,255,0.3)] bg-[#0A1521] px-3 py-1.5 text-[#E6F6FF] outline-none focus:border-[#2FD7FF]" />
            {duration > 0 && <span className="text-[10px] text-[#5A7A92]">≈ {Math.round(duration / 60)}小时{duration % 60}分钟</span>}
          </div>
          <div>
            <label className="block mb-1 text-[#79A3BF]">交付结果量化</label>
            <div className="flex items-center gap-2">
              <input type="number" value={deliverableQty} onChange={(e) => setDeliverableQty(e.target.value)} placeholder="如：500"
                className="flex-1 rounded border border-[rgba(91,183,255,0.3)] bg-[#0A1521] px-3 py-1.5 text-[#E6F6FF] outline-none focus:border-[#2FD7FF]" />
               <span className="w-16 text-[#aecce0]">{formatUnit(deliverableUnit)}</span>
            </div>
            <span className="text-[10px] text-[#5A7A92]">该工序完成后应交付的量化结果</span>
          </div>
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
