export interface WSMessage {
  channel: string;
  data: Record<string, unknown>;
}

export type WSChannel =
  | 'devices' | 'tasks' | 'alerts' | 'pointcloud'
  | 'events' | 'estop' | 'script';

export type Role = 'pm' | 'om';

export interface EstopStatus {
  active: boolean;
  source?: string;
}
