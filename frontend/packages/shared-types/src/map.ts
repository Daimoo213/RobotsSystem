export type RegionType = 'work' | 'restricted' | 'stack' | 'parking';
export type MapPathDirection = 'bidirectional' | 'forward' | 'reverse';
export type MapPathStatus = 'active' | 'disabled';

export interface GridMapConfig {
  origin_x: number;
  origin_y: number;
  origin_z: number;
  cell_length: number;
  cell_width: number;
  cell_height: number;
  extent_length: number;
  extent_width: number;
  vertical_layers: number;
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
  direction: MapPathDirection;
  min_width_m: number;
  max_slope_percent: number;
  /** 空数组表示平台不限制设备类型。 */
  device_types: string[];
  status: MapPathStatus;
}
