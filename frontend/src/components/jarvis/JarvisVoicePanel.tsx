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

function ListeningBar({ transcript, timeout }: { transcript: string; timeout: number }) {
  return (
    <div style={{
      padding: '10px 14px',
      background: 'rgba(124,58,237,0.08)',
      border: '1px solid rgba(124,58,237,0.25)',
      borderRadius: 10,
      display: 'flex', alignItems: 'center', gap: 10,
    }}>
      {/* Animated mic */}
      <motion.div
        style={{ flexShrink: 0, display: 'flex', gap: 2, alignItems: 'flex-end' }}
      >
        {[3, 5, 4, 6, 3].map((h, i) => (
          <motion.div
            key={i}
            style={{ width: 2, background: '#7c3aed', borderRadius: 2 }}
            animate={{ height: [h, h + 4, h] }}
            transition={{ duration: 0.5, repeat: Infinity, delay: i * 0.1, ease: 'easeInOut' }}
          />
        ))}
      </motion.div>

      <div style={{ flex: 1, minWidth: 0 }}>
        {transcript ? (
          <p style={{
            margin: 0, fontSize: 11, color: 'rgba(200,185,255,0.9)',
            fontFamily: 'monospace', whiteSpace: 'nowrap', overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}>
            "{transcript}"
          </p>
        ) : (
          <p style={{ margin: 0, fontSize: 10, color: 'rgba(124,58,237,0.7)', fontFamily: 'monospace', letterSpacing: '0.1em' }}>
            LISTENING…
          </p>
        )}
      </div>

      {/* Timeout arc */}
      <svg width={20} height={20} style={{ flexShrink: 0 }}>
        <circle cx={10} cy={10} r={8} fill="none" stroke="rgba(124,58,237,0.15)" strokeWidth={2} />
        <circle cx={10} cy={10} r={8} fill="none" stroke="rgba(124,58,237,0.6)" strokeWidth={2}
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
  const active   = convOpen && convState !== 'closed';
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

      {/* Listening ring when conversation is listening */}
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
        title={convOpen ? 'Close VAAYU' : micReady ? 'Ask VAAYU (or clap)' : 'Ask VAAYU'}
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
  const [convOpen,     setConvOpen]     = useState(false);
  const [convState,    setConvState]    = useState<ConvState>('closed');
  const [messages,     setMessages]     = useState<Message[]>([]);
  const [transcript,   setTranscript]   = useState('');
  const [listenTimer,  setListenTimer]  = useState(1.0);  // 0→1 countdown for arc
  const [topics,       setTopics]       = useState<Topic[]>(FALLBACK_TOPICS);
  const [showTopics,   setShowTopics]   = useState(false);
  const [textInput,    setTextInput]    = useState('');

  const voice          = useJarvisVoice();
  const scrollRef      = useRef<HTMLDivElement>(null);
  const recogRef       = useRef<any>(null);
  const listenTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const stateRef        = useRef<ConvState>('closed');
  stateRef.current      = convState;
  const bargeInRef      = useRef<any>(null);
  const startListenRef  = useRef<() => void>(() => {});

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

  // ── Stop listening ───────────────────────────────────────────────
  const stopListening = useCallback(() => {
    if (recogRef.current) {
      recogRef.current.onend  = null;
      recogRef.current.onresult = null;
      try { recogRef.current.stop(); } catch {}
      recogRef.current = null;
    }
    if (listenTimerRef.current) {
      clearInterval(listenTimerRef.current);
      listenTimerRef.current = null;
    }
    setTranscript('');
    setListenTimer(1.0);
  }, []);

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
    const recog = new SpeechRecog();
    recog.continuous     = true;
    recog.interimResults = true;
    recog.lang           = 'en-IN';
    bargeInRef.current   = recog;
    recog.onresult = (e: any) => {
      const t = e.results[e.results.length - 1][0].transcript.trim();
      if (t.length >= 2) {
        console.debug('[VAAYU barge-in]', t);
        stopBargeIn();
        voice.stop();
        setTimeout(() => startListenRef.current(), 150);
      }
    };
    recog.onend = () => { bargeInRef.current = null; };
    try { recog.start(); } catch {}
  }, [stopBargeIn, voice]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Start listening for user question ────────────────────────────
  const startListening = useCallback(() => {
    stopListening();
    setConvState('listening');
    setTranscript('');

    const TIMEOUT_S = 12;
    let elapsed = 0;
    listenTimerRef.current = setInterval(() => {
      elapsed += 0.1;
      setListenTimer(1 - elapsed / TIMEOUT_S);
      if (elapsed >= TIMEOUT_S) {
        stopListening();
        setConvState('closed');
        setConvOpen(false);
      }
    }, 100);

    const SpeechRecog = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecog) {
      // No speech recognition — just show a text-based idle
      return;
    }

    const recog = new SpeechRecog();
    recog.continuous      = false;
    recog.interimResults  = true;
    recog.lang            = 'en-IN';
    recog.maxAlternatives = 1;
    recogRef.current = recog;

    recog.onresult = (e: any) => {
      const result = e.results[0];
      const text   = result[0].transcript;
      setTranscript(text);
      if (result.isFinal && text.trim()) {
        handleUserQuestion(text.trim());
      }
    };

    recog.onspeechend = () => {
      try { recog.stop(); } catch {}
    };

    recog.onerror = (e: any) => {
      console.debug('[VAAYU listen] error:', e.error);
    };

    recog.onend = () => {
      // If we got a transcript, it's been handled; otherwise no-op
    };

    try { recog.start(); } catch {}
  }, [stopListening]); // eslint-disable-line react-hooks/exhaustive-deps

  // Keep startListenRef in sync so barge-in can call latest closure
  useEffect(() => { startListenRef.current = startListening; }, [startListening]);

  // ── Handle user's spoken question ────────────────────────────────
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
      voice.chat("The user wants to end the conversation. Say a brief warm goodbye.", [], () => {
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

    // Replace placeholder with actual script once available (watched via effect below)
  }, [stopListening, addMessage, voice, startListening, messages]);

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

  // ── Open conversation (greet + brief) ────────────────────────────
  const openConversation = useCallback((topicId = 'market_summary') => {
    setConvOpen(true);
    setMessages([]);
    setConvState('loading');
    // Placeholder vaayu bubble
    setMessages([{ id: ++msgCounter, role: 'vaayu', text: '…', time: now() }]);

    voice.speak(topicId, () => {
      // After greeting brief → start listening
      setTimeout(startListening, 500);
    });
  }, [voice, startListening]);

  // ── Wake word handler (disabled while conv is open) ───────────────
  const { permission: wakePermission } = useWakeWord({
    enabled: !convOpen,
    onWake: (source) => {
      console.debug('[VAAYU] woken by', source);
      openConversation('market_summary');
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
    // 1.5s grace so VAAYU's own audio doesn't self-trigger
    const timer = setTimeout(startBargeIn, 1500);
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

  const micReady   = wakePermission === 'granted';
  const isSpeaking = convState === 'speaking';
  const isListening = convState === 'listening';

  const handleFabClick = () => {
    if (convOpen) {
      if (isListening) {
        // Close while listening
        closeConv();
      } else {
        setShowTopics(s => !s);
      }
    } else {
      setShowTopics(s => !s);
    }
  };

  return (
    <div style={{ position: 'fixed', bottom: 28, right: 28, zIndex: 1000 }}>

      {/* ── Conversation panel ── */}
      <AnimatePresence>
        {convOpen && (
          <motion.div
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
                  {isSpeaking ? 'VAAYU SPEAKING' : isListening ? 'LISTENING' : convState === 'processing' ? 'THINKING…' : 'VAAYU'}
                </span>
              </div>
              <div style={{ display: 'flex', gap: 6 }}>
                {/* Topic selector mini button */}
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

            {/* Topic mini-panel (shown when Topics clicked) */}
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

            {/* Waveform when speaking */}
            <AnimatePresence>
              {isSpeaking && (
                <motion.div
                  initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                  style={{ padding: '0 14px', flexShrink: 0 }}
                >
                  <AudioVisualizer analyser={voice.analyser} isSpeaking={isSpeaking} width={332} height={48} />
                </motion.div>
              )}
            </AnimatePresence>

            {/* Listening bar */}
            <div style={{ padding: '8px 14px 14px', flexShrink: 0 }}>
              <AnimatePresence>
                {isListening && (
                  <motion.div
                    initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                  >
                    <ListeningBar transcript={transcript} timeout={listenTimer} />
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
                  Conversation ended — clap or click ◈ to restart
                </p>
              )}

              {/* ── Text input (always shown while conv is open) ── */}
              <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
                <input
                  value={textInput}
                  onChange={e => setTextInput(e.target.value)}
                  onKeyDown={e => {
                    if (e.key === 'Enter' && !e.shiftKey && textInput.trim()) {
                      e.preventDefault();
                      handleUserQuestion(textInput.trim());
                      setTextInput('');
                    }
                  }}
                  placeholder={isListening ? 'Listening… (or type here)' : 'Type a message…'}
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
