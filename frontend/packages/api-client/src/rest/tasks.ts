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
}

export function updateTask(id: string, body: TaskUpdateBody) {
  return apiPatch<Task>(`/tasks/${id}`, body);
}

export function reassignTask(taskId: string, deviceId: string) {
  return apiPost<Task>(`/tasks/${taskId}/reassign?device_id=${deviceId}`);
}

export function pauseTask(taskId: string) {
  return apiPost(`/tasks/${taskId}/pause`);
}

export function resumeTask(taskId: string) {
  return apiPost(`/tasks/${taskId}/resume`);
}

export function deleteTask(taskId: string) {
  return apiDelete(`/tasks/${taskId}`);
}
