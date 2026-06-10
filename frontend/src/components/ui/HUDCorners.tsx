import React, { ReactNode } from 'react';

interface HUDCornersProps {
  children: ReactNode;
  className?: string;
  quad?: boolean;
  color?: string;
  style?: React.CSSProperties;
  onClick?: () => void;
}

export function HUDCorners({
  children, className = '', quad = false, color, style, onClick,
}: HUDCornersProps) {
  return (
    <div
      className={`${quad ? 'hud-quad' : 'hud-corners'} ${className}`}
      style={
        {
          '--hud-color': color,
          '--hud-c':     color,
          ...style,
        } as React.CSSProperties
      }
      onClick={onClick}
    >
      {children}
    </div>
  );
}
