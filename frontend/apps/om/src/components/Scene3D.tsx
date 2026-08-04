/** O&M spatial view with a project-configured three-dimensional voxel grid. */

import { Component, type ReactNode, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Canvas, type ThreeEvent } from '@react-three/fiber';
import { Html, OrbitControls, useGLTF } from '@react-three/drei';
import { Grid3X3 } from 'lucide-react';
import * as THREE from 'three';
import { useOmStore } from '../stores/omStore';
import { DEFAULT_GRID_CONFIG, getDisplayGridConfig, type GridCell, useMapEditorStore } from '../stores/mapEditorStore';
import { createRegionSelectionUnion } from '../utils/voxelSelection';
import { COLORS, COMMAND_LABELS, FILTER_CHIPS, getDeviceDisplayStatus } from '@robots/utils';
import { getSceneConfig, sendBatchCommand, triggerEstop } from '@robots/api-client';
import type { Device, GridMapConfig, MapAsset, MapPath, MapPoint, MapRegion, MapRegionVolume, PointCloudData } from '@robots/shared-types';

const DEFAULT_MAP_COLOR = '#2FD7FF';
const EPSILON = 0.0001;
const MAX_GRID_DISPLAY_SEGMENTS = 50_000;

interface Projection {
  centerX: number;
  centerY: number;
  scale: number;
}

interface GridVolume {
  minX: number;
  minY: number;
  minZ: number;
  maxX: number;
  maxY: number;
  maxZ: number;
  columns: number;
  rows: number;
  layers: number;
}

interface Segment {
  start: THREE.Vector3;
  end: THREE.Vector3;
}

interface PathGridCell {
  column: number;
  row: number;
  layer: number;
}

function project(point: { x: number; y: number; z?: number }, projection: Projection): [number, number, number] {
  return [
    (point.x - projection.centerX) * projection.scale,
    (point.z || 0) * projection.scale,
    -(point.y - projection.centerY) * projection.scale,
  ];
}

function projectMapPosition(x: number, y: number, projection: Projection): [number, number] {
  return [(x - projection.centerX) * projection.scale, -(y - projection.centerY) * projection.scale];
}

function calculateProjection(regions: MapRegion[], points: MapPoint[], paths: MapPath[], devices: Device[], pointcloud: PointCloudData | null, gridVolume: GridVolume): Projection {
  let minX = gridVolume.minX;
  let maxX = gridVolume.maxX;
  let minY = gridVolume.minY;
  let maxY = gridVolume.maxY;
  const include = (x: number, y: number) => {
    minX = Math.min(minX, x); maxX = Math.max(maxX, x);
    minY = Math.min(minY, y); maxY = Math.max(maxY, y);
  };
  for (const region of regions) {
    for (const volume of getRegionVolumes(region)) {
      for (const vertex of volume.polygon) include(vertex[0], vertex[1]);
    }
  }
  for (const point of points) include(point.x, point.y);
  for (const path of paths) {
    for (const [x, y] of path.points) include(x, y);
  }
  for (const device of devices) include(device.position.x, device.position.y);
  if (pointcloud?.points.length) {
    const stride = Math.max(1, Math.floor(pointcloud.points.length / 300));
    for (let index = 0; index < pointcloud.points.length; index += stride) {
      const item = pointcloud.points[index];
      include(item[0], item[1]);
    }
  }
  const span = Math.max(maxX - minX, maxY - minY, 1);
  return { centerX: (minX + maxX) / 2, centerY: (minY + maxY) / 2, scale: 24 / span };
}

function getGridVolume(config: GridMapConfig, baseConfig: GridMapConfig = config): GridVolume {
  const columns = Math.ceil(baseConfig.extent_length / config.cell_length);
  const rows = Math.ceil(baseConfig.extent_width / config.cell_width);
  const layers = Math.ceil((baseConfig.vertical_layers * baseConfig.cell_height) / config.cell_height);
  return {
    minX: baseConfig.origin_x,
    minY: baseConfig.origin_y,
    minZ: baseConfig.origin_z,
    maxX: baseConfig.origin_x + baseConfig.extent_length,
    maxY: baseConfig.origin_y + baseConfig.extent_width,
    maxZ: baseConfig.origin_z + baseConfig.vertical_layers * baseConfig.cell_height,
    columns,
    rows,
    layers,
  };
}

function gridSegmentCount(columns: number, rows: number, layers: number, stepCells: number): number {
  const displayedColumns = Math.ceil(columns / stepCells);
  const displayedRows = Math.ceil(rows / stepCells);
  return (displayedColumns + 1) * (displayedRows + 1) + (displayedColumns + displayedRows + 2) * (layers + 1);
}

function getGridDisplayStep(columns: number, rows: number, layers: number): number {
  let lower = 1;
  let upper = Math.max(columns, rows);
  while (lower < upper) {
    const middle = Math.floor((lower + upper) / 2);
    if (gridSegmentCount(columns, rows, layers, middle) <= MAX_GRID_DISPLAY_SEGMENTS) upper = middle;
    else lower = middle + 1;
  }
  return lower;
}

function gridLineIndexes(count: number, stepCells: number): number[] {
  const indexes: number[] = [];
  for (let index = 0; index <= count; index += stepCells) indexes.push(index);
  if (indexes[indexes.length - 1] !== count) indexes.push(count);
  return indexes;
}

function gridCoordinate(minimum: number, maximum: number, index: number, cellSize: number, count: number): number {
  return index >= count ? maximum : Math.min(maximum, minimum + index * cellSize);
}

function snapGridCell(point: THREE.Vector3, projection: Projection, config: GridMapConfig, volume: GridVolume, editLayer: number): GridCell {
  const rawX = point.x / projection.scale + projection.centerX;
  const rawY = -point.z / projection.scale + projection.centerY;
  const column = Math.max(0, Math.min(volume.columns - 1, Math.floor((rawX - volume.minX) / config.cell_length)));
  const row = Math.max(0, Math.min(volume.rows - 1, Math.floor((rawY - volume.minY) / config.cell_width)));
  return {
    x: gridCoordinate(volume.minX, volume.maxX, column, config.cell_length, volume.columns),
    y: gridCoordinate(volume.minY, volume.maxY, row, config.cell_width, volume.rows),
    z: gridCoordinate(volume.minZ, volume.maxZ, editLayer, config.cell_height, volume.layers),
    sizeX: Math.min(config.cell_length, volume.maxX - (volume.minX + column * config.cell_length)),
    sizeY: Math.min(config.cell_width, volume.maxY - (volume.minY + row * config.cell_width)),
    sizeZ: Math.min(config.cell_height, volume.maxZ - (volume.minZ + editLayer * config.cell_height)),
  };
}

