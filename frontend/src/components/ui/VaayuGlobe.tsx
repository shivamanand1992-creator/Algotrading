import React from 'react';
import { motion } from 'framer-motion';
import { useVaayuConvState } from '../../stores/vaayuStore';

export interface GlobeSector {
  name:  string;
  score: number; // 0–1
}

export interface GlobeHolding {
  symbol: string;
  pnlPct: number;
}

interface VaayuGlobeProps {
  ltp?:        number;
  change?:     number;
  changePct?:  number;
  isUp?:       boolean;
  size?:       number;
  sectors?:    GlobeSector[];
  topHolding?: GlobeHolding | null;
}

const R    = 155;
const CX   = 200;
const CY   = 200;
const TILT = 25;
const sinT = Math.sin((TILT * Math.PI) / 180);
const cosT = Math.cos((TILT * Math.PI) / 180);

function project(latDeg: number, lonDeg: number): [number, number] {
  const lat = (latDeg * Math.PI) / 180;
  const lon = (lonDeg * Math.PI) / 180;
  const x3  = R * Math.cos(lat) * Math.sin(lon);
  const y3  = R * Math.sin(lat);
  const z3  = R * Math.cos(lat) * Math.cos(lon);
  return [CX + x3, CY - (y3 * cosT - z3 * sinT)];
}

function isFront(latDeg: number, lonDeg: number): boolean {
  const lat = (latDeg * Math.PI) / 180;
  const lon = (lonDeg * Math.PI) / 180;
  return Math.cos(lat) * Math.cos(lon) > 0.08;
}

function latRingPath(latDeg: number): string {
  const pts: [number, number][] = [];
  for (let lon = -180; lon <= 180; lon += 6) pts.push(project(latDeg, lon));
  return pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ') + ' Z';
}

function lonHalfPath(lonDeg: number): string {
  const pts: [number, number][] = [];
  for (let lat = -80; lat <= 80; lat += 6) pts.push(project(lat, lonDeg));
  return pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ');
}

function sweepSector(): string {
  const [x1, y1] = project(0, 0);
  const [x2, y2] = project(0, 70);
  const [x3, y3] = project(20, 35);
  return `M${CX},${CY} L${x1.toFixed(1)},${y1.toFixed(1)} Q${x3.toFixed(1)},${y3.toFixed(1)} ${x2.toFixed(1)},${y2.toFixed(1)} Z`;
}

// Spread sector markers across the visible globe face
const SECTOR_ORBITALS: [number, number][] = [
  [ 44, -58 ],  // top-left
  [  6, -64 ],  // mid-left
  [-32, -42 ],  // bottom-left
  [-18,  28 ],  // bottom-right
  [ 28,  46 ],  // mid-right
];

const SECTOR_COLORS = ['#60a5fa', '#34d399', '#fbbf24', '#f472b6', '#fb923c'];

// Fixed position for top-holding badge (top-center area)
const HOLDING_LAT =  48;
const HOLDING_LON = -10;

// Shown when no live scan data is available yet
const FALLBACK_SECTORS: GlobeSector[] = [
  { name: 'IT',      score: 0.72 },
  { name: 'BANKING', score: 0.65 },
  { name: 'ENERGY',  score: 0.58 },
  { name: 'FMCG',    score: 0.52 },
  { name: 'PHARMA',  score: 0.47 },
];

