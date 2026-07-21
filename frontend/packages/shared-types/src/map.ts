export type RegionType = 'work' | 'restricted' | 'stack' | 'parking';

export interface MapRegion {
  id: string; code: string; name: string; region_type: RegionType;
  polygon: number[][]; stage?: string | null;
}

export interface MapPoint {
  id: string; code: string; name: string; point_type: string;
  x: number; y: number; z: number;
  process_type: string | null; device_types: string[]; stage?: string | null;
  qrcode_id?: string | null; qrcode_type?: string | null;
}
