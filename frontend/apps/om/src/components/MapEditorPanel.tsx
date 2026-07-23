/** Map annotations are placed from the visible raster instead of typed coordinates. */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Layers3, Map, MapPin, MousePointer2, Save, Square, Trash2, X } from 'lucide-react';
import { createPoint, createRegion, deletePoint, deleteRegion, getSceneConfig, updatePoint, updateRegion } from '@robots/api-client';
import type { MapPoint, MapRegion } from '@robots/shared-types';
import { useMapEditorStore } from '../stores/mapEditorStore';

const DEFAULT_COLOR = '#2FD7FF';
const COLOR_SWATCHES = ['#2FD7FF', '#34DF9A', '#FFB33D', '#FF5C6D', '#B56CFF'];
const POINT_TYPES = ['work', 'loading', 'unloading', 'charge'];
const REGION_TYPES: Array<{ value: MapRegion['region_type']; label: string }> = [
  { value: 'work', label: '作业区' },
  { value: 'restricted', label: '禁行区' },
  { value: 'stack', label: '堆场' },
  { value: 'parking', label: '停车区' },
];

interface PointDraft {
  name: string;
  pointType: string;
  color: string;
}

interface RegionDraft {
  name: string;
  regionType: MapRegion['region_type'];
  color: string;
}

function createMapCode(prefix: 'P' | 'R'): string {
  return `${prefix}-${crypto.randomUUID().slice(0, 8).toUpperCase()}`;
}

function getRegionPolygon(selection: NonNullable<ReturnType<typeof useMapEditorStore.getState>['regionSelection']>): number[][] {
  const minX = Math.min(selection.start.x, selection.end.x);
  const minY = Math.min(selection.start.y, selection.end.y);
  const maxX = Math.max(selection.start.x, selection.end.x) + selection.start.size;
  const maxY = Math.max(selection.start.y, selection.end.y) + selection.start.size;
  return [[minX, minY], [maxX, minY], [maxX, maxY], [minX, maxY]];
}

function getSelectionSize(selection: NonNullable<ReturnType<typeof useMapEditorStore.getState>['regionSelection']>): string {
  const columns = Math.round(Math.abs(selection.end.x - selection.start.x) / selection.start.size) + 1;
  const rows = Math.round(Math.abs(selection.end.y - selection.start.y) / selection.start.size) + 1;
  return `${columns} x ${rows} 栅格`;
}

