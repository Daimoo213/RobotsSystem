/** REST API: Reports, PointCloud, Estop, Ops */

import { apiFetch, apiGet, apiPost, apiDelete } from './client';

// Reports
export function exportReport(params: {
  report_type?: string; date_from?: string; date_to?: string;
}) {
  const qs = new URLSearchParams();
  if (params.report_type) qs.set('report_type', params.report_type);
  if (params.date_from) qs.set('date_from', params.date_from);
  if (params.date_to) qs.set('date_to', params.date_to);
  return apiFetch<Blob>(`/reports/export?${qs.toString()}`, { method: 'POST' });
}

// PointCloud
export function getPointcloudStatus() {
  return apiGet<{ source: string; active: boolean; points_count: number; progress: number }>('/pointcloud/status');
}

export function exportPdfReport(params: { date_from?: string; date_to?: string }) {
  const qs = new URLSearchParams();
  if (params.date_from) qs.set('date_from', params.date_from);
  if (params.date_to) qs.set('date_to', params.date_to);
  return apiFetch<Blob>(`/reports/export-pdf?${qs.toString()}`, { method: 'POST' });
}

export function getLatestPointcloud() {
  return apiGet<{ has_data: boolean; points: number[][]; total_count: number; progress: number; frame_id?: string; metadata?: Record<string, unknown> }>('/pointcloud/latest');
}

// Estop
export function triggerEstop() {
  return apiPost('/estop');
}

export function recoverEstop() {
  return apiDelete('/estop');
}

// Ops (8 quick commands)
export function runOpsCommand(command: string) {
  return apiPost(`/ops/${command.replace(/_/g, '-')}`);
}
