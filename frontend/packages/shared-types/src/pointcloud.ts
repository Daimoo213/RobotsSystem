export interface PointCloudData {
  map_id: string;
  source_id?: string;
  points: number[][];
  total_count: number;
  progress: number;
  frame_id?: string;
  metadata?: Record<string, unknown>;
  observed_at?: string;
  received_at?: string;
}
