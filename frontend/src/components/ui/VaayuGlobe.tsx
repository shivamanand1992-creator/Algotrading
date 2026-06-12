import React from 'react';

interface VaayuGlobeProps {
  ltp?:       number;
  change?:    number;
  changePct?: number;
  isUp?:      boolean;
  size?:      number;
}

// Globe constants — orthographic projection, 25° tilt from equatorial plane
const R    = 155;   // globe radius (px)
const CX   = 200;   // center x
const CY   = 200;   // center y
const TILT = 25;    // degrees

// pre-compute trig
const sinT = Math.sin((TILT * Math.PI) / 180);
const cosT = Math.cos((TILT * Math.PI) / 180);

/** Project a (lat, lon) to SVG (x, y). lon is degrees from front-center meridian. */
function project(latDeg: number, lonDeg: number): [number, number] {
  const lat = (latDeg * Math.PI) / 180;
  const lon = (lonDeg * Math.PI) / 180;
  const x3  = R * Math.cos(lat) * Math.sin(lon);
  const y3  = R * Math.sin(lat);
  const z3  = R * Math.cos(lat) * Math.cos(lon);
  // Apply tilt rotation around x-axis
  const xp  = x3;
  const yp  = y3 * cosT - z3 * sinT;
  return [CX + xp, CY - yp];
}

/** Build SVG 'd' for a full latitude ring. */
function latRingPath(latDeg: number): string {
  const pts: [number, number][] = [];
  for (let lon = -180; lon <= 180; lon += 6) {
    pts.push(project(latDeg, lon));
  }
  return pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ') + ' Z';
}

/** Build SVG 'd' for a longitude great-circle (visible half only). */
function lonHalfPath(lonDeg: number): string {
  const pts: [number, number][] = [];
  for (let lat = -80; lat <= 80; lat += 6) {
    pts.push(project(lat, lonDeg));
  }
  return pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ');
}

// Fixed market locations [lat, lon, label, color]
const MARKET_DOTS: [number, number, string, string][] = [
  [ 18.9,  72.8,  'NIFTY',  '#00e5ff' ],  // Mumbai
  [ 40.7, -74.0,  'NYSE',   '#a78bfa' ],  // New York
  [ 51.5,  -0.1,  'LSE',    '#34d399' ],  // London
  [ 35.7, 139.7,  'NIKKEI', '#f472b6' ],  // Tokyo
  [ 31.2, 121.5,  'SSE',    '#fbbf24' ],  // Shanghai
];

// Build scan sector path (wedge from center)
function sweepSector(): string {
  const arcAngle = 70; // degrees of sweep
  const [x1, y1] = project(0,  0);
  const [x2, y2] = project(0, arcAngle);
  const [x3, y3] = project(20, arcAngle / 2);
  return `M${CX},${CY} L${x1.toFixed(1)},${y1.toFixed(1)} Q${x3.toFixed(1)},${y3.toFixed(1)} ${x2.toFixed(1)},${y2.toFixed(1)} Z`;
}

