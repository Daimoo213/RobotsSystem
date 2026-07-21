/** Panel component — semi-transparent dark panel with cyan border. */

import { type ReactNode } from 'react';

interface PanelProps {
  title?: string;
  children: ReactNode;
  className?: string;
  actions?: ReactNode;
}

export function Panel({ title, children, className = '', actions }: PanelProps) {
  return (
    <div
      className={`flex min-h-0 flex-col rounded-lg border border-[rgba(91,183,255,0.22)] bg-[rgba(9,25,41,0.86)] p-3 backdrop-blur-sm ${className}`}
      style={{ boxShadow: '0 4px 24px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.04)' }}
    >
      {title && (
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-[14px] font-medium text-[#E6F6FF]" style={{ textShadow: '0 0 8px rgba(47,215,255,0.3)' }}>
            {title}
          </h3>
          {actions}
        </div>
      )}
      {children}
    </div>
  );
}
