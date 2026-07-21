/** PM端 Dashboard page — main layout. */

import { useWebSocket } from '../hooks/useWebSocket';
import { TopBar } from '../components/TopBar';
import { KpiStrip } from '../components/KpiStrip';
import { LeftColumn } from '../components/LeftColumn';
import { GanttColumn } from '../components/GanttColumn';
import { RightColumn } from '../components/RightColumn';
import { EstopOverlay } from '@robots/ui';
import { usePmStore } from '../stores/pmStore';

export function DashboardPage() {
  useWebSocket();
  const { estopActive, estopSource } = usePmStore();

  return (
    <div className="flex h-full flex-col gap-2 p-3">
      <TopBar />
      <KpiStrip />
      <div className="grid min-w-0 flex-1 grid-cols-[330px_minmax(0,1fr)_380px] gap-2 overflow-hidden">
        <LeftColumn />
        <GanttColumn />
        <RightColumn />
      </div>
      <EstopOverlay active={estopActive} source={estopSource || undefined} canRecover={false} />
    </div>
  );
}
