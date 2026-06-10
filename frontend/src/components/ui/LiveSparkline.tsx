import React, { useMemo } from 'react';

interface LiveSparklineProps {
  data: number[];
  width?: number;
  height?: number;
  color?: string;
  fill?: boolean;
  strokeWidth?: number;
}

export function LiveSparkline({
  data, width = 120, height = 40, color = '#00e5ff', fill = true, strokeWidth = 1.5,
}: LiveSparklineProps) {
  const { polyline, areaPath, lx, ly, gradId, glowId } = useMemo(() => {
    if (data.length < 2) return { polyline: '', areaPath: '', lx: 0, ly: 0, gradId: '', glowId: '' };

    const min   = Math.min(...data);
    const max   = Math.max(...data);
    const range = max - min || 1;
    const pad   = height * 0.08;

    const pts = data.map((v, i) => ({
      x: (i / (data.length - 1)) * width,
      y: height - pad - ((v - min) / range) * (height - pad * 2),
    }));

    const id = `sp-${(data[0] * 100 + data.length).toFixed(0)}`;
    return {
      polyline: pts.map(p => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' '),
      areaPath: `M${pts[0].x.toFixed(1)},${height} ` +
        pts.map(p => `L${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ') +
        ` L${pts[pts.length - 1].x.toFixed(1)},${height} Z`,
      lx: pts[pts.length - 1].x,
      ly: pts[pts.length - 1].y,
      gradId: `sg-${id}`,
      glowId: `gw-${id}`,
    };
  }, [data, width, height]);

  if (data.length < 2) return null;

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} overflow="visible">
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%"   stopColor={color} stopOpacity={0.28} />
          <stop offset="100%" stopColor={color} stopOpacity={0} />
        </linearGradient>
        <filter id={glowId}>
          <feGaussianBlur stdDeviation="2" result="blur" />
          <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>
      {fill && <path d={areaPath} fill={`url(#${gradId})`} />}
      <polyline
        points={polyline}
        fill="none"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
        filter={`url(#${glowId})`}
      />
      {/* Live dot with pulse ring */}
      <circle cx={lx} cy={ly} r={3} fill={color} className="live-dot" style={{ color }} />
    </svg>
  );
}
