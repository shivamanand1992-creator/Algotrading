import React, { useEffect, useRef, useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useJarvisVoice } from '../../hooks/useJarvisVoice';
import { useWakeWord } from '../../hooks/useWakeWord';
import { AudioVisualizer } from './AudioVisualizer';
import { api } from '../../api/client';
import { setVaayuConvState } from '../../stores/vaayuStore';

// ── Types ─────────────────────────────────────────────────────────────────

type ConvState = 'closed' | 'loading' | 'speaking' | 'listening' | 'processing';

interface Message {
  id:   number;
  role: 'vaayu' | 'user';
  text: string;
  time: string;
}

interface Topic { id: string; label: string; icon: string; desc: string; }

const FALLBACK_TOPICS: Topic[] = [
  { id: 'market_summary', label: 'Market Summary', icon: '◈', desc: 'Nifty status & trend' },
  { id: 'my_positions',   label: 'My Positions',   icon: '⬡', desc: 'Portfolio P&L' },
  { id: 'news_brief',     label: 'News Brief',      icon: '≡', desc: 'AI-summarised headlines' },
  { id: 'global_cues',    label: 'Global Cues',     icon: '⊕', desc: 'US, Asia & commodities' },
  { id: 'nifty_trend',    label: 'Nifty Trend',     icon: '↗', desc: 'Technical deep-dive' },
  { id: 'full_briefing',  label: 'Full Briefing',   icon: '⊞', desc: '90-second overview' },
];

const now = () => new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false });
let msgCounter = 0;

// ── Small avatar (used in chat bubbles) ───────────────────────────────────

function VaayuDot({ speaking }: { speaking: boolean }) {
  return (
    <div style={{
      width: 28, height: 28, borderRadius: '50%',
      background: 'linear-gradient(135deg, rgba(0,229,255,0.2), rgba(124,58,237,0.3))',
      border: `1.5px solid ${speaking ? 'rgba(0,229,255,0.8)' : 'rgba(0,229,255,0.35)'}`,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      flexShrink: 0,
      boxShadow: speaking ? '0 0 10px rgba(0,229,255,0.4)' : 'none',
    }}>
      <span style={{ fontSize: 12, fontFamily: 'monospace', fontWeight: 900, color: '#00e5ff' }}>V</span>
    </div>
  );
}

// ── Chat bubble ───────────────────────────────────────────────────────────

function Bubble({ msg, isLatest, isSpeaking }: {
  msg: Message; isLatest: boolean; isSpeaking: boolean;
}) {
  const isVaayu    = msg.role === 'vaayu';
  const shouldType = isVaayu && isLatest && msg.text !== '…' && msg.text.length > 0;

  const [displayed, setDisplayed] = useState<string>(shouldType ? '' : msg.text);
  const [typing,    setTyping]    = useState(shouldType);

  useEffect(() => {
    if (!isVaayu || !shouldType) { setDisplayed(msg.text); setTyping(false); return; }
    setDisplayed('');
    setTyping(true);
    let i = 0;
    const total = msg.text.length;
    const speed = Math.max(8, Math.min(22, 2500 / total));
    const iv = setInterval(() => {
      i++;
      setDisplayed(msg.text.slice(0, i));
      if (i >= total) { clearInterval(iv); setTyping(false); }
    }, speed);
    return () => clearInterval(iv);
  }, [msg.text, shouldType, isVaayu]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22 }}
      style={{
        display: 'flex',
        flexDirection: isVaayu ? 'row' : 'row-reverse',
        alignItems: 'flex-start',
        gap: 8, marginBottom: 12,
      }}
    >
      {isVaayu && <VaayuDot speaking={isSpeaking} />}
      <div style={{
        maxWidth: '86%',
        padding: '10px 14px',
        borderRadius: isVaayu ? '4px 14px 14px 14px' : '14px 4px 14px 14px',
        background: isVaayu ? 'rgba(0,229,255,0.05)' : 'rgba(124,58,237,0.12)',
        border: `1px solid ${isVaayu ? 'rgba(0,229,255,0.13)' : 'rgba(124,58,237,0.26)'}`,
        boxShadow: isVaayu ? '0 2px 12px rgba(0,229,255,0.04)' : 'none',
      }}>
        <div style={{
          fontSize: 7, letterSpacing: '0.14em', marginBottom: 5,
          display: 'flex', justifyContent: 'space-between', gap: 16,
          color: isVaayu ? 'rgba(0,229,255,0.45)' : 'rgba(160,120,255,0.55)',
          fontFamily: 'monospace',
        }}>
          <span>{isVaayu ? 'VAAYU' : 'YOU'}</span>
          <span>{msg.time}</span>
        </div>
        <p style={{
          fontSize: 12.5, lineHeight: 1.65,
          color: isVaayu ? 'rgba(210,232,248,0.92)' : 'rgba(210,195,255,0.92)',
          fontFamily: 'system-ui, -apple-system, sans-serif',
          margin: 0, whiteSpace: 'pre-wrap',
        }}>
          {displayed}
          {typing && (
            <motion.span
              animate={{ opacity: [1, 0, 1] }}
              transition={{ duration: 0.85, repeat: Infinity, ease: 'linear' }}
              style={{ color: '#00e5ff', marginLeft: 1 }}
            >
              ▋
            </motion.span>
          )}
        </p>
      </div>
    </motion.div>
  );
}

// ── Listening indicator ───────────────────────────────────────────────────

