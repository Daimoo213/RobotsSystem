/** REST API: Reports, PointCloud, Estop, Ops */

import { apiFetch, apiGet, apiPost, apiDelete, apiPatch } from './client';

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
  return apiGet<{
    mapping_enabled: boolean;
    source: string | null;
    map_id: string | null;
    active: boolean;
    points_count: number;
    progress: number;
    updated_at: string | null;
  }>('/pointcloud/status');
}

export function exportPdfReport(params: { date_from?: string; date_to?: string }) {
  const qs = new URLSearchParams();
  if (params.date_from) qs.set('date_from', params.date_from);
  if (params.date_to) qs.set('date_to', params.date_to);
  return apiFetch<Blob>(`/reports/export-pdf?${qs.toString()}`, { method: 'POST' });
}

export function getPointcloudMap() {
  return apiGet<{
    has_data: boolean;
    mapping_enabled: boolean;
    map_id?: string;
    source_id?: string;
    points: number[][];
    total_count: number;
    progress: number;
    frame_id?: string;
    metadata?: Record<string, unknown>;
    observed_at?: string;
    received_at?: string;
  }>('/pointcloud/map');
}

export function getMappingMode() {
  return apiGet<{ configured: boolean; enabled: boolean; project_code: string | null }>('/ops/mapping');
}

export function setMappingMode(enabled: boolean) {
  return apiPatch<{ ok: boolean; enabled: boolean; project_code: string }>('/ops/mapping', { enabled });
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
