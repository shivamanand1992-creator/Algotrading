import React, { useMemo } from 'react';

// Deterministic pseudo-random from seed (no re-render flicker)
function rng(seed: number) {
  const s = Math.sin(seed * 9301 + 49297) * 233280;
  return s - Math.floor(s);
}

interface Building {
  x: number; w: number; h: number;
  windows: { x: number; y: number; w: number; h: number; color: string; delay: number }[];
  antenna: boolean;
}

const WINDOW_COLORS = [
  'rgba(0,229,255,0.7)',
  'rgba(124,58,237,0.7)',
  'rgba(244,114,182,0.65)',
  'rgba(251,191,36,0.6)',
  'rgba(52,211,153,0.6)',
];

function genBuildings(totalW: number, baseY: number): Building[] {
  const buildings: Building[] = [];
  let x = -10;
  let seed = 0;

  while (x < totalW + 50) {
    const w    = 35 + rng(seed++) * 70;
    const h    = 60 + rng(seed++) * 200;
    const ant  = rng(seed++) > 0.7;
    const wins: Building['windows'] = [];

    const cols = Math.floor(w / 12);
    const rows = Math.floor(h / 14);
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        if (rng(seed++) > 0.35) {
          wins.push({
            x:     x + 4 + c * 12,
            y:     baseY - h + 8 + r * 14,
            w:     6, h: 8,
            color: WINDOW_COLORS[Math.floor(rng(seed++) * WINDOW_COLORS.length)],
            delay: rng(seed++) * 8,
          });
        }
      }
    }

    buildings.push({ x, w, h, windows: wins, antenna: ant });
    x += w + 2 + rng(seed++) * 6;
  }
  return buildings;
}

export function CityBackground() {
  const W = 1600;
  const H = 420;
  const BASE = H;

  const buildings = useMemo(() => genBuildings(W, BASE), [BASE]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 0, pointerEvents: 'none', overflow: 'hidden' }}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="xMidYMax slice"
        style={{ position: 'absolute', bottom: 0, left: 0, width: '100%', height: '55%' }}
      >
        <defs>
          <linearGradient id="sky-grad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%"   stopColor="rgba(4,8,28,0)" />
            <stop offset="100%" stopColor="rgba(20,10,50,0.55)" />
          </linearGradient>
          <style>{`
            @keyframes winFlicker {
              0%,100% { opacity: 0.85; }
              50%      { opacity: 0.2; }
            }
            .win { animation: winFlicker 3s step-end infinite; }
          `}</style>
        </defs>

        {/* Sky gradient */}
        <rect width={W} height={H} fill="url(#sky-grad)" />

        {/* Horizon glow */}
        <ellipse cx={W / 2} cy={H} rx={W * 0.7} ry={80}
          fill="rgba(80,20,160,0.18)" />
        <ellipse cx={W / 2} cy={H} rx={W * 0.5} ry={40}
          fill="rgba(0,100,200,0.12)" />

        {/* Buildings */}
        {buildings.map((b, i) => (
          <g key={i}>
            {/* Building body */}
            <rect x={b.x} y={BASE - b.h} width={b.w} height={b.h}
              fill={`rgba(${4 + i % 8},${8 + i % 6},${28 + i % 20},0.95)`}
              stroke="rgba(60,40,100,0.3)" strokeWidth={0.5}
            />
            {/* Antenna */}
            {b.antenna && (
              <line
                x1={b.x + b.w / 2} y1={BASE - b.h}
                x2={b.x + b.w / 2} y2={BASE - b.h - 20 - rng(i * 7) * 30}
                stroke="rgba(0,229,255,0.3)" strokeWidth={0.8}
              />
            )}
          </g>
        ))}

        {/* Windows overlay (separate pass so they're on top) */}
        {buildings.flatMap((b, bi) =>
          b.windows.map((w, wi) => (
            <rect
              key={`${bi}-${wi}`}
              x={w.x} y={w.y} width={w.w} height={w.h}
              fill={w.color}
              className="win"
              style={{ animationDelay: `${w.delay}s`, animationDuration: `${2 + rng(bi + wi) * 4}s` }}
            />
          ))
        )}
      </svg>

      {/* Top-to-bottom fade so city blends into app background */}
      <div style={{
        position:   'absolute',
        inset:      0,
        background: 'linear-gradient(to bottom, rgba(4,8,28,0.4) 0%, transparent 40%, transparent 70%, rgba(4,8,28,0.9) 100%)',
        pointerEvents: 'none',
      }} />
    </div>
  );
}
