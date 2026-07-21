/** REST API: Alerts */

import type { Alert } from '@robots/shared-types';
import { apiGet, apiPost } from './client';

export function listAlerts(params?: { level?: string; status?: string }) {
  const qs = new URLSearchParams();
  if (params?.level) qs.set('level', params.level);
  if (params?.status) qs.set('status', params.status);
  const q = qs.toString();
  return apiGet<Alert[]>(`/alerts${q ? `?${q}` : ''}`);
}

export function acknowledgeAlert(alertId: string) {
  return apiPost(`/alerts/${alertId}/acknowledge`);
}
