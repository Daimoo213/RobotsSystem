export type AlertLevel = 'critical' | 'warning' | 'info';
export type AlertStatus = 'open' | 'ack' | 'resolved';

export interface Alert {
  id: string; device_id: string | null; level: AlertLevel;
  category: string; message: string; status: AlertStatus;
  created_at: string; resolved_at?: string | null; payload?: Record<string, unknown>;
}
