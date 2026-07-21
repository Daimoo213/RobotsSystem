/** 设备类型 */
export type DeviceType = 'agv' | 'excavator' | 'crane' | 'masonry' | 'inspect';
/** 设备状态 */
export type DeviceStatus = 'idle' | 'charging' | 'moving' | 'working' | 'paused' | 'maintenance' | 'occupancy' | 'fault';

export interface DevicePosition { x: number; y: number; z: number; }

export interface DeviceHealth {
  connection: string; location: string; battery: string; task: string; safety: string;
}

export interface Device {
  id: string; code: string; name: string; type: DeviceType;
  status: DeviceStatus; battery: number; position: DevicePosition;
  section_id: string | null; capabilities: Record<string, unknown>;
  health: DeviceHealth; current_task?: string | null; task_progress?: number;
  model?: string | null; last_heartbeat?: string | null;
  operational_metrics?: Record<string, number>;
}
