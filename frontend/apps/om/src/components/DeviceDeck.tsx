/** O&M 端底部设备条。 */

import { DeviceCard } from '@robots/ui';
import { useOmStore } from '../stores/omStore';

export function DeviceDeck() {
  const { devices, selectedDeviceId, selectDevice } = useOmStore();

  return (
    <div
      className="flex h-full snap-x snap-proximity items-stretch gap-2 overflow-x-auto overflow-y-hidden py-1.5 pr-1 [scrollbar-gutter:stable] overscroll-x-contain"
      aria-label="设备列表"
    >
      {devices.length === 0 && (
        <div className="flex w-full items-center justify-center text-[12px] text-[#5A7A92]">暂无已接入设备</div>
      )}
      {devices.map((device) => (
        <DeviceCard
          key={device.id}
          device={device}
          selected={device.id === selectedDeviceId}
          onClick={() => selectDevice(device.id)}
        />
      ))}
    </div>
  );
}
