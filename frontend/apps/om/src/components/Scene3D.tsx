/** O&M spatial view. Map annotations share the point-cloud coordinate frame. */

import { useEffect, useMemo, useRef, useState } from 'react';
import { Canvas } from '@react-three/fiber';
import { Grid, Html, OrbitControls, useGLTF } from '@react-three/drei';
import * as THREE from 'three';
import { useOmStore } from '../stores/omStore';
import { MAP_GRID_SIZE, type GridCell, type RegionGridSelection, useMapEditorStore } from '../stores/mapEditorStore';
import { COLORS, COMMAND_LABELS, FILTER_CHIPS } from '@robots/utils';
import { getSceneConfig, sendBatchCommand, triggerEstop } from '@robots/api-client';
import type { Device, MapAsset, MapPoint, MapRegion, PointCloudData } from '@robots/shared-types';

const DEFAULT_MAP_COLOR = '#2FD7FF';
const EPSILON = 0.0001;

interface Projection {
  centerX: number;
  centerY: number;
  scale: number;
}

interface MapBounds {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

function project(point: { x: number; y: number; z?: number }, projection: Projection): [number, number, number] {
  return [
    (point.x - projection.centerX) * projection.scale,
    (point.z || 0) * projection.scale,
    (point.y - projection.centerY) * projection.scale,
  ];
}

function projectMapPosition(x: number, y: number, projection: Projection): [number, number] {
  return [(x - projection.centerX) * projection.scale, (y - projection.centerY) * projection.scale];
}

function snapGridCell(point: THREE.Vector3, projection: Projection): GridCell {
  const x = point.x / projection.scale + projection.centerX;
  const y = point.z / projection.scale + projection.centerY;
  return {
    x: Math.floor(x / MAP_GRID_SIZE) * MAP_GRID_SIZE,
    y: Math.floor(y / MAP_GRID_SIZE) * MAP_GRID_SIZE,
    size: MAP_GRID_SIZE,
  };
}

function getSelectionBounds(selection: RegionGridSelection): MapBounds {
  return {
    minX: Math.min(selection.start.x, selection.end.x),
    minY: Math.min(selection.start.y, selection.end.y),
    maxX: Math.max(selection.start.x, selection.end.x) + selection.start.size,
    maxY: Math.max(selection.start.y, selection.end.y) + selection.start.size,
  };
}

function getAxisAlignedBounds(polygon: number[][]): MapBounds | null {
  if (polygon.length !== 4) return null;
  const xs = polygon.map((vertex) => vertex[0]);
  const ys = polygon.map((vertex) => vertex[1]);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  if (maxX - minX < EPSILON || maxY - minY < EPSILON) return null;
  const corners = new Set([
    `${minX}:${minY}`,
    `${minX}:${maxY}`,
    `${maxX}:${minY}`,
    `${maxX}:${maxY}`,
  ]);
  return polygon.every(([x, y]) => corners.has(`${x}:${y}`)) ? { minX, minY, maxX, maxY } : null;
}

function calculateProjection(regions: MapRegion[], points: MapPoint[], devices: Device[], pointcloud: PointCloudData | null): Projection {
  const samples: Array<{ x: number; y: number }> = [];
  for (const region of regions) for (const vertex of region.polygon) samples.push({ x: vertex[0], y: vertex[1] });
  for (const point of points) samples.push(point);
  for (const device of devices) samples.push(device.position);
  if (pointcloud?.points.length) {
    const stride = Math.max(1, Math.floor(pointcloud.points.length / 300));
    for (let index = 0; index < pointcloud.points.length; index += stride) {
      const item = pointcloud.points[index];
      samples.push({ x: item[0], y: item[1] });
    }
  }
  if (!samples.length) return { centerX: 0, centerY: 0, scale: 1 };
  let minX = samples[0].x;
  let maxX = samples[0].x;
  let minY = samples[0].y;
  let maxY = samples[0].y;
  for (const sample of samples) {
    minX = Math.min(minX, sample.x); maxX = Math.max(maxX, sample.x);
    minY = Math.min(minY, sample.y); maxY = Math.max(maxY, sample.y);
  }
  const span = Math.max(maxX - minX, maxY - minY, 1);
  return { centerX: (minX + maxX) / 2, centerY: (minY + maxY) / 2, scale: 24 / span };
}

function buildLineGeometry(vertices: number[]): THREE.BufferGeometry {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3));
  return geometry;
}

