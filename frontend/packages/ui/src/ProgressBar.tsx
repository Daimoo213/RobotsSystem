/** Progress bar — colored progress with label. */

interface ProgressBarProps {
  value: number; // 0-100
  color?: string;
  height?: number;
  showLabel?: boolean;
  label?: string;
}

export function ProgressBar({ value, color = '#2FD7FF', height = 8, showLabel, label }: ProgressBarProps) {
  const pct = Math.min(100, Math.max(0, value));
  return (
    <div className="w-full">
      {(showLabel || label) && (
        <div className="mb-1 flex justify-between text-[11px]">
          <span className="text-[#aecce0]">{label}</span>
          {showLabel && <span className="font-mono text-[#E6F6FF]">{Math.round(pct)}%</span>}
        </div>
      )}
      <div className="w-full overflow-hidden rounded-full bg-[rgba(91,183,255,0.1)]" style={{ height }}>
        <div
          className="h-full rounded-full transition-all duration-300"
          style={{
            width: `${pct}%`,
            background: `linear-gradient(90deg, ${color}88, ${color})`,
            boxShadow: `0 0 8px ${color}55`,
          }}
        />
      </div>
    </div>
  );
}
