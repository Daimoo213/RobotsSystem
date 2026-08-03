/** REST API: Map */

import type { GridMapConfig, MapPath, MapPoint, MapRegion, SceneConfig } from '@robots/shared-types';
import { apiDelete, apiFetch, apiGet } from './client';

export function getRegions() {
  return apiGet<MapRegion[]>('/map/regions');
}

export function getPoints() {
  return apiGet<MapPoint[]>('/map/points');
}

export function getPaths() {
  return apiGet<MapPath[]>('/map/paths');
}

export function getSceneConfig() {
  return apiGet<SceneConfig>('/map/scene-config');
}

export function getGridConfig() {
  return apiGet<GridMapConfig>('/map/grid-config');
}

export function updateGridConfig(config: GridMapConfig) {
  return apiFetch<GridMapConfig>('/map/grid-config', { method: 'PUT', body: JSON.stringify(config) });
}

export function createRegion(region: Omit<MapRegion, 'id'>) {
  return apiFetch<MapRegion>('/map/regions', { method: 'POST', body: JSON.stringify(region) });
}

export function createPoint(point: Omit<MapPoint, 'id'>) {
  return apiFetch<MapPoint>('/map/points', { method: 'POST', body: JSON.stringify(point) });
}

export function createPath(path: Omit<MapPath, 'id'>) {
  return apiFetch<MapPath>('/map/paths', { method: 'POST', body: JSON.stringify(path) });
}

export function updateRegion(regionId: string, region: Omit<MapRegion, 'id'>) {
  return apiFetch<MapRegion>(`/map/regions/${regionId}`, { method: 'PUT', body: JSON.stringify(region) });
}

export function updatePoint(pointId: string, point: Omit<MapPoint, 'id'>) {
  return apiFetch<MapPoint>(`/map/points/${pointId}`, { method: 'PUT', body: JSON.stringify(point) });
}

export function updatePath(pathId: string, path: Omit<MapPath, 'id'>) {
  return apiFetch<MapPath>(`/map/paths/${pathId}`, { method: 'PUT', body: JSON.stringify(path) });
}

export function deleteRegion(regionId: string) {
  return apiDelete(`/map/regions/${regionId}`);
}

export function deletePoint(pointId: string) {
  return apiDelete(`/map/points/${pointId}`);
}

export function deletePath(pathId: string) {
  return apiDelete(`/map/paths/${pathId}`);
}
