import { useRef, useCallback } from 'react';

export function useTilt(maxDeg = 8) {
  const ref = useRef<HTMLDivElement>(null);

  const onMouseMove = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    const el = ref.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const dx = ((e.clientX - rect.left) / rect.width  - 0.5) * 2;
    const dy = ((e.clientY - rect.top)  / rect.height - 0.5) * 2;
    el.style.transform = `perspective(600px) rotateY(${dx * maxDeg}deg) rotateX(${-dy * maxDeg}deg) scale(1.025)`;
    el.style.transition = 'transform 0.08s ease-out';
  }, [maxDeg]);

  const onMouseLeave = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    el.style.transform = 'perspective(600px) rotateX(0deg) rotateY(0deg) scale(1)';
    el.style.transition = 'transform 0.35s ease-out';
  }, []);

  return { ref, onMouseMove, onMouseLeave };
}