function RasterGridLines({ bounds, cellSize, color, projection, y = 0.045 }: { bounds: MapBounds; cellSize: number; color: string; projection: Projection; y?: number }) {
  const geometry = useMemo(() => {
    const vertices: number[] = [];
    const columns = Math.max(1, Math.round((bounds.maxX - bounds.minX) / cellSize));
    const rows = Math.max(1, Math.round((bounds.maxY - bounds.minY) / cellSize));
    const columnStride = Math.max(1, Math.ceil(columns / 180));
    const rowStride = Math.max(1, Math.ceil(rows / 180));
    for (let column = 0; column <= columns; column += columnStride) {
      const x = bounds.minX + Math.min(column, columns) * cellSize;
      const [worldX, minZ] = projectMapPosition(x, bounds.minY, projection);
      const [, maxZ] = projectMapPosition(x, bounds.maxY, projection);
      vertices.push(worldX, y, minZ, worldX, y, maxZ);
    }
    if (columns % columnStride !== 0) {
      const [worldX, minZ] = projectMapPosition(bounds.maxX, bounds.minY, projection);
      const [, maxZ] = projectMapPosition(bounds.maxX, bounds.maxY, projection);
      vertices.push(worldX, y, minZ, worldX, y, maxZ);
    }
    for (let row = 0; row <= rows; row += rowStride) {
      const mapY = bounds.minY + Math.min(row, rows) * cellSize;
      const [minX, worldZ] = projectMapPosition(bounds.minX, mapY, projection);
      const [maxX] = projectMapPosition(bounds.maxX, mapY, projection);
      vertices.push(minX, y, worldZ, maxX, y, worldZ);
    }
    if (rows % rowStride !== 0) {
      const [minX, worldZ] = projectMapPosition(bounds.minX, bounds.maxY, projection);
      const [maxX] = projectMapPosition(bounds.maxX, bounds.maxY, projection);
      vertices.push(minX, y, worldZ, maxX, y, worldZ);
    }
    return buildLineGeometry(vertices);
  }, [bounds, cellSize, projection, y]);

  return <lineSegments geometry={geometry} renderOrder={3}><lineBasicMaterial color={color} transparent opacity={0.95} /></lineSegments>;
}

function GridCellHighlight({ cell, projection, color = DEFAULT_MAP_COLOR, opacity = 0.12 }: { cell: GridCell; projection: Projection; color?: string; opacity?: number }) {
  const bounds = useMemo(() => ({ minX: cell.x, minY: cell.y, maxX: cell.x + cell.size, maxY: cell.y + cell.size }), [cell]);
  const [centerX, centerZ] = projectMapPosition((bounds.minX + bounds.maxX) / 2, (bounds.minY + bounds.maxY) / 2, projection);
  const width = (bounds.maxX - bounds.minX) * projection.scale;
  const height = (bounds.maxY - bounds.minY) * projection.scale;
  return <group><mesh position={[centerX, 0.035, centerZ]} rotation-x={-Math.PI / 2} renderOrder={1}><planeGeometry args={[width, height]} /><meshBasicMaterial color={color} transparent opacity={opacity} depthWrite={false} /></mesh><RasterGridLines bounds={bounds} cellSize={cell.size} color={color} projection={projection} /></group>;
}

function RegionSelectionPreview({ selection, projection }: { selection: RegionGridSelection; projection: Projection }) {
  const bounds = useMemo(() => getSelectionBounds(selection), [selection]);
  const [centerX, centerZ] = projectMapPosition((bounds.minX + bounds.maxX) / 2, (bounds.minY + bounds.maxY) / 2, projection);
  return <group><mesh position={[centerX, 0.034, centerZ]} rotation-x={-Math.PI / 2} renderOrder={1}><planeGeometry args={[(bounds.maxX - bounds.minX) * projection.scale, (bounds.maxY - bounds.minY) * projection.scale]} /><meshBasicMaterial color={DEFAULT_MAP_COLOR} transparent opacity={0.1} depthWrite={false} /></mesh><RasterGridLines bounds={bounds} cellSize={selection.start.size} color={DEFAULT_MAP_COLOR} projection={projection} /></group>;
}

