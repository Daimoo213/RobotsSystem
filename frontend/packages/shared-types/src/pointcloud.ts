export interface PointCloudData {
  points: number[][];
  total_count: number;
  progress: number;
  frame_id?: string;
  metadata?: Record<string, unknown>;
}
