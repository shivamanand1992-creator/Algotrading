import { useState, useRef, useCallback } from 'react';
import { api } from '../api/client';

export type VoiceState = 'idle' | 'loading' | 'speaking' | 'error';

export interface JarvisVoiceState {
  state:    VoiceState;
  script:   string;
  topic:    string;
  error:    string;
  analyser: AnalyserNode | null;
  speak:    (topic: string, onEnd?: () => void) => Promise<void>;
  chat:     (message: string, history?: {role: string; content: string}[], onEnd?: () => void) => Promise<void>;
  stop:     () => void;
}

// iOS Safari routes AudioContext audio through the earpiece (voice call audio session).
// Detect iOS once so we can skip AudioContext routing and play directly to loudspeaker.
const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
  (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);

export function useJarvisVoice(): JarvisVoiceState {
  const [state,    setState]    = useState<VoiceState>('idle');
  const [script,   setScript]   = useState('');
  const [topic,    setTopic]    = useState('');
  const [error,    setError]    = useState('');
  const [analyser, setAnalyser] = useState<AnalyserNode | null>(null);

  const audioRef    = useRef<HTMLAudioElement | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);

  const stop = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.src = '';
      audioRef.current = null;
    }
    if (window.speechSynthesis) window.speechSynthesis.cancel();
    if (audioCtxRef.current && audioCtxRef.current.state !== 'closed') {
      audioCtxRef.current.close().catch(() => {});
      audioCtxRef.current = null;
    }
    setAnalyser(null);
    setState('idle');
  }, []);

  // Shared audio playback logic
  const _playResponse = useCallback(async (
    text: string,
    audioB64: string | null,
    onEnd?: () => void,
  ) => {
    setScript(text);

    if (audioB64) {
      // ElevenLabs audio
      const bytes = atob(audioB64);
      const arr   = new Uint8Array(bytes.length);
      for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i);
      const blob  = new Blob([arr], { type: 'audio/mpeg' });
      const url   = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.setAttribute('playsinline', '');
      audioRef.current = audio;

      if (!isIOS) {
        // Desktop/Android: route through AudioContext for waveform visualiser
        const ctx  = new AudioContext();
        const anl  = ctx.createAnalyser();
        anl.fftSize = 64;
        anl.smoothingTimeConstant = 0.8;
        const src = ctx.createMediaElementSource(audio);
        src.connect(anl);
        anl.connect(ctx.destination);
        audioCtxRef.current = ctx;
        setAnalyser(anl);
      }
      // On iOS: play directly — AudioContext routes to earpiece, direct play uses loudspeaker

      setState('speaking');
      await audio.play();
      audio.onended = () => {
        URL.revokeObjectURL(url);
        if (audioCtxRef.current && audioCtxRef.current.state !== 'closed') {
          audioCtxRef.current.close().catch(() => {});
        }
        audioCtxRef.current = null;
        setAnalyser(null);
        setState('idle');
        onEnd?.();
      };
    } else {
      // Browser Web Speech fallback
      setState('speaking');
      const utter   = new SpeechSynthesisUtterance(text);
      utter.rate    = 0.92;
      utter.pitch   = 0.85;
      utter.volume  = 1;
      const voices  = window.speechSynthesis.getVoices();
      const best    = voices.find(v => /en.*gb/i.test(v.lang) && /male/i.test(v.name))
        ?? voices.find(v => /en/i.test(v.lang));
      if (best) utter.voice = best;
      utter.onend   = () => { setState('idle'); onEnd?.(); };
      utter.onerror = () => { setState('idle'); onEnd?.(); };
      window.speechSynthesis.speak(utter);
    }
  }, []);

  const speak = useCallback(async (topicId: string, onEnd?: () => void) => {
    stop();
    setTopic(topicId);
    setState('loading');
    setScript('');
    setError('');

    try {
      const res = await api.post<{ script: string; audio: string | null }>(
        '/api/jarvis/speak', { topic: topicId }, { timeout: 45000 },
      );
      await _playResponse(res.data.script, res.data.audio, onEnd);
    } catch (exc: any) {
      const msg = exc?.response?.data?.detail ?? exc?.message ?? 'Unknown error';
      setError(msg);
      setState('error');
      onEnd?.();
    }
  }, [stop, _playResponse]);

  const chat = useCallback(async (
    message: string,
    history: {role: string; content: string}[] = [],
    onEnd?: () => void,
  ) => {
    stop();
    setState('loading');
    setScript('');
    setError('');

    try {
      const res = await api.post<{ script: string; audio: string | null }>(
        '/api/jarvis/chat', { message, history }, { timeout: 30000 },
      );
      await _playResponse(res.data.script, res.data.audio, onEnd);
    } catch (exc: any) {
      const msg = exc?.response?.data?.detail ?? exc?.message ?? 'Chat failed';
      setError(msg);
      setState('error');
      onEnd?.();
    }
  }, [stop, _playResponse]);

  return { state, script, topic, error, analyser, speak, chat, stop };
}
