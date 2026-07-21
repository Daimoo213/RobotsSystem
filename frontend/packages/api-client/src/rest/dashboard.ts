/** REST API: Dashboard — 派生指标聚合计算 */

import { apiGet } from './client';

export interface KpiData {
  overall_progress: number;
  earthwork_rate: number;
  running_tasks: number;
  pending_tasks: number;
  delay_risk: number;
  resource_load: number;
  spoil_trips: number;
  ai_compliance: number;
  total_tasks: number;
  completed_tasks: number;
  total_devices: number;
  working_devices: number;
}

export interface TrendData {
  labels: string[];
  planned: number[];
  actual: number[];
  predicted: number[];
}

export interface ResourceLoad {
  type: string;
  label: string;
  total: number;
  active: number;
  idle: number;
  charging: number;
  fault: number;
  load_rate: number;
}

export interface EnvironmentData {
  has_data: boolean;
  dust_level: string;
  temperature: number | null;
  humidity: number | null;
  noise: number | null;
  updated_at: string | null;
  source?: string;
}

export interface HealthScore {
  score: number;
  total_devices: number;
  healthy_devices: number;
  open_alerts: number;
  critical_alerts: number;
}

export interface ProjectInfo {
  configured: boolean;
  code?: string;
  name?: string;
  location?: string | null;
  map_frame?: string;
  timezone?: string;
}

export interface EnergyView {
  has_data: boolean;
  total_energy_kwh: number | null;
  current_power_kw: number | null;
  devices_reporting_energy: number;
  devices: Array<{
    id: string;
    code: string;
    type: string;
    battery: number;
    status: string;
    power_kw: number | null;
    energy_kwh_total: number | null;
    mileage_km_total: number | null;
    runtime_hours_total: number | null;
  }>;
}

export interface SafetyView {
  global_estop: { active: boolean; cycle_id: string | null; source: string | null; updated_at: string | null };
  open_alert_count: number;
  critical_alert_count: number;
  alerts: Array<{ id: string; device_id: string | null; level: string; category: string; message: string; status: string; created_at: string }>;
}

export interface CameraInfo {
  id: string;
  code: string;
  name: string;
  location: string;
  stream_url?: string | null;
  is_online: boolean;
  latest_detection: {
    excavator_count: number;
    truck_count: number;
    person_count: number;
    dust_level: string;
    slope_risk: string;
    ai_compliance_rate: number;
    detected_at: string | null;
  } | null;
}

export function getKpi() {
  return apiGet<KpiData>('/dashboard/kpi');
}

export function getTrend(days = 7) {
  return apiGet<TrendData>(`/dashboard/trend?days=${days}`);
}

export function getResourceLoad() {
  return apiGet<ResourceLoad[]>('/dashboard/resource-load');
}

export function getEnvironment() {
  return apiGet<EnvironmentData>('/dashboard/environment');
}

export function getHealthScore() {
  return apiGet<HealthScore>('/dashboard/health-score');
}

export function getProject() {
  return apiGet<ProjectInfo>('/dashboard/project');
}

export function getEnergyView() {
  return apiGet<EnergyView>('/dashboard/energy');
}

export function getSafetyView() {
  return apiGet<SafetyView>('/dashboard/safety');
}

export function getCameras() {
  return apiGet<CameraInfo[]>('/dashboard/cameras');
}
