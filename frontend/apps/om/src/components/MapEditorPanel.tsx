/** O&M 3D voxel-map editor. Geometry is persisted through the map API. */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronUp, Layers3, Map, MapPin, MousePointer2, Route, Save, SlidersHorizontal, Square, Trash2, Undo2, X } from 'lucide-react';
import { createPathsBatch, createPoint, createRegion, deletePath, deletePoint, deleteRegion, getSceneConfig, updateGridConfig, updatePath, updatePoint, updateRegion } from '@robots/api-client';
import { VOXEL_CELL_SIZE_M, VOXEL_CELL_VOLUME_M3, type GridMapConfig, type MapPath, type MapPoint, type MapRegion } from '@robots/shared-types';
import { DEFAULT_GRID_CONFIG, getDisplayGridConfig, useMapEditorStore } from '../stores/mapEditorStore';
import { createRegionSelectionUnion } from '../utils/voxelSelection';

const DEFAULT_COLOR = '#2FD7FF';
const COLOR_SWATCHES = ['#2FD7FF', '#34DF9A', '#FFB33D', '#FF5C6D', '#B56CFF'];
const POINT_TYPES = [
  { value: 'work', label: '作业点' },
  { value: 'loading', label: '装载点' },
  { value: 'unloading', label: '卸载点' },
  { value: 'parking', label: '停车点' },
  { value: 'standby', label: '待机点' },
  { value: 'charge', label: '充电点' },
];
const REGION_TYPES: Array<{ value: MapRegion['region_type']; label: string }> = [
  { value: 'work', label: '作业区' },
  { value: 'restricted', label: '禁行区' },
  { value: 'stack', label: '堆场' },
  { value: 'parking', label: '停车区' },
];

interface PointDraft {
  name: string;
  pointType: string;
  z: number;
  color: string;
}

interface RegionDraft {
  name: string;
  regionType: MapRegion['region_type'];
  minZ: number;
  maxZ: number;
  color: string;
}

interface PathDraft {
  name: string;
  direction: MapPath['direction'];
  minWidthM: number;
  maxSlopePercent: number;
  deviceTypes: string;
  status: MapPath['status'];
}

function createMapCode(prefix: 'P' | 'R' | 'PATH'): string {
  const cryptoApi = globalThis.crypto;
  if (!cryptoApi?.getRandomValues) {
    throw new Error('当前浏览器不支持安全随机数，请升级浏览器后重试');
  }
  const bytes = new Uint8Array(8);
  cryptoApi.getRandomValues(bytes);
  const suffix = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('').toUpperCase();
  return `${prefix}-${suffix}`;
}

