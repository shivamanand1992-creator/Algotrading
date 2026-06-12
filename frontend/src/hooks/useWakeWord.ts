import { useEffect, useRef, useCallback, useState } from 'react';

export type WakePermission = 'pending' | 'granted' | 'denied';
export type WakeSource    = 'clap' | 'voice';

interface Options {
  enabled?: boolean;
  onWake: (source: WakeSource) => void;
}

/**
 * Always-on wake word listener.
 *
 * Triggers `onWake` when:
 *   • A clap is detected (loud transient via AnalyserNode)
 *   • The user says "Vaayu" / "Vayu" (Web Speech API)
 *
 * Automatically requests mic permission on mount.
 * 2-second cooldown after each trigger to avoid double-firing.
 */
export function useWakeWord({ enabled = true, onWake }: Options) {
  const [permission, setPermission] = useState<WakePermission>('pending');

  const cooldownRef = useRef(false);
  const onWakeRef   = useRef(onWake);
  onWakeRef.current = onWake;

  const fire = useCallback((source: WakeSource) => {
    if (cooldownRef.current) return;
    cooldownRef.current = true;
    setTimeout(() => { cooldownRef.current = false; }, 2000);
    onWakeRef.current(source);
  }, []);

  useEffect(() => {
    if (!enabled) return;

    let rafId    = 0;
    let stopped  = false;
    let stream:  MediaStream | null  = null;
    let audioCtx: AudioContext | null = null;

    // ── Clap detection via mic ───────────────────────────────────────
    navigator.mediaDevices
      .getUserMedia({ audio: true, video: false })
      .then(s => {
        if (stopped) { s.getTracks().forEach(t => t.stop()); return; }
        stream  = s;
        setPermission('granted');

        audioCtx = new AudioContext();
        const src      = audioCtx.createMediaStreamSource(s);
        const analyser = audioCtx.createAnalyser();
        analyser.fftSize = 512;
        // Low smoothing so we catch the sharp attack of a clap
        analyser.smoothingTimeConstant = 0.05;
        src.connect(analyser);

        const buf     = new Float32Array(analyser.fftSize);
        let prevRMS   = 0;
        let noisePlane = 0.01; // auto-calibrated quiet-room level

        const loop = () => {
          if (stopped) return;
          analyser.getFloatTimeDomainData(buf);

          let sum = 0;
          for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
          const rms = Math.sqrt(sum / buf.length);

          // Slowly update noise floor so we adapt to ambient room level
          noisePlane = noisePlane * 0.999 + rms * 0.001;

          // Clap = sudden spike: RMS at least 8× the previous frame AND
          // absolute level well above the noise floor
          const ratio = rms / (prevRMS + 0.001);
          if (rms > Math.max(noisePlane * 10, 0.25) && ratio > 8) {
            fire('clap');
          }
          prevRMS = rms;
          rafId = requestAnimationFrame(loop);
        };
        rafId = requestAnimationFrame(loop);
      })
      .catch(() => setPermission('denied'));

    // ── Wake word: "Vaayu" (Web Speech API) ──────────────────────────
    const SpeechRecog =
      (window as any).SpeechRecognition ||
      (window as any).webkitSpeechRecognition;

    let recog: any = null;
    if (SpeechRecog) {
      recog = new SpeechRecog();
      recog.continuous      = true;
      recog.interimResults  = true;
      recog.lang            = 'en-IN';
      recog.maxAlternatives = 3;

      recog.onresult = (e: any) => {
        // Scan last few results from all alternatives
        const text = Array.from(e.results as SpeechRecognitionResultList)
          .slice(-4)
          .flatMap((r: SpeechRecognitionResult) =>
            Array.from({ length: r.length }, (_: unknown, i: number) =>
              r[i].transcript.toLowerCase()
            )
          )
          .join(' ');

        if (
          text.includes('vaayu')  ||
          text.includes('vayu')   ||
          text.includes('vajyu')  ||
          text.includes('bayu')   // common mis-recognition
        ) {
          fire('voice');
        }
      };

      recog.onend = () => {
        if (!stopped) {
          try { recog.start(); } catch {}
        }
      };

      try { recog.start(); } catch {}
    }

    return () => {
      stopped = true;
      cancelAnimationFrame(rafId);
      stream?.getTracks().forEach(t => t.stop());
      audioCtx?.close().catch(() => {});
      if (recog) {
        recog.onend = null;
        try { recog.stop(); } catch {}
      }
    };
  }, [enabled, fire]);

  return { permission };
}
