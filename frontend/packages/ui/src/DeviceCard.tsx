/** Device card — used in O&M bottom deck. */

import type { Device } from '@robots/shared-types';
import { DEVICE_TYPE_LABELS, DEVICE_STATUS_LABELS, HEALTH_KEYS, HEALTH_STATUS_LABELS, getHealthColor, getStatusColor } from '@robots/utils';

interface DeviceCardProps {
  device: Device;
  onClick?: () => void;
}

export function DeviceCard({ device, onClick }: DeviceCardProps) {
  const statusColor = getStatusColor(device.status);
  const isFault = device.status === 'fault';

  return (
    <div
      onClick={onClick}
      className="min-w-[180px] cursor-pointer rounded-lg border p-2.5 transition-colors hover:border-[#2FD7FF]"
      style={{
        borderColor: isFault ? statusColor : 'rgba(91,183,255,0.22)',
        backgroundColor: 'rgba(9,25,41,0.86)',
        animation: isFault ? 'blink 1.5s ease-in-out infinite' : undefined,
      }}
    >
      <div className="mb-1.5 flex items-center justify-between">
        <span className="text-[12px] text-[#79A3BF]">{DEVICE_TYPE_LABELS[device.type] || '未知设备类型'}</span>
        <span
          className="rounded px-1.5 py-0.5 text-[10px] font-medium"
          style={{ color: statusColor, backgroundColor: `${statusColor}22` }}
        >
          {DEVICE_STATUS_LABELS[device.status] || '未知状态'}
        </span>
      </div>
      <div className="mb-2 text-[14px] font-mono font-bold text-[#E6F6FF]">{device.code}</div>
      <div className="flex justify-between border-t border-[rgba(91,183,255,0.15)] pt-1.5">
        {HEALTH_KEYS.map(({ key, label }) => {
          const val = device.health?.[key as keyof typeof device.health] || 'ok';
          return (
            <div key={key} className="text-center">
              <div className="text-[10px] text-[#5A7A92]">{label}</div>
              <div className="text-[10px] font-mono" style={{ color: getHealthColor(val) }}>
                {HEALTH_STATUS_LABELS[val] || '未知'}
              </div>
            </div>
          );
        })}
      </div>
      <div className="mt-1 text-[9px] text-[#5A7A92]">电量 {Math.round(device.battery)}%</div>
    </div>
  );
}