export function MapEditorPanel() {
  const {
    isOpen, mode, gridConfig, editLayer, regionHeightCells, pointCell, regionSelections, roadSegments, pendingRoadStart, editingPathId, pathCells, selectedEntity,
    setOpen, setMode, setGridConfig, setEditLayer, setRegionHeightCells, selectEntity, clearDraft, clearPathDraft, clearRegionSelections, beginRoadNetwork, beginPathGeometryEdit, setPathPreviewWidthM, undoLastPathInput, undoLastRegionSelection,
  } = useMapEditorStore();
  const [regions, setRegions] = useState<MapRegion[]>([]);
  const [points, setPoints] = useState<MapPoint[]>([]);
  const [paths, setPaths] = useState<MapPath[]>([]);
  const [message, setMessage] = useState('');
  const [pointDraft, setPointDraft] = useState<PointDraft>({ name: '', pointType: 'work', z: 0, color: DEFAULT_COLOR });
  const [regionDraft, setRegionDraft] = useState<RegionDraft>({ name: '', regionType: 'work', minZ: 0, maxZ: 0.5, color: DEFAULT_COLOR });
  const [pathDraft, setPathDraft] = useState<PathDraft>({ name: '', direction: 'bidirectional', minWidthM: 1, maxSlopePercent: 10, deviceTypes: '', status: 'active' });
  const [gridDraft, setGridDraft] = useState<GridMapConfig>(gridConfig || DEFAULT_GRID_CONFIG);
  const [saving, setSaving] = useState(false);
  const [savingGrid, setSavingGrid] = useState(false);
  const displayGridConfig = useMemo(() => getDisplayGridConfig(gridConfig), [gridConfig]);

  const previewGridChange = (change: Partial<GridMapConfig>) => {
    const next = { ...gridDraft, ...change };
    setGridDraft(next);
    setGridConfig(next);
  };

  const refresh = useCallback(async () => {
    const scene = await getSceneConfig();
    setRegions(scene.regions);
    setPoints(scene.points);
    setPaths(scene.paths || []);
    setGridConfig(scene.grid_config || DEFAULT_GRID_CONFIG);
  }, [setGridConfig]);

  useEffect(() => {
    setGridDraft(gridConfig);
  }, [gridConfig]);

  useEffect(() => {
    if (!isOpen) return;
    refresh().catch((error) => setMessage(error instanceof Error ? error.message : '读取地图失败'));
    const onMapChanged = () => refresh().catch((error) => setMessage(error instanceof Error ? error.message : '读取地图失败'));
    window.addEventListener('robots:map-changed', onMapChanged);
    return () => window.removeEventListener('robots:map-changed', onMapChanged);
  }, [isOpen, refresh]);

  const selectedPoint = useMemo(
    () => selectedEntity?.kind === 'point' ? points.find((point) => point.id === selectedEntity.id) ?? null : null,
    [points, selectedEntity],
  );
  const selectedRegion = useMemo(
    () => selectedEntity?.kind === 'region' ? regions.find((region) => region.id === selectedEntity.id) ?? null : null,
    [regions, selectedEntity],
  );
  const selectedPath = useMemo(
    () => {
      const pathId = editingPathId || (selectedEntity?.kind === 'path' ? selectedEntity.id : null);
      return pathId ? paths.find((path) => path.id === pathId) ?? null : null;
    },
    [editingPathId, paths, selectedEntity],
  );
  const selectionUnion = useMemo(() => createRegionSelectionUnion(regionSelections), [regionSelections]);

  useEffect(() => {
    if (selectedPoint) setPointDraft({ name: selectedPoint.name, pointType: selectedPoint.point_type, z: selectedPoint.z, color: selectedPoint.color || DEFAULT_COLOR });
  }, [selectedPoint]);
  useEffect(() => {
    if (selectedRegion) setRegionDraft({ name: selectedRegion.name, regionType: selectedRegion.region_type, minZ: selectedRegion.min_z, maxZ: selectedRegion.max_z, color: selectedRegion.color || DEFAULT_COLOR });
  }, [selectedRegion]);
  useEffect(() => {
    if (selectedPath) setPathDraft({
      name: selectedPath.name,
      direction: selectedPath.direction,
      minWidthM: selectedPath.min_width_m,
      maxSlopePercent: selectedPath.max_slope_percent,
      deviceTypes: selectedPath.device_types.join(', '),
      status: selectedPath.status,
    });
  }, [selectedPath]);
  useEffect(() => {
    setPathPreviewWidthM(pathDraft.minWidthM);
  }, [pathDraft.minWidthM, setPathPreviewWidthM]);
  const notifyMapChanged = () => window.dispatchEvent(new Event('robots:map-changed'));
  const startPoint = () => {
    setPointDraft({ name: '', pointType: 'work', z: displayGridConfig.origin_z + (editLayer + 0.5) * displayGridConfig.cell_height, color: DEFAULT_COLOR });
    setMessage('');
    setMode('point');
  };
  const startRegion = () => {
    const minZ = displayGridConfig.origin_z + editLayer * displayGridConfig.cell_height;
    const mapTopZ = gridConfig.origin_z + gridConfig.vertical_layers * gridConfig.cell_height;
    setRegionDraft({ name: '', regionType: 'work', minZ, maxZ: Math.min(mapTopZ, minZ + regionHeightCells * displayGridConfig.cell_height), color: DEFAULT_COLOR });
    setMessage('');
    setMode('region');
  };
  const startPath = () => {
    setPathDraft({ name: '', direction: 'bidirectional', minWidthM: displayGridConfig.cell_length, maxSlopePercent: 10, deviceTypes: '', status: 'active' });
    setPathPreviewWidthM(displayGridConfig.cell_length);
    setMessage('');
    beginRoadNetwork();
  };
  const editPathGeometry = () => {
    if (!selectedPath) return;
    beginPathGeometryEdit(selectedPath.id);
    setMessage('请依次点击新的道路起点和终点；第二次点击后即可保存替换。');
  };

  const saveGrid = async () => {
    setSavingGrid(true);
    setMessage('');
    try {
      const saved = await updateGridConfig({
        ...gridDraft,
        cell_volume_m3: VOXEL_CELL_VOLUME_M3,
        cell_length: VOXEL_CELL_SIZE_M,
        cell_width: VOXEL_CELL_SIZE_M,
        cell_height: VOXEL_CELL_SIZE_M,
      });
      setGridConfig(saved);
      clearDraft();
      notifyMapChanged();
      setMessage('三维栅格设置已保存');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '三维栅格设置保存失败');
    } finally {
      setSavingGrid(false);
    }
  };

  const savePoint = async () => {
    if (!pointDraft.name.trim()) {
      setMessage('请填写点位名称');
      return;
    }
    if (!pointCell && !selectedPoint) {
      setMessage('请先在当前高度层选择一个体素');
      return;
    }
    setSaving(true);
    try {
      if (selectedPoint) {
        const { id, ...point } = selectedPoint;
        await updatePoint(id, { ...point, name: pointDraft.name.trim(), point_type: pointDraft.pointType, z: pointDraft.z, color: pointDraft.color });
        setMessage('点位设置已保存');
      } else if (pointCell) {
        const point = await createPoint({
          code: createMapCode('P'),
          name: pointDraft.name.trim(),
          point_type: pointDraft.pointType,
          x: pointCell.x + pointCell.sizeX / 2,
          y: pointCell.y + pointCell.sizeY / 2,
          z: pointCell.z + pointCell.sizeZ / 2,
          process_type: null,
          device_types: [],
          stage: null,
          qrcode_id: null,
          qrcode_type: null,
          color: pointDraft.color,
        });
        selectEntity({ kind: 'point', id: point.id });
        setMessage('点位已添加');
      }
      await refresh();
      notifyMapChanged();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '点位保存失败');
    } finally {
      setSaving(false);
    }
  };

  const saveRegion = async () => {
    if (!regionDraft.name.trim()) {
      setMessage('请填写区域名称');
      return;
    }
    if (regionDraft.maxZ <= regionDraft.minZ) {
      setMessage('区域顶部高度必须大于底部高度');
      return;
    }
    if (!regionSelections.length && !selectedRegion) {
      setMessage('请先在当前高度层拖拽框选体素');
      return;
    }
    setSaving(true);
    try {
      if (selectedRegion) {
        const { id, ...region } = selectedRegion;
        const volumes = region.volumes.map((volume) => ({ ...volume, min_z: regionDraft.minZ, max_z: regionDraft.maxZ }));
        const primaryVolume = volumes[0];
        await updateRegion(id, { ...region, name: regionDraft.name.trim(), region_type: regionDraft.regionType, polygon: primaryVolume.polygon, min_z: primaryVolume.min_z, max_z: primaryVolume.max_z, volumes, color: regionDraft.color });
        setMessage('区域设置已保存');
      } else if (selectionUnion.volumes.length) {
        const volumes = selectionUnion.volumes;
        const primaryVolume = volumes[0];
        const region = await createRegion({
          code: createMapCode('R'),
          name: regionDraft.name.trim(),
          region_type: regionDraft.regionType,
          polygon: primaryVolume.polygon,
          min_z: primaryVolume.min_z,
          max_z: primaryVolume.max_z,
          volumes,
          stage: null,
          color: regionDraft.color,
        });
        selectEntity({ kind: 'region', id: region.id });
        setMessage('区域已添加');
      }
      await refresh();
      notifyMapChanged();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '区域保存失败');
    } finally {
      setSaving(false);
    }
  };

  const savePath = async () => {
    if (!pathDraft.name.trim()) {
      setMessage(selectedPath ? '请填写道路名称' : '请填写道路网络名称');
      return;
    }
    const pathPoints = pathCells.length
      ? pathCells.map((cell) => [cell.x + cell.sizeX / 2, cell.y + cell.sizeY / 2, cell.z] as [number, number, number])
      : selectedPath?.points || [];
    if (selectedPath && pathPoints.length !== 2) {
      setMessage('道路必须包含起点和终点两个端点');
      return;
    }
    if (!selectedPath && !roadSegments.length) {
      setMessage('请先依次点击道路起点和终点，至少完成一条道路');
      return;
    }
    const deviceTypes = pathDraft.deviceTypes.split(',').map((value) => value.trim()).filter(Boolean);
    setSaving(true);
    try {
      if (selectedPath) {
        const saved = await updatePath(selectedPath.id, {
          code: selectedPath.code,
          name: pathDraft.name.trim(),
          points: pathPoints,
          direction: pathDraft.direction,
          min_width_m: pathDraft.minWidthM,
          max_slope_percent: pathDraft.maxSlopePercent,
          device_types: deviceTypes,
          status: pathDraft.status,
        });
        selectEntity({ kind: 'path', id: saved.id });
        clearPathDraft();
        setMessage('道路已保存');
      } else {
        const networkName = pathDraft.name.trim();
        const saved = await createPathsBatch(roadSegments.map((segment, index) => ({
          code: createMapCode('PATH'),
          name: roadSegments.length === 1 ? networkName : `${networkName} ${index + 1}`,
          points: segment.map((cell) => [cell.x + cell.sizeX / 2, cell.y + cell.sizeY / 2, cell.z] as [number, number, number]),
          direction: pathDraft.direction,
          min_width_m: pathDraft.minWidthM,
          max_slope_percent: pathDraft.maxSlopePercent,
          device_types: deviceTypes,
          status: pathDraft.status,
        })));
        clearPathDraft();
        setMessage(`已保存 ${saved.length} 条道路；相邻端点已组成道路网络`);
      }
      await refresh();
      notifyMapChanged();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '道路保存失败');
    } finally {
      setSaving(false);
    }
  };

  const deleteSelected = async () => {
    const selected = selectedPoint || selectedRegion || selectedPath;
    if (!selected || !window.confirm(`删除“${selected.name}”后不可恢复，是否继续？`)) return;
    setSaving(true);
    try {
      if (selectedPoint) await deletePoint(selectedPoint.id);
      if (selectedRegion) await deleteRegion(selectedRegion.id);
      if (selectedPath) await deletePath(selectedPath.id);
      selectEntity(null);
      await refresh();
      notifyMapChanged();
      setMessage('已删除');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '删除失败');
    } finally {
      setSaving(false);
    }
  };

  if (!isOpen) {
    return <button onClick={() => setOpen(true)} className="flex items-center gap-1 text-[11px] text-[#2FD7FF] hover:text-[#34DF9A]"><Map size={13} /> 地图编辑</button>;
  }

  const editingPoint = mode === 'point' || Boolean(selectedPoint);
  const editingRegion = mode === 'region' || Boolean(selectedRegion);
  const editingPath = mode === 'path' || Boolean(selectedPath);
  const layerZ = displayGridConfig.origin_z + editLayer * displayGridConfig.cell_height;
  const pathSelectionText = editingPathId
    ? pathCells.length
      ? `正在替换道路端点：已选择 ${pathCells.length}/2 个端点`
      : '请点击新的道路起点'
    : pendingRoadStart
      ? `已选择道路起点；下一次点击为终点（已完成 ${roadSegments.length} 条）`
      : roadSegments.length
        ? `已完成 ${roadSegments.length} 条道路；下一次点击开始新道路`
        : '请点击道路起点，再点击终点完成第一条道路';
  const selectionText = mode === 'path'
    ? pathSelectionText
    : pointCell
    ? `显示单元 X ${pointCell.x.toFixed(2)}，Y ${pointCell.y.toFixed(2)}，Z ${pointCell.z.toFixed(2)}，覆盖 ${Math.round(pointCell.sizeX / VOXEL_CELL_SIZE_M) * Math.round(pointCell.sizeY / VOXEL_CELL_SIZE_M) * Math.round(pointCell.sizeZ / VOXEL_CELL_SIZE_M)} 个最小体素`
    : regionSelections.length
      ? `已选 ${selectionUnion.displayVoxelCount} 个显示单元，覆盖 ${selectionUnion.baseVoxelCount} 个最小体素`
      : selectedPoint?.name || selectedRegion?.name || selectedPath?.name || '未选择';

  return (
    <aside className="fixed top-[64px] bottom-[116px] right-3 z-40 flex w-[min(360px,calc(100vw-24px))] flex-col border border-[rgba(91,183,255,0.38)] bg-[rgba(8,22,36,0.96)] shadow-2xl shadow-black/40">
      <div className="flex items-center justify-between border-b border-[rgba(91,183,255,0.22)] px-3 py-2">
        <div className="flex items-center gap-2"><Layers3 size={15} className="text-[#2FD7FF]" /><h2 className="text-[13px] font-medium text-[#E6F6FF]">三维地图编辑</h2></div>
        <button onClick={() => setOpen(false)} title="关闭地图编辑" aria-label="关闭地图编辑" className="grid h-7 w-7 place-items-center text-[#79A3BF] hover:text-[#E6F6FF]"><X size={16} /></button>
      </div>
      <div className="flex border-b border-[rgba(91,183,255,0.18)] p-1">
        <ToolButton active={mode === 'select'} icon={<MousePointer2 size={15} />} label="选择" onClick={() => setMode('select')} />
        <ToolButton active={mode === 'point'} icon={<MapPin size={15} />} label="点位" onClick={startPoint} />
        <ToolButton active={mode === 'region'} icon={<Square size={15} />} label="区域" onClick={startRegion} />
        <ToolButton active={mode === 'path'} icon={<Route size={15} />} label="路径" onClick={startPath} />
      </div>
      <div className="flex-1 overflow-y-auto p-3">
        <EditorSection title="三维栅格">
          <div className="grid grid-cols-2 gap-x-2">
            <ReadOnlyField label="单格边长（米）" value={VOXEL_CELL_SIZE_M.toFixed(2)} />
            <ReadOnlyField label="单格体积（立方米）" value={VOXEL_CELL_VOLUME_M3.toFixed(6)} />
            <ReadOnlyField label="体素形态" value="正立方体" />
            <RangeField label="显示单元倍率" value={gridDraft.display_voxel_multiplier} min={1} max={32} step={1} onChange={(display_voxel_multiplier) => previewGridChange({ display_voxel_multiplier: Math.round(display_voxel_multiplier) })} />
            <ReadOnlyField label="显示单元边长（米）" value={displayGridConfig.cell_length.toFixed(2)} />
            <RangeField label="垂直层数" value={gridDraft.vertical_layers} min={1} max={200} step={1} onChange={(vertical_layers) => previewGridChange({ vertical_layers: Math.round(vertical_layers) })} />
            <RangeField label="显示长度（米）" value={gridDraft.extent_length} min={1} max={1000} step={0.5} onChange={(extent_length) => previewGridChange({ extent_length })} />
            <RangeField label="显示宽度（米）" value={gridDraft.extent_width} min={1} max={1000} step={0.5} onChange={(extent_width) => previewGridChange({ extent_width })} />
            <RangeField label="原点 X（米）" value={gridDraft.origin_x} min={-500} max={500} step={0.05} onChange={(origin_x) => previewGridChange({ origin_x })} />
            <RangeField label="原点 Y（米）" value={gridDraft.origin_y} min={-500} max={500} step={0.05} onChange={(origin_y) => previewGridChange({ origin_y })} />
            <RangeField label="原点高度（米）" value={gridDraft.origin_z} min={-10} max={50} step={0.05} onChange={(origin_z) => previewGridChange({ origin_z })} />
            <RangeField label="线条粗细（米）" value={gridDraft.line_thickness} min={0.001} max={0.05} step={0.001} onChange={(line_thickness) => previewGridChange({ line_thickness })} />
            <RangeField label="线条透明度" value={gridDraft.opacity} min={0.05} max={1} step={0.01} onChange={(opacity) => previewGridChange({ opacity })} />
          </div>
          <ColorPicker label="线条颜色" value={gridDraft.line_color} onChange={(line_color) => previewGridChange({ line_color })} />
          <div className="mt-3"><PrimaryButton label="保存栅格设置" icon={<Save size={14} />} onClick={saveGrid} disabled={savingGrid} /></div>
        </EditorSection>

        <EditorSection title="当前编辑层">
          <div className="flex items-center justify-between gap-2">
            <button type="button" title="降低一层" aria-label="降低一层" onClick={() => setEditLayer(editLayer - 1)} disabled={editLayer === 0} className="grid h-8 w-8 place-items-center border border-[rgba(91,183,255,0.28)] text-[#aecce0] disabled:opacity-35"><ChevronDown size={15} /></button>
            <div className="min-w-0 flex-1 text-center"><p className="text-[12px] text-[#E6F6FF]">第 {editLayer + 1} 层</p><p className="text-[10px] text-[#79A3BF]">底高 {layerZ.toFixed(2)} 米</p></div>
            <button type="button" title="升高一层" aria-label="升高一层" onClick={() => setEditLayer(editLayer + 1)} disabled={editLayer >= displayGridConfig.vertical_layers - 1} className="grid h-8 w-8 place-items-center border border-[rgba(91,183,255,0.28)] text-[#aecce0] disabled:opacity-35"><ChevronUp size={15} /></button>
          </div>
          {mode === 'region' && <RangeField label="新区域高度（显示层）" value={regionHeightCells} min={1} max={displayGridConfig.vertical_layers - editLayer} step={1} onChange={setRegionHeightCells} />}
        </EditorSection>

        <div className="mb-3 flex items-center gap-2 border-l-2 border-[#2FD7FF] bg-[rgba(47,215,255,0.07)] px-2 py-1.5 text-[11px] text-[#aecce0]"><span className="min-w-0 flex-1 truncate">{selectionText}</span>{mode === 'region' && regionSelections.length > 0 && <div className="flex shrink-0"><button type="button" title="撤销最后一次框选" aria-label="撤销最后一次框选" onClick={undoLastRegionSelection} className="grid h-6 w-6 place-items-center text-[#79A3BF] hover:text-[#E6F6FF]"><Undo2 size={13} /></button><button type="button" title="清除已选体素" aria-label="清除已选体素" onClick={clearRegionSelections} className="grid h-6 w-6 place-items-center text-[#79A3BF] hover:text-[#FF5C6D]"><Trash2 size={13} /></button></div>}{mode === 'path' && (editingPathId || pendingRoadStart || roadSegments.length > 0) && <div className="flex shrink-0"><button type="button" title={editingPathId ? '撤销最后一个道路端点' : pendingRoadStart ? '撤销道路起点' : '撤销最后一条道路'} aria-label={editingPathId ? '撤销最后一个道路端点' : pendingRoadStart ? '撤销道路起点' : '撤销最后一条道路'} onClick={undoLastPathInput} className="grid h-6 w-6 place-items-center text-[#79A3BF] hover:text-[#E6F6FF]"><Undo2 size={13} /></button><button type="button" title="清除道路草稿" aria-label="清除道路草稿" onClick={clearPathDraft} className="grid h-6 w-6 place-items-center text-[#79A3BF] hover:text-[#FF5C6D]"><Trash2 size={13} /></button></div>}</div>

        {editingPoint && <EditorSection title={selectedPoint ? '点位设置' : '新建点位'}>
          <TextField label="名称" value={pointDraft.name} onChange={(name) => setPointDraft((draft) => ({ ...draft, name }))} placeholder="点位名称" />
          <label className="mb-3 block text-[11px] text-[#79A3BF]">类型
            <select value={pointDraft.pointType} onChange={(event) => setPointDraft((draft) => ({ ...draft, pointType: event.target.value }))} className="mt-1 h-8 w-full border border-[rgba(91,183,255,0.28)] bg-[#091929] px-2 text-[12px] text-[#E6F6FF]">
              {!POINT_TYPES.some((type) => type.value === pointDraft.pointType) && <option value={pointDraft.pointType}>其他已保存类型</option>}
              {POINT_TYPES.map((type) => <option key={type.value} value={type.value}>{type.label}</option>)}
            </select>
          </label>
          {selectedPoint && <RangeField label="高度（米）" value={pointDraft.z} min={gridConfig.origin_z} max={gridConfig.origin_z + gridConfig.vertical_layers * gridConfig.cell_height} step={VOXEL_CELL_SIZE_M} onChange={(z) => setPointDraft((draft) => ({ ...draft, z }))} />}
          <ColorPicker label="标记颜色" value={pointDraft.color} onChange={(color) => setPointDraft((draft) => ({ ...draft, color }))} />
          <div className="mt-3 flex gap-2"><PrimaryButton label="保存点位" icon={<Save size={14} />} onClick={savePoint} disabled={saving} />{selectedPoint && <DeleteButton onClick={deleteSelected} disabled={saving} />}</div>
        </EditorSection>}

        {editingRegion && <EditorSection title={selectedRegion ? '区域设置' : '新建区域'}>
          <TextField label="名称" value={regionDraft.name} onChange={(name) => setRegionDraft((draft) => ({ ...draft, name }))} placeholder="区域名称" />
          <label className="mb-3 block text-[11px] text-[#79A3BF]">类型
            <select value={regionDraft.regionType} onChange={(event) => setRegionDraft((draft) => ({ ...draft, regionType: event.target.value as MapRegion['region_type'] }))} className="mt-1 h-8 w-full border border-[rgba(91,183,255,0.28)] bg-[#091929] px-2 text-[12px] text-[#E6F6FF]">
              {REGION_TYPES.map((type) => <option key={type.value} value={type.value}>{type.label}</option>)}
            </select>
          </label>
          {selectedRegion && <div className="grid grid-cols-2 gap-x-2"><RangeField label="底部高度（米）" value={regionDraft.minZ} min={gridConfig.origin_z} max={gridConfig.origin_z + gridConfig.vertical_layers * gridConfig.cell_height - VOXEL_CELL_SIZE_M} step={VOXEL_CELL_SIZE_M} onChange={(minZ) => setRegionDraft((draft) => ({ ...draft, minZ }))} /><RangeField label="顶部高度（米）" value={regionDraft.maxZ} min={gridConfig.origin_z + VOXEL_CELL_SIZE_M} max={gridConfig.origin_z + gridConfig.vertical_layers * gridConfig.cell_height} step={VOXEL_CELL_SIZE_M} onChange={(maxZ) => setRegionDraft((draft) => ({ ...draft, maxZ }))} /></div>}
          <ColorPicker label="区域颜色" value={regionDraft.color} onChange={(color) => setRegionDraft((draft) => ({ ...draft, color }))} />
          <div className="mt-3 flex gap-2"><PrimaryButton label="保存区域" icon={<Save size={14} />} onClick={saveRegion} disabled={saving} />{selectedRegion && <DeleteButton onClick={deleteSelected} disabled={saving} />}</div>
        </EditorSection>}

        {editingPath && <EditorSection title={selectedPath ? '道路设置' : '新建道路网络'}>
          {!selectedPath && <p className="mb-3 text-[11px] leading-5 text-[#79A3BF]">每条道路只需依次点击起点和终点。完成一条道路后，下一次点击会自动开始新道路；相邻端点可连通。</p>}
          {editingPathId && <p className="mb-3 text-[11px] leading-5 text-[#79A3BF]">重新点击两个端点即可替换此道路的几何位置。</p>}
          <TextField label={selectedPath ? '道路名称' : '道路网络名称'} value={pathDraft.name} onChange={(name) => setPathDraft((draft) => ({ ...draft, name }))} placeholder={selectedPath ? '道路名称' : '道路网络名称'} />
          <label className="mb-3 block text-[11px] text-[#79A3BF]">通行方向
            <select value={pathDraft.direction} onChange={(event) => setPathDraft((draft) => ({ ...draft, direction: event.target.value as MapPath['direction'] }))} className="mt-1 h-8 w-full border border-[rgba(91,183,255,0.28)] bg-[#091929] px-2 text-[12px] text-[#E6F6FF]">
              <option value="bidirectional">双向通行</option>
              <option value="forward">按路径方向通行</option>
              <option value="reverse">按反向通行</option>
            </select>
          </label>
          <div className="grid grid-cols-2 gap-x-2"><RangeField label="最小净宽（米）" value={pathDraft.minWidthM} min={VOXEL_CELL_SIZE_M} max={20} step={VOXEL_CELL_SIZE_M} onChange={(minWidthM) => setPathDraft((draft) => ({ ...draft, minWidthM }))} /><RangeField label="最大坡度（%）" value={pathDraft.maxSlopePercent} min={0} max={100} step={0.5} onChange={(maxSlopePercent) => setPathDraft((draft) => ({ ...draft, maxSlopePercent }))} /></div>
          <TextField label="适用设备类型" value={pathDraft.deviceTypes} onChange={(deviceTypes) => setPathDraft((draft) => ({ ...draft, deviceTypes }))} placeholder="多个类型以逗号分隔" />
          <label className="mb-3 block text-[11px] text-[#79A3BF]">启用状态
            <select value={pathDraft.status} onChange={(event) => setPathDraft((draft) => ({ ...draft, status: event.target.value as MapPath['status'] }))} className="mt-1 h-8 w-full border border-[rgba(91,183,255,0.28)] bg-[#091929] px-2 text-[12px] text-[#E6F6FF]">
              <option value="active">启用</option>
              <option value="disabled">停用</option>
            </select>
          </label>
          <div className="mt-3 flex gap-2"><PrimaryButton label={selectedPath ? '保存道路' : '保存道路网络'} icon={<Save size={14} />} onClick={savePath} disabled={saving} />{selectedPath && <><button type="button" onClick={editPathGeometry} disabled={saving} className="flex h-8 items-center gap-1 border border-[rgba(91,183,255,0.38)] px-3 text-[12px] text-[#aecce0] hover:border-[#2FD7FF] hover:text-[#E6F6FF] disabled:opacity-45"><Route size={14} />重新选择端点</button><DeleteButton onClick={deleteSelected} disabled={saving} /></>}</div>
        </EditorSection>}

        <ObjectList title={`点位 ${points.length}`} items={points} selectedId={selectedPoint?.id} onSelect={(id) => selectEntity({ kind: 'point', id })} />
        <ObjectList title={`区域 ${regions.length}`} items={regions} selectedId={selectedRegion?.id} onSelect={(id) => selectEntity({ kind: 'region', id })} />
        <PathList paths={paths} selectedId={selectedPath?.id} onSelect={(id) => selectEntity({ kind: 'path', id })} />
        {message && <p className="mt-3 text-[11px] text-[#FFB33D]" role="status">{message}</p>}
      </div>
    </aside>
  );
}

