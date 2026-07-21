/** Donut chart — SVG ring chart for distribution display. */

interface DonutChartProps {
  data: { label: string; value: number; color: string }[];
  size?: number;
  thickness?: number;
  centerLabel?: string;
  centerValue?: string | number;
}

export function DonutChart({ data, size = 150, thickness = 20, centerLabel, centerValue }: DonutChartProps) {
  const total = data.reduce((sum, d) => sum + d.value, 0) || 1;
  const radius = (size - thickness) / 2;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;

  return (
    <div className="flex flex-col items-center gap-1.5">
      <div className="relative w-full" style={{ maxWidth: size }}>
        <svg width="100%" height={size} viewBox={`0 0 ${size} ${size}`} className="block" style={{ maxHeight: size }}>
          <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="rgba(91,183,255,0.1)" strokeWidth={thickness} />
          {data.map((d, i) => {
            const length = (d.value / total) * circumference;
            const circle = (
              <circle
                key={i}
                cx={size / 2}
                cy={size / 2}
                r={radius}
                fill="none"
                stroke={d.color}
                strokeWidth={thickness}
                strokeDasharray={`${length} ${circumference - length}`}
                strokeDashoffset={-offset}
                transform={`rotate(-90 ${size / 2} ${size / 2})`}
                style={{ transition: 'stroke-dasharray 0.3s ease' }}
              />
            );
            offset += length;
            return circle;
          })}
          {(centerValue !== undefined || centerLabel) && (
            <>
              <text x="50%" y="46%" textAnchor="middle" className="fill-[#E6F6FF] font-mono" style={{ fontSize: 22, fontWeight: 700 }}>
                {centerValue}
              </text>
              <text x="50%" y="60%" textAnchor="middle" className="fill-[#79A3BF]" style={{ fontSize: 11 }}>
                {centerLabel}
              </text>
            </>
          )}
        </svg>
      </div>
      <div className="flex w-full flex-wrap justify-center gap-x-2.5 gap-y-0.5">
        {data.map((d, i) => (
          <div key={i} className="flex items-center gap-1 text-[11px]">
            <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: d.color }} />
            <span className="text-[#aecce0]">{d.label}</span>
            <span className="font-mono text-[#E6F6FF]">{d.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
