/** O&M header: real project metadata, fleet status, and view switching. */

import { useEffect, useState } from 'react';
import { Activity, AlertCircle, AlertTriangle, Heart, LogOut, User } from 'lucide-react';
import { getEnergyView, getHealthScore, getProject, getSafetyView, triggerEstop } from '@robots/api-client';
import type { HealthScore, ProjectInfo } from '@robots/api-client';
import { useAuthStore } from '../stores/authStore';
import { useOmStore } from '../stores/omStore';

export function TopBar() {
  const { devices, currentView, estopActive, setEnergyView, setEstop, setSafetyView, setView } = useOmStore();
  const { displayName, logout } = useAuthStore();
  const [health, setHealth] = useState<HealthScore | null>(null);
  const [project, setProject] = useState<ProjectInfo | null>(null);
  const [confirmingEstop, setConfirmingEstop] = useState(false);

  useEffect(() => {
    const refresh = async () => {
      try {
        const [healthData, projectData] = await Promise.all([getHealthScore(), getProject()]);
        setHealth(healthData); setProject(projectData);
      } catch (error) { console.error(error); }
    };
    refresh();
    const timer = window.setInterval(refresh, 10_000);
    return () => window.clearInterval(timer);
  }, []);

  const online = devices.filter((device) => device.status !== 'fault' && device.status !== 'maintenance').length;
  const faults = devices.filter((device) => device.status === 'fault').length;

  const switchView = async (view: typeof currentView) => {
    setView(view);
    try {
      if (view === 'energy') setEnergyView(await getEnergyView());
      if (view === 'safety') setSafetyView(await getSafetyView());
    } catch (error) { console.error(error); }
  };

  const handleEstop = async () => {
    setConfirmingEstop(false);
    try { await triggerEstop(); setEstop(true, 'om'); } catch (error) { console.error(error); }
  };

  const views = [{ id: 'dispatch' as const, label: '调度' }, { id: 'energy' as const, label: '能耗' }, { id: 'safety' as const, label: '安全' }];
  return (
    <>
      <div className="flex items-center justify-between rounded-lg border border-[rgba(79,153,231,0.24)] bg-[rgba(10,28,47,0.84)] px-4 py-2">
        <div className="flex min-w-0 items-center gap-3"><div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md font-mono font-black text-[#07111C]" style={{ background: 'linear-gradient(135deg, #2FD7FF, #34DF9A)' }}>R</div><span className="truncate text-[14px] font-medium text-[#E6F6FF]">{project?.name || '机器人集群调度系统'}</span></div>
        <div className="flex items-center gap-4"><div className="flex items-center gap-1.5"><Activity size={14} className="text-[#34DF9A]" /><span className="text-[12px] text-[#aecce0]">在线 <span className="font-mono text-[#34DF9A]">{online}/{devices.length}</span></span></div><div className="flex items-center gap-1.5"><AlertCircle size={14} style={{ color: faults ? '#FF5C6D' : '#34DF9A' }} /><span className="text-[12px] text-[#aecce0]">故障 <span className="font-mono">{faults}</span></span></div><div className="flex items-center gap-1.5"><Heart size={14} className="text-[#2FD7FF]" /><span className="text-[12px] text-[#aecce0]">健康 <span className="font-mono text-[#2FD7FF]">{health?.score ?? '--'}%</span></span></div></div>
        <div className="flex items-center gap-3"><div className="flex border border-[rgba(91,183,255,0.3)] p-0.5">{views.map((view) => <button key={view.id} onClick={() => switchView(view.id)} className={`px-3 py-1 text-[12px] ${currentView === view.id ? 'bg-[#2FD7FF] text-[#050B13]' : 'text-[#79A3BF]'}`}>{view.label}</button>)}</div><button onClick={() => setConfirmingEstop(true)} disabled={estopActive} className="flex items-center gap-1.5 border border-[#FF5C6D] bg-[rgba(255,92,109,0.15)] px-3 py-1 text-[12px] font-medium text-[#FF5C6D] disabled:opacity-40"><AlertTriangle size={13} /> 急停</button><div className="flex items-center gap-1.5"><User size={14} className="text-[#B56CFF]" /><span className="text-[12px] text-[#aecce0]">{displayName || '未登录'}</span><button onClick={logout} title="退出登录" className="text-[#79A3BF] hover:text-[#FF5C6D]"><LogOut size={13} /></button></div></div>
      </div>
      {confirmingEstop && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"><div className="border border-[#FF5C6D] bg-[#140508] p-6 text-center"><AlertTriangle size={36} className="mx-auto mb-3 text-[#FF5C6D]" /><div className="mb-4 text-[16px] font-bold text-[#FF5C6D]">确认触发全局急停？</div><div className="flex justify-center gap-3"><button onClick={() => setConfirmingEstop(false)} className="border border-[rgba(91,183,255,0.3)] px-5 py-2 text-[#aecce0]">取消</button><button onClick={handleEstop} className="bg-[#FF5C6D] px-5 py-2 text-white">确认急停</button></div></div></div>}
    </>
  );
}