function ToolButton({ active, icon, label, onClick }: { active: boolean; icon: React.ReactNode; label: string; onClick: () => void }) {
  return <button onClick={onClick} title={label} aria-label={label} className={`flex h-8 flex-1 items-center justify-center gap-1 border text-[11px] ${active ? 'border-[#2FD7FF] bg-[rgba(47,215,255,0.15)] text-[#2FD7FF]' : 'border-transparent text-[#79A3BF] hover:text-[#E6F6FF]'}`}>{icon}<span>{label}</span></button>;
}

function EditorSection({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="mb-3 border border-[rgba(91,183,255,0.22)] p-3"><h3 className="mb-3 flex items-center gap-1.5 text-[12px] font-medium text-[#E6F6FF]"><SlidersHorizontal size={13} className="text-[#2FD7FF]" />{title}</h3>{children}</section>;
}

function TextField({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (value: string) => void; placeholder: string }) {
  return <label className="mb-3 block text-[11px] text-[#79A3BF]">{label}<input value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} className="mt-1 h-8 w-full border border-[rgba(91,183,255,0.28)] bg-[#091929] px-2 text-[12px] text-[#E6F6FF] outline-none focus:border-[#2FD7FF]" /></label>;
}

function RangeField({ label, value, onChange, min, max, step }: { label: string; value: number; onChange: (value: number) => void; min: number; max: number; step: number }) {
  const bounded = Math.min(max, Math.max(min, Number.isFinite(value) ? value : min));
  const precision = step < 0.01 ? 3 : step < 1 ? 2 : 0;
  return <label className="mb-3 block text-[11px] text-[#79A3BF]"><span className="flex items-center justify-between gap-2"><span>{label}</span><output className="font-mono text-[#E6F6FF]">{bounded.toFixed(precision)}</output></span><input type="range" value={bounded} min={min} max={max} step={step} onChange={(event) => onChange(Number(event.target.value))} className="mt-1 h-5 w-full accent-[#2FD7FF]" /></label>;
}

