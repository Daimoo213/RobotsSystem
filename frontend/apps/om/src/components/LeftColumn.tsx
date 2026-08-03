/** O&M left column: persisted fleet state and the configured backup operation. */

import { useState } from 'react';
import { Panel, DonutChart, EventFeed } from '@robots/ui';
import { useOmStore } from '../stores/omStore';
import { DEVICE_STATUS_LABELS, getDeviceDisplayStatus, STATUS_COLORS } from '@robots/utils';
import { runOpsCommand, setMappingMode } from '@robots/api-client';

type BackupState = 'idle' | 'running' | 'success' | 'unavailable' | 'error';

export function LeftColumn() {
  const { devices, events, mappingEnabled, setMappingEnabled } = useOmStore();
  const [backupState, setBackupState] = useState<BackupState>('idle');
  const [mappingBusy, setMappingBusy] = useState(false);
  const [mappingError, setMappingError] = useState('');

  const statusData = Object.entries(DEVICE_STATUS_LABELS)
    .map(([status, label]) => ({
      label,
      value: devices.filter((device) => getDeviceDisplayStatus(device.status, device.connection_status) === status).length,
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
      setBackupState(message.includes('当前部署尚未配置') ? 'unavailable' : 'error');
    }
  };

  const handleMappingToggle = async () => {
    setMappingBusy(true);
    setMappingError('');
    try {
      const result = await setMappingMode(!mappingEnabled);
      setMappingEnabled(result.enabled);
    } catch (error) {
      setMappingError(error instanceof Error ? error.message : '建图模式切换失败');
    } finally {
      setMappingBusy(false);
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col gap-2 overflow-y-auto">
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

      <Panel title="建图模式">
        <div className="space-y-2 text-[11px] text-[#79A3BF]">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-[#E6F6FF]">完整点云地图上传</p>
              <p className="mt-0.5">仅允许建图端上传并替换当前地图</p>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={mappingEnabled}
              aria-label="切换建图模式"
              onClick={handleMappingToggle}
              disabled={mappingBusy}
              className={`relative h-5 w-10 rounded-full border transition ${mappingEnabled ? 'border-[#34DF9A] bg-[rgba(52,223,154,0.35)]' : 'border-[rgba(91,183,255,0.35)] bg-[rgba(91,183,255,0.1)]'} disabled:opacity-50`}
            >
              <span className={`absolute top-0.5 h-3.5 w-3.5 rounded-full transition ${mappingEnabled ? 'left-5 bg-[#34DF9A]' : 'left-0.5 bg-[#79A3BF]'}`} />
            </button>
          </div>
          <p className={mappingEnabled ? 'text-[#34DF9A]' : 'text-[#FFB33D]'}>{mappingEnabled ? '已开启：允许完整地图上传' : '已关闭：拒绝完整地图上传'}</p>
          {mappingError && <p className="text-[#FF5C6D]">{mappingError}</p>}
        </div>
      </Panel>

      <Panel title="实时运行日志" className="flex-1 min-h-[100px]">
        <EventFeed events={events} maxItems={20} />
      </Panel>
    </div>
  );
}
