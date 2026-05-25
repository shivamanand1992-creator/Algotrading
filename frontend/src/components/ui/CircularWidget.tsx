import React from 'react';

interface CircularWidgetProps {
  title: string;
  value: string | number;
  unit?: string;
  progress?: number; // 0-100
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

const sizes = {
  sm: { container: 'w-24 h-24', text: 'text-lg', label: 'text-xs' },
  md: { container: 'w-32 h-32', text: 'text-2xl', label: 'text-sm' },
  lg: { container: 'w-48 h-48', text: 'text-4xl', label: 'text-base' },
};

export function CircularWidget({
  title,
  value,
  unit,
  progress,
  size = 'md',
  className = '',
}: CircularWidgetProps) {
  const sizeClasses = sizes[size];
  const radius = size === 'sm' ? 40 : size === 'md' ? 56 : 88;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = progress
    ? circumference - (progress / 100) * circumference
    : 0;

  return (
    <div className={`flex flex-col items-center ${className}`}>
      <div className={`relative ${sizeClasses.container}`}>
        {/* Background circle */}
        <svg className="absolute inset-0 w-full h-full -rotate-90">
          <circle
            cx="50%"
            cy="50%"
            r={radius}
            fill="none"
            stroke="rgba(0, 229, 255, 0.1)"
            strokeWidth="3"
          />
          {progress !== undefined && (
            <circle
              cx="50%"
              cy="50%"
              r={radius}
              fill="none"
              stroke="var(--jarvis-primary)"
              strokeWidth="3"
              strokeDasharray={circumference}
              strokeDashoffset={strokeDashoffset}
              strokeLinecap="round"
              className="transition-all duration-500 ease-out"
              style={{
                filter: 'drop-shadow(0 0 8px var(--jarvis-glow))',
              }}
            />
          )}
        </svg>

        {/* Rotating border effect */}
        <div
          className="absolute inset-0 rounded-full opacity-50 animate-spin-slow"
          style={{
            background:
              'conic-gradient(from 0deg, transparent 0%, var(--jarvis-primary) 50%, transparent 100%)',
            WebkitMask: 'radial-gradient(farthest-side, transparent calc(100% - 2px), #fff calc(100% - 2px))',
            mask: 'radial-gradient(farthest-side, transparent calc(100% - 2px), #fff calc(100% - 2px))',
          }}
        />

        {/* Content */}
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span
            className={`${sizeClasses.text} font-bold font-mono text-jarvis-primary glow-text`}
          >
            {value}
          </span>
          {unit && (
            <span className="text-xs text-jarvis-text-secondary mt-1">
              {unit}
            </span>
          )}
        </div>
      </div>

      {/* Label */}
      <span
        className={`${sizeClasses.label} text-jarvis-text-secondary uppercase tracking-wider mt-3 text-center`}
      >
        {title}
      </span>
    </div>
  );
}