const BAR_SHAPE = [0.45, 0.75, 1.0, 0.9, 1.0, 0.7, 0.4];

function ListeningBar({ transcript, timeout, pauseCountdown, micLevel }: {
  transcript: string; timeout: number; pauseCountdown: number | null; micLevel: number;
}) {
  const isHearing   = micLevel > 0.04;
  const isThinking  = pauseCountdown !== null;

  return (
    <div style={{
      padding: '12px 14px',
      background: isThinking ? 'rgba(0,229,255,0.05)' : isHearing ? 'rgba(124,58,237,0.12)' : 'rgba(124,58,237,0.06)',
      border: `1px solid ${isThinking ? 'rgba(0,229,255,0.35)' : isHearing ? 'rgba(168,85,247,0.55)' : 'rgba(124,58,237,0.22)'}`,
      borderRadius: 10,
      display: 'flex', alignItems: 'center', gap: 10,
      transition: 'background 0.2s, border-color 0.2s',
    }}>

      {/* Real-time mic bars — height driven by actual AudioContext level */}
      <div style={{ flexShrink: 0, display: 'flex', gap: 3, alignItems: 'center', height: 32 }}>
        {BAR_SHAPE.map((shape, i) => {
          const h = isThinking
            ? 3
            : Math.max(3, Math.min(28, micLevel * 140 * shape));
          return (
            <div
              key={i}
              style={{
                width: 3,
                height: h,
                borderRadius: 3,
                background: isThinking
                  ? '#00e5ff'
                  : isHearing
                    ? `rgba(168,85,247,${0.6 + shape * 0.4})`
                    : 'rgba(124,58,237,0.3)',
                transition: 'height 0.07s ease-out, background 0.15s',
              }}
            />
          );
        })}
      </div>

      {/* Status text */}
      <div style={{ flex: 1, minWidth: 0 }}>
        {isThinking ? (
          <p style={{ margin: 0, fontSize: 10, color: 'rgba(0,229,255,0.85)', fontFamily: 'monospace', letterSpacing: '0.1em' }}>
            Got it — thinking…
          </p>
        ) : transcript ? (
          <p style={{
            margin: 0, fontSize: 11, color: 'rgba(210,185,255,0.95)',
            fontFamily: 'monospace', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
          }}>
            "{transcript}"
          </p>
        ) : isHearing ? (
          <p style={{ margin: 0, fontSize: 10, color: 'rgba(168,85,247,0.95)', fontFamily: 'monospace', letterSpacing: '0.1em', fontWeight: 700 }}>
            HEARING YOU…
          </p>
        ) : (
          <p style={{ margin: 0, fontSize: 10, color: 'rgba(124,58,237,0.6)', fontFamily: 'monospace', letterSpacing: '0.1em' }}>
            LISTENING… SPEAK NOW
          </p>
        )}
      </div>

      {/* Timeout arc */}
      <svg width={20} height={20} style={{ flexShrink: 0 }}>
        <circle cx={10} cy={10} r={8} fill="none" stroke="rgba(124,58,237,0.15)" strokeWidth={2} />
        <circle cx={10} cy={10} r={8} fill="none"
          stroke={isThinking ? 'rgba(0,229,255,0.6)' : 'rgba(124,58,237,0.55)'}
          strokeWidth={2}
          strokeDasharray={`${50.3 * timeout} 50.3`}
          strokeLinecap="round"
          transform="rotate(-90 10 10)"
        />
      </svg>
    </div>
  );
}

// ── FAB Button ────────────────────────────────────────────────────────────

