export type TaskStatus = 'pending' | 'assigned' | 'running' | 'paused' | 'completed' | 'failed';

export interface Task {
  id: string;
  code: string;
  name: string;
  process_id: string;
  device_id: string | null;
  device_code: string | null;
  status: TaskStatus;
  priority: number;
  map_point_id: string | null;
  map_point_code: string | null;
  map_point_name: string | null;
  progress: number;
  dependencies: string[];
  estimated_duration: number;
  planned_start: string | null;
  planned_end: string | null;
  started_at: string | null;
  completed_at: string | null;
  deliverable_qty: number | null;
  deliverable_unit: string | null;
  completed_qty: number;
  stage: string;
  params?: Record<string, unknown>;
}

export interface ProcessOption {
  id: string;
  name: string;
  stage: string;
  unit: string;
  duration: number;
}
