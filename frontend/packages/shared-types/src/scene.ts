export interface SceneModel {
  id: string; type: string; name: string;
  position: [number, number, number];
  size: [number, number, number];
  color: string; opacity: number;
}

export interface SceneConfig {
  regions: import('./map').MapRegion[];
  points: import('./map').MapPoint[];
  assets?: MapAsset[];
  frame_id: string;
}

export interface MapAsset {
  id: string;
  event_id: string;
  source_id: string;
  asset_type: 'mesh_gltf' | 'octomap' | 'geojson';
  asset_uri: string;
  checksum_sha256: string | null;
  frame_id: string;
  metadata: Record<string, unknown>;
  observed_at: string;
  received_at: string;
}
