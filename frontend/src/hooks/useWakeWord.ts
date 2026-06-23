import { useEffect, useRef, useState, useCallback } from 'react';

interface UseWakeWordOptions {
  enabled: boolean;
  onWake: (source: 'clap' | 'voice') => void;
}

export function useWakeWord({ enabled, onWake }: UseWakeWordOptions) {
  const [permission, setPermission] = useState<'prompt' | 'granted' | 'denied'>('prompt');

  const audioCtxRef  = useRef<AudioContext | null>(null);
  const animFrameRef = useRef<number | null>(null);
  const recogRef     = useRef<any>(null);
  const lastWakeRef  = useRef<number>(0);
  const streamRef    = useRef<MediaStream | null>(null);

  // Always-current ref so async callbacks (onend, setTimeout) never read a stale closure value.
  // Without this, when enabled flips false the pending onend callback still sees enabled=true
  // and relaunches the recognition — blocking Chrome from starting conversation recognition.
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;

  const COOLDOWN_MS = 2000;

  const triggerWake = useCallback((source: 'clap' | 'voice') => {
    const now = Date.now();
    if (now - lastWakeRef.current < COOLDOWN_MS) return;
    lastWakeRef.current = now;
    onWake(source);
  }, [onWake]);

  // ── Clap / sound-spike detection ─────────────────────────────────
  useEffect(() => {
    if (!enabled) {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
      if (audioCtxRef.current) { audioCtxRef.current.close().catch(() => {}); audioCtxRef.current = null; }
      if (streamRef.current) { streamRef.current.getTracks().forEach(t => t.stop()); streamRef.current = null; }
      return;
    }

    navigator.mediaDevices.getUserMedia({ audio: true }).then(stream => {
      streamRef.current = stream;
      setPermission('granted');

      const ctx = new AudioContext();
      audioCtxRef.current = ctx;
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.3;
      ctx.createMediaStreamSource(stream).connect(analyser);

      const buf = new Float32Array(analyser.fftSize);
      let prevRms    = 0;
      let noiseFloor = 0;

      const detect = () => {
        analyser.getFloatTimeDomainData(buf);
        let sum = 0;
        for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
        const rms = Math.sqrt(sum / buf.length);

        noiseFloor = noiseFloor * 0.999 + rms * 0.001;

        if (rms > prevRms * 8 && rms > noiseFloor * 10 && rms > 0.015) {
          triggerWake('clap');
        }

        prevRms = rms * 0.7 + prevRms * 0.3;
        animFrameRef.current = requestAnimationFrame(detect);
      };

      animFrameRef.current = requestAnimationFrame(detect);
    }).catch(() => {
      setPermission('denied');
    });

    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
      if (audioCtxRef.current) { audioCtxRef.current.close().catch(() => {}); audioCtxRef.current = null; }
      if (streamRef.current) { streamRef.current.getTracks().forEach(t => t.stop()); streamRef.current = null; }
    };
  }, [enabled, triggerWake]);

  // ── Voice wake word detection ─────────────────────────────────────
  useEffect(() => {
    if (!enabled) {
      if (recogRef.current) {
        try { recogRef.current.stop(); } catch {}
        recogRef.current = null;
      }
      return;
    }

    const SpeechRecog = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecog) return;

    const WAKE_TRIGGERS = [
      'vaayu', 'vayu', 'vajyu', 'bayu', 'wayu', 'vayoo', 'bayou',
      'buy you', 'why you', 'wai u', 'vau', 'vaau',
      'hey vaayu', 'hey vayu', 'hey bayu', 'hey vaau',
      'hello vaayu', 'hello vayu', 'hello bayu',
      'hi vaayu', 'hi vayu',
      'ok vaayu', 'okay vaayu',
    ];

    const launch = () => {
      // Read from ref — not the closure — so this always sees the current enabled state
      if (!enabledRef.current) return;

      const recog = new SpeechRecog();
      recog.continuous     = true;
      recog.interimResults = true;
      recog.lang           = 'en-IN';
      recogRef.current     = recog;

      recog.onresult = (e: any) => {
        const texts: string[] = [];
        for (let i = e.resultIndex; i < e.results.length; i++) {
          texts.push(e.results[i][0].transcript.toLowerCase().trim());
        }
        const combined = texts.join(' ');
        if (WAKE_TRIGGERS.some(w => combined.includes(w))) {
          triggerWake('voice');
        }
      };

      recog.onend = () => {
        recogRef.current = null;
        // Use ref here — this callback fires asynchronously after React may have
        // already flipped enabled to false; without the ref we'd relaunch with a
        // stale enabled=true and block Chrome from starting conversation recognition.
        if (enabledRef.current) setTimeout(launch, 300);
      };

      recog.onerror = () => {};

      try { recog.start(); } catch {}
    };

    launch();

    return () => {
      if (recogRef.current) {
        try { recogRef.current.stop(); } catch {}
        recogRef.current = null;
      }
    };
  }, [enabled, triggerWake]); // eslint-disable-line react-hooks/exhaustive-deps

  return { permission };
}
