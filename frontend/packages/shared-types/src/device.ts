/** 设备类型 */
export type DeviceType = 'agv' | 'excavator' | 'crane' | 'masonry' | 'inspect' | 'inspection';
/** 设备状态 */
export type DeviceStatus = 'idle' | 'charging' | 'moving' | 'working' | 'paused' | 'maintenance' | 'occupancy' | 'fault';
export type DeviceConnectionStatus = 'online' | 'offline';

export interface DevicePosition { x: number; y: number; z: number; }

export interface DeviceHealth {
  connection: string; location: string; battery: string; task: string; safety: string;
}

export interface DeviceOperationalMetrics {
  power_kw?: number;
  energy_kwh_total?: number;
  mileage_km_total?: number;
  runtime_hours_total?: number;
  payload_ratio?: number;
  localization_drift_meters?: number;
  mission_phase?: string;
  camera?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface Device {
  id: string; code: string; name: string; type: DeviceType;
  status: DeviceStatus; battery: number; position: DevicePosition;
  section_id: string | null; capabilities: Record<string, unknown>;
  health: DeviceHealth; current_task?: string | null; task_progress?: number;
  model?: string | null; last_heartbeat?: string | null; connection_status?: DeviceConnectionStatus;
  protocol_version?: 'v1' | 'v2';
  operational_metrics?: DeviceOperationalMetrics;
  work_capacities?: Array<{
    capability_code: string;
    output_unit: string;
    rate_per_hour: number;
    source: string;
    evidence_ref: string;
    reported_at: string;
    measured_at: string | null;
    sample_count: number | null;
    valid_until: string | null;
  }>;
}
