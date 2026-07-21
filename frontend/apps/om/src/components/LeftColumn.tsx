/** O&M left column: persisted fleet state and the configured backup operation. */

import { useState } from 'react';
import { Panel, DonutChart, EventFeed } from '@robots/ui';
import { useOmStore } from '../stores/omStore';
import { DEVICE_STATUS_LABELS, STATUS_COLORS } from '@robots/utils';
import { runOpsCommand } from '@robots/api-client';

type BackupState = 'idle' | 'running' | 'success' | 'unavailable' | 'error';

export function LeftColumn() {
  const { devices, events } = useOmStore();
  const [backupState, setBackupState] = useState<BackupState>('idle');

  const statusData = Object.entries(DEVICE_STATUS_LABELS)
    .map(([status, label]) => ({
      label,
      value: devices.filter((device) => device.status === status).length,
      color: STATUS_COLORS[status] || '#687988',
    }))
    .filter((entry) => entry.value > 0);

  const handleBackup = async () => {
    setBackupState('running');
    try {
      await runOpsCommand('backup');
      setBackupState('success');
    } catch (error) {
      const message = error instanceof Error ? error.message : '';
      setBackupState(message.includes('501') ? 'unavailable' : 'error');
    }
  };

  return (
    <div className="flex h-full flex-col gap-2 overflow-y-auto">
      <Panel title="设备状态分布">
        {statusData.length > 0 ? (
          <DonutChart data={statusData} size={130} thickness={18} centerValue={devices.length} centerLabel="台" />
        ) : (
          <div className="py-4 text-center text-[12px] text-[#5A7A92]">尚未接入设备</div>
        )}
      </Panel>

      <Panel title="数据库备份">
        <div className="space-y-2 text-[11px] text-[#79A3BF]">
          <p>仅在部署环境配置备份目录和 pg_dump 后可执行。</p>
          <button
            onClick={handleBackup}
            disabled={backupState === 'running'}
            className="rounded border border-[rgba(91,183,255,0.3)] px-3 py-1.5 text-[#aecce0] hover:border-[#2FD7FF] hover:text-[#2FD7FF] disabled:opacity-50"
          >
            {backupState === 'running' ? '正在备份...' : '执行数据库备份'}
          </button>
          {backupState === 'success' && <p className="text-[#34DF9A]">备份作业已完成。</p>}
          {backupState === 'unavailable' && <p className="text-[#FFB33D]">当前部署尚未配置备份。</p>}
          {backupState === 'error' && <p className="text-[#FF5C6D]">备份执行失败，请检查服务日志。</p>}
        </div>
      </Panel>

      <Panel title="实时运行日志" className="flex-1 min-h-[100px]">
        <EventFeed events={events} maxItems={20} />
      </Panel>
    </div>
  );
}
