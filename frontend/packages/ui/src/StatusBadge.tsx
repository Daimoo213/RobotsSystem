/** Status badge — colored pill for device/task/alert status. */

interface StatusBadgeProps {
  label: string;
  color: string;
  blinking?: boolean;
}

export function StatusBadge({ label, color, blinking }: StatusBadgeProps) {
  return (
    <span
      className="inline-flex items-center rounded px-2 py-0.5 text-[11px] font-medium"
      style={{
        color,
        backgroundColor: `${color}22`,
        border: `1px solid ${color}55`,
        animation: blinking ? 'blink 1s ease-in-out infinite' : undefined,
      }}
    >
      {label}
    </span>
  );
}
