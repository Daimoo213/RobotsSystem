export type TaskStatus = 'pending' | 'assigned' | 'running' | 'paused' | 'completed' | 'failed' | 'reassign_pending' | 'cancel_requested' | 'cancelled';
export type TaskScheduleMode = 'auto' | 'fixed';
export type DispatchState = 'waiting_dependencies' | 'waiting_schedule' | 'waiting_device' | 'waiting_planning_input' | 'waiting_capacity' | 'dispatched' | 'cancelling' | 'cancelled' | 'finished' | 'failed';
export type MissionPhase = 'preparing' | 'navigating_to_target' | 'arrived_at_target' | 'working' | 'work_completed' | 'returning' | 'returned';

export interface TaskResourcePlanSummary {
  state: 'waiting_planning_input' | 'waiting_capacity' | 'preplanned' | 'ready_to_dispatch' | 'dispatched' | 'executing' | 'completed' | 'at_risk' | 'cancelled';
  reason: string | null;
  revision: number;
  window_start: string | null;
  window_end: string | null;
  required_rate_per_hour: number | null;
  planned_rate_per_hour: number;
  coverage_ratio: number;
  predicted_completion_at: string | null;
  generated_at: string | null;
  summary: {
    requirements?: Array<{
      requirement_id: string;
      role_code: string;
      capability_code: string;
      required_qty: number;
      completed_qty: number;
      reserved_qty: number;
      planned_qty: number;
      remaining_qty: number;
      output_unit: string;
      required_rate_per_hour: number;
      coverage_ratio: number;
      device_types: Array<{
        device_type: string;
        planned_count: number;
        available_count: number;
        planned_qty: number;
        planned_rate_per_hour: number;
      }>;
    }>;
    selection_is_live?: boolean;
    candidate_basis?: string;
    message?: string;
  };
}

export interface TaskResourceRequirement {
  id: string;
  role_code: string;
  capability_code: string;
  required_qty: number;
  completed_qty: number;
  output_unit: string;
  is_completion_gate: boolean;
  work_scope: Record<string, unknown>;
}

export interface TaskResourceAllocation {
  id: string;
  requirement_id: string;
  device_id: string;
  device_code: string | null;
  device_type: string | null;
  plan_revision: number;
  planned_qty: number;
  completed_qty: number;
  output_unit: string;
  rate_per_hour_snapshot: number;
  capacity_source: string;
  capacity_evidence_ref: string;
  capacity_reported_at: string;
  work_scope: Record<string, unknown>;
  available_from: string;
  predicted_finish_at: string | null;
  state: string;
  execution_id: string | null;
  execution_phase: MissionPhase | null;
  execution_progress: number | null;
}

export interface Task {
  id: string;
  code: string;
  name: string;
  process_id: string;
  device_id: string | null;
  device_code: string | null;
  status: TaskStatus;
  priority: number;
  schedule_mode?: TaskScheduleMode;
  map_point_id: string | null;
  map_point_code: string | null;
  map_point_name: string | null;
  return_policy: 'stay' | 'return_to_point';
  return_point_id: string | null;
  return_point_code: string | null;
  return_point_name: string | null;
  work_parameters: Record<string, unknown>;
  dispatch_state: DispatchState;
  dispatch_reason: string | null;
  dispatch_attempts: number;
  last_dispatch_attempt_at: string | null;
  current_phase: MissionPhase | null;
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
  resource_plan: TaskResourcePlanSummary | null;
  resource_requirements: TaskResourceRequirement[];
  resource_allocations: TaskResourceAllocation[];
}

export interface ProcessOption {
  id: string;
  name: string;
  stage: string;
  unit: string;
  duration: number;
}
