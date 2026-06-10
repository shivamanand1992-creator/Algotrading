import React, { useMemo } from 'react';

interface VectorSpec {
  id: number;
  type: 'buy' | 'sell';
  top: string;
  width: number;
  angle: number;
  delay: number;
  duration: number;
}

// Seeded random so SSR / hydration won't mismatch
function seeded(seed: number) {
  const s = Math.sin(seed * 9301 + 49297) * 233280;
  return s - Math.floor(s);
}

interface OrderFlowVectorsProps {
  count?: number;
  buyBias?: number; // 0-1, fraction that are buy
}

export function OrderFlowVectors({ count = 7, buyBias = 0.55 }: OrderFlowVectorsProps) {
  const vectors = useMemo<VectorSpec[]>(() => {
    return Array.from({ length: count }, (_, i) => ({
      id:       i,
      type:     seeded(i * 3)     < buyBias ? 'buy' : 'sell',
      top:      `${4 + seeded(i * 7) * 90}%`,
      width:    70 + seeded(i * 11) * 140,
      angle:    (seeded(i * 13) - 0.5) * 14,
      delay:    seeded(i * 17) * 7,
      duration: 2.2 + seeded(i * 19) * 3.5,
    }));
  }, [count, buyBias]);

  return (
    <div style={{ position: 'absolute', inset: 0, overflow: 'hidden', pointerEvents: 'none', zIndex: 1 }}>
      {vectors.map(v => (
        <div
          key={v.id}
          className={`order-vector order-vector-${v.type}`}
          style={{
            top:     v.top,
            width:   v.width,
            '--angle': `${v.angle}deg`,
            '--delay': `${v.delay}s`,
            '--dur':   `${v.duration}s`,
          } as React.CSSProperties}
        />
      ))}
    </div>
  );
}