function PolygonBoundary({ polygon, projection, color, selected }: { polygon: number[][]; projection: Projection; color: string; selected: boolean }) {
  const geometry = useMemo(() => {
    const vertices: number[] = [];
    polygon.forEach(([x, y], index) => {
      const next = polygon[(index + 1) % polygon.length];
      const [worldX, worldZ] = projectMapPosition(x, y, projection);
      const [nextX, nextZ] = projectMapPosition(next[0], next[1], projection);
      vertices.push(worldX, 0.052, worldZ, nextX, 0.052, nextZ);
    });
    return buildLineGeometry(vertices);
  }, [polygon, projection]);
  return <lineSegments geometry={geometry} renderOrder={4}><lineBasicMaterial color={color} transparent opacity={selected ? 1 : 0.82} /></lineSegments>;
}

function DeviceMarker({ device, projection, onClick }: { device: Device; projection: Projection; onClick: () => void }) {
  const fault = device.status === 'fault' || device.status === 'maintenance';
  const color = fault ? COLORS.red : device.status === 'working' ? COLORS.green : device.status === 'moving' ? COLORS.cyan : COLORS.gray;
  const [x, y, z] = project(device.position, projection);
  return (
    <group position={[x, Math.max(y, 0) + 0.4, z]} onClick={onClick}>
      <mesh>
        <sphereGeometry args={[0.28, 12, 12]} />
        <meshStandardMaterial color={color} emissive={color} emissiveIntensity={fault ? 0.8 : 0.35} />
      </mesh>
      <Html position={[0, 0.8, 0]} center distanceFactor={14} style={{ pointerEvents: 'none' }}>
        <div className="whitespace-nowrap border border-[rgba(91,183,255,0.3)] bg-[rgba(9,25,41,0.85)] px-1 text-[9px] text-[#E6F6FF]">{device.code}</div>
      </Html>
    </group>
  );
}

function PointCloud({ pointcloud, projection }: { pointcloud: PointCloudData; projection: Projection }) {
  const geometry = useMemo(() => {
    const geometry = new THREE.BufferGeometry();
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
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    return geometry;
  }, [pointcloud, projection]);
  return <points geometry={geometry}><pointsMaterial size={0.1} vertexColors transparent opacity={0.82} sizeAttenuation /></points>;
}

function RegionOverlay({ region, projection, selected, editorOpen, onSelect }: { region: MapRegion; projection: Projection; selected: boolean; editorOpen: boolean; onSelect: () => void }) {
  const geometry = useMemo(() => new THREE.ShapeGeometry(new THREE.Shape(region.polygon.map(([x, y]) => new THREE.Vector2((x - projection.centerX) * projection.scale, (y - projection.centerY) * projection.scale)))), [projection, region.polygon]);
  const color = region.color || (region.region_type === 'restricted' ? COLORS.red : region.region_type === 'work' ? COLORS.cyan : COLORS.green);
  const rasterBounds = useMemo(() => getAxisAlignedBounds(region.polygon), [region.polygon]);
  const labelPosition = useMemo(() => {
    const centroid = region.polygon.reduce((sum, [x, y]) => ({ x: sum.x + x, y: sum.y + y }), { x: 0, y: 0 });
    return projectMapPosition(centroid.x / region.polygon.length, centroid.y / region.polygon.length, projection);
  }, [projection, region.polygon]);
  return <group><mesh geometry={geometry} rotation-x={-Math.PI / 2} position={[0, 0.01, 0]} onClick={editorOpen ? (event) => { event.stopPropagation(); onSelect(); } : undefined}><meshBasicMaterial color={color} transparent opacity={selected ? 0.33 : 0.18} side={THREE.DoubleSide} /></mesh><PolygonBoundary polygon={region.polygon} projection={projection} color={color} selected={selected} />{rasterBounds && <RasterGridLines bounds={rasterBounds} cellSize={MAP_GRID_SIZE} color={color} projection={projection} />}{editorOpen && <Html position={[labelPosition[0], 0.18, labelPosition[1]]} center distanceFactor={14} style={{ pointerEvents: 'none' }}><div className="whitespace-nowrap border px-1.5 py-0.5 text-[9px]" style={{ borderColor: color, color, backgroundColor: 'rgba(5,11,19,0.86)' }}>{region.name}</div></Html>}</group>;
}

