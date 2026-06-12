import { useState, useRef, useCallback } from 'react';
import { api } from '../api/client';

export type VoiceState = 'idle' | 'loading' | 'speaking' | 'error';

export interface JarvisVoiceState {
  state:        VoiceState;
  script:       string;
  topic:        string;
  error:        string;
  audioCtx:     AudioContext | null;
  analyser:     AnalyserNode | null;
  speak:        (topic: string) => Promise<void>;
  stop:         () => void;
}

export function useJarvisVoice(): JarvisVoiceState {
  const [state,  setState]  = useState<VoiceState>('idle');
  const [script, setScript] = useState('');
  const [topic,  setTopic]  = useState('');
  const [error,  setError]  = useState('');
  const [audioCtx,  setAudioCtx]  = useState<AudioContext | null>(null);
  const [analyser,  setAnalyser]  = useState<AnalyserNode | null>(null);

  const audioRef      = useRef<HTMLAudioElement | null>(null);
  const utteranceRef  = useRef<SpeechSynthesisUtterance | null>(null);
  const audioCtxRef   = useRef<AudioContext | null>(null);

  const stop = useCallback(() => {
    // Stop HTML5 audio
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.src = '';
      audioRef.current = null;
    }
    // Stop browser TTS
    if (window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }
    // Close AudioContext
    if (audioCtxRef.current && audioCtxRef.current.state !== 'closed') {
      audioCtxRef.current.close().catch(() => {});
      audioCtxRef.current = null;
    }
    setAudioCtx(null);
    setAnalyser(null);
    setState('idle');
  }, []);

  const speak = useCallback(async (topicId: string) => {
    stop();
    setTopic(topicId);
    setState('loading');
    setScript('');
    setError('');

    try {
      const res = await api.post<{ script: string; audio: string | null }>(
        '/api/jarvis/speak', { topic: topicId },
        { timeout: 45000 }
      );

      const { script: text, audio: audioB64 } = res.data;
      setScript(text);

      if (audioB64) {
        // ── ElevenLabs audio path ──────────────────────────────────
        const bytes     = atob(audioB64);
        const arr       = new Uint8Array(bytes.length);
        for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i);
        const blob      = new Blob([arr], { type: 'audio/mpeg' });
        const url       = URL.createObjectURL(blob);
        const audio     = new Audio(url);
        audioRef.current = audio;

        // Wire to Web Audio API for visualiser
        const ctx      = new AudioContext();
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 64; // 32 bars
        analyser.smoothingTimeConstant = 0.8;
        const src = ctx.createMediaElementSource(audio);
        src.connect(analyser);
        analyser.connect(ctx.destination);
        audioCtxRef.current = ctx;
        setAudioCtx(ctx);
        setAnalyser(analyser);

        setState('speaking');
        await audio.play();
        audio.onended = () => {
          URL.revokeObjectURL(url);
          if (audioCtxRef.current && audioCtxRef.current.state !== 'closed') {
            audioCtxRef.current.close().catch(() => {});
          }
          audioCtxRef.current = null;
          setAudioCtx(null);
          setAnalyser(null);
          setState('idle');
        };
      } else {
        // ── Browser Web Speech fallback ────────────────────────────
        setState('speaking');
        const utter    = new SpeechSynthesisUtterance(text);
        utter.rate     = 0.92;
        utter.pitch    = 0.85;
        utter.volume   = 1;
        // Pick the deepest English male voice available
        const voices = window.speechSynthesis.getVoices();
        const best   = voices.find(v => /en.*gb/i.test(v.lang) && /male/i.test(v.name))
          ?? voices.find(v => /en/i.test(v.lang));
        if (best) utter.voice = best;
        utteranceRef.current = utter;
        utter.onend = () => setState('idle');
        utter.onerror = () => setState('idle');
        window.speechSynthesis.speak(utter);
      }
    } catch (exc: any) {
      const msg = exc?.response?.data?.detail ?? exc?.message ?? 'Unknown error';
      setError(msg);
      setState('error');
    }
  }, [stop]);

  return { state, script, topic, error, audioCtx, analyser, speak, stop };
}
