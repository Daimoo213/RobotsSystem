/** REST API: Map */

import type { MapPoint, MapRegion, SceneConfig } from '@robots/shared-types';
import { apiDelete, apiFetch, apiGet } from './client';

export function getRegions() {
  return apiGet<MapRegion[]>('/map/regions');
}

export function getPoints() {
  return apiGet<MapPoint[]>('/map/points');
}

export function getSceneConfig() {
  return apiGet<SceneConfig>('/map/scene-config');
}

export function createRegion(region: Omit<MapRegion, 'id'>) {
  return apiFetch<MapRegion>('/map/regions', { method: 'POST', body: JSON.stringify(region) });
}

export function createPoint(point: Omit<MapPoint, 'id'>) {
  return apiFetch<MapPoint>('/map/points', { method: 'POST', body: JSON.stringify(point) });
}

export function updateRegion(regionId: string, region: Omit<MapRegion, 'id'>) {
  return apiFetch<MapRegion>(`/map/regions/${regionId}`, { method: 'PUT', body: JSON.stringify(region) });
}

export function updatePoint(pointId: string, point: Omit<MapPoint, 'id'>) {
  return apiFetch<MapPoint>(`/map/points/${pointId}`, { method: 'PUT', body: JSON.stringify(point) });
}

export function deleteRegion(regionId: string) {
  return apiDelete(`/map/regions/${regionId}`);
}

export function deletePoint(pointId: string) {
  return apiDelete(`/map/points/${pointId}`);
}