export function VaayuGlobe({
  ltp = 0, change = 0, changePct = 0, isUp = true, size = 400,
  sectors = [], topHolding = null,
}: VaayuGlobeProps) {
  const latitudes  = [-60, -30, 0, 30, 60];
  const longitudes = [-90, -60, -30, 0, 30, 60, 90];

  const convState   = useVaayuConvState();
  const isSpeaking  = convState === 'speaking';
  const isListening = convState === 'listening';
  const isActive    = isSpeaking || isListening;
  const globeR      = R * (size / 400);
  const stateColor  = isSpeaking ? '#00e5ff' : '#a855f7';

  const holdingPt    = isFront(HOLDING_LAT, HOLDING_LON) ? project(HOLDING_LAT, HOLDING_LON) : null;
  const displaySectors = sectors.length > 0 ? sectors : FALLBACK_SECTORS;

  return (
    <motion.div
      style={{ width: size, height: size, position: 'relative', flexShrink: 0 }}
      animate={
        isSpeaking  ? { scale: [1, 1.008, 0.994, 1.008, 1] }
        : isListening ? { scale: [1, 1.004, 1] }
        : { scale: 1 }
      }
      transition={
        isSpeaking  ? { duration: 0.18, repeat: Infinity, ease: 'easeInOut' }
        : isListening ? { duration: 2,    repeat: Infinity, ease: 'easeInOut' }
        : { duration: 0.3 }
      }
    >
      {/* ── Expanding state rings ── */}
      {isActive && [0, 1, 2].map(i => (
        <motion.div
          key={`ring-${i}-${convState}`}
          style={{
            position: 'absolute', top: '50%', left: '50%',
            width: globeR * 2, height: globeR * 2,
            marginLeft: -globeR, marginTop: -globeR,
            borderRadius: '50%',
            border: `1.5px solid ${isSpeaking ? 'rgba(0,229,255,0.55)' : 'rgba(168,85,247,0.55)'}`,
            pointerEvents: 'none', zIndex: 1,
          }}
          initial={{ scale: 1, opacity: 0.7 }}
          animate={{ scale: 1.45, opacity: 0 }}
          transition={{ duration: 2.4, repeat: Infinity, delay: i * 0.8, ease: 'easeOut' }}
        />
      ))}
      {isActive && (
        <motion.div
          style={{
            position: 'absolute', top: '50%', left: '50%',
            width: globeR * 2.1, height: globeR * 2.1,
            marginLeft: -(globeR * 1.05), marginTop: -(globeR * 1.05),
            borderRadius: '50%',
            background: `radial-gradient(circle, ${isSpeaking ? 'rgba(0,229,255,0.04)' : 'rgba(168,85,247,0.04)'} 0%, transparent 70%)`,
            pointerEvents: 'none', zIndex: 1,
          }}
          animate={{ opacity: [0.4, 1, 0.4] }}
          transition={{ duration: isSpeaking ? 1 : 2, repeat: Infinity, ease: 'easeInOut' }}
        />
      )}

      <svg viewBox="0 0 400 400" width={size} height={size}
        style={{ overflow: 'visible', position: 'relative', zIndex: 2 }}>
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
          <linearGradient id="sweep-grad" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%"   stopColor="rgba(0,229,255,0.5)" />
            <stop offset="100%" stopColor="rgba(0,229,255,0)" />
          </linearGradient>
        </defs>

        {/* Outer glow rings */}
        <circle cx={CX} cy={CY} r={R + 18} fill="none"
          stroke={isActive ? `${stateColor}1f` : 'rgba(0,229,255,0.06)'} strokeWidth={isActive ? 8 : 12} />
        <circle cx={CX} cy={CY} r={R + 6}  fill="none"
          stroke={isActive ? stateColor : 'rgba(0,229,255,0.15)'} strokeWidth={isActive ? 1.5 : 1} />
        <circle cx={CX} cy={CY} r={R + 28} fill="url(#globe-glow-grad)" />

        {/* Globe body */}
        <circle cx={CX} cy={CY} r={R} fill="url(#globe-fill)" />
        <circle cx={CX} cy={CY} r={R} fill="url(#globe-atmo)" />

        {/* Grid */}
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

        {/* Radar sweep */}
        <g clipPath="url(#globe-clip)">
          <g className="radar-sweep" style={{ transformOrigin: `${CX}px ${CY}px` }}>
            <path d={sweepSector()} fill="url(#sweep-grad)" opacity={0.55} />
          </g>
        </g>

        {/* ── Sector markers ─────────────────────────────────────── */}
        {displaySectors.slice(0, 5).map((sector, i) => {
          const [lat, lon] = SECTOR_ORBITALS[i];
          if (!isFront(lat, lon)) return null;
          const [px, py] = project(lat, lon);
          const col      = SECTOR_COLORS[i];
          const barW     = 28;
          const label    = sector.name.split(' & ')[0].toUpperCase().slice(0, 8);
          return (
            <g key={`s${i}`} filter="url(#dot-glow)">
              <circle cx={px} cy={py} r={4.5} fill={col} opacity={0.9} />
              <circle cx={px} cy={py} r={9}   fill="none" stroke={col} strokeWidth={0.9} opacity={0.35} className="radar-ring" />
              {/* Rank */}
              <text x={px} y={py - 11} textAnchor="middle"
                style={{ fontSize: 6, fontFamily: 'monospace', fill: col, opacity: 0.65 }}>
                #{i + 1}
              </text>
              {/* Name */}
              <text x={px + 11} y={py - 1}
                style={{ fontSize: 8, fontFamily: 'monospace', fill: col, fontWeight: 700, letterSpacing: 0.4 }}>
                {label}
              </text>
              {/* Confidence bar BG */}
              <rect x={px + 11} y={py + 5} width={barW}                        height={2.5} rx={1} fill={col} opacity={0.12} />
              {/* Confidence bar fill */}
              <rect x={px + 11} y={py + 5} width={barW * Math.min(1, sector.score)} height={2.5} rx={1} fill={col} opacity={0.75} />
              {/* Score */}
              <text x={px + 11 + barW + 3} y={py + 8}
                style={{ fontSize: 6.5, fontFamily: 'monospace', fill: col, opacity: 0.7 }}>
                {(sector.score * 100).toFixed(0)}%
              </text>
            </g>
          );
        })}

        {/* ── Top Holding marker ─────────────────────────────────── */}
        {topHolding && holdingPt && (
          <g filter="url(#dot-glow)">
            <circle cx={holdingPt[0]} cy={holdingPt[1]} r={5.5} fill="rgba(251,191,36,0.9)" />
            <circle cx={holdingPt[0]} cy={holdingPt[1]} r={11}  fill="none" stroke="#fbbf24" strokeWidth={0.9} opacity={0.35} className="radar-ring" />
            <text x={holdingPt[0]} y={holdingPt[1] - 12} textAnchor="middle"
              style={{ fontSize: 6.5, fontFamily: 'monospace', fill: '#fbbf24', opacity: 0.7, letterSpacing: 0.5 }}>
              ◆ TOP HOLD
            </text>
            <text x={holdingPt[0] + 12} y={holdingPt[1] - 1}
              style={{ fontSize: 8.5, fontFamily: 'monospace', fill: '#fbbf24', fontWeight: 700 }}>
              {topHolding.symbol}
            </text>
            <text x={holdingPt[0] + 12} y={holdingPt[1] + 11}
              style={{ fontSize: 8.5, fontFamily: 'monospace', fill: '#4ade80', fontWeight: 700 }}>
              +{topHolding.pnlPct.toFixed(1)}%
            </text>
          </g>
        )}

        {/* HUD tick ring */}
        <g opacity={0.6}>
          {Array.from({ length: 36 }, (_, i) => {
            const angle = (i / 36) * 2 * Math.PI;
            const r1    = R + 10;
            const r2    = R + 14 + (i % 3 === 0 ? 4 : 0);
            return (
              <line key={i}
                x1={CX + r1 * Math.cos(angle)} y1={CY + r1 * Math.sin(angle)}
                x2={CX + r2 * Math.cos(angle)} y2={CY + r2 * Math.sin(angle)}
                stroke={isActive ? stateColor : 'rgba(0,229,255,0.4)'}
                strokeWidth={i % 3 === 0 ? 1.2 : 0.6}
              />
            );
          })}
          {['N', 'E', 'S', 'W'].map((d, i) => {
            const a = (i / 4) * 2 * Math.PI - Math.PI / 2;
            return (
              <text key={d}
                x={CX + (R + 26) * Math.cos(a)} y={CY + (R + 26) * Math.sin(a) + 3}
                textAnchor="middle"
                style={{ fontSize: 8, fontFamily: 'monospace', fill: 'rgba(0,229,255,0.5)', letterSpacing: 1 }}>
                {d}
              </text>
            );
          })}
        </g>

        {/* Conversation state label */}
        {isActive && (
          <text x={CX} y={CY - 50} textAnchor="middle"
            style={{ fontSize: 8, fontFamily: 'monospace', letterSpacing: '0.3em',
              fill: isSpeaking ? 'rgba(0,229,255,0.85)' : 'rgba(168,85,247,0.85)' }}>
            {isSpeaking ? '◈ SPEAKING' : '◈ LISTENING'}
          </text>
        )}

        {/* Centre: VAAYU label + LTP + change */}
        <g filter="url(#dot-glow)">
          <text x={CX} y={CY - 28} textAnchor="middle"
            style={{ fontSize: 9, fontFamily: 'monospace', fill: 'rgba(0,229,255,0.55)', letterSpacing: '0.3em' }}>
            VAAYU · NIFTY 50
          </text>
          <text x={CX} y={CY + 4} textAnchor="middle"
            style={{ fontSize: ltp > 0 ? 26 : 14, fontFamily: 'monospace', fill: '#00e5ff', fontWeight: 900, letterSpacing: '-1px' }}>
            {ltp > 0 ? ltp.toLocaleString('en-IN', { maximumFractionDigits: 0 }) : '—'}
          </text>
          {ltp > 0 && (
            <text x={CX} y={CY + 24} textAnchor="middle"
              style={{ fontSize: 11, fontFamily: 'monospace', fill: isUp ? '#4ade80' : '#f87171', fontWeight: 700 }}>
              {isUp ? '▲' : '▼'} {isUp ? '+' : ''}{change.toFixed(1)}  ({isUp ? '+' : ''}{changePct.toFixed(2)}%)
            </text>
          )}
        </g>

        {/* Atmosphere shimmer */}
        <circle cx={CX} cy={CY} r={R} fill="none" stroke="rgba(0,229,255,0.08)" strokeWidth={8} />
      </svg>
    </motion.div>
  );
}
