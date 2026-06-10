import React from 'react';

interface RadarPulseProps {
  size?: number;
  color?: string;
  active?: boolean;
}

export function RadarPulse({ size = 28, color = '#00e5ff', active = true }: RadarPulseProps) {
  const r = size / 2;
  const inner = r * 0.65;
  const sweepId = `rsw-${size}-${color.replace('#', '')}`;
  const ringStyle: React.CSSProperties = { color };

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} overflow="visible" style={{ display: 'block' }}>
      <defs>
        <radialGradient id={sweepId} cx="50%" cy="50%" r="50%">
          <stop offset="0%"   stopColor={color} stopOpacity={0.55} />
          <stop offset="100%" stopColor={color} stopOpacity={0} />
        </radialGradient>
      </defs>

      {/* Outer ring */}
      <circle cx={r} cy={r} r={inner} fill="none" stroke={color} strokeOpacity={0.12} strokeWidth={1} />

      {/* Rotating sweep */}
      {active && (
        <g className="radar-sweep" style={{ transformOrigin: `${r}px ${r}px` }}>
          <path
            d={`M${r},${r} L${r},${r - inner} A${inner},${inner} 0 0 1 ${(r + inner * Math.sin(Math.PI / 3)).toFixed(2)},${(r - inner * Math.cos(Math.PI / 3)).toFixed(2)} Z`}
            fill={`url(#${sweepId})`}
          />
        </g>
      )}

      {/* Centre dot */}
      <circle cx={r} cy={r} r={2.2} fill={color} opacity={active ? 1 : 0.4} />

      {/* Pulse rings */}
      {active && (
        <>
          <circle cx={r} cy={r} r={inner} fill="none" stroke={color} strokeWidth={1.2}
            className="radar-ring" style={ringStyle} />
          <circle cx={r} cy={r} r={inner} fill="none" stroke={color} strokeWidth={1.2}
            className="radar-ring radar-ring-delay" style={ringStyle} />
        </>
      )}
    </svg>
  );
}