function FabButton({ convOpen, convState, micReady, onClick }: {
  convOpen: boolean; convState: ConvState; micReady: boolean; onClick: () => void;
}) {
  const active    = convOpen && convState !== 'closed';
  const isLoading = convState === 'loading';

  return (
    <div style={{ position: 'relative', width: 60, height: 60 }}>
      {/* Pulse ring when idle + mic active */}
      {micReady && !convOpen && (
        <motion.div
          style={{
            position: 'absolute', inset: -5, borderRadius: '50%',
            border: '1px solid rgba(0,229,255,0.3)', pointerEvents: 'none',
          }}
          animate={{ scale: [1, 1.22, 1], opacity: [0.5, 0.05, 0.5] }}
          transition={{ duration: 2.8, repeat: Infinity, ease: 'easeInOut' }}
        />
      )}

      {/* Listening ring */}
      {convState === 'listening' && (
        <motion.div
          style={{
            position: 'absolute', inset: -6, borderRadius: '50%',
            border: '2px solid rgba(124,58,237,0.7)', pointerEvents: 'none',
          }}
          animate={{ scale: [1, 1.15, 1], opacity: [0.8, 0.3, 0.8] }}
          transition={{ duration: 1.4, repeat: Infinity, ease: 'easeInOut' }}
        />
      )}

      {/* Mic status dot */}
      <div style={{
        position: 'absolute', top: 2, right: 2, width: 8, height: 8,
        borderRadius: '50%',
        background: convState === 'listening'
          ? '#a855f7'
          : micReady ? '#4ade80' : '#6b7280',
        border: '1.5px solid rgba(2,4,18,0.9)',
        zIndex: 2,
        boxShadow: convState === 'listening'
          ? '0 0 6px rgba(168,85,247,0.8)'
          : micReady ? '0 0 5px rgba(74,222,128,0.6)' : 'none',
      }} />

      <motion.button
        onClick={onClick}
        animate={
          convState === 'speaking'
            ? { scale: [1, 1.1, 1], boxShadow: ['0 0 0px rgba(0,229,255,0)', '0 0 24px rgba(0,229,255,0.6)', '0 0 0px rgba(0,229,255,0)'] }
            : convState === 'listening'
              ? { boxShadow: ['0 0 0px rgba(168,85,247,0)', '0 0 18px rgba(168,85,247,0.5)', '0 0 0px rgba(168,85,247,0)'] }
              : isLoading
                ? { rotate: 360 }
                : {}
        }
        transition={
          convState === 'speaking' || convState === 'listening'
            ? { duration: 1.6, repeat: Infinity, ease: 'easeInOut' }
            : isLoading
              ? { duration: 2, repeat: Infinity, ease: 'linear' }
              : {}
        }
        title={
          convState === 'speaking' ? 'Speak or tap to interrupt'
          : convOpen ? 'Close VAAYU'
          : 'Talk to VAAYU'
        }
        style={{
          width: 60, height: 60, borderRadius: '50%',
          background: active
            ? 'linear-gradient(135deg, rgba(0,229,255,0.2), rgba(80,20,160,0.4))'
            : 'linear-gradient(135deg, rgba(2,4,18,0.95), rgba(0,15,50,0.95))',
          border: `1.5px solid ${active ? 'rgba(0,229,255,0.65)' : 'rgba(0,229,255,0.25)'}`,
          boxShadow: active ? '0 0 20px rgba(0,229,255,0.3)' : '0 4px 20px rgba(0,0,0,0.5)',
          cursor: 'pointer',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          outline: 'none',
        }}
      >
        <svg width={26} height={26} viewBox="0 0 26 26" fill="none">
          <polygon points="13,2 22,7.5 22,18.5 13,24 4,18.5 4,7.5"
            fill="rgba(0,229,255,0.07)" stroke="rgba(0,229,255,0.55)" strokeWidth="1.2" />
          <text x="13" y="17.5" textAnchor="middle"
            style={{ fontFamily: 'monospace', fontSize: 11, fontWeight: 900, fill: '#00e5ff' }}>
            V
          </text>
        </svg>
      </motion.button>
    </div>
  );
}

// ── Main Panel ────────────────────────────────────────────────────────────

