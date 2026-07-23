/** Event feed — scrolling list of realtime events. */

import type { RealtimeEvent } from '@robots/shared-types';
import { EVENT_TYPE_LABELS, formatTime, formatUserMessage } from '@robots/utils';

interface EventFeedProps {
  events: RealtimeEvent[];
  maxItems?: number;
}

const TYPE_COLORS: Record<string, string> = {
  alert: '#FF5C6D', charging: '#3D8CFF', sync: '#2FD7FF',
  normal: '#687988', update: '#3D8CFF', completed: '#34DF9A',
  task_assigned: '#2FD7FF', task_completed: '#34DF9A',
};

export function EventFeed({ events, maxItems = 20 }: EventFeedProps) {
  const items = events.slice(0, maxItems);
  return (
    <div className="space-y-1 overflow-y-auto" style={{ maxHeight: '100%' }}>
      {items.length === 0 && (
        <div className="py-4 text-center text-[12px] text-[#5A7A92]">暂无事件</div>
      )}
      {items.map((e, i) => {
        const color = TYPE_COLORS[e.type] || '#79A3BF';
        return (
          <div key={i} className="flex items-start gap-2 text-[12px]">
            <span className="font-mono text-[#5A7A92] whitespace-nowrap">{formatTime(e.time)}</span>
            <span className="rounded px-1 text-[10px] whitespace-nowrap" style={{ color, backgroundColor: `${color}22` }}>
              {EVENT_TYPE_LABELS[e.type] || '其他事件'}
            </span>
            <span className="text-[#aecce0]">{formatUserMessage(e.message)}</span>
          </div>
        );
      })}
    </div>
  );
}
