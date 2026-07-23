/** Alert bar — alert list item. */

import type { Alert } from '@robots/shared-types';
import { ALERT_LEVEL_COLORS, ALERT_STATUS_COLORS, ALERT_STATUS_LABELS, formatDateTime, formatUserMessage } from '@robots/utils';
import { Check } from 'lucide-react';

interface AlertListProps {
  alerts: Alert[];
  onSelect?: (alert: Alert) => void;
  onAcknowledge?: (alertId: string) => void;
  acknowledgingId?: string | null;
  maxItems?: number;
}

export function AlertList({
  alerts,
  onSelect,
  onAcknowledge,
  acknowledgingId,
  maxItems = 20,
}: AlertListProps) {
  const items = alerts.slice(0, maxItems);
  return (
    <div className="space-y-1 overflow-y-auto" style={{ maxHeight: '100%' }}>
      {items.length === 0 && (
        <div className="py-4 text-center text-[12px] text-[#5A7A92]">暂无告警</div>
      )}
      {items.map((a) => {
        const levelColor = ALERT_LEVEL_COLORS[a.level] || '#79A3BF';
        const statusColor = ALERT_STATUS_COLORS[a.status] || '#79A3BF';
        return (
          <div
            key={a.id}
            onClick={() => onSelect?.(a)}
            className="cursor-pointer rounded border border-[rgba(91,183,255,0.15)] p-2 transition-colors hover:border-[#2FD7FF]"
            style={{ borderLeft: `3px solid ${levelColor}` }}
          >
            <div className="flex items-start justify-between gap-2">
              <span className="text-[12px] text-[#E6F6FF]">{formatUserMessage(a.message)}</span>
              <div className="flex shrink-0 items-center gap-1">
                <span className="rounded px-1 text-[10px]" style={{ color: statusColor, backgroundColor: `${statusColor}22` }}>
                  {ALERT_STATUS_LABELS[a.status] || '未知状态'}
                </span>
                {onAcknowledge && a.status === 'open' && (
                  <button
                    type="button"
                    title="确认告警"
                    aria-label="确认告警"
                    disabled={acknowledgingId === a.id}
                    onClick={(event) => {
                      event.stopPropagation();
                      onAcknowledge(a.id);
                    }}
                    className="text-[#79A3BF] hover:text-[#34DF9A] disabled:opacity-40"
                  >
                    <Check size={14} />
                  </button>
                )}
              </div>
            </div>
            <div className="mt-0.5 text-[10px] text-[#5A7A92]">{formatDateTime(a.created_at)}</div>
          </div>
        );
      })}
    </div>
  );
}