export function JarvisVoicePanel() {
  const [convOpen,       setConvOpen]       = useState(false);
  const [convState,      setConvState]      = useState<ConvState>('closed');
  const [messages,       setMessages]       = useState<Message[]>([]);
  const [transcript,     setTranscript]     = useState('');
  const [listenTimer,    setListenTimer]    = useState(1.0);
  const [pauseCountdown, setPauseCountdown] = useState<number | null>(null);
  const [topics,         setTopics]         = useState<Topic[]>(FALLBACK_TOPICS);
  const [showTopics,     setShowTopics]     = useState(false);
  const [textInput,      setTextInput]      = useState('');
  const [micLevel,      setMicLevel]       = useState(0);

  // Detect once: Safari / iOS Chrome have no SpeechRecognition API
  const hasSTT = !!(
    (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
  );

  const voice          = useJarvisVoice();
  const scrollRef      = useRef<HTMLDivElement>(null);
  const textInputRef   = useRef<HTMLInputElement>(null);
  const recogRef       = useRef<any>(null);
  const listenTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const stateRef        = useRef<ConvState>('closed');
  stateRef.current      = convState;
  const bargeInRef      = useRef<any>(null);
  const startListenRef  = useRef<() => void>(() => {});
  const pauseTimerRef        = useRef<ReturnType<typeof setTimeout> | null>(null);
  const countdownRef         = useRef<ReturnType<typeof setInterval> | null>(null);
  const handleUserQuestionRef = useRef<(q: string) => void>(() => {});
  const micCtxRef    = useRef<AudioContext | null>(null);
  const micStreamRef = useRef<MediaStream | null>(null);
  const micAnimRef   = useRef<number | null>(null);

  // Load topics from API
  useEffect(() => {
    api.get<Topic[]>('/api/jarvis/topics')
      .then(r => { if (r.data?.length) setTopics(r.data); })
      .catch(() => {});
  }, []);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
    }
  }, [messages, transcript]);

  // ── Add message to chat ──────────────────────────────────────────
  const addMessage = useCallback((role: 'vaayu' | 'user', text: string) => {
    setMessages(prev => [...prev, { id: ++msgCounter, role, text, time: now() }]);
  }, []);

  // ── Clear pause countdown ────────────────────────────────────────
  const clearPauseTimer = useCallback(() => {
    if (pauseTimerRef.current) { clearTimeout(pauseTimerRef.current); pauseTimerRef.current = null; }
    if (countdownRef.current)  { clearInterval(countdownRef.current); countdownRef.current = null; }
    setPauseCountdown(null);
  }, []);

  // ── Mic level monitor (parallel to SpeechRecognition) ───────────
  const stopMicMonitor = useCallback(() => {
    if (micAnimRef.current)   { cancelAnimationFrame(micAnimRef.current); micAnimRef.current = null; }
    if (micCtxRef.current)    { micCtxRef.current.close().catch(() => {}); micCtxRef.current = null; }
    if (micStreamRef.current) { micStreamRef.current.getTracks().forEach(t => t.stop()); micStreamRef.current = null; }
    setMicLevel(0);
  }, []);

  const startMicMonitor = useCallback(() => {
    stopMicMonitor();
    navigator.mediaDevices.getUserMedia({ audio: true, video: false }).then(stream => {
      micStreamRef.current = stream;
      const ctx = new AudioContext();
      micCtxRef.current = ctx;
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 64;
      analyser.smoothingTimeConstant = 0.8;
      ctx.createMediaStreamSource(stream).connect(analyser);
      const buf = new Uint8Array(analyser.frequencyBinCount);
      const tick = () => {
        analyser.getByteFrequencyData(buf);
        // Speech frequencies sit roughly in bins 2-12 of a 64-point FFT at 48 kHz
        const avg = Array.from(buf.slice(2, 12)).reduce((a, b) => a + b, 0) / 10;
        setMicLevel(avg / 255);
        micAnimRef.current = requestAnimationFrame(tick);
      };
      tick();
    }).catch(() => { setMicLevel(0); });
  }, [stopMicMonitor]);

  // ── Stop listening ───────────────────────────────────────────────
  const stopListening = useCallback(() => {
    if (recogRef.current) {
      recogRef.current.onend    = null;
      recogRef.current.onresult = null;
      try { recogRef.current.stop(); } catch {}
      recogRef.current = null;
    }
    if (listenTimerRef.current) {
      clearInterval(listenTimerRef.current);
      listenTimerRef.current = null;
    }
    clearPauseTimer();
    stopMicMonitor();
    setTranscript('');
    setListenTimer(1.0);
  }, [clearPauseTimer, stopMicMonitor]);

  // ── Barge-in control ─────────────────────────────────────────────
  const stopBargeIn = useCallback(() => {
    if (bargeInRef.current) {
      bargeInRef.current.onresult = null;
      bargeInRef.current.onend    = null;
      try { bargeInRef.current.stop(); } catch {}
      bargeInRef.current = null;
    }
  }, []);

  const startBargeIn = useCallback(() => {
    stopBargeIn();
    const SpeechRecog = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecog) return;

    const _launch = () => {
      if (stateRef.current !== 'speaking') return;
      const recog = new SpeechRecog();
      recog.continuous     = true;
      recog.interimResults = true;
      recog.lang           = 'en-IN';
      bargeInRef.current   = recog;

      recog.onresult = (e: any) => {
        const t = e.results[e.results.length - 1][0].transcript.trim();
        // Need ≥4 chars to avoid false triggers from ambient noise
        if (t.length >= 4) {
          stopBargeIn();
          voice.stop();
          setTimeout(() => startListenRef.current(), 120);
        }
      };

      // Auto-restart barge-in when Chrome times out due to silence,
      // so the user can interrupt VAAYU at any point during playback.
      recog.onend = () => {
        bargeInRef.current = null;
        if (stateRef.current === 'speaking') {
          setTimeout(_launch, 150);
        }
      };

      try { recog.start(); } catch {}
    };

    _launch();
  }, [stopBargeIn, voice]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Start listening for user question ────────────────────────────
  const startListening = useCallback(() => {
    stopListening();
    stateRef.current = 'listening';
    setConvState('listening');
    setTranscript('');

    // iOS Safari / Chrome on iOS: SpeechRecognition not available.
    // Skip the fake 20-second listen loop — just focus the text input instead.
    if (!hasSTT) {
      setTimeout(() => textInputRef.current?.focus(), 150);
      return;
    }

    const TIMEOUT_S = 20;
    let elapsed = 0;
    let handled = false;
    let accumulatedText = '';

    listenTimerRef.current = setInterval(() => {
      elapsed += 0.1;
      setListenTimer(1 - elapsed / TIMEOUT_S);
      if (elapsed >= TIMEOUT_S && !handled) {
        if (accumulatedText.trim()) {
          handled = true;
          clearPauseTimer();
          handleUserQuestionRef.current(accumulatedText.trim());
        } else {
          stopListening();
          setConvState('closed');
          setConvOpen(false);
        }
      }
    }, 100);

    const SpeechRecog = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecog) return;

    const _launch = () => {
      if (handled) return;

      const recog = new SpeechRecog();
      recog.continuous      = true;
      recog.interimResults  = true;
      recog.lang            = 'en-IN';
      recog.maxAlternatives = 1;
      recogRef.current = recog;

      // Track the latest interim text so we can fall back to it when
      // Chrome commits no final result before ending the session.
      let lastInterim = '';

      recog.onresult = (e: any) => {
        const result = e.results[e.results.length - 1];
        const text   = result[0].transcript.trim();

        if (result.isFinal && text) {
          lastInterim = '';
          accumulatedText += (accumulatedText ? ' ' : '') + text;
          setTranscript(accumulatedText);
          clearPauseTimer();
          setPauseCountdown(1);
          pauseTimerRef.current = setTimeout(() => {
            if (!handled && accumulatedText.trim()) {
              handled = true;
              clearPauseTimer();
              try { recog.stop(); } catch {}
              handleUserQuestionRef.current(accumulatedText.trim());
            }
          }, 1500);

        } else if (!result.isFinal && text) {
          lastInterim = text;
          setTranscript(accumulatedText + (accumulatedText ? ' ' : '') + text);
          clearPauseTimer();
        }
      };

      recog.onerror = (e: any) => {
        if (e.error !== 'no-speech') console.debug('[VAAYU listen] error:', e.error);
      };

      recog.onend = () => {
        recogRef.current = null;
        if (handled) return;

        // Chrome sometimes ends a session with only interim results and no final commit.
        // Use the last interim text as a fallback so the query isn't silently lost.
        if (lastInterim && !accumulatedText.trim()) {
          accumulatedText = lastInterim;
          lastInterim = '';
          setTranscript(accumulatedText);
          setPauseCountdown(1);
          pauseTimerRef.current = setTimeout(() => {
            if (!handled && accumulatedText.trim()) {
              handled = true;
              clearPauseTimer();
              handleUserQuestionRef.current(accumulatedText.trim());
            }
          }, 1500);
          return;
        }

        if (stateRef.current === 'listening') {
          setTimeout(_launch, 120);
        }
      };

      try {
        recog.start();
      } catch (err) {
        // Chrome throws if another recognition instance is still active.
        // Retry after a short delay to let the previous session fully close.
        console.debug('[VAAYU] recog.start() blocked, retrying in 400ms', err);
        recogRef.current = null;
        if (!handled && stateRef.current === 'listening') {
          setTimeout(_launch, 400);
        }
      }
    };

    // 300ms head-start: gives Chrome time to fully tear down the wake-word
    // SpeechRecognition before we try to start the conversation recognition.
    setTimeout(_launch, 300);
    startMicMonitor();
  }, [stopListening, clearPauseTimer, startMicMonitor]); // eslint-disable-line react-hooks/exhaustive-deps

  // Keep startListenRef in sync so barge-in can call latest closure
  useEffect(() => { startListenRef.current = startListening; }, [startListening]);

  // ── Handle user's spoken / typed question ────────────────────────
  const handleUserQuestion = useCallback(async (question: string) => {
    stopListening();

    // Detect exit phrases
    const lower = question.toLowerCase();
    if (
      lower.includes("thank you") || lower.includes("thanks") ||
      lower.includes("goodbye")   || lower.includes("bye") ||
      lower.includes("that's all") || lower.includes("stop")
    ) {
      addMessage('user', question);
      setConvState('loading');
      voice.chat("The user wants to end the conversation. Say a brief warm goodbye, Boss.", [], () => {
        setConvState('closed');
        setConvOpen(false);
        setMessages([]);
      });
      addMessage('vaayu', '…');
      return;
    }

    addMessage('user', question);
    // Placeholder while processing
    const placeholderId = ++msgCounter;
    setMessages(prev => [...prev, { id: placeholderId, role: 'vaayu', text: '…', time: now() }]);
    setConvState('processing');

    // Build conversation history from existing messages (skip placeholder dots)
    const history = messages
      .filter(m => m.text !== '…')
      .slice(-8)
      .map(m => ({
        role: m.role === 'vaayu' ? 'assistant' : 'user',
        content: m.text,
      }));

    voice.chat(question, history, () => {
      // After VAAYU responds, listen for next question
      setTimeout(startListening, 600);
    });
  }, [stopListening, addMessage, voice, startListening, messages]);

  // Keep ref in sync so startListening closures always call the latest version
  useEffect(() => { handleUserQuestionRef.current = handleUserQuestion; }, [handleUserQuestion]);

  // Replace placeholder "…" with actual script when it arrives
  useEffect(() => {
    if (voice.state === 'speaking' && voice.script) {
      setMessages(prev => {
        const last = prev[prev.length - 1];
        if (last?.role === 'vaayu' && last.text === '…') {
          setConvState('speaking');
          return [...prev.slice(0, -1), { ...last, text: voice.script }];
        }
        return prev;
      });
    }
  }, [voice.state, voice.script]);

  // ── Close conversation ────────────────────────────────────────────
  const closeConv = useCallback(() => {
    stopListening();
    voice.stop();
    setConvOpen(false);
    setConvState('closed');
    setMessages([]);
    setTranscript('');
  }, [stopListening, voice]);

  // ── Open conversation — greet first, then listen ─────────────────
  const openConversationListening = useCallback(() => {
    const hour   = new Date().getHours();
    const period = hour < 12 ? 'morning' : hour < 17 ? 'afternoon' : 'evening';

    setConvOpen(true);
    setMessages([]);
    setConvState('loading');
    setMessages([{ id: ++msgCounter, role: 'vaayu', text: '…', time: now() }]);

    // VAAYU greets with time-appropriate phrase, then starts listening
    voice.chat(
      `Greet your boss Shivam with a warm good-${period} greeting in one short sentence, ` +
      `then tell him you're listening. Keep it natural and brief — no questions yet.`,
      [],
      () => setTimeout(startListening, 500),
    );
  }, [voice, startListening]);

  // ── Open conversation — topic briefing flow ───────────────────────
  const openConversation = useCallback((topicId = 'market_summary') => {
    setConvOpen(true);
    setMessages([]);
    setConvState('loading');
    setMessages([{ id: ++msgCounter, role: 'vaayu', text: '…', time: now() }]);

    voice.speak(topicId, () => {
      setTimeout(startListening, 500);
    });
  }, [voice, startListening]);

  // ── Wake word handler (disabled while conv is open) ───────────────
  const { permission: wakePermission } = useWakeWord({
    enabled: !convOpen,
    onWake: (source) => {
      console.debug('[VAAYU] woken by', source);
      openConversationListening();
    },
  });

  // When voice generates script, update last placeholder bubble
  useEffect(() => {
    if ((voice.state === 'speaking' || voice.state === 'loading') && voice.script) {
      setMessages(prev => {
        const last = prev[prev.length - 1];
        if (last?.role === 'vaayu' && last.text === '…') {
          if (voice.state === 'speaking') setConvState('speaking');
          return [...prev.slice(0, -1), { ...last, text: voice.script }];
        }
        return prev;
      });
    }
  }, [voice.script, voice.state]);

  // ── Barge-in: listen for speech while VAAYU is talking ───────────
  useEffect(() => {
    if (convState !== 'speaking') {
      stopBargeIn();
      return;
    }
    // 300ms grace so VAAYU's first word doesn't self-trigger, but user can
    // interrupt quickly — barge-in auto-restarts itself on silence timeouts.
    const timer = setTimeout(startBargeIn, 300);
    return () => { clearTimeout(timer); stopBargeIn(); };
  }, [convState, startBargeIn, stopBargeIn]);

  // ── Sync conv state → global store (drives VaayuGlobe rings) ─────
  useEffect(() => {
    if (!convOpen) { setVaayuConvState('idle'); return; }
    if (convState === 'speaking')                                    setVaayuConvState('speaking');
    else if (convState === 'listening')                              setVaayuConvState('listening');
    else if (convState === 'processing' || convState === 'loading')  setVaayuConvState('processing');
    else                                                             setVaayuConvState('idle');
  }, [convOpen, convState]);

  const micReady    = wakePermission === 'granted';
  const isSpeaking  = convState === 'speaking';
  const isListening = convState === 'listening';

  // FAB click: when closed → go directly to listening mode.
  // When open + speaking → interrupt. When open + listening → close.
  const handleFabClick = () => {
    if (convOpen) {
      if (isSpeaking) {
        stopBargeIn();
        voice.stop();
        setTimeout(() => startListenRef.current(), 150);
      } else if (isListening) {
        closeConv();
      } else {
        setShowTopics(s => !s);
      }
    } else {
      openConversationListening();
    }
  };

  return (
    <div id="jarvis-fab" style={{ position: 'fixed', bottom: 28, right: 28, zIndex: 1000 }}>

      {/* ── Conversation panel ── */}
      <AnimatePresence>
        {convOpen && (
          <motion.div
            className="jarvis-conv-panel"
            initial={{ opacity: 0, y: 24, scale: 0.93 }}
            animate={{ opacity: 1, y: 0,  scale: 1 }}
            exit={{    opacity: 0, y: 24, scale: 0.93 }}
            transition={{ type: 'spring', stiffness: 320, damping: 28 }}
            style={{
              position: 'absolute', bottom: 72, right: 0, width: 400,
              background: 'rgba(2,4,18,0.97)',
              border: '1px solid rgba(0,229,255,0.2)',
              borderRadius: 18,
              backdropFilter: 'blur(20px)',
              boxShadow: '0 0 50px rgba(0,229,255,0.08), 0 12px 40px rgba(0,0,0,0.75)',
              overflow: 'hidden',
              display: 'flex', flexDirection: 'column',
            }}
          >
            {/* Panel header */}
            <div style={{
              padding: '12px 16px', display: 'flex',
              alignItems: 'center', justifyContent: 'space-between',
              borderBottom: '1px solid rgba(0,229,255,0.07)',
              background: 'rgba(0,229,255,0.025)',
              flexShrink: 0,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <motion.div
                  style={{
                    width: 7, height: 7, borderRadius: '50%',
                    background: isSpeaking ? '#00e5ff' : isListening ? '#a855f7' : 'rgba(0,229,255,0.35)',
                  }}
                  animate={isSpeaking || isListening ? { scale: [1, 1.5, 1], opacity: [1, 0.4, 1] } : {}}
                  transition={{ duration: 1.4, repeat: Infinity }}
                />
                <span style={{
                  fontSize: 10, fontFamily: 'monospace', letterSpacing: '0.2em',
                  color: isSpeaking ? '#00e5ff' : isListening ? '#a855f7' : 'rgba(0,229,255,0.55)',
                  fontWeight: 700,
                }}>
                  {isSpeaking ? 'VAAYU SPEAKING' : isListening ? (hasSTT ? 'LISTENING…' : 'TYPE BELOW') : convState === 'processing' ? 'THINKING…' : 'VAAYU'}
                </span>
              </div>
              <div style={{ display: 'flex', gap: 6 }}>
                {/* Topic selector */}
                <button
                  onClick={() => setShowTopics(s => !s)}
                  style={{
                    background: 'rgba(0,229,255,0.06)', border: '1px solid rgba(0,229,255,0.15)',
                    color: 'rgba(0,229,255,0.6)', borderRadius: 6, padding: '3px 8px',
                    fontSize: 9, cursor: 'pointer', letterSpacing: 1, fontFamily: 'monospace',
                  }}
                >
                  TOPICS
                </button>
                <button
                  onClick={closeConv}
                  style={{
                    background: 'rgba(255,23,68,0.08)', border: '1px solid rgba(255,23,68,0.2)',
                    color: '#ff1744', borderRadius: 6, padding: '3px 10px',
                    fontSize: 9, cursor: 'pointer', letterSpacing: 1, fontFamily: 'monospace',
                  }}
                >
                  CLOSE
                </button>
              </div>
            </div>

            {/* Topic mini-panel */}
            <AnimatePresence>
              {showTopics && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  style={{ overflow: 'hidden', borderBottom: '1px solid rgba(0,229,255,0.07)' }}
                >
                  <div style={{ padding: '10px 12px', display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 5 }}>
                    {topics.map(t => (
                      <button
                        key={t.id}
                        onClick={() => {
                          setShowTopics(false);
                          stopListening();
                          voice.stop();
                          setConvState('loading');
                          const plId = ++msgCounter;
                          setMessages(prev => [...prev, { id: plId, role: 'vaayu', text: '…', time: now() }]);
                          voice.speak(t.id, () => setTimeout(startListening, 500));
                        }}
                        style={{
                          background: 'rgba(0,229,255,0.03)',
                          border: '1px solid rgba(0,229,255,0.1)',
                          borderRadius: 7, padding: '6px 4px',
                          cursor: 'pointer', textAlign: 'center',
                          color: 'rgba(0,229,255,0.8)', fontSize: 9,
                          fontFamily: 'monospace', letterSpacing: '0.05em',
                        }}
                      >
                        <div style={{ fontSize: 14, marginBottom: 2 }}>{t.icon}</div>
                        {t.label}
                      </button>
                    ))}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            {/* Chat messages */}
            <div
              ref={scrollRef}
              style={{
                flex: 1, overflowY: 'auto', padding: '14px 14px 6px',
                maxHeight: 360, minHeight: 120,
              }}
            >
              {messages.map((msg, i) => (
                <Bubble
                  key={msg.id} msg={msg}
                  isLatest={i === messages.length - 1}
                  isSpeaking={isSpeaking && i === messages.length - 1}
                />
              ))}
            </div>

            {/* Waveform + interrupt hint when speaking */}
            <AnimatePresence>
              {isSpeaking && (
                <motion.div
                  initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                  style={{ padding: '0 14px', flexShrink: 0 }}
                >
                  <AudioVisualizer analyser={voice.analyser} isSpeaking={isSpeaking} width={332} height={48} />
                  <motion.button
                    onClick={() => {
                      stopBargeIn();
                      voice.stop();
                      setTimeout(() => startListenRef.current(), 150);
                    }}
                    animate={{ opacity: [0.45, 0.75, 0.45] }}
                    transition={{ duration: 2, repeat: Infinity, ease: 'easeInOut' }}
                    style={{
                      display: 'block', width: '100%', marginTop: 6,
                      background: 'transparent',
                      border: '1px solid rgba(124,58,237,0.18)',
                      borderRadius: 7, padding: '5px 0',
                      color: 'rgba(168,85,247,0.65)',
                      fontSize: 9, letterSpacing: '0.18em',
                      fontFamily: 'monospace', cursor: 'pointer',
                    }}
                  >
                    ⏸ SPEAK OR TAP TO INTERRUPT
                  </motion.button>
                </motion.div>
              )}
            </AnimatePresence>

            {/* Listening bar / processing indicator */}
            <div style={{ padding: '8px 14px 14px', flexShrink: 0 }}>
              <AnimatePresence>
                {isListening && hasSTT && (
                  <motion.div
                    initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                  >
                    <ListeningBar
                      transcript={transcript}
                      timeout={listenTimer}
                      pauseCountdown={pauseCountdown}
                      micLevel={micLevel}
                    />
                  </motion.div>
                )}
                {isListening && !hasSTT && (
                  <motion.div
                    initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                    style={{
                      padding: '8px 12px',
                      background: 'rgba(168,85,247,0.06)',
                      border: '1px solid rgba(168,85,247,0.2)',
                      borderRadius: 8,
                      display: 'flex', alignItems: 'center', gap: 8,
                    }}
                  >
                    <span style={{ fontSize: 14 }}>⌨️</span>
                    <span style={{ fontSize: 10, color: 'rgba(168,85,247,0.8)', fontFamily: 'monospace', letterSpacing: '0.1em' }}>
                      Voice not available on this browser — type below ↓
                    </span>
                  </motion.div>
                )}
              </AnimatePresence>
              {convState === 'processing' && (
                <div style={{
                  display: 'flex', alignItems: 'center', gap: 8,
                  padding: '8px 12px', background: 'rgba(0,229,255,0.04)',
                  border: '1px solid rgba(0,229,255,0.1)', borderRadius: 8,
                }}>
                  <motion.div
                    style={{ width: 14, height: 14, borderRadius: '50%', border: '2px solid rgba(0,229,255,0.6)', borderTopColor: '#00e5ff' }}
                    animate={{ rotate: 360 }}
                    transition={{ duration: 0.8, repeat: Infinity, ease: 'linear' }}
                  />
                  <span style={{ fontSize: 10, color: 'rgba(0,229,255,0.6)', fontFamily: 'monospace', letterSpacing: '0.15em' }}>
                    GENERATING RESPONSE…
                  </span>
                </div>
              )}
              {!isListening && convState === 'closed' && (
                <p style={{ margin: 0, fontSize: 9.5, color: 'rgba(160,196,224,0.35)', fontFamily: 'monospace', textAlign: 'center' }}>
                  {hasSTT
                    ? 'Conversation ended — say "Hey VAAYU" or click ◈ to restart'
                    : 'Conversation ended — click ◈ to restart'}
                </p>
              )}

              {/* Text input */}
              <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
                <input
                  ref={textInputRef}
                  value={textInput}
                  onChange={e => setTextInput(e.target.value)}
                  onKeyDown={e => {
                    if (e.key === 'Enter' && !e.shiftKey && textInput.trim()) {
                      e.preventDefault();
                      handleUserQuestion(textInput.trim());
                      setTextInput('');
                    }
                  }}
                  placeholder={isListening && hasSTT ? 'Listening… (or type here)' : 'Type your message…'}
                  disabled={convState === 'loading' || convState === 'processing'}
                  style={{
                    flex: 1,
                    background: 'rgba(0,229,255,0.03)',
                    border: '1px solid rgba(0,229,255,0.13)',
                    borderRadius: 10,
                    padding: '8px 13px',
                    fontSize: 12,
                    fontFamily: 'system-ui, -apple-system, sans-serif',
                    color: 'rgba(200,225,240,0.92)',
                    outline: 'none',
                    transition: 'border-color 0.15s',
                    opacity: (convState === 'loading' || convState === 'processing') ? 0.45 : 1,
                  }}
                  onFocus={e => { e.currentTarget.style.borderColor = 'rgba(0,229,255,0.35)'; }}
                  onBlur={e  => { e.currentTarget.style.borderColor = 'rgba(0,229,255,0.13)'; }}
                />
                <button
                  onClick={() => {
                    if (textInput.trim()) { handleUserQuestion(textInput.trim()); setTextInput(''); }
                  }}
                  disabled={!textInput.trim() || convState === 'loading' || convState === 'processing'}
                  style={{
                    background: textInput.trim() ? 'rgba(0,229,255,0.12)' : 'rgba(0,229,255,0.03)',
                    border: '1px solid rgba(0,229,255,0.2)',
                    borderRadius: 10,
                    width: 38, flexShrink: 0,
                    color: textInput.trim() ? '#00e5ff' : 'rgba(0,229,255,0.25)',
                    cursor: textInput.trim() ? 'pointer' : 'default',
                    fontSize: 16, fontWeight: 700,
                    transition: 'all 0.15s',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                  }}
                >
                  ↑
                </button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Topic quick-launch panel (when conv is closed) ── */}
      <AnimatePresence>
        {showTopics && !convOpen && (
          <motion.div
            initial={{ opacity: 0, y: 12, scale: 0.95 }}
            animate={{ opacity: 1, y: 0,  scale: 1 }}
            exit={{    opacity: 0, y: 12, scale: 0.95 }}
            transition={{ type: 'spring', stiffness: 340, damping: 28 }}
            className="jarvis-conv-panel"
            style={{
              position: 'absolute', bottom: 72, right: 0, width: 300,
              background: 'rgba(2,4,18,0.97)',
              border: '1px solid rgba(0,229,255,0.18)',
              borderRadius: 16, padding: '16px 14px',
              backdropFilter: 'blur(16px)',
              boxShadow: '0 0 30px rgba(0,229,255,0.08), 0 8px 24px rgba(0,0,0,0.6)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
              <span style={{ fontSize: 11, fontFamily: 'monospace', letterSpacing: '0.2em', color: '#00e5ff', fontWeight: 700 }}>
                ASK VAAYU
              </span>
              <button
                onClick={() => setShowTopics(false)}
                style={{ background: 'transparent', border: 'none', color: 'rgba(160,196,224,0.4)', fontSize: 16, cursor: 'pointer' }}
              >
                ✕
              </button>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
              {topics.map(t => (
                <button
                  key={t.id}
                  onClick={() => { setShowTopics(false); openConversation(t.id); }}
                  style={{
                    background: 'rgba(0,229,255,0.03)', border: '1px solid rgba(0,229,255,0.1)',
                    borderRadius: 10, padding: '10px 8px', cursor: 'pointer', textAlign: 'left', transition: 'all 0.2s',
                  }}
                  onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(0,229,255,0.07)'; }}
                  onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(0,229,255,0.03)'; }}
                >
                  <div style={{ fontSize: 16, marginBottom: 4, color: '#00e5ff', fontFamily: 'monospace' }}>{t.icon}</div>
                  <div style={{ fontSize: 10, fontWeight: 700, color: 'rgba(0,229,255,0.9)', fontFamily: 'monospace' }}>{t.label}</div>
                  <div style={{ fontSize: 9, color: 'rgba(160,196,224,0.45)', marginTop: 2 }}>{t.desc}</div>
                </button>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── "TALK TO VAAYU" label (shown when conversation is closed) ── */}
      {!convOpen && (
        <motion.div
          initial={{ opacity: 0, x: 10 }}
          animate={{ opacity: 1, x: 0 }}
          style={{
            position: 'absolute', right: 68, bottom: 16,
            display: 'flex', alignItems: 'center', gap: 6,
            background: 'rgba(2,4,18,0.90)',
            border: '1px solid rgba(0,229,255,0.18)',
            borderRadius: 8, padding: '5px 12px',
            cursor: 'pointer', pointerEvents: 'all',
            whiteSpace: 'nowrap',
          }}
          onClick={openConversationListening}
          whileHover={{ borderColor: 'rgba(0,229,255,0.4)', background: 'rgba(0,20,40,0.95)' }}
        >
          <motion.div
            style={{ width: 6, height: 6, borderRadius: '50%', background: micReady ? '#4ade80' : 'rgba(0,229,255,0.4)' }}
            animate={micReady ? { scale: [1, 1.4, 1], opacity: [1, 0.5, 1] } : {}}
            transition={{ duration: 2, repeat: Infinity }}
          />
          <span style={{
            fontSize: 10, fontFamily: 'monospace', letterSpacing: '0.15em',
            color: 'rgba(0,229,255,0.8)', fontWeight: 700,
          }}>
            TALK TO VAAYU
          </span>
        </motion.div>
      )}

      {/* ── FAB ── */}
      <FabButton
        convOpen={convOpen}
        convState={convState}
        micReady={micReady}
        onClick={handleFabClick}
      />
    </div>
  );
}
