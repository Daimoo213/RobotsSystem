/** PM header populated from authenticated project and telemetry APIs. */

import { useEffect, useState } from 'react';
import { Activity, AlertTriangle, Eye, Gauge, LogOut, User } from 'lucide-react';
import { getEnvironment, getHealthScore, getProject, triggerEstop } from '@robots/api-client';
import type { EnvironmentData, HealthScore, ProjectInfo } from '@robots/api-client';
import { useAuthStore } from '../stores/authStore';
import { usePmStore } from '../stores/pmStore';

export function TopBar() {
  const { devices, estopActive, setEstop } = usePmStore();
  const { displayName, logout } = useAuthStore();
  const [environment, setEnvironment] = useState<EnvironmentData | null>(null);
  const [health, setHealth] = useState<HealthScore | null>(null);
  const [project, setProject] = useState<ProjectInfo | null>(null);
  const [confirmingEstop, setConfirmingEstop] = useState(false);

  useEffect(() => {
    const refresh = async () => {
      try {
        const [environmentData, healthData, projectData] = await Promise.all([getEnvironment(), getHealthScore(), getProject()]);
        setEnvironment(environmentData);
        setHealth(healthData);
        setProject(projectData);
      } catch (error) {
        console.error(error);
      }
    };
    refresh();
    const timer = window.setInterval(refresh, 10_000);
    return () => window.clearInterval(timer);
  }, []);

  const onlineCount = devices.filter((device) => device.status !== 'fault' && device.status !== 'maintenance').length;
  const dustColor = environment?.has_data ? '#34DF9A' : '#687988';

  const handleEstop = async () => {
    setConfirmingEstop(false);
    try {
      await triggerEstop();
      setEstop(true, 'pm');
    } catch (error) {
      console.error(error);
    }
  };

  return (
    <>
      <div className="flex items-center justify-between rounded-lg border border-[rgba(91,183,255,0.2)] bg-[rgba(12,31,52,0.86)] px-4 py-2" style={{ boxShadow: '0 4px 24px rgba(0,0,0,0.35)' }}>
        <div className="flex min-w-0 items-center gap-4">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md font-mono font-black text-[#07111C]" style={{ background: 'linear-gradient(135deg, #2FD7FF, #34DF9A)' }}>R</div>
          <div className="min-w-0">
            <div className="truncate text-[15px] font-medium text-[#E6F6FF]">{project?.name || '机器人集群调度系统'}</div>
            <div className="truncate text-[11px] text-[#79A3BF]">{project?.location || '项目资料尚未配置'}</div>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <div className="flex items-center gap-1.5"><Activity size={14} className="text-[#34DF9A]" /><span className="text-[12px] text-[#aecce0]">在线 <span className="font-mono text-[#34DF9A]">{onlineCount}/{devices.length}</span></span></div>
          <div className="flex items-center gap-1.5"><Eye size={14} style={{ color: dustColor }} /><span className="text-[12px] text-[#aecce0]">环境 <span style={{ color: dustColor }}>{environment?.has_data ? environment.dust_level : '无数据'}</span></span></div>
          <div className="flex items-center gap-1.5"><Gauge size={14} className="text-[#2FD7FF]" /><span className="text-[12px] text-[#aecce0]">健康 <span className="font-mono text-[#2FD7FF]">{health?.score ?? '--'}</span></span></div>
          <div className="flex items-center gap-1.5"><User size={14} className="text-[#B56CFF]" /><span className="text-[12px] text-[#aecce0]">{displayName || '未登录'}</span><button onClick={logout} title="退出登录" className="text-[#79A3BF] hover:text-[#FF5C6D]"><LogOut size={13} /></button></div>
          <button onClick={() => setConfirmingEstop(true)} disabled={estopActive} className="flex items-center gap-1.5 rounded-lg border border-[#FF5C6D] bg-[rgba(255,92,109,0.15)] px-4 py-1.5 text-[13px] font-medium text-[#FF5C6D] disabled:opacity-40"><AlertTriangle size={14} /> 急停</button>
        </div>
      </div>

      {confirmingEstop && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"><div className="border border-[#FF5C6D] bg-[#140508] p-6 text-center"><AlertTriangle size={36} className="mx-auto mb-3 text-[#FF5C6D]" /><div className="mb-4 text-[16px] font-bold text-[#FF5C6D]">确认触发全局急停？</div><div className="flex justify-center gap-3"><button onClick={() => setConfirmingEstop(false)} className="border border-[rgba(91,183,255,0.3)] px-5 py-2 text-[#aecce0]">取消</button><button onClick={handleEstop} className="bg-[#FF5C6D] px-5 py-2 text-white">确认急停</button></div></div></div>}
    </>
  );
}