function MapPointMarker({ point, projection, selected, editorOpen, onSelect }: { point: MapPoint; projection: Projection; selected: boolean; editorOpen: boolean; onSelect: () => void }) {
  const [x, y, z] = project(point, projection);
  const color = point.color || COLORS.amber;
  const cell = useMemo(() => ({ x: Math.floor(point.x / MAP_GRID_SIZE) * MAP_GRID_SIZE, y: Math.floor(point.y / MAP_GRID_SIZE) * MAP_GRID_SIZE, size: MAP_GRID_SIZE }), [point.x, point.y]);
  return <group><GridCellHighlight cell={cell} projection={projection} color={color} opacity={selected ? 0.28 : 0.08} /><group position={[x, Math.max(y, 0) + 0.12, z]} onClick={editorOpen ? (event) => { event.stopPropagation(); onSelect(); } : undefined}><mesh><coneGeometry args={[0.12, 0.38, 4]} /><meshStandardMaterial color={color} emissive={color} emissiveIntensity={selected ? 0.65 : 0.3} /></mesh><Html position={[0, 0.45, 0]} center distanceFactor={14} style={{ pointerEvents: 'none' }}><div className="whitespace-nowrap border px-1.5 py-0.5 text-[9px]" style={{ borderColor: color, color, backgroundColor: 'rgba(5,11,19,0.86)' }}>{point.name}</div></Html></group></group>;
}

function MapRasterSelector({ mode, projection }: { mode: 'point' | 'region'; projection: Projection }) {
  const dragging = useRef(false);
  const startCell = useRef<GridCell | null>(null);
  const { setPointCell, setRegionSelection } = useMapEditorStore();
  const planeSize = 60;

  const handlePointerDown = (event: { button: number; point: THREE.Vector3; stopPropagation: () => void }) => {
    if (event.button !== 0) return;
    event.stopPropagation();
    const cell = snapGridCell(event.point, projection);
    if (mode === 'point') {
      setPointCell(cell);
      return;
    }
    dragging.current = true;
    startCell.current = cell;
    setRegionSelection({ start: cell, end: cell });
  };

  const handlePointerMove = (event: { point: THREE.Vector3; stopPropagation: () => void }) => {
    if (!dragging.current || !startCell.current) return;
    event.stopPropagation();
    setRegionSelection({ start: startCell.current, end: snapGridCell(event.point, projection) });
  };

  const handlePointerUp = () => {
    dragging.current = false;
    startCell.current = null;
  };

  return <mesh position={[0, 0.08, 0]} rotation-x={-Math.PI / 2} onPointerDown={handlePointerDown} onPointerMove={handlePointerMove} onPointerUp={handlePointerUp}><planeGeometry args={[planeSize, planeSize]} /><meshBasicMaterial transparent opacity={0} depthWrite={false} /></mesh>;
}

