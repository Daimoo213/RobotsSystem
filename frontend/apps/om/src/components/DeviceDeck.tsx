/** O&M端 Bottom device deck — 18 cards horizontal scroll. */

import { DeviceCard } from '@robots/ui';
import { useOmStore } from '../stores/omStore';

export function DeviceDeck() {
  const { devices, selectDevice } = useOmStore();
  const display = devices.slice(0, 18);

  return (
    <div className="flex gap-2 overflow-x-auto py-1" style={{ minHeight: '90px' }}>
      {display.length === 0 && (
        <div className="flex w-full items-center justify-center text-[12px] text-[#5A7A92]">加载设备数据...</div>
      )}
      {display.map((d) => (
        <DeviceCard key={d.id} device={d} onClick={() => selectDevice(d.id)} />
      ))}
    </div>
  );
}
