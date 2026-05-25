import React from 'react';
import { motion } from 'framer-motion';

interface CircularWidgetProps {
  title: string;
  value: string | number;
  unit?: string;
  progress?: number;
  size?: 'sm' | 'md' | 'lg';
  className?: string;
  color?: 'primary' | 'green' | 'red' | 'yellow';
}

const sizes = {
  sm: { container: 'w-28 h-28', text: 'text-xl',  label: 'text-xs', radius: 46 },
  md: { container: 'w-36 h-36', text: 'text-2xl', label: 'text-xs', radius: 58 },
  lg: { container: 'w-52 h-52', text: 'text-4xl', label: 'text-sm', radius: 88 },
};

const colors = {
  primary: { stroke: 'var(--jarvis-primary)', glow: 'rgba(0,229,255,0.6)',  text: 'text-jarvis-primary' },
  green:   { stroke: '#00e676',               glow: 'rgba(0,230,118,0.6)',  text: 'text-green-400' },
  red:     { stroke: '#ff1744',               glow: 'rgba(255,23,68,0.6)',  text: 'text-red-400' },
  yellow:  { stroke: '#ffd600',               glow: 'rgba(255,214,0,0.6)', text: 'text-yellow-400' },
};

export function CircularWidget({
  title, value, unit, progress, size = 'md', className = '', color = 'primary',
}: CircularWidgetProps) {
  const sz   = sizes[size];
  const col  = colors[color];
  const r    = sz.radius;
  const circ = 2 * Math.PI * r;
  const pct  = progress !== undefined ? Math.min(Math.max(progress, 0), 100) : 0;
  const dashOffset = circ - (pct / 100) * circ;
  const vbSize = r * 2 + 20;

  return (
    <motion.div
      className={`flex flex-col items-center ${className}`}
      initial={{ opacity: 0, scale: 0.75 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.55, ease: 'easeOut' }}
      whileHover={{ scale: 1.06 }}
    >
      <div className={`relative ${sz.container}`}>

        {/* Expanding pulse rings */}
        {progress !== undefined && progress > 5 && (
          <>
            <motion.div
              className="absolute inset-0 rounded-full border"
              style={{ borderColor: col.stroke }}
              animate={{ scale: [1, 1.45], opacity: [0.35, 0] }}
              transition={{ duration: 2.8, repeat: Infinity, ease: 'easeOut' }}
            />
            <motion.div
              className="absolute inset-0 rounded-full border"
              style={{ borderColor: col.stroke }}
              animate={{ scale: [1, 1.8], opacity: [0.2, 0] }}
              transition={{ duration: 2.8, repeat: Infinity, ease: 'easeOut', delay: 0.7 }}
            />
          </>
        )}

        {/* SVG rings */}
        <svg
          className="absolute inset-0 w-full h-full -rotate-90"
          viewBox={`0 0 ${vbSize} ${vbSize}`}
        >
          <defs>
            <filter id={`gw-${size}-${color}`} x="-60%" y="-60%" width="220%" height="220%">
              <feGaussianBlur stdDeviation="3" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>

          {/* Dashed outer ring */}
          <circle
            cx={vbSize / 2} cy={vbSize / 2} r={r + 5}
            fill="none" stroke="rgba(0,229,255,0.06)" strokeWidth="1" strokeDasharray="3 7"
          />

          {/* Track */}
          <circle
            cx={vbSize / 2} cy={vbSize / 2} r={r}
            fill="none" stroke="rgba(0,229,255,0.08)" strokeWidth="3.5"
          />

          {/* Progress */}
          {progress !== undefined && (
            <motion.circle
              cx={vbSize / 2} cy={vbSize / 2} r={r}
              fill="none"
              stroke={col.stroke}
              strokeWidth="4"
              strokeDasharray={circ}
              strokeLinecap="round"
              filter={`url(#gw-${size}-${color})`}
              initial={{ strokeDashoffset: circ }}
              animate={{ strokeDashoffset: dashOffset }}
              transition={{ duration: 1.4, ease: 'easeOut' }}
            />
          )}

          {/* Inner ring */}
          <circle
            cx={vbSize / 2} cy={vbSize / 2} r={r - 10}
            fill="none" stroke="rgba(0,229,255,0.04)" strokeWidth="1"
          />
        </svg>

        {/* Spinning conic border */}
        <div
          className="absolute inset-0 rounded-full animate-spin-slow"
          style={{
            background: `conic-gradient(from 0deg, transparent, ${col.stroke} 50%, transparent)`,
            WebkitMask: 'radial-gradient(farthest-side, transparent calc(100% - 3px), #fff calc(100% - 3px))',
            mask: 'radial-gradient(farthest-side, transparent calc(100% - 3px), #fff calc(100% - 3px))',
            opacity: 0.4,
          }}
        />

        {/* Inner ambient glow */}
        <div
          className="absolute inset-3 rounded-full"
          style={{
            background: `radial-gradient(circle, ${col.glow.replace('0.6', '0.05')} 0%, transparent 70%)`,
          }}
        />

        {/* Value */}
        <div className="absolute inset-0 flex flex-col items-center justify-center z-10">
          <motion.span
            key={String(value)}
            className={`${sz.text} font-bold font-mono ${col.text} glow-text`}
            initial={{ opacity: 0, y: 5 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3 }}
          >
            {value}
          </motion.span>
          {unit && (
            <span className="text-xs text-jarvis-text-secondary mt-0.5 tracking-widest uppercase">
              {unit}
            </span>
          )}
        </div>
      </div>

      <motion.span
        className={`${sz.label} text-jarvis-text-secondary uppercase tracking-widest mt-4 text-center font-semibold`}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.35 }}
      >
        {title}
      </motion.span>
    </motion.div>
  );
}
