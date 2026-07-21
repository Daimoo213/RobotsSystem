/** O&M spatial view. Every overlay is derived from persisted map/telemetry data. */

import { useEffect, useMemo, useState } from 'react';
import { Canvas } from '@react-three/fiber';
import { Grid, Html, OrbitControls, useGLTF } from '@react-three/drei';
import * as THREE from 'three';
import { useOmStore } from '../stores/omStore';
import { COLORS, FILTER_CHIPS } from '@robots/utils';
import { getSceneConfig, sendBatchCommand, triggerEstop } from '@robots/api-client';
import type { Device, MapAsset, MapPoint, MapRegion, PointCloudData } from '@robots/shared-types';

interface Projection {
  centerX: number;
  centerY: number;
  scale: number;
}

function project(point: { x: number; y: number; z?: number }, projection: Projection): [number, number, number] {
  return [
    (point.x - projection.centerX) * projection.scale,
    (point.z || 0) * projection.scale,
    (point.y - projection.centerY) * projection.scale,
  ];
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
      <Html position={[0, 0.8, 0]} center distanceFactor={14}>
        <div className="cursor-pointer whitespace-nowrap border border-[rgba(91,183,255,0.3)] bg-[rgba(9,25,41,0.85)] px-1 text-[9px] text-[#E6F6FF]">{device.code}</div>
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

function RegionOverlay({ region, projection }: { region: MapRegion; projection: Projection }) {
  const geometry = useMemo(() => new THREE.ShapeGeometry(new THREE.Shape(region.polygon.map(([x, y]) => new THREE.Vector2((x - projection.centerX) * projection.scale, (y - projection.centerY) * projection.scale)))), [projection, region]);
  const color = region.region_type === 'restricted' ? COLORS.red : region.region_type === 'work' ? COLORS.cyan : COLORS.green;
  return <mesh geometry={geometry} rotation-x={-Math.PI / 2} position={[0, 0.01, 0]}><meshBasicMaterial color={color} transparent opacity={0.18} side={THREE.DoubleSide} /></mesh>;
}

function MapPointMarker({ point, projection }: { point: MapPoint; projection: Projection }) {
  const [x, y, z] = project(point, projection);
  return <group position={[x, Math.max(y, 0) + 0.12, z]}><mesh><coneGeometry args={[0.12, 0.38, 4]} /><meshStandardMaterial color={COLORS.amber} emissive={COLORS.amber} emissiveIntensity={0.3} /></mesh><Html position={[0, 0.45, 0]} center distanceFactor={14}><div className="whitespace-nowrap text-[9px] text-[#FFB33D]">{point.code}</div></Html></group>;
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
    const onMapChanged = () => refresh();
    window.addEventListener('robots:map-changed', onMapChanged);
    return () => window.removeEventListener('robots:map-changed', onMapChanged);
  }, []);

  const filteredDevices = useMemo(() => devices.filter((device) => !filterStatuses.size || filterStatuses.has(device.status)), [devices, filterStatuses]);
  const projection = useMemo(() => calculateProjection(regions, points, devices, pointcloud), [regions, points, devices, pointcloud]);
  const hasPointcloud = Boolean(pointcloud?.points.length);
  const meshAssets = useMemo(() => assets.filter(isRenderableMeshAsset), [assets]);
  const summary = currentView === 'energy'
    ? energyView?.has_data ? `累计能耗 ${energyView.total_energy_kwh ?? '--'} kWh · 当前功率 ${energyView.current_power_kw ?? '--'} kW` : '等待设备上报能耗数据'
    : currentView === 'safety'
      ? `急停 ${safetyView?.global_estop.active ? '已触发' : '未触发'} · 活动告警 ${safetyView?.open_alert_count ?? 0}`
      : hasPointcloud ? `点云快照 ${pointcloud!.total_count} 点` : '等待点云快照';

  const runCommand = async (command: 'pause' | 'release' | 'reset') => {
    try {
      const response = await sendBatchCommand({ command });
      setActionState(`已向 ${response.targets.length} 台设备写入 ${command} 命令队列`);
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
          <Grid args={[40, 40]} cellSize={1} cellColor="rgba(91,183,255,0.15)" sectionSize={5} sectionColor="rgba(91,183,255,0.3)" fadeDistance={50} />
          {meshAssets.map((asset) => <MapMesh key={asset.id} asset={asset} projection={projection} />)}
          {hasPointcloud ? <PointCloud pointcloud={pointcloud!} projection={projection} /> : <Html center position={[0, 2, 0]}><div className="whitespace-nowrap text-[12px] text-[#79A3BF]">等待外部建图网关上传点云</div></Html>}
          {regions.map((region) => <RegionOverlay key={region.id} region={region} projection={projection} />)}
          {points.map((point) => <MapPointMarker key={point.id} point={point} projection={projection} />)}
          {filteredDevices.map((device) => <DeviceMarker key={device.id} device={device} projection={projection} onClick={() => selectDevice(device.id)} />)}
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