function ReadOnlyField({ label, value }: { label: string; value: string }) {
  return <label className="mb-3 block text-[11px] text-[#79A3BF]">{label}<span className="mt-1 flex h-8 items-center border border-[rgba(91,183,255,0.18)] bg-[rgba(5,11,19,0.55)] px-2 text-[12px] text-[#aecce0]">{value}</span></label>;
}

function ColorPicker({ label, value, onChange }: { label: string; value: string; onChange: (color: string) => void }) {
  return <div><span className="block text-[11px] text-[#79A3BF]">{label}</span><div className="mt-1 flex items-center gap-2">{COLOR_SWATCHES.map((color) => <button key={color} type="button" onClick={() => onChange(color)} title={color} aria-label={`选择颜色 ${color}`} className={`h-6 w-6 border ${value === color ? 'border-white' : 'border-transparent'}`} style={{ backgroundColor: color }} />)}<input type="color" value={value} onChange={(event) => onChange(event.target.value.toUpperCase())} title="自定义颜色" aria-label="自定义颜色" className="h-6 w-6 cursor-pointer border border-[rgba(91,183,255,0.28)] bg-transparent p-0" /></div></div>;
}

function PrimaryButton({ label, icon, onClick, disabled }: { label: string; icon: React.ReactNode; onClick: () => void; disabled: boolean }) {
  return <button onClick={onClick} disabled={disabled} className="flex h-8 items-center gap-1 border border-[#2FD7FF] bg-[rgba(47,215,255,0.12)] px-3 text-[12px] text-[#2FD7FF] hover:bg-[rgba(47,215,255,0.2)] disabled:opacity-45">{icon}{label}</button>;
}

