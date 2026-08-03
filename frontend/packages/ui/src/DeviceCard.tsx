/** Device card — used in O&M bottom deck. */

import type { Device } from '@robots/shared-types';
import { DEVICE_TYPE_LABELS, DEVICE_STATUS_LABELS, HEALTH_KEYS, HEALTH_STATUS_LABELS, getDeviceDisplayStatus, getHealthColor, getStatusColor } from '@robots/utils';

interface DeviceCardProps {
  device: Device;
  onClick?: () => void;
  selected?: boolean;
}

export function DeviceCard({ device, onClick, selected = false }: DeviceCardProps) {
  const displayStatus = getDeviceDisplayStatus(device.status, device.connection_status);
  const statusColor = getStatusColor(displayStatus);
  const isFault = displayStatus === 'fault';
  const isOffline = displayStatus === 'offline';

  return (
    <button
      type="button"
      onClick={onClick}
      title={`${device.name || device.code}：${DEVICE_STATUS_LABELS[displayStatus] || '未知状态'}`}
      aria-pressed={selected}
      className={`grid h-full min-h-0 w-[184px] shrink-0 snap-start grid-rows-[18px_22px_minmax(0,1fr)] overflow-hidden rounded-md border px-2 py-1.5 text-left transition-[border-color,box-shadow,background-color] hover:border-[#2FD7FF] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[#2FD7FF] motion-reduce:animate-none ${isFault ? 'animate-[blink_1.5s_ease-in-out_infinite]' : ''}`}
      style={{
        borderColor: selected || isFault || isOffline ? statusColor : 'rgba(91,183,255,0.22)',
        backgroundColor: selected ? 'rgba(12,37,57,0.96)' : 'rgba(9,25,41,0.86)',
        boxShadow: selected ? `inset 3px 0 0 ${statusColor}, 0 0 0 1px ${statusColor}44` : undefined,
      }}
    >
      <div className="flex min-w-0 items-center justify-between gap-2">
        <span className="truncate text-[11px] text-[#79A3BF]">{DEVICE_TYPE_LABELS[device.type] || '未知设备类型'}</span>
        <span
          className="shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium"
          style={{ color: statusColor, backgroundColor: `${statusColor}22` }}
        >
          {DEVICE_STATUS_LABELS[displayStatus] || '未知状态'}
        </span>
      </div>
      <div className="flex min-w-0 items-center justify-between gap-2">
        <span className="truncate font-mono text-[13px] font-bold text-[#E6F6FF]">{device.code}</span>
        <span className="shrink-0 text-[10px] text-[#5A7A92]">
          {isOffline ? '末次电量' : '电量'} {Math.round(device.battery)}%
        </span>
      </div>
      <div className="grid min-h-0 grid-cols-5 items-center border-t border-[rgba(91,183,255,0.15)] pt-1">
        {HEALTH_KEYS.map(({ key, label }) => {
          const reportedValue = device.health?.[key as keyof typeof device.health] || 'unknown';
          const value = isOffline ? (key === 'connection' ? 'fail' : 'unknown') : reportedValue;
          return (
            <div
              key={key}
              className="grid min-w-0 grid-rows-[13px_14px] place-items-center text-center"
              title={isOffline && key !== 'connection' ? `${label}：设备离线，当前状态未知` : `${label}：${HEALTH_STATUS_LABELS[value] || '未知'}`}
            >
              <div className="text-[10px] leading-[13px] text-[#5A7A92]">{label}</div>
              <div className="w-full truncate text-[10px] font-mono leading-[14px]" style={{ color: getHealthColor(value) }}>
                {HEALTH_STATUS_LABELS[value] || '未知'}
              </div>
            </div>
          );
        })}
      </div>
    </button>
  );
}