export function MapEditorPanel() {
  const { isOpen, mode, pointCell, regionSelection, selectedEntity, setOpen, setMode, selectEntity } = useMapEditorStore();
  const [regions, setRegions] = useState<MapRegion[]>([]);
  const [points, setPoints] = useState<MapPoint[]>([]);
  const [message, setMessage] = useState('');
  const [pointDraft, setPointDraft] = useState<PointDraft>({ name: '', pointType: 'work', color: DEFAULT_COLOR });
  const [regionDraft, setRegionDraft] = useState<RegionDraft>({ name: '', regionType: 'work', color: DEFAULT_COLOR });
  const [saving, setSaving] = useState(false);

  const refresh = useCallback(async () => {
    const scene = await getSceneConfig();
    setRegions(scene.regions);
    setPoints(scene.points);
  }, []);

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

  useEffect(() => {
    if (selectedPoint) {
      setPointDraft({ name: selectedPoint.name, pointType: selectedPoint.point_type, color: selectedPoint.color || DEFAULT_COLOR });
    }
  }, [selectedPoint]);

  useEffect(() => {
    if (selectedRegion) {
      setRegionDraft({ name: selectedRegion.name, regionType: selectedRegion.region_type, color: selectedRegion.color || DEFAULT_COLOR });
    }
  }, [selectedRegion]);

  const notifyMapChanged = () => window.dispatchEvent(new Event('robots:map-changed'));

  const startPoint = () => {
    setPointDraft({ name: '', pointType: 'work', color: DEFAULT_COLOR });
    setMessage('');
    setMode('point');
  };

  const startRegion = () => {
    setRegionDraft({ name: '', regionType: 'work', color: DEFAULT_COLOR });
    setMessage('');
    setMode('region');
  };

  const savePoint = async () => {
    if (!pointDraft.name.trim()) {
      setMessage('请填写点位名称');
      return;
    }
    if (!pointCell && !selectedPoint) {
      setMessage('请先在地图中选择一个栅格');
      return;
    }
    setSaving(true);
    try {
      if (selectedPoint) {
        const { id, ...point } = selectedPoint;
        await updatePoint(id, { ...point, name: pointDraft.name.trim(), point_type: pointDraft.pointType, color: pointDraft.color });
        setMessage('点位设置已保存');
      } else if (pointCell) {
        const point = await createPoint({
          code: createMapCode('P'),
          name: pointDraft.name.trim(),
          point_type: pointDraft.pointType,
          x: pointCell.x + pointCell.size / 2,
          y: pointCell.y + pointCell.size / 2,
          z: 0,
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
    if (!regionSelection && !selectedRegion) {
      setMessage('请先在地图中框选栅格');
      return;
    }
    setSaving(true);
    try {
      if (selectedRegion) {
        const { id, ...region } = selectedRegion;
        await updateRegion(id, { ...region, name: regionDraft.name.trim(), region_type: regionDraft.regionType, color: regionDraft.color });
        setMessage('区域设置已保存');
      } else if (regionSelection) {
        const region = await createRegion({
          code: createMapCode('R'),
          name: regionDraft.name.trim(),
          region_type: regionDraft.regionType,
          polygon: getRegionPolygon(regionSelection),
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

  const deleteSelected = async () => {
    const selected = selectedPoint || selectedRegion;
    if (!selected || !window.confirm(`删除“${selected.name}”后不可恢复，是否继续？`)) return;
    setSaving(true);
    try {
      if (selectedPoint) await deletePoint(selectedPoint.id);
      if (selectedRegion) await deleteRegion(selectedRegion.id);
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
  const selectionText = pointCell
    ? `栅格 ${pointCell.x.toFixed(1)}, ${pointCell.y.toFixed(1)}`
    : regionSelection
      ? getSelectionSize(regionSelection)
      : selectedPoint?.name || selectedRegion?.name || '未选择';

  return (
    <aside className="fixed inset-y-3 right-3 z-40 flex w-[min(360px,calc(100vw-24px))] flex-col border border-[rgba(91,183,255,0.38)] bg-[rgba(8,22,36,0.96)] shadow-2xl shadow-black/40">
      <div className="flex items-center justify-between border-b border-[rgba(91,183,255,0.22)] px-3 py-2">
        <div className="flex items-center gap-2"><Layers3 size={15} className="text-[#2FD7FF]" /><h2 className="text-[13px] font-medium text-[#E6F6FF]">地图编辑</h2></div>
        <button onClick={() => setOpen(false)} title="关闭地图编辑" aria-label="关闭地图编辑" className="grid h-7 w-7 place-items-center text-[#79A3BF] hover:text-[#E6F6FF]"><X size={16} /></button>
      </div>

      <div className="flex border-b border-[rgba(91,183,255,0.18)] p-1">
        <ToolButton active={mode === 'select'} icon={<MousePointer2 size={15} />} label="选择" onClick={() => setMode('select')} />
        <ToolButton active={mode === 'point'} icon={<MapPin size={15} />} label="点位" onClick={startPoint} />
        <ToolButton active={mode === 'region'} icon={<Square size={15} />} label="区域" onClick={startRegion} />
      </div>

      <div className="flex-1 overflow-y-auto p-3">
        <div className="mb-3 border-l-2 border-[#2FD7FF] bg-[rgba(47,215,255,0.07)] px-2 py-1.5 text-[11px] text-[#aecce0]">{selectionText}</div>

        {editingPoint && (
          <EditorSection title={selectedPoint ? '点位设置' : '新建点位'}>
            <TextField label="名称" value={pointDraft.name} onChange={(name) => setPointDraft((draft) => ({ ...draft, name }))} placeholder="点位名称" />
            <label className="block text-[11px] text-[#79A3BF]">类型
              <select value={pointDraft.pointType} onChange={(event) => setPointDraft((draft) => ({ ...draft, pointType: event.target.value }))} className="mt-1 h-8 w-full border border-[rgba(91,183,255,0.28)] bg-[#091929] px-2 text-[12px] text-[#E6F6FF]">
                {!POINT_TYPES.includes(pointDraft.pointType) && <option value={pointDraft.pointType}>{pointDraft.pointType}</option>}
                {POINT_TYPES.map((type) => <option key={type} value={type}>{type}</option>)}
              </select>
            </label>
            <ColorPicker value={pointDraft.color} onChange={(color) => setPointDraft((draft) => ({ ...draft, color }))} />
            <div className="mt-3 flex gap-2"><PrimaryButton label="保存点位" icon={<Save size={14} />} onClick={savePoint} disabled={saving} />{selectedPoint && <DeleteButton onClick={deleteSelected} disabled={saving} />}</div>
          </EditorSection>
        )}

        {editingRegion && (
          <EditorSection title={selectedRegion ? '区域设置' : '新建区域'}>
            <TextField label="名称" value={regionDraft.name} onChange={(name) => setRegionDraft((draft) => ({ ...draft, name }))} placeholder="区域名称" />
            <label className="block text-[11px] text-[#79A3BF]">类型
              <select value={regionDraft.regionType} onChange={(event) => setRegionDraft((draft) => ({ ...draft, regionType: event.target.value as MapRegion['region_type'] }))} className="mt-1 h-8 w-full border border-[rgba(91,183,255,0.28)] bg-[#091929] px-2 text-[12px] text-[#E6F6FF]">
                {REGION_TYPES.map((type) => <option key={type.value} value={type.value}>{type.label}</option>)}
              </select>
            </label>
            <ColorPicker value={regionDraft.color} onChange={(color) => setRegionDraft((draft) => ({ ...draft, color }))} />
            <div className="mt-3 flex gap-2"><PrimaryButton label="保存区域" icon={<Save size={14} />} onClick={saveRegion} disabled={saving} />{selectedRegion && <DeleteButton onClick={deleteSelected} disabled={saving} />}</div>
          </EditorSection>
        )}

        <ObjectList title={`点位 ${points.length}`} items={points} selectedId={selectedPoint?.id} onSelect={(id) => selectEntity({ kind: 'point', id })} />
        <ObjectList title={`区域 ${regions.length}`} items={regions} selectedId={selectedRegion?.id} onSelect={(id) => selectEntity({ kind: 'region', id })} />
        {message && <p className="mt-3 text-[11px] text-[#FFB33D]" role="status">{message}</p>}
      </div>
    </aside>
  );
}

function ToolButton({ active, icon, label, onClick }: { active: boolean; icon: React.ReactNode; label: string; onClick: () => void }) {
  return <button onClick={onClick} title={label} aria-label={label} className={`flex h-8 flex-1 items-center justify-center gap-1 border text-[11px] ${active ? 'border-[#2FD7FF] bg-[rgba(47,215,255,0.15)] text-[#2FD7FF]' : 'border-transparent text-[#79A3BF] hover:text-[#E6F6FF]'}`}>{icon}<span>{label}</span></button>;
}

function EditorSection({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="mb-3 border border-[rgba(91,183,255,0.22)] p-3"><h3 className="mb-3 text-[12px] font-medium text-[#E6F6FF]">{title}</h3>{children}</section>;
}

function TextField({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (value: string) => void; placeholder: string }) {
  return <label className="mb-3 block text-[11px] text-[#79A3BF]">{label}<input value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} className="mt-1 h-8 w-full border border-[rgba(91,183,255,0.28)] bg-[#091929] px-2 text-[12px] text-[#E6F6FF] outline-none focus:border-[#2FD7FF]" /></label>;
}

function ColorPicker({ value, onChange }: { value: string; onChange: (color: string) => void }) {
  return <div><span className="block text-[11px] text-[#79A3BF]">颜色</span><div className="mt-1 flex items-center gap-2">{COLOR_SWATCHES.map((color) => <button key={color} type="button" onClick={() => onChange(color)} title={color} aria-label={`选择颜色 ${color}`} className={`h-6 w-6 border ${value === color ? 'border-white' : 'border-transparent'}`} style={{ backgroundColor: color }} />)}<input type="color" value={value} onChange={(event) => onChange(event.target.value.toUpperCase())} title="自定义颜色" aria-label="自定义颜色" className="h-6 w-6 cursor-pointer border border-[rgba(91,183,255,0.28)] bg-transparent p-0" /></div></div>;
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