function DeleteButton({ onClick, disabled }: { onClick: () => void; disabled: boolean }) {
  return <button onClick={onClick} disabled={disabled} title="删除" aria-label="删除" className="grid h-8 w-8 place-items-center border border-[#FF5C6D] text-[#FF5C6D] hover:bg-[rgba(255,92,109,0.12)] disabled:opacity-45"><Trash2 size={14} /></button>;
}

function ObjectList({ title, items, selectedId, onSelect }: { title: string; items: Array<MapPoint | MapRegion>; selectedId?: string; onSelect: (id: string) => void }) {
  return <section className="mb-3 border-t border-[rgba(91,183,255,0.18)] pt-3"><h3 className="mb-1.5 text-[11px] font-medium text-[#79A3BF]">{title}</h3>{items.length ? <div className="space-y-1">{items.map((item) => <button key={item.id} onClick={() => onSelect(item.id)} className={`flex h-7 w-full items-center gap-2 px-1.5 text-left text-[11px] ${selectedId === item.id ? 'bg-[rgba(47,215,255,0.13)] text-[#E6F6FF]' : 'text-[#aecce0] hover:bg-[rgba(91,183,255,0.08)]'}`}><span className="h-2 w-2 shrink-0" style={{ backgroundColor: item.color || DEFAULT_COLOR }} /><span className="truncate">{item.name}</span></button>)}</div> : <p className="text-[11px] text-[#5A7A92]">暂无记录</p>}</section>;
}

function PathList({ paths, selectedId, onSelect }: { paths: MapPath[]; selectedId?: string; onSelect: (id: string) => void }) {
  return <section className="mb-3 border-t border-[rgba(91,183,255,0.18)] pt-3"><h3 className="mb-1.5 text-[11px] font-medium text-[#79A3BF]">路径 {paths.length}</h3>{paths.length ? <div className="space-y-1">{paths.map((path) => <button key={path.id} onClick={() => onSelect(path.id)} className={`flex min-h-8 w-full items-center gap-2 px-1.5 py-1 text-left text-[11px] ${selectedId === path.id ? 'bg-[rgba(47,215,255,0.13)] text-[#E6F6FF]' : 'text-[#aecce0] hover:bg-[rgba(91,183,255,0.08)]'}`}><span className={`h-2 w-2 shrink-0 ${path.status === 'active' ? 'bg-[#34DF9A]' : 'bg-[#5A7A92]'}`} /><span className="min-w-0 flex-1 truncate">{path.name}</span><span className="shrink-0 text-[10px] text-[#79A3BF]">{path.points.length} 点</span></button>)}</div> : <p className="text-[11px] text-[#5A7A92]">暂无记录</p>}</section>;
}
