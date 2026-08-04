/** REST API: Tasks */

import type { Task, ProcessOption } from '@robots/shared-types';
import { apiGet, apiPost, apiPatch, apiDelete } from './client';

export function listTasks(params?: { status?: string; stage?: string }) {
  const qs = new URLSearchParams();
  if (params?.status) qs.set('status', params.status);
  if (params?.stage) qs.set('stage', params.stage);
  const q = qs.toString();
  return apiGet<Task[]>(`/tasks${q ? `?${q}` : ''}`);
}

export function getTask(id: string) {
  return apiGet<Task>(`/tasks/${id}`);
}

/** 获取29项工序选项（任务发布表单用） */
export function listProcesses() {
  return apiGet<ProcessOption[]>('/tasks/meta/processes');
}

export interface TaskCreateBody {
  name: string;
  process_id: string;
  /** auto: 服务端根据依赖和资源可用性安排；fixed: 使用 planned_start。 */
  schedule_mode?: 'auto' | 'fixed';
  map_point_id?: string;
  priority?: number;
  estimated_duration?: number;
  planned_start?: string;
  planned_end?: string;
  deliverable_qty?: number;
  deliverable_unit?: string;
  dependencies?: string[];
  stage?: string;
  required_device_type?: string;
  description?: string;
  work_parameters?: Record<string, unknown>;
  constraints?: Record<string, unknown>;
  return_policy?: 'stay' | 'return_to_point';
  return_point_id?: string;
  resource_requirements?: Array<{
    role_code: string;
    capability_code: string;
    required_qty: number;
    output_unit: string;
    is_completion_gate?: boolean;
    work_scope?: Record<string, unknown>;
  }>;
}

export function createTask(body: TaskCreateBody) {
  return apiPost<Task>('/tasks', body);
}

export interface TaskUpdateBody {
  name?: string;
  priority?: number;
  planned_start?: string;
  planned_end?: string;
  deliverable_qty?: number;
  deliverable_unit?: string;
}

export function updateTask(id: string, body: TaskUpdateBody) {
  return apiPatch<Task>(`/tasks/${id}`, body);
}

export function reassignTask(taskId: string, deviceId: string) {
  return apiPost<Task>(`/tasks/${taskId}/reassign?device_id=${deviceId}`);
}

export function recalculateTaskResourcePlan(taskId: string) {
  return apiPost<Task>(`/tasks/${taskId}/resource-plan/recalculate`);
}

export interface TaskControlResult {
  ok: boolean;
  delivery: 'queued';
  command_ids?: string[];
  execution_ids?: string[];
  task?: Task;
}

export function pauseTask(taskId: string) {
  return apiPost<TaskControlResult>(`/tasks/${taskId}/pause`);
}

export function resumeTask(taskId: string) {
  return apiPost<TaskControlResult>(`/tasks/${taskId}/resume`);
}

export interface TaskCancelResult {
  ok: boolean;
  task?: Task;
}

export function cancelTask(taskId: string) {
  return apiPost<TaskCancelResult>(`/tasks/${taskId}/cancel`);
}

export interface TaskDeleteResult {
  ok: boolean;
}

export function deleteTask(taskId: string) {
  return apiDelete<TaskDeleteResult>(`/tasks/${taskId}`);
}
