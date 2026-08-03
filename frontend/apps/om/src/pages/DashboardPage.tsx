/** O&M端 Dashboard page. */

import { useWebSocket } from '../hooks/useWebSocket';
import { TopBar } from '../components/TopBar';
import { LeftColumn } from '../components/LeftColumn';
import { Scene3D } from '../components/Scene3D';
import { RightColumn } from '../components/RightColumn';
import { DeviceDeck } from '../components/DeviceDeck';
import { DeviceDetailPanel } from '../components/DeviceDetailPanel';
import { MapEditorPanel } from '../components/MapEditorPanel';
import { EstopOverlay } from '@robots/ui';
import { useOmStore } from '../stores/omStore';
import { recoverEstop } from '@robots/api-client';

export function DashboardPage() {
  useWebSocket();
  const { estopActive, estopSource, selectedDeviceId } = useOmStore();

  const handleRecover = async () => {
    try { await recoverEstop(); } catch (e) { console.error(e); }
  };

  return (
    <div className="flex h-full min-h-0 flex-col gap-2 overflow-hidden p-3">
      <div className="flex shrink-0 items-center gap-2"><div className="min-w-0 flex-1"><TopBar /></div><MapEditorPanel /></div>
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-2 overflow-hidden xl:grid-cols-[minmax(260px,320px)_minmax(0,1fr)_minmax(300px,360px)]">
        <LeftColumn />
        <Scene3D />
        <RightColumn />
      </div>
      <div className="h-[116px] shrink-0"><DeviceDeck /></div>
      {selectedDeviceId && <DeviceDetailPanel />}
      <EstopOverlay active={estopActive} source={estopSource || undefined} canRecover onRecover={handleRecover} />
    </div>
  );
}
