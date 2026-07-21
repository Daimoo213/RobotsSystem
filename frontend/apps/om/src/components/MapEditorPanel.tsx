/** Database-backed map point and region entry; no synthetic geometry is created. */

import { useEffect, useState } from 'react';
import { MapPin, Plus, Trash2 } from 'lucide-react';
import { createPoint, createRegion, deletePoint, deleteRegion, getSceneConfig } from '@robots/api-client';
import type { MapPoint, MapRegion } from '@robots/shared-types';

export function MapEditorPanel() {
  const [open, setOpen] = useState(false);
  const [regions, setRegions] = useState<MapRegion[]>([]);
  const [points, setPoints] = useState<MapPoint[]>([]);
  const [message, setMessage] = useState('');
  const [pointForm, setPointForm] = useState({ code: '', name: '', point_type: '', x: '', y: '', z: '0', process_type: '', device_types: '', stage: '', qrcode_id: '', qrcode_type: '' });
  const [regionForm, setRegionForm] = useState({ code: '', name: '', region_type: 'work', polygon: '', stage: '' });

  const refresh = async () => {
    const scene = await getSceneConfig();
    setRegions(scene.regions); setPoints(scene.points);
  };
  useEffect(() => { if (open) refresh().catch((error) => setMessage(error instanceof Error ? error.message : '读取地图失败')); }, [open]);

  const createMapPoint = async () => {
    try {
      await createPoint({
        code: pointForm.code, name: pointForm.name, point_type: pointForm.point_type,
        x: Number(pointForm.x), y: Number(pointForm.y), z: Number(pointForm.z || 0),
        process_type: pointForm.process_type || null,
        device_types: pointForm.device_types.split(',').map((value) => value.trim()).filter(Boolean),
        stage: pointForm.stage || null, qrcode_id: pointForm.qrcode_id || null, qrcode_type: pointForm.qrcode_type || null,
      });
      setPointForm({ code: '', name: '', point_type: '', x: '', y: '', z: '0', process_type: '', device_types: '', stage: '', qrcode_id: '', qrcode_type: '' });
      setMessage('点位已保存'); await refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : '点位保存失败'); }
  };

  const createMapRegion = async () => {
    try {
      const polygon = JSON.parse(regionForm.polygon) as number[][];
      await createRegion({ code: regionForm.code, name: regionForm.name, region_type: regionForm.region_type as MapRegion['region_type'], polygon, stage: regionForm.stage || null });
      setRegionForm({ code: '', name: '', region_type: 'work', polygon: '', stage: '' });
      setMessage('区域已保存'); await refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : '区域保存失败，请使用 [[x,y],[x,y],[x,y]] 格式'); }
  };

  if (!open) return <button onClick={() => setOpen(true)} className="flex items-center gap-1 text-[11px] text-[#2FD7FF] hover:text-[#34DF9A]"><MapPin size={13} /> 地图维护</button>;
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/40" onClick={() => setOpen(false)}>
      <div className="h-full w-[440px] overflow-y-auto border-l border-[rgba(91,183,255,0.3)] bg-[#091929] p-4" onClick={(event) => event.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between"><h3 className="text-[16px] text-[#E6F6FF]">地图维护</h3><button onClick={() => setOpen(false)} className="text-[#79A3BF]">关闭</button></div>
        <p className="mb-3 text-[11px] text-[#79A3BF]">坐标必须与外部地图网关使用同一 map 坐标系。</p>
        <EditorSection title="新增施工点位"><div className="grid grid-cols-2 gap-2"><Input value={pointForm.code} onChange={(value) => setPointForm({ ...pointForm, code: value })} placeholder="点位编码" /><Input value={pointForm.name} onChange={(value) => setPointForm({ ...pointForm, name: value })} placeholder="点位名称" /><Input value={pointForm.point_type} onChange={(value) => setPointForm({ ...pointForm, point_type: value })} placeholder="点位类型" /><Input value={pointForm.device_types} onChange={(value) => setPointForm({ ...pointForm, device_types: value })} placeholder="适配设备，逗号分隔" /><Input value={pointForm.x} onChange={(value) => setPointForm({ ...pointForm, x: value })} placeholder="X" type="number" /><Input value={pointForm.y} onChange={(value) => setPointForm({ ...pointForm, y: value })} placeholder="Y" type="number" /><Input value={pointForm.z} onChange={(value) => setPointForm({ ...pointForm, z: value })} placeholder="Z" type="number" /><Input value={pointForm.process_type} onChange={(value) => setPointForm({ ...pointForm, process_type: value })} placeholder="工序 ID" /><Input value={pointForm.qrcode_id} onChange={(value) => setPointForm({ ...pointForm, qrcode_id: value })} placeholder="二维码 ID" /><Input value={pointForm.qrcode_type} onChange={(value) => setPointForm({ ...pointForm, qrcode_type: value })} placeholder="二维码类型" /></div><ActionButton onClick={createMapPoint} label="保存点位" /></EditorSection>
        <EditorSection title="新增区域"><div className="grid grid-cols-2 gap-2"><Input value={regionForm.code} onChange={(value) => setRegionForm({ ...regionForm, code: value })} placeholder="区域编码" /><Input value={regionForm.name} onChange={(value) => setRegionForm({ ...regionForm, name: value })} placeholder="区域名称" /><select value={regionForm.region_type} onChange={(event) => setRegionForm({ ...regionForm, region_type: event.target.value })} className="border border-[rgba(91,183,255,0.3)] bg-[#0A1521] p-2 text-[12px]"><option value="work">作业区</option><option value="restricted">禁行区</option><option value="stack">堆场</option><option value="parking">停车区</option></select><Input value={regionForm.stage} onChange={(value) => setRegionForm({ ...regionForm, stage: value })} placeholder="施工阶段" /></div><textarea value={regionForm.polygon} onChange={(event) => setRegionForm({ ...regionForm, polygon: event.target.value })} placeholder="[[x,y],[x,y],[x,y]]" className="mt-2 h-16 w-full border border-[rgba(91,183,255,0.3)] bg-[#0A1521] p-2 text-[12px]" /><ActionButton onClick={createMapRegion} label="保存区域" /></EditorSection>
        {message && <div className="mb-3 text-[11px] text-[#FFB33D]">{message}</div>}
        <EditorSection title={`已有点位 (${points.length})`}>{points.map((point) => <div key={point.id} className="flex items-center justify-between border-b border-[rgba(91,183,255,0.1)] py-1 text-[11px]"><span>{point.code} · {point.name}</span><button onClick={() => deletePoint(point.id).then(refresh).catch((error) => setMessage(error instanceof Error ? error.message : '删除失败'))} title="删除点位" className="text-[#FF5C6D]"><Trash2 size={12} /></button></div>)}</EditorSection>
        <EditorSection title={`已有区域 (${regions.length})`}>{regions.map((region) => <div key={region.id} className="flex items-center justify-between border-b border-[rgba(91,183,255,0.1)] py-1 text-[11px]"><span>{region.code} · {region.name}</span><button onClick={() => deleteRegion(region.id).then(refresh).catch((error) => setMessage(error instanceof Error ? error.message : '删除失败'))} title="删除区域" className="text-[#FF5C6D]"><Trash2 size={12} /></button></div>)}</EditorSection>
      </div>
    </div>
  );
}

function EditorSection({ title, children }: { title: string; children: React.ReactNode }) { return <section className="mb-4 border border-[rgba(91,183,255,0.15)] p-3"><h4 className="mb-2 text-[12px] text-[#2FD7FF]">{title}</h4>{children}</section>; }
function Input({ value, onChange, placeholder, type = 'text' }: { value: string; onChange: (value: string) => void; placeholder: string; type?: string }) { return <input required type={type} value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} className="min-w-0 border border-[rgba(91,183,255,0.3)] bg-[#0A1521] p-2 text-[12px] text-[#E6F6FF]" />; }
function ActionButton({ onClick, label }: { onClick: () => void; label: string }) { return <button onClick={onClick} className="mt-2 flex items-center gap-1 border border-[rgba(47,215,255,0.4)] px-3 py-1.5 text-[12px] text-[#2FD7FF]"><Plus size={12} /> {label}</button>; }
