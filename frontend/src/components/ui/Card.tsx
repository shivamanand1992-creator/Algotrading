import React, { ReactNode, useRef } from 'react';
import { motion, useMotionValue, useSpring, useTransform } from 'framer-motion';

interface CardProps {
  title?: string;
  children: ReactNode;
  className?: string;
  headerAction?: ReactNode;
  glow?: boolean;
  scanLine?: boolean;
}

export function Card({ title, children, className = '', headerAction, glow = false, scanLine = false }: CardProps) {
  const ref = useRef<HTMLDivElement>(null);
  const rawX = useMotionValue(0);
  const rawY = useMotionValue(0);
  const spring = { damping: 25, stiffness: 350 };
  const rotateX = useSpring(useTransform(rawY, [-120, 120], [6, -6]), spring);
  const rotateY = useSpring(useTransform(rawX, [-120, 120], [-6, 6]), spring);
  const glowX   = useSpring(useTransform(rawX, [-120, 120], [0, 100]), spring);
  const glowY   = useSpring(useTransform(rawY, [-120, 120], [0, 100]), spring);

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!ref.current) return;
    const rect = ref.current.getBoundingClientRect();
    rawX.set(e.clientX - rect.left - rect.width / 2);
    rawY.set(e.clientY - rect.top - rect.height / 2);
  };

  const handleMouseLeave = () => {
    rawX.set(0);
    rawY.set(0);
  };

  return (
    <motion.div
      ref={ref}
      className={`glass-panel p-6 ${glow ? 'neon-border' : ''} ${className}`}
      style={{
        rotateX,
        rotateY,
        transformStyle: 'preserve-3d',
        perspective: 1200,
        backgroundImage: useTransform(
          [glowX, glowY],
          ([x, y]) =>
            `radial-gradient(circle at ${x}% ${y}%, rgba(0,229,255,0.06) 0%, transparent 60%)`
        ) as any,
      }}
      whileHover={{ scale: 1.012 }}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
      transition={{ scale: { duration: 0.2 } }}
    >
      {scanLine && <div className="scan-line" />}

      <div style={{ transform: 'translateZ(4px)' }}>
        {title && (
          <div className="flex items-center justify-between mb-4 pb-3 border-b border-jarvis-primary/20">
            <h3 className="text-xs font-bold text-jarvis-primary uppercase tracking-widest flex items-center gap-2">
              <span className="inline-block w-1 h-4 bg-jarvis-primary rounded-full" />
              {title}
            </h3>
            {headerAction && <div>{headerAction}</div>}
          </div>
        )}
        {children}
      </div>
    </motion.div>
  );
}