function mapRegionVolumeToGridVolume(volume: MapRegionVolume): GridVolume {
  const xCoordinates = volume.polygon.map(([x]) => x);
  const yCoordinates = volume.polygon.map(([, y]) => y);
  return {
    minX: Math.min(...xCoordinates),
    minY: Math.min(...yCoordinates),
    minZ: volume.min_z,
    maxX: Math.max(...xCoordinates),
    maxY: Math.max(...yCoordinates),
    maxZ: volume.max_z,
    columns: 0,
    rows: 0,
    layers: 0,
  };
}

function getRegionVolumes(region: MapRegion): MapRegionVolume[] {
  return region.volumes?.length
    ? region.volumes
    : [{ polygon: region.polygon, min_z: region.min_z, max_z: region.max_z }];
}

function VoxelGrid({ config, projection, volume }: { config: GridMapConfig; projection: Projection; volume: GridVolume }) {
  const meshRef = useRef<THREE.InstancedMesh>(null);
  const segments = useMemo<Segment[]>(() => {
    const gridSegments: Segment[] = [];
    const point = (x: number, y: number, z: number) => new THREE.Vector3(...project({ x, y, z }, projection));
    const displayStep = getGridDisplayStep(volume.columns, volume.rows, volume.layers);
    const columns = gridLineIndexes(volume.columns, displayStep);
    const rows = gridLineIndexes(volume.rows, displayStep);
    for (const column of columns) {
      const x = gridCoordinate(volume.minX, volume.maxX, column, config.cell_length, volume.columns);
      for (const row of rows) {
        const y = gridCoordinate(volume.minY, volume.maxY, row, config.cell_width, volume.rows);
        gridSegments.push({ start: point(x, y, volume.minZ), end: point(x, y, volume.maxZ) });
      }
    }
    for (let layer = 0; layer <= volume.layers; layer += 1) {
      const z = gridCoordinate(volume.minZ, volume.maxZ, layer, config.cell_height, volume.layers);
      for (const column of columns) {
        const x = gridCoordinate(volume.minX, volume.maxX, column, config.cell_length, volume.columns);
        gridSegments.push({ start: point(x, volume.minY, z), end: point(x, volume.maxY, z) });
      }
      for (const row of rows) {
        const y = gridCoordinate(volume.minY, volume.maxY, row, config.cell_width, volume.rows);
        gridSegments.push({ start: point(volume.minX, y, z), end: point(volume.maxX, y, z) });
      }
    }
    return gridSegments;
  }, [config.cell_height, config.cell_length, config.cell_width, projection, volume]);
  const worldThickness = Math.max(config.line_thickness * projection.scale, 0.006);

  useLayoutEffect(() => {
    const mesh = meshRef.current;
    if (!mesh) return;
    const object = new THREE.Object3D();
    const up = new THREE.Vector3(0, 1, 0);
    const direction = new THREE.Vector3();
    const center = new THREE.Vector3();
    mesh.count = segments.length;
    segments.forEach((segment, index) => {
      direction.subVectors(segment.end, segment.start);
      const length = direction.length();
      center.addVectors(segment.start, segment.end).multiplyScalar(0.5);
      object.position.copy(center);
      object.quaternion.setFromUnitVectors(up, direction.normalize());
      object.scale.set(worldThickness, length, worldThickness);
      object.updateMatrix();
      mesh.setMatrixAt(index, object.matrix);
    });
    mesh.instanceMatrix.needsUpdate = true;
  }, [segments, worldThickness]);

  return (
    <instancedMesh ref={meshRef} args={[undefined, undefined, Math.max(segments.length, 1)]} frustumCulled={false} renderOrder={0}>
      <boxGeometry args={[1, 1, 1]} />
      <meshBasicMaterial color={config.line_color} transparent opacity={config.opacity} depthWrite={false} toneMapped={false} />
    </instancedMesh>
  );
}

function VoxelHighlight({ volume, projection, color = DEFAULT_MAP_COLOR, opacity = 0.14 }: { volume: GridVolume; projection: Projection; color?: string; opacity?: number }) {
  const width = (volume.maxX - volume.minX) * projection.scale;
  const depth = (volume.maxY - volume.minY) * projection.scale;
  const height = (volume.maxZ - volume.minZ) * projection.scale;
  const [x, y, z] = project({ x: (volume.minX + volume.maxX) / 2, y: (volume.minY + volume.maxY) / 2, z: (volume.minZ + volume.maxZ) / 2 }, projection);
  const edges = useMemo(() => {
    const geometry = new THREE.BoxGeometry(width, height, depth);
    const result = new THREE.EdgesGeometry(geometry);
    geometry.dispose();
    return result;
  }, [depth, height, width]);
  return <group position={[x, y, z]} renderOrder={2}><mesh><boxGeometry args={[width, height, depth]} /><meshBasicMaterial color={color} transparent opacity={opacity} depthWrite={false} /></mesh><lineSegments geometry={edges}><lineBasicMaterial color={color} transparent opacity={Math.min(opacity + 0.55, 0.95)} /></lineSegments></group>;
}

interface UnionVoxelCell {
  x: number;
  y: number;
  z: number;
}

function volumeKey(x: number, y: number, z: number): string {
  return `${x}:${y}:${z}`;
}

