export type RegionType = 'work' | 'restricted' | 'stack' | 'parking';
export type MapPathDirection = 'bidirectional' | 'forward' | 'reverse';
export type MapPathStatus = 'active' | 'disabled';

/** 项目地图的固定体素语义：每个正立方体格子的三条边均为 0.05 米。 */
export const VOXEL_CELL_SIZE_M = 0.05;
export const VOXEL_CELL_VOLUME_M3 = VOXEL_CELL_SIZE_M ** 3;

export interface GridMapConfig {
  origin_x: number;
  origin_y: number;
  origin_z: number;
  cell_volume_m3: number;
  cell_length: number;
  cell_width: number;
  cell_height: number;
  extent_length: number;
  extent_width: number;
  vertical_layers: number;
  /** 一个 O&M 显示体素沿每个轴聚合的最小 0.05m 体素数量。 */
  display_voxel_multiplier: number;
  line_color: string;
  line_thickness: number;
  opacity: number;
}

export interface MapRegionVolume {
  polygon: number[][];
  min_z: number;
  max_z: number;
}

export interface MapRegion {
  id: string; code: string; name: string; region_type: RegionType;
  polygon: number[][]; min_z: number; max_z: number; volumes: MapRegionVolume[]; stage?: string | null; color: string;
}

export interface MapPoint {
  id: string; code: string; name: string; point_type: string;
  x: number; y: number; z: number;
  process_type: string | null; device_types: string[]; stage?: string | null;
  qrcode_id?: string | null; qrcode_type?: string | null; color: string;
}

/** 按地图坐标系顺序排列的 [x, y, z] 路径点，z 为高程。 */
export type MapPathPoint = [number, number, number];

export interface MapPath {
  id: string;
  code: string;
  name: string;
  points: MapPathPoint[];
  /** 后端道路响应的显式起点；三维草稿可省略。 */
  start?: MapPathPoint;
  /** 后端道路响应的显式终点；三维草稿可省略。 */
  end?: MapPathPoint;
  direction: MapPathDirection;
  min_width_m: number;
  max_slope_percent: number;
  /** 空数组表示平台不限制设备类型。 */
  device_types: string[];
  status: MapPathStatus;
}
