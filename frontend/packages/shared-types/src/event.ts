export interface DeviceEvent {
  time: string;
  device_id: string;
  event_type: string;
  payload: Record<string, unknown>;
}

export interface RealtimeEvent {
  time: string;
  type: string;
  message: string;
}