function buildVolumeUnionGeometry(volumes: GridVolume[], projection: Projection): THREE.BufferGeometry | null {
  if (!volumes.length) return null;

  const xCoordinates = [...new Set(volumes.flatMap((volume) => [volume.minX, volume.maxX]))].sort((left, right) => left - right);
  const yCoordinates = [...new Set(volumes.flatMap((volume) => [volume.minY, volume.maxY]))].sort((left, right) => left - right);
  const zCoordinates = [...new Set(volumes.flatMap((volume) => [volume.minZ, volume.maxZ]))].sort((left, right) => left - right);
  const occupied = new Map<string, UnionVoxelCell>();

  for (let xIndex = 0; xIndex < xCoordinates.length - 1; xIndex += 1) {
    const x = xCoordinates[xIndex];
    const centerX = (x + xCoordinates[xIndex + 1]) / 2;
    for (let yIndex = 0; yIndex < yCoordinates.length - 1; yIndex += 1) {
      const y = yCoordinates[yIndex];
      const centerY = (y + yCoordinates[yIndex + 1]) / 2;
      for (let zIndex = 0; zIndex < zCoordinates.length - 1; zIndex += 1) {
        const z = zCoordinates[zIndex];
        const centerZ = (z + zCoordinates[zIndex + 1]) / 2;
        if (volumes.some((volume) => (
          centerX > volume.minX + EPSILON && centerX < volume.maxX - EPSILON
          && centerY > volume.minY + EPSILON && centerY < volume.maxY - EPSILON
          && centerZ > volume.minZ + EPSILON && centerZ < volume.maxZ - EPSILON
        ))) {
          occupied.set(volumeKey(xIndex, yIndex, zIndex), { x: xIndex, y: yIndex, z: zIndex });
        }
      }
    }
  }

  if (!occupied.size) return null;
  const positions: number[] = [];
  const addVertex = (x: number, y: number, z: number) => positions.push(...project({ x, y, z }, projection));
  const addFace = (vertices: Array<[number, number, number]>) => {
    addVertex(...vertices[0]); addVertex(...vertices[1]); addVertex(...vertices[2]);
    addVertex(...vertices[0]); addVertex(...vertices[2]); addVertex(...vertices[3]);
  };
  const faces: Array<{ offset: [number, number, number]; vertices: (x0: number, x1: number, y0: number, y1: number, z0: number, z1: number) => Array<[number, number, number]> }> = [
    { offset: [-1, 0, 0], vertices: (x0, _x1, y0, y1, z0, z1) => [[x0, y0, z0], [x0, y1, z0], [x0, y1, z1], [x0, y0, z1]] },
    { offset: [1, 0, 0], vertices: (_x0, x1, y0, y1, z0, z1) => [[x1, y0, z0], [x1, y0, z1], [x1, y1, z1], [x1, y1, z0]] },
    { offset: [0, -1, 0], vertices: (x0, x1, y0, _y1, z0, z1) => [[x0, y0, z0], [x0, y0, z1], [x1, y0, z1], [x1, y0, z0]] },
    { offset: [0, 1, 0], vertices: (x0, x1, _y0, y1, z0, z1) => [[x0, y1, z0], [x1, y1, z0], [x1, y1, z1], [x0, y1, z1]] },
    { offset: [0, 0, -1], vertices: (x0, x1, y0, y1, z0, _z1) => [[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0]] },
    { offset: [0, 0, 1], vertices: (x0, x1, y0, y1, _z0, z1) => [[x0, y0, z1], [x0, y1, z1], [x1, y1, z1], [x1, y0, z1]] },
  ];

  for (const cell of occupied.values()) {
    const x0 = xCoordinates[cell.x]; const x1 = xCoordinates[cell.x + 1];
    const y0 = yCoordinates[cell.y]; const y1 = yCoordinates[cell.y + 1];
    const z0 = zCoordinates[cell.z]; const z1 = zCoordinates[cell.z + 1];
    for (const face of faces) {
      if (!occupied.has(volumeKey(cell.x + face.offset[0], cell.y + face.offset[1], cell.z + face.offset[2]))) {
        addFace(face.vertices(x0, x1, y0, y1, z0, z1));
      }
    }
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  return geometry;
}

function VoxelUnionHighlight({ volumes, projection, color = DEFAULT_MAP_COLOR, opacity = 0.14, onSelect }: { volumes: GridVolume[]; projection: Projection; color?: string; opacity?: number; onSelect?: () => void }) {
  const geometry = useMemo(() => buildVolumeUnionGeometry(volumes, projection), [projection, volumes]);
  const edges = useMemo(() => geometry ? new THREE.EdgesGeometry(geometry) : null, [geometry]);

  useEffect(() => () => {
    geometry?.dispose();
    edges?.dispose();
  }, [edges, geometry]);

  if (!geometry || !edges) return null;
  return <group renderOrder={2}><mesh geometry={geometry} onClick={onSelect ? (event) => { event.stopPropagation(); onSelect(); } : undefined}><meshBasicMaterial color={color} transparent opacity={opacity} depthWrite={false} side={THREE.DoubleSide} /></mesh><lineSegments geometry={edges}><lineBasicMaterial color={color} transparent opacity={Math.min(opacity + 0.55, 0.95)} /></lineSegments></group>;
}

function axisAlignedRegionVolumes(volumes: MapRegionVolume[]): GridVolume[] | null {
  const result: GridVolume[] = [];
  for (const volume of volumes) {
    if (volume.polygon.length !== 4) return null;
    const xCoordinates = [...new Set(volume.polygon.map(([x]) => x))].sort((left, right) => left - right);
    const yCoordinates = [...new Set(volume.polygon.map(([, y]) => y))].sort((left, right) => left - right);
    if (xCoordinates.length !== 2 || yCoordinates.length !== 2) return null;
    const corners = new Set(volume.polygon.map(([x, y]) => `${x}:${y}`));
    if (![
      `${xCoordinates[0]}:${yCoordinates[0]}`, `${xCoordinates[0]}:${yCoordinates[1]}`,
      `${xCoordinates[1]}:${yCoordinates[0]}`, `${xCoordinates[1]}:${yCoordinates[1]}`,
    ].every((corner) => corners.has(corner))) return null;
    result.push({
      minX: xCoordinates[0], minY: yCoordinates[0], minZ: volume.min_z,
      maxX: xCoordinates[1], maxY: yCoordinates[1], maxZ: volume.max_z,
      columns: 0, rows: 0, layers: 0,
    });
  }
  return result;
}

function RegionVolumePart({ region, volume, projection, selected, editorOpen, onSelect, showLabel }: { region: MapRegion; volume: MapRegionVolume; projection: Projection; selected: boolean; editorOpen: boolean; onSelect: () => void; showLabel: boolean }) {
  const { geometry, edges, labelPosition } = useMemo(() => {
    const shape = new THREE.Shape(volume.polygon.map(([x, y]) => {
      const [worldX, worldZ] = projectMapPosition(x, y, projection);
      return new THREE.Vector2(worldX, -worldZ);
    }));
    const extruded = new THREE.ExtrudeGeometry(shape, {
      depth: Math.max((volume.max_z - volume.min_z) * projection.scale, 0.01),
      bevelEnabled: false,
    });
    extruded.rotateX(-Math.PI / 2);
    extruded.translate(0, volume.min_z * projection.scale, 0);
    const centroid = volume.polygon.reduce((sum, [x, y]) => ({ x: sum.x + x, y: sum.y + y }), { x: 0, y: 0 });
    return {
      geometry: extruded,
      edges: new THREE.EdgesGeometry(extruded),
      labelPosition: project({ x: centroid.x / volume.polygon.length, y: centroid.y / volume.polygon.length, z: volume.max_z }, projection),
    };
  }, [projection, volume]);
  const color = region.color || (region.region_type === 'restricted' ? COLORS.red : region.region_type === 'work' ? COLORS.cyan : COLORS.green);
  return <group><mesh geometry={geometry} renderOrder={1} onClick={editorOpen ? (event) => { event.stopPropagation(); onSelect(); } : undefined}><meshBasicMaterial color={color} transparent opacity={selected ? 0.34 : 0.16} side={THREE.DoubleSide} depthWrite={false} /></mesh><lineSegments geometry={edges} renderOrder={3}><lineBasicMaterial color={color} transparent opacity={selected ? 1 : 0.85} /></lineSegments>{editorOpen && showLabel && <Html position={[labelPosition[0], labelPosition[1] + 0.16, labelPosition[2]]} center distanceFactor={14} style={{ pointerEvents: 'none' }}><div className="whitespace-nowrap border px-1.5 py-0.5 text-[9px]" style={{ borderColor: color, color, backgroundColor: 'rgba(5,11,19,0.86)' }}>{region.name}</div></Html>}</group>;
}

function RegionVolume({ region, projection, selected, editorOpen, onSelect }: { region: MapRegion; projection: Projection; selected: boolean; editorOpen: boolean; onSelect: () => void }) {
  const volumes = useMemo(() => getRegionVolumes(region), [region]);
  const rectangularVolumes = useMemo(() => axisAlignedRegionVolumes(volumes), [volumes]);
  const color = region.color || (region.region_type === 'restricted' ? COLORS.red : region.region_type === 'work' ? COLORS.cyan : COLORS.green);
  const labelPosition = useMemo(() => {
    const primary = volumes[0];
    const centroid = primary.polygon.reduce((sum, [x, y]) => ({ x: sum.x + x, y: sum.y + y }), { x: 0, y: 0 });
    return project({ x: centroid.x / primary.polygon.length, y: centroid.y / primary.polygon.length, z: primary.max_z }, projection);
  }, [projection, volumes]);

  if (rectangularVolumes) {
    return <group><VoxelUnionHighlight volumes={rectangularVolumes} projection={projection} color={color} opacity={selected ? 0.34 : 0.16} onSelect={editorOpen ? onSelect : undefined} />{editorOpen && <Html position={[labelPosition[0], labelPosition[1] + 0.16, labelPosition[2]]} center distanceFactor={14} style={{ pointerEvents: 'none' }}><div className="whitespace-nowrap border px-1.5 py-0.5 text-[9px]" style={{ borderColor: color, color, backgroundColor: 'rgba(5,11,19,0.86)' }}>{region.name}</div></Html>}</group>;
  }
  return <group>{volumes.map((volume, index) => <RegionVolumePart key={`${region.id}-${index}`} region={region} volume={volume} projection={projection} selected={selected} editorOpen={editorOpen} onSelect={onSelect} showLabel={index === 0} />)}</group>;
}

function DeviceMarker({ device, projection, onClick }: { device: Device; projection: Projection; onClick: () => void }) {
  const displayStatus = getDeviceDisplayStatus(device.status, device.connection_status);
  const unavailable = displayStatus === 'offline' || displayStatus === 'planned_offline';
  const fault = device.status === 'fault' || device.status === 'maintenance';
  const color = unavailable ? COLORS.gray : fault ? COLORS.red : device.status === 'working' ? COLORS.green : device.status === 'moving' ? COLORS.cyan : COLORS.gray;
  const [x, y, z] = project(device.position, projection);
  return (
    <group position={[x, y + 0.4, z]} onClick={onClick}>
      <mesh><sphereGeometry args={[0.28, 12, 12]} /><meshStandardMaterial color={color} emissive={color} emissiveIntensity={unavailable ? 0.1 : fault ? 0.8 : 0.35} transparent={unavailable} opacity={unavailable ? 0.45 : 1} /></mesh>
      <Html position={[0, 0.8, 0]} center distanceFactor={14} style={{ pointerEvents: 'none' }}><div className="whitespace-nowrap border border-[rgba(91,183,255,0.3)] bg-[rgba(9,25,41,0.85)] px-1 text-[9px] text-[#E6F6FF]">{device.code}{displayStatus === 'planned_offline' ? ' · 主动离线' : unavailable ? ' · 离线' : ''}</div></Html>
    </group>
  );
}

function PointCloud({ pointcloud, projection }: { pointcloud: PointCloudData; projection: Projection }) {
  const geometry = useMemo(() => {
    const result = new THREE.BufferGeometry();
    const positions = new Float32Array(pointcloud.points.length * 3);
    const colors = new Float32Array(pointcloud.points.length * 3);
    pointcloud.points.forEach((item, index) => {
      const [x, y, z] = project({ x: item[0], y: item[1], z: item[2] }, projection);
      positions[index * 3] = x; positions[index * 3 + 1] = y; positions[index * 3 + 2] = z;
      const height = Math.max(0, Math.min(1, (item[2] || 0) / 30));
      colors[index * 3] = 0.18 + height * 0.55;
      colors[index * 3 + 1] = 0.58 + height * 0.25;
      colors[index * 3 + 2] = 0.95;
    });
    result.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    result.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    return result;
  }, [pointcloud, projection]);
  return <points geometry={geometry}><pointsMaterial size={0.1} vertexColors transparent opacity={0.82} sizeAttenuation /></points>;
}

function MapPointMarker({ point, config, projection, selected, editorOpen, onSelect }: { point: MapPoint; config: GridMapConfig; projection: Projection; selected: boolean; editorOpen: boolean; onSelect: () => void }) {
  const [x, y, z] = project(point, projection);
  const color = point.color || COLORS.amber;
  const cell = useMemo<GridCell>(() => ({
    x: config.origin_x + Math.floor((point.x - config.origin_x) / config.cell_length) * config.cell_length,
    y: config.origin_y + Math.floor((point.y - config.origin_y) / config.cell_width) * config.cell_width,
    z: config.origin_z + Math.floor((point.z - config.origin_z) / config.cell_height) * config.cell_height,
    sizeX: config.cell_length,
    sizeY: config.cell_width,
    sizeZ: config.cell_height,
  }), [config, point.x, point.y, point.z]);
  const cellVolume = useMemo<GridVolume>(() => ({ minX: cell.x, minY: cell.y, minZ: cell.z, maxX: cell.x + cell.sizeX, maxY: cell.y + cell.sizeY, maxZ: cell.z + cell.sizeZ, columns: 1, rows: 1, layers: 1 }), [cell]);
  return <group><VoxelHighlight volume={cellVolume} projection={projection} color={color} opacity={selected ? 0.24 : 0.07} /><group position={[x, y + 0.12, z]} onClick={editorOpen ? (event) => { event.stopPropagation(); onSelect(); } : undefined}><mesh><coneGeometry args={[0.12, 0.38, 4]} /><meshStandardMaterial color={color} emissive={color} emissiveIntensity={selected ? 0.65 : 0.3} /></mesh><Html position={[0, 0.45, 0]} center distanceFactor={14} style={{ pointerEvents: 'none' }}><div className="whitespace-nowrap border px-1.5 py-0.5 text-[9px]" style={{ borderColor: color, color, backgroundColor: 'rgba(5,11,19,0.86)' }}>{point.name}</div></Html></group></group>;
}

function pathGridCellKey(cell: PathGridCell): string {
  return `${cell.column}:${cell.row}:${cell.layer}`;
}

function pathPointToGridCell(point: [number, number, number], config: GridMapConfig): PathGridCell {
  return {
    column: Math.floor((point[0] - config.origin_x + EPSILON) / config.cell_length),
    row: Math.floor((point[1] - config.origin_y + EPSILON) / config.cell_width),
    layer: Math.floor((point[2] - config.origin_z + EPSILON) / config.cell_height),
  };
}

function rasterizePathGridCells(path: MapPath, config: GridMapConfig): PathGridCell[] {
  const routeCells = new Map<string, PathGridCell>();
  const addPoint = (point: [number, number, number]) => {
    const cell = pathPointToGridCell(point, config);
    routeCells.set(pathGridCellKey(cell), cell);
  };

  for (let index = 0; index < path.points.length - 1; index += 1) {
    const start = path.points[index];
    const end = path.points[index + 1];
    const steps = Math.max(1, Math.ceil(Math.max(
      Math.abs(end[0] - start[0]) / config.cell_length,
      Math.abs(end[1] - start[1]) / config.cell_width,
    )));
    for (let step = 0; step <= steps; step += 1) {
      const progress = step / steps;
      addPoint([
        start[0] + (end[0] - start[0]) * progress,
        start[1] + (end[1] - start[1]) * progress,
        start[2] + (end[2] - start[2]) * progress,
      ]);
    }
  }

  const widthCells = Math.max(1, Math.ceil(path.min_width_m / Math.min(config.cell_length, config.cell_width)));
  const radiusCells = Math.ceil((widthCells - 1) / 2);
  const corridorCells = new Map<string, PathGridCell>();
  for (const cell of routeCells.values()) {
    for (let rowOffset = -radiusCells; rowOffset <= radiusCells; rowOffset += 1) {
      for (let columnOffset = -radiusCells; columnOffset <= radiusCells; columnOffset += 1) {
        const expanded = { column: cell.column + columnOffset, row: cell.row + rowOffset, layer: cell.layer };
        corridorCells.set(pathGridCellKey(expanded), expanded);
      }
    }
  }
  return [...corridorCells.values()];
}

function MapPathRoute({ path, config, projection, selected, editorOpen, onSelect, draft = false }: { path: MapPath; config: GridMapConfig; projection: Projection; selected: boolean; editorOpen: boolean; onSelect?: () => void; draft?: boolean }) {
  const { corridor, edges, centerLine, labelPosition, hasCorridor } = useMemo(() => {
    const worldPoints = path.points.map(([x, y, z]) => new THREE.Vector3(...project({ x, y, z }, projection)));
    const corridorGeometry = new THREE.BufferGeometry();
    const edgeGeometry = new THREE.BufferGeometry();
    const centerLineGeometry = new THREE.BufferGeometry();
    const surfaceOffset = Math.min(config.cell_height * projection.scale * 0.04, 0.02);
    const linePositions = worldPoints.slice(0, -1).flatMap((point, index) => [
      point.x, point.y + surfaceOffset, point.z,
      worldPoints[index + 1].x, worldPoints[index + 1].y + surfaceOffset, worldPoints[index + 1].z,
    ]);
    if (linePositions.length > 0) centerLineGeometry.setAttribute('position', new THREE.Float32BufferAttribute(linePositions, 3));
    if (worldPoints.length < 2) return { corridor: corridorGeometry, edges: null, centerLine: centerLineGeometry, labelPosition: worldPoints[0] || new THREE.Vector3(), hasCorridor: false };

    const cells = rasterizePathGridCells(path, config);
    const occupied = new Set(cells.map(pathGridCellKey));
    const positions: number[] = [];
    const edgePositions: number[] = [];
    const appendVertex = (target: number[], x: number, y: number, z: number) => target.push(...project({ x, y, z }, projection));
    const appendEdge = (start: [number, number], end: [number, number], z: number) => {
      appendVertex(edgePositions, start[0], start[1], z);
      appendVertex(edgePositions, end[0], end[1], z);
    };
    const neighbors: Array<{ column: number; row: number; edge: (x0: number, x1: number, y0: number, y1: number) => [[number, number], [number, number]] }> = [
      { column: -1, row: 0, edge: (x0, _x1, y0, y1) => [[x0, y0], [x0, y1]] },
      { column: 1, row: 0, edge: (_x0, x1, y0, y1) => [[x1, y1], [x1, y0]] },
      { column: 0, row: -1, edge: (x0, x1, y0, _y1) => [[x1, y0], [x0, y0]] },
      { column: 0, row: 1, edge: (x0, x1, _y0, y1) => [[x0, y1], [x1, y1]] },
    ];

    for (const cell of cells) {
      const x0 = config.origin_x + cell.column * config.cell_length;
      const x1 = x0 + config.cell_length;
      const y0 = config.origin_y + cell.row * config.cell_width;
      const y1 = y0 + config.cell_width;
      const z = config.origin_z + cell.layer * config.cell_height + surfaceOffset / projection.scale;
      appendVertex(positions, x0, y0, z); appendVertex(positions, x1, y0, z); appendVertex(positions, x1, y1, z);
      appendVertex(positions, x0, y0, z); appendVertex(positions, x1, y1, z); appendVertex(positions, x0, y1, z);
      for (const neighbor of neighbors) {
        if (!occupied.has(pathGridCellKey({ column: cell.column + neighbor.column, row: cell.row + neighbor.row, layer: cell.layer }))) {
          const [start, end] = neighbor.edge(x0, x1, y0, y1);
          appendEdge(start, end, z);
        }
      }
    }
    corridorGeometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    if (edgePositions.length > 0) edgeGeometry.setAttribute('position', new THREE.Float32BufferAttribute(edgePositions, 3));
    return {
      corridor: corridorGeometry,
      edges: edgePositions.length > 0 ? edgeGeometry : null,
      centerLine: centerLineGeometry,
      labelPosition: worldPoints[Math.floor(worldPoints.length / 2)],
      hasCorridor: positions.length > 0,
    };
  }, [config, path, projection]);
  const color = draft ? DEFAULT_MAP_COLOR : path.status === 'active' ? (selected ? COLORS.amber : COLORS.green) : COLORS.gray;

  useEffect(() => () => {
    corridor.dispose();
    edges?.dispose();
    centerLine.dispose();
  }, [centerLine, corridor, edges]);

  if (path.points.length === 0) return null;
  const handleClick = editorOpen && onSelect ? (event: ThreeEvent<MouseEvent>) => { event.stopPropagation(); onSelect(); } : undefined;
  return <group><>{hasCorridor && <mesh geometry={corridor} onClick={handleClick}><meshBasicMaterial color={color} transparent opacity={draft ? 0.18 : selected ? 0.32 : 0.18} side={THREE.DoubleSide} depthWrite={false} /></mesh>}{edges && <lineSegments geometry={edges}><lineBasicMaterial color={color} transparent opacity={draft ? 0.9 : selected ? 1 : 0.78} /></lineSegments>}{hasCorridor && <lineSegments geometry={centerLine}><lineBasicMaterial color={color} transparent opacity={0.98} /></lineSegments>}{!hasCorridor && <mesh position={[labelPosition.x, labelPosition.y, labelPosition.z]} onClick={handleClick}><sphereGeometry args={[Math.max(path.min_width_m * projection.scale / 4, 0.06), 8, 8]} /><meshBasicMaterial color={color} transparent opacity={draft ? 0.55 : selected ? 0.8 : 0.6} /></mesh>}</>{editorOpen && !draft && <Html position={[labelPosition.x, labelPosition.y + 0.18, labelPosition.z]} center distanceFactor={14} style={{ pointerEvents: 'none' }}><div className="whitespace-nowrap border px-1.5 py-0.5 text-[9px]" style={{ borderColor: color, color, backgroundColor: 'rgba(5,11,19,0.86)' }}>{path.name}</div></Html>}</group>;
}

class MapPathRouteBoundary extends Component<{ children: ReactNode }, { hasError: boolean }> {
  state = { hasError: false };

  static getDerivedStateFromError(): { hasError: boolean } {
    return { hasError: true };
  }

  componentDidCatch(error: unknown): void {
    if (import.meta.env.DEV) console.error('地图路径渲染失败，已跳过异常路径。', error);
  }

  render(): ReactNode {
    return this.state.hasError ? null : this.props.children;
  }
}

function VoxelGridSelector({ mode, config, volume, projection, editLayer, regionHeightCells }: { mode: 'point' | 'region' | 'path'; config: GridMapConfig; volume: GridVolume; projection: Projection; editLayer: number; regionHeightCells: number }) {
  const dragging = useRef(false);
  const startCell = useRef<GridCell | null>(null);
  const selectionHeightCells = useRef(1);
  const { setPointCell, appendPathCell, appendRegionSelection, updateLastRegionSelection } = useMapEditorStore();
  const layerZ = volume.minZ + editLayer * config.cell_height;
  const [centerX, centerZ] = projectMapPosition((volume.minX + volume.maxX) / 2, (volume.minY + volume.maxY) / 2, projection);
  const width = (volume.maxX - volume.minX) * projection.scale;
  const depth = (volume.maxY - volume.minY) * projection.scale;

  const cellAtPointer = (point: THREE.Vector3) => snapGridCell(point, projection, config, volume, editLayer);
  const handlePointerDown = (event: { button: number; point: THREE.Vector3; stopPropagation: () => void }) => {
    if (event.button !== 0) return;
    event.stopPropagation();
    const cell = cellAtPointer(event.point);
    if (mode === 'point') {
      setPointCell(cell);
      return;
    }
    if (mode === 'path') {
      appendPathCell(cell);
      return;
    }
    dragging.current = true;
    startCell.current = cell;
    selectionHeightCells.current = regionHeightCells;
    appendRegionSelection({
      start: cell,
      end: cell,
      heightCells: selectionHeightCells.current,
      maxZ: Math.min(volume.maxZ, cell.z + selectionHeightCells.current * config.cell_height),
    });
  };
  const handlePointerMove = (event: { point: THREE.Vector3; stopPropagation: () => void }) => {
    if (!dragging.current || !startCell.current) return;
    event.stopPropagation();
    updateLastRegionSelection({
      start: startCell.current,
      end: cellAtPointer(event.point),
      heightCells: selectionHeightCells.current,
      maxZ: Math.min(volume.maxZ, startCell.current.z + selectionHeightCells.current * config.cell_height),
    });
  };
  const handlePointerUp = () => {
    dragging.current = false;
    startCell.current = null;
  };

  return <mesh position={[centerX, layerZ * projection.scale + 0.004, centerZ]} rotation-x={-Math.PI / 2} onPointerDown={handlePointerDown} onPointerMove={handlePointerMove} onPointerUp={handlePointerUp}><planeGeometry args={[width, depth]} /><meshBasicMaterial transparent opacity={0} depthWrite={false} /></mesh>;
}

function isRenderableMeshAsset(asset: MapAsset, frameId: string): boolean {
  if (asset.asset_type !== 'mesh_gltf' || asset.frame_id !== frameId) return false;
  try {
    const url = new URL(asset.asset_uri);
    return url.protocol === 'https:' && /\.(gltf|glb)$/i.test(url.pathname);
  } catch {
    return false;
  }
}

function MapMesh({ asset, projection }: { asset: MapAsset; projection: Projection }) {
  const gltf = useGLTF(asset.asset_uri);
  const scene = useMemo(() => gltf.scene.clone(true), [gltf.scene]);
  const metadata = asset.metadata as { origin?: [number, number, number]; scale?: number };
  const origin = metadata.origin || [0, 0, 0];
  const scale = Number(metadata.scale || 1) * projection.scale;
  const [x, y, z] = project({ x: origin[0], y: origin[1], z: origin[2] }, projection);
  return <primitive object={scene} position={[x, y, z]} scale={[scale, scale, scale]} />;
}

export function Scene3D() {
  const { devices, energyView, filterStatuses, pointcloud, safetyView, selectDevice, currentView } = useOmStore();
  const { isOpen: editorOpen, mode, pointCell, regionSelections, roadSegments, pendingRoadStart, editingPathId, pathCells, pathPreviewWidthM, selectedEntity, selectEntity, gridConfig, setGridConfig, editLayer, regionHeightCells, gridVisible, setGridVisible } = useMapEditorStore();
  const [regions, setRegions] = useState<MapRegion[]>([]);
  const [points, setPoints] = useState<MapPoint[]>([]);
  const [paths, setPaths] = useState<MapPath[]>([]);
  const [assets, setAssets] = useState<MapAsset[]>([]);
  const [frameId, setFrameId] = useState('map');
  const [actionState, setActionState] = useState('');

  useEffect(() => {
    const refresh = () => getSceneConfig().then((scene) => {
      setRegions(scene.regions);
      setPoints(scene.points);
      setPaths(scene.paths || []);
      setAssets(scene.assets || []);
      setFrameId(scene.frame_id);
      setGridConfig(scene.grid_config || DEFAULT_GRID_CONFIG);
    }).catch((error) => setActionState(error instanceof Error ? error.message : '地图读取失败'));
    refresh();
    window.addEventListener('robots:map-changed', refresh);
    return () => window.removeEventListener('robots:map-changed', refresh);
  }, [setGridConfig]);

  const filteredDevices = useMemo(() => devices.filter((device) => !filterStatuses.size || filterStatuses.has(getDeviceDisplayStatus(device.status, device.connection_status))), [devices, filterStatuses]);
  const displayGridConfig = useMemo(() => getDisplayGridConfig(gridConfig), [gridConfig]);
  const gridVolume = useMemo(() => getGridVolume(displayGridConfig, gridConfig), [displayGridConfig, gridConfig]);
  const projection = useMemo(() => calculateProjection(regions, points, paths, devices, pointcloud, gridVolume), [regions, points, paths, devices, pointcloud, gridVolume]);
  const hasPointcloud = Boolean(pointcloud?.points.length);
  const meshAssets = useMemo(() => assets.filter((asset) => isRenderableMeshAsset(asset, frameId)), [assets, frameId]);
  const activeLayerVolume = useMemo<GridVolume>(() => ({
    minX: gridVolume.minX, minY: gridVolume.minY, minZ: gridVolume.minZ + editLayer * displayGridConfig.cell_height,
    maxX: gridVolume.maxX, maxY: gridVolume.maxY, maxZ: Math.min(gridVolume.maxZ, gridVolume.minZ + (editLayer + 1) * displayGridConfig.cell_height),
    columns: gridVolume.columns, rows: gridVolume.rows, layers: 1,
  }), [displayGridConfig.cell_height, editLayer, gridVolume]);
  const pointSelectionVolume = pointCell ? {
    minX: pointCell.x, minY: pointCell.y, minZ: pointCell.z,
    maxX: pointCell.x + pointCell.sizeX, maxY: pointCell.y + pointCell.sizeY, maxZ: pointCell.z + pointCell.sizeZ,
    columns: 1, rows: 1, layers: 1,
  } : null;
  const regionSelectionVolumes = useMemo(
    () => createRegionSelectionUnion(regionSelections).volumes.map(mapRegionVolumeToGridVolume),
    [regionSelections],
  );
  const pathDrafts = useMemo<MapPath[]>(() => {
    const toPoint = (cell: GridCell): [number, number, number] => [
      cell.x + cell.sizeX / 2,
      cell.y + cell.sizeY / 2,
      cell.z,
    ];
    if (editingPathId) {
      return pathCells.length ? [{
        id: 'road-replacement-draft', code: 'ROAD-REPLACEMENT-DRAFT', name: '道路端点草稿',
        points: pathCells.map(toPoint), direction: 'bidirectional', min_width_m: pathPreviewWidthM,
        max_slope_percent: 100, device_types: [], status: 'active',
      }] : [];
    }
    return roadSegments.map((segment, index) => ({
      id: `road-segment-draft-${index}`, code: `ROAD-SEGMENT-DRAFT-${index}`, name: `道路草稿 ${index + 1}`,
      points: segment.map(toPoint), direction: 'bidirectional', min_width_m: pathPreviewWidthM,
      max_slope_percent: 100, device_types: [], status: 'active',
    }));
  }, [editingPathId, pathCells, pathPreviewWidthM, roadSegments]);
  const pendingRoadDraft = useMemo<MapPath | null>(() => pendingRoadStart && !editingPathId ? {
    id: 'road-start-draft', code: 'ROAD-START-DRAFT', name: '道路起点',
    points: [[
      pendingRoadStart.x + pendingRoadStart.sizeX / 2,
      pendingRoadStart.y + pendingRoadStart.sizeY / 2,
      pendingRoadStart.z,
    ]],
    direction: 'bidirectional', min_width_m: pathPreviewWidthM,
    max_slope_percent: 100, device_types: [], status: 'active',
  } : null, [editingPathId, pathPreviewWidthM, pendingRoadStart]);
  const editingGeometry = editorOpen && mode !== 'select';
  const navigationMouseButtons = useMemo(() => ({ LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.PAN, RIGHT: THREE.MOUSE.ROTATE }), []);
  const editMouseButtons = useMemo(() => ({ LEFT: -1, MIDDLE: THREE.MOUSE.PAN, RIGHT: THREE.MOUSE.ROTATE }), []);
  const summary = editorOpen
    ? mode === 'point' ? `点位体素编辑 · 第 ${editLayer + 1} 层` : mode === 'region' ? `区域体素编辑 · 第 ${editLayer + 1} 层` : mode === 'path' ? `通行路径编辑 · 第 ${editLayer + 1} 层` : '地图对象选择'
    : currentView === 'energy'
      ? energyView?.has_data ? `累计能耗 ${energyView.total_energy_kwh ?? '--'} 千瓦时 · 当前功率 ${energyView.current_power_kw ?? '--'} 千瓦` : '等待设备上报能耗数据'
      : currentView === 'safety'
        ? `急停 ${safetyView?.global_estop.active ? '已触发' : '未触发'} · 活动告警 ${safetyView?.open_alert_count ?? 0}`
        : hasPointcloud ? `完整点云地图 ${pointcloud!.total_count} 点` : '等待外部建图网关上传完整点云地图';

  const runCommand = async (command: 'pause' | 'release' | 'reset') => {
    try {
      const response = await sendBatchCommand({ command });
      setActionState(`已向 ${response.targets.length} 台设备写入${COMMAND_LABELS[command] || '控制'}命令队列`);
    } catch (error) {
      setActionState(error instanceof Error ? error.message : '命令入队失败');
    }
  };
  const runEstop = async () => {
    try { await triggerEstop(); setActionState('全局急停命令已写入设备队列'); }
    catch (error) { setActionState(error instanceof Error ? error.message : '急停请求失败'); }
  };

  return (
    <div className="relative flex h-full min-h-0 flex-col">
      <div className="mb-1 flex shrink-0 flex-wrap gap-1">
        {FILTER_CHIPS.map((chip) => {
          const active = filterStatuses.has(chip.id);
          return <button key={chip.id} onClick={() => useOmStore.getState().toggleFilter(chip.id)} className={`rounded-full border px-2.5 py-0.5 text-[11px] ${active ? 'text-[#050B13]' : 'text-[#79A3BF]'}`} style={{ borderColor: chip.color, backgroundColor: active ? chip.color : `${chip.color}22` }}>{chip.label}</button>;
        })}
        <button type="button" title={gridVisible ? '隐藏三维栅格' : '显示三维栅格'} aria-label={gridVisible ? '隐藏三维栅格' : '显示三维栅格'} aria-pressed={gridVisible} onClick={() => setGridVisible(!gridVisible)} className={`grid h-6 w-6 place-items-center border ${gridVisible ? 'border-[#2FD7FF] bg-[rgba(47,215,255,0.15)] text-[#2FD7FF]' : 'border-[rgba(91,183,255,0.28)] text-[#79A3BF] hover:text-[#E6F6FF]'}`}><Grid3X3 size={14} /></button>
      </div>
      <div className="min-h-0 flex-1 border border-[rgba(91,183,255,0.22)] bg-[rgba(5,11,19,0.6)]">
        <Canvas dpr={[1, 2]} camera={{ position: [20, 20, 20], fov: 50 }} onContextMenu={(event) => event.preventDefault()}>
          <ambientLight intensity={0.4} />
          <directionalLight position={[10, 20, 10]} intensity={0.6} />
          <OrbitControls enablePan enableZoom enableRotate mouseButtons={editingGeometry ? editMouseButtons : navigationMouseButtons} />
          {gridVisible && <VoxelGrid config={displayGridConfig} projection={projection} volume={gridVolume} />}
          {editorOpen && <VoxelHighlight volume={activeLayerVolume} projection={projection} color="#E6F6FF" opacity={0.025} />}
          {meshAssets.map((asset) => <MapMesh key={asset.id} asset={asset} projection={projection} />)}
          {hasPointcloud ? <PointCloud pointcloud={pointcloud!} projection={projection} /> : <Html center position={[0, 2, 0]}><div className="whitespace-nowrap text-[12px] text-[#79A3BF]">等待外部建图网关上传完整点云地图</div></Html>}
          {regions.map((region) => <RegionVolume key={region.id} region={region} projection={projection} selected={selectedEntity?.kind === 'region' && selectedEntity.id === region.id} editorOpen={editorOpen} onSelect={() => selectEntity({ kind: 'region', id: region.id })} />)}
          {points.map((point) => <MapPointMarker key={point.id} point={point} config={gridConfig} projection={projection} selected={selectedEntity?.kind === 'point' && selectedEntity.id === point.id} editorOpen={editorOpen} onSelect={() => selectEntity({ kind: 'point', id: point.id })} />)}
          {paths.map((path) => <MapPathRouteBoundary key={path.id}><MapPathRoute path={path} config={gridConfig} projection={projection} selected={selectedEntity?.kind === 'path' && selectedEntity.id === path.id} editorOpen={editorOpen} onSelect={() => selectEntity({ kind: 'path', id: path.id })} /></MapPathRouteBoundary>)}
          {editorOpen && mode === 'point' && pointSelectionVolume && <VoxelHighlight volume={pointSelectionVolume} projection={projection} color="#E6F6FF" opacity={0.16} />}
          {editorOpen && mode === 'region' && <VoxelUnionHighlight volumes={regionSelectionVolumes} projection={projection} color={DEFAULT_MAP_COLOR} opacity={0.13} />}
          {editorOpen && mode === 'path' && pathDrafts.map((path) => <MapPathRouteBoundary key={path.id}><MapPathRoute path={path} config={gridConfig} projection={projection} selected={false} editorOpen={false} draft /></MapPathRouteBoundary>)}
          {editorOpen && mode === 'path' && pendingRoadDraft && <MapPathRouteBoundary><MapPathRoute path={pendingRoadDraft} config={gridConfig} projection={projection} selected={false} editorOpen={false} draft /></MapPathRouteBoundary>}
          {editorOpen && mode !== 'select' && <VoxelGridSelector mode={mode} config={displayGridConfig} volume={gridVolume} projection={projection} editLayer={editLayer} regionHeightCells={regionHeightCells} />}
          {filteredDevices.map((device) => <DeviceMarker key={device.id} device={device} projection={projection} onClick={() => { if (!editorOpen) selectDevice(device.id); }} />)}
        </Canvas>
      </div>
      <div className="mt-1 flex shrink-0 items-center justify-between gap-2">
        <div className="flex gap-1">
          <button onClick={runEstop} className="rounded border border-[#FF5C6D] bg-[rgba(255,92,109,0.15)] px-3 py-1 text-[12px] font-medium text-[#FF5C6D]">急停</button>
          <button onClick={() => runCommand('pause')} className="rounded border border-[#FFB33D] bg-[rgba(255,179,61,0.12)] px-3 py-1 text-[12px] font-medium text-[#FFB33D]">全部暂停</button>
          <button onClick={() => runCommand('release')} className="rounded border border-[#34DF9A] bg-[rgba(52,223,154,0.12)] px-3 py-1 text-[12px] font-medium text-[#34DF9A]">释放设备</button>
          <button onClick={() => runCommand('reset')} className="rounded border border-[#B56CFF] bg-[rgba(181,108,255,0.12)] px-3 py-1 text-[12px] font-medium text-[#B56CFF]">复位</button>
        </div>
        <span className="max-w-[48%] truncate text-right text-[10px] text-[#5A7A92]" title={actionState || summary}>{actionState || summary}</span>
      </div>
    </div>
  );
}
