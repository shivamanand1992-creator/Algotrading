import React, { useEffect, useRef } from 'react';

interface AudioVisualizerProps {
  analyser:    AnalyserNode | null;
  isSpeaking:  boolean;
  width?:      number;
  height?:     number;
}

const BARS         = 32;
const BAR_GAP      = 2;
const COLOR_TOP    = 'rgba(0,229,255,0.9)';
const COLOR_BOTTOM = 'rgba(0,100,200,0.5)';

// CSS-animation fallback heights (simulate voice activity)
const FALLBACK_HEIGHTS = Array.from({ length: BARS }, (_, i) => {
  const x = (i / BARS) * Math.PI * 2;
  return 0.25 + 0.55 * Math.abs(Math.sin(x * 2.3 + 1));
});

export function AudioVisualizer({
  analyser, isSpeaking, width = 320, height = 80,
}: AudioVisualizerProps) {
  const canvasRef   = useRef<HTMLCanvasElement>(null);
  const frameRef    = useRef<number>(0);
  const phaseRef    = useRef<number>(0);  // for CSS-fallback animation

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    canvas.width  = width;
    canvas.height = height;

    const barW = (width / BARS) - BAR_GAP;
    const data  = new Uint8Array(analyser ? analyser.frequencyBinCount : BARS);

    const draw = () => {
      ctx.clearRect(0, 0, width, height);

      if (analyser) {
        analyser.getByteFrequencyData(data);
      }

      for (let i = 0; i < BARS; i++) {
        let fraction: number;

        if (analyser && isSpeaking) {
          fraction = (data[i] ?? 0) / 255;
        } else if (isSpeaking) {
          // CSS-animation fallback — oscillating bars
          const wave = FALLBACK_HEIGHTS[i] * Math.abs(Math.sin(phaseRef.current * 2 + i * 0.4));
          fraction   = 0.08 + wave;
        } else {
          // Idle — tiny baseline bars
          fraction = 0.04;
        }

        const barH    = Math.max(3, fraction * height * 0.92);
        const x       = i * (barW + BAR_GAP);
        const y       = height - barH;

        const grad = ctx.createLinearGradient(0, y, 0, height);
        grad.addColorStop(0, COLOR_TOP);
        grad.addColorStop(1, COLOR_BOTTOM);

        ctx.shadowBlur  = fraction > 0.5 ? 8 : 3;
        ctx.shadowColor = 'rgba(0,229,255,0.6)';
        ctx.fillStyle   = grad;

        // Rounded top
        ctx.beginPath();
        const r = Math.min(barW / 2, 2);
        ctx.moveTo(x + r, y);
        ctx.lineTo(x + barW - r, y);
        ctx.quadraticCurveTo(x + barW, y, x + barW, y + r);
        ctx.lineTo(x + barW, height);
        ctx.lineTo(x, height);
        ctx.lineTo(x, y + r);
        ctx.quadraticCurveTo(x, y, x + r, y);
        ctx.closePath();
        ctx.fill();
      }

      ctx.shadowBlur = 0;
      phaseRef.current += 0.045;
      frameRef.current  = requestAnimationFrame(draw);
    };

    draw();
    return () => cancelAnimationFrame(frameRef.current);
  }, [analyser, isSpeaking, width, height]);

  return (
    <canvas
      ref={canvasRef}
      style={{
        display:      'block',
        borderRadius: 4,
        opacity:      isSpeaking ? 1 : 0.3,
        transition:   'opacity 0.4s',
      }}
    />
  );
}
