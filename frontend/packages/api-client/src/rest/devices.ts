/** REST API: Devices */

import type { Device } from '@robots/shared-types';
import { apiGet, apiPost } from './client';

export function listDevices(params?: { status?: string; type?: string }) {
  const qs = new URLSearchParams();
  if (params?.status) qs.set('status', params.status);
  if (params?.type) qs.set('type', params.type);
  const q = qs.toString();
  return apiGet<Device[]>(`/devices${q ? `?${q}` : ''}`);
}

export function getDevice(id: string) {
  return apiGet<Device>(`/devices/${id}`);
}

export interface DeviceDetail {
  device: Device;
  trajectory: Array<{ time: string; position: { x: number; y: number; z: number }; status: string | null; battery: number | null }>;
  alerts: Array<{ id: string; level: string; category: string; message: string; status: string; created_at: string; resolved_at: string | null }>;
  executions: Array<{ id: string; execution_id: string; task_id: string; task_code: string; task_name: string; state: string; progress: number; failure_code: string | null; dispatched_at: string; started_at: string | null; completed_at: string | null }>;
}

export function getDeviceDetail(id: string, hours = 24) {
  return apiGet<DeviceDetail>(`/devices/${id}/detail?hours=${hours}`);
}

export function requestManualCalibration(id: string) {
  return apiPost<{ ok: boolean; device_id: string; command_id: string; delivery: string }>(`/devices/${id}/calibrate`);
}

export function sendCommand(deviceId: string, command: string) {
  return apiPost(`/devices/${deviceId}/command`, { command });
}

export function sendBatchCommand(body: { command: string; section_id?: string; device_type?: string; process_id?: string }) {
  return apiPost<{ ok: boolean; targets: string[]; command_ids: string[] }>('/devices/commands/batch', body);
}