function isRenderableMeshAsset(asset: MapAsset): boolean {
  if (asset.asset_type !== 'mesh_gltf' || asset.frame_id !== 'map') return false;
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
  const { isOpen: editorOpen, mode, pointCell, regionSelection, selectedEntity, selectEntity } = useMapEditorStore();
  const [regions, setRegions] = useState<MapRegion[]>([]);
  const [points, setPoints] = useState<MapPoint[]>([]);
  const [assets, setAssets] = useState<MapAsset[]>([]);
  const [actionState, setActionState] = useState('');

  useEffect(() => {
    const refresh = () => getSceneConfig().then((scene) => {
      setRegions(scene.regions);
      setPoints(scene.points);
      setAssets(scene.assets || []);
    }).catch((error) => setActionState(error instanceof Error ? error.message : '地图读取失败'));
    refresh();
    window.addEventListener('robots:map-changed', refresh);
    return () => window.removeEventListener('robots:map-changed', refresh);
  }, []);

  const filteredDevices = useMemo(() => devices.filter((device) => !filterStatuses.size || filterStatuses.has(device.status)), [devices, filterStatuses]);
  const projection = useMemo(() => calculateProjection(regions, points, devices, pointcloud), [regions, points, devices, pointcloud]);
  const hasPointcloud = Boolean(pointcloud?.points.length);
  const meshAssets = useMemo(() => assets.filter(isRenderableMeshAsset), [assets]);
  const gridCellSize = Math.max(MAP_GRID_SIZE * projection.scale, 0.05);
  const [gridOriginX, gridOriginZ] = projectMapPosition(0, 0, projection);
  const summary = editorOpen
    ? mode === 'point' ? '点位栅格编辑' : mode === 'region' ? '区域栅格编辑' : '地图对象选择'
    : currentView === 'energy'
      ? energyView?.has_data ? `累计能耗 ${energyView.total_energy_kwh ?? '--'} 千瓦时 · 当前功率 ${energyView.current_power_kw ?? '--'} 千瓦` : '等待设备上报能耗数据'
      : currentView === 'safety'
        ? `急停 ${safetyView?.global_estop.active ? '已触发' : '未触发'} · 活动告警 ${safetyView?.open_alert_count ?? 0}`
        : hasPointcloud ? `点云快照 ${pointcloud!.total_count} 点` : '等待外部建图网关上传点云';

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
    <div className="relative flex h-full flex-col">
      <div className="mb-1 flex flex-wrap gap-1">
        {FILTER_CHIPS.map((chip) => {
          const active = filterStatuses.has(chip.id);
          return <button key={chip.id} onClick={() => useOmStore.getState().toggleFilter(chip.id)} className={`rounded-full border px-2.5 py-0.5 text-[11px] ${active ? 'text-[#050B13]' : 'text-[#79A3BF]'}`} style={{ borderColor: chip.color, backgroundColor: active ? chip.color : `${chip.color}22` }}>{chip.label}</button>;
        })}
      </div>

      <div className="flex-1 border border-[rgba(91,183,255,0.22)] bg-[rgba(5,11,19,0.6)]">
        <Canvas camera={{ position: [20, 20, 20], fov: 50 }}>
          <ambientLight intensity={0.4} />
          <directionalLight position={[10, 20, 10]} intensity={0.6} />
          <OrbitControls enablePan enableZoom enableRotate />
          <Grid position={[gridOriginX, 0, gridOriginZ]} args={[60, 60]} cellSize={gridCellSize} cellColor="rgba(91,183,255,0.15)" sectionSize={gridCellSize * 5} sectionColor="rgba(91,183,255,0.3)" fadeDistance={65} />
          {meshAssets.map((asset) => <MapMesh key={asset.id} asset={asset} projection={projection} />)}
          {hasPointcloud ? <PointCloud pointcloud={pointcloud!} projection={projection} /> : <Html center position={[0, 2, 0]}><div className="whitespace-nowrap text-[12px] text-[#79A3BF]">等待外部建图网关上传点云</div></Html>}
          {regions.map((region) => <RegionOverlay key={region.id} region={region} projection={projection} selected={selectedEntity?.kind === 'region' && selectedEntity.id === region.id} editorOpen={editorOpen} onSelect={() => selectEntity({ kind: 'region', id: region.id })} />)}
          {points.map((point) => <MapPointMarker key={point.id} point={point} projection={projection} selected={selectedEntity?.kind === 'point' && selectedEntity.id === point.id} editorOpen={editorOpen} onSelect={() => selectEntity({ kind: 'point', id: point.id })} />)}
          {editorOpen && mode === 'point' && pointCell && <GridCellHighlight cell={pointCell} projection={projection} color="#E6F6FF" opacity={0.16} />}
          {editorOpen && mode === 'region' && regionSelection && <RegionSelectionPreview selection={regionSelection} projection={projection} />}
          {editorOpen && mode !== 'select' && <MapRasterSelector mode={mode} projection={projection} />}
          {filteredDevices.map((device) => <DeviceMarker key={device.id} device={device} projection={projection} onClick={() => { if (!editorOpen) selectDevice(device.id); }} />)}
        </Canvas>
      </div>

      <div className="mt-1 flex items-center justify-between gap-2">
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