export function VaayuGlobe({ ltp = 0, change = 0, changePct = 0, isUp = true, size = 400 }: VaayuGlobeProps) {
  const latitudes  = [-60, -30, 0, 30, 60];
  const longitudes = [-90, -60, -30, 0, 30, 60, 90];

  return (
    <div style={{ width: size, height: size, position: 'relative', flexShrink: 0 }}>
      <svg
        viewBox="0 0 400 400"
        width={size}
        height={size}
        style={{ overflow: 'visible' }}
      >
        <defs>
          <radialGradient id="globe-fill" cx="45%" cy="40%" r="60%">
            <stop offset="0%"   stopColor="rgba(0,30,80,0.85)" />
            <stop offset="100%" stopColor="rgba(0,5,20,0.95)" />
          </radialGradient>
          <radialGradient id="globe-atmo" cx="50%" cy="50%" r="55%">
            <stop offset="70%"  stopColor="transparent" />
            <stop offset="100%" stopColor="rgba(0,180,255,0.12)" />
          </radialGradient>
          <radialGradient id="globe-glow-grad" cx="50%" cy="50%" r="50%">
            <stop offset="0%"   stopColor="rgba(0,229,255,0)" />
            <stop offset="80%"  stopColor="rgba(0,229,255,0)" />
            <stop offset="100%" stopColor="rgba(0,229,255,0.18)" />
          </radialGradient>
          <filter id="globe-glow">
            <feGaussianBlur stdDeviation="6" result="blur" />
            <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
          </filter>
          <filter id="dot-glow">
            <feGaussianBlur stdDeviation="3" result="blur" />
            <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
          </filter>
          <clipPath id="globe-clip">
            <circle cx={CX} cy={CY} r={R + 1} />
          </clipPath>
        </defs>

        {/* ── Outer glow rings ─────────────────────────────────────── */}
        <circle cx={CX} cy={CY} r={R + 18} fill="none" stroke="rgba(0,229,255,0.06)" strokeWidth={12} />
        <circle cx={CX} cy={CY} r={R + 6}  fill="none" stroke="rgba(0,229,255,0.15)" strokeWidth={1} />
        <circle cx={CX} cy={CY} r={R + 28} fill="url(#globe-glow-grad)" />

        {/* ── Globe body ───────────────────────────────────────────── */}
        <circle cx={CX} cy={CY} r={R} fill="url(#globe-fill)" />
        <circle cx={CX} cy={CY} r={R} fill="url(#globe-atmo)" />

        {/* ── Grid (clipped to globe) ───────────────────────────────── */}
        <g clipPath="url(#globe-clip)" opacity={0.5}>
          {latitudes.map(lat => (
            <path key={`lat-${lat}`} d={latRingPath(lat)}
              fill="none" stroke="rgba(0,229,255,0.18)" strokeWidth={0.7} />
          ))}
          {longitudes.map(lon => (
            <path key={`lon-${lon}`} d={lonHalfPath(lon)}
              fill="none" stroke="rgba(0,229,255,0.14)" strokeWidth={0.6} />
          ))}
        </g>

        {/* ── Radar sweep (rotating) ────────────────────────────────── */}
        <g clipPath="url(#globe-clip)">
          <g className="radar-sweep" style={{ transformOrigin: `${CX}px ${CY}px` }}>
            <path d={sweepSector()}
              fill="url(#sweep-grad)"
              opacity={0.55}
            />
            <defs>
              <linearGradient id="sweep-grad" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%"   stopColor="rgba(0,229,255,0.5)" />
                <stop offset="100%" stopColor="rgba(0,229,255,0)" />
              </linearGradient>
            </defs>
          </g>
        </g>

        {/* ── Market location dots ──────────────────────────────────── */}
        {MARKET_DOTS.map(([lat, lon, label, color]) => {
          const [px, py] = project(lat, lon);
          // Only show if roughly on front face (simplified)
          const z = Math.cos((lat * Math.PI) / 180) * Math.cos((lon * Math.PI) / 180);
          if (z < 0) return null;
          return (
            <g key={label} filter="url(#dot-glow)">
              <circle cx={px} cy={py} r={4}  fill={color} opacity={0.9} />
              <circle cx={px} cy={py} r={8}  fill="none" stroke={color} strokeWidth={0.8} opacity={0.4} className="radar-ring" style={{ color }} />
              <text x={px + 8} y={py + 4}
                style={{ fontSize: 8, fontFamily: 'monospace', fill: color, opacity: 0.8, letterSpacing: 0.5 }}>
                {label}
              </text>
            </g>
          );
        })}

        {/* ── Outer HUD ring with tick marks ───────────────────────── */}
        <g opacity={0.6}>
          {Array.from({ length: 36 }, (_, i) => {
            const angle  = (i / 36) * 2 * Math.PI;
            const r1     = R + 10;
            const r2     = R + 14 + (i % 3 === 0 ? 4 : 0);
            return (
              <line key={i}
                x1={CX + r1 * Math.cos(angle)}
                y1={CY + r1 * Math.sin(angle)}
                x2={CX + r2 * Math.cos(angle)}
                y2={CY + r2 * Math.sin(angle)}
                stroke="rgba(0,229,255,0.4)"
                strokeWidth={i % 3 === 0 ? 1.2 : 0.6}
              />
            );
          })}
          {/* Degree labels at 4 cardinal points */}
          {['N', 'E', 'S', 'W'].map((d, i) => {
            const a = (i / 4) * 2 * Math.PI - Math.PI / 2;
            return (
              <text key={d}
                x={CX + (R + 26) * Math.cos(a)}
                y={CY + (R + 26) * Math.sin(a) + 3}
                textAnchor="middle"
                style={{ fontSize: 8, fontFamily: 'monospace', fill: 'rgba(0,229,255,0.5)', letterSpacing: 1 }}>
                {d}
              </text>
            );
          })}
        </g>

        {/* ── Centre data display ───────────────────────────────────── */}
        <g filter="url(#dot-glow)">
          {/* VAAYU label */}
          <text x={CX} y={CY - 28}
            textAnchor="middle"
            style={{ fontSize: 9, fontFamily: 'monospace', fill: 'rgba(0,229,255,0.55)', letterSpacing: '0.3em', textTransform: 'uppercase' }}>
            VAAYU · NIFTY 50
          </text>
          {/* LTP */}
          <text x={CX} y={CY + 4}
            textAnchor="middle"
            style={{ fontSize: ltp > 0 ? 26 : 14, fontFamily: 'monospace', fill: '#00e5ff', fontWeight: 900, letterSpacing: '-1px' }}>
            {ltp > 0 ? ltp.toLocaleString('en-IN', { minimumFractionDigits: 0, maximumFractionDigits: 0 }) : '—'}
          </text>
          {/* Change */}
          {ltp > 0 && (
            <text x={CX} y={CY + 24}
              textAnchor="middle"
              style={{ fontSize: 11, fontFamily: 'monospace', fill: isUp ? '#4ade80' : '#f87171', fontWeight: 700 }}>
              {isUp ? '▲' : '▼'} {isUp ? '+' : ''}{change.toFixed(1)}  ({isUp ? '+' : ''}{changePct.toFixed(2)}%)
            </text>
          )}
        </g>

        {/* ── Atmosphere shimmer overlay ────────────────────────────── */}
        <circle cx={CX} cy={CY} r={R}
          fill="none" stroke="rgba(0,229,255,0.08)" strokeWidth={8} />
      </svg>
    </div>
  );
}
