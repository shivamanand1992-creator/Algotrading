import React, { useEffect, useRef } from 'react';

const CHARS = '01₹VAAYU NIFTY50 BUY SELL ΔΣΦ'.split('');
const FONT_SIZE = 11;

export function ParticleCanvas() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const resize = () => {
      canvas.width  = window.innerWidth;
      canvas.height = window.innerHeight;
    };
    resize();
    window.addEventListener('resize', resize);

    const cols  = Math.ceil(window.innerWidth / FONT_SIZE);
    const drops = Array.from({ length: cols }, () => Math.random() * -80);

    let animId: number;
    const draw = () => {
      ctx.fillStyle = 'rgba(5,13,26,0.055)';
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      ctx.font = `${FONT_SIZE}px "Courier New", monospace`;

      drops.forEach((y, i) => {
        const frac = (y * FONT_SIZE) / canvas.height;
        const alpha = Math.max(0.04, Math.min(0.22, frac * 0.4));
        ctx.fillStyle = `rgba(0,229,255,${alpha})`;
        const char = CHARS[Math.floor(Math.random() * CHARS.length)];
        ctx.fillText(char, i * FONT_SIZE, y * FONT_SIZE);
        if (y * FONT_SIZE > canvas.height && Math.random() > 0.978) {
          drops[i] = 0;
        }
        drops[i] += 0.5;
      });

      animId = requestAnimationFrame(draw);
    };
    draw();

    return () => {
      window.removeEventListener('resize', resize);
      cancelAnimationFrame(animId);
    };
  }, []);

  return (
    <canvas
      id="jarvis-particles"
      ref={canvasRef}
    />
  );
}
