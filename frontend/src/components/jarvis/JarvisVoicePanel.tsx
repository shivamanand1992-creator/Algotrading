import React, { useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useJarvisVoice } from '../../hooks/useJarvisVoice';
import { AudioVisualizer } from './AudioVisualizer';
import { api } from '../../api/client';

interface Topic { id: string; label: string; icon: string; desc: string; }

const FALLBACK_TOPICS: Topic[] = [
  { id: 'market_summary', label: 'Market Summary',  icon: '📊', desc: 'Nifty status & trend' },
  { id: 'my_positions',   label: 'My Positions',    icon: '💼', desc: 'Portfolio P&L' },
  { id: 'news_brief',     label: 'News Brief',      icon: '📰', desc: 'AI-summarised headlines' },
  { id: 'global_cues',    label: 'Global Cues',     icon: '🌐', desc: 'US, Asia & commodities' },
  { id: 'nifty_trend',    label: 'Nifty Trend',     icon: '📈', desc: 'Technical deep-dive' },
  { id: 'full_briefing',  label: 'Full Briefing',   icon: '🎯', desc: '90-second overview' },
];

// ── JARVIS hexagon avatar ─────────────────────────────────────────────────

function JarvisAvatar({ speaking }: { speaking: boolean }) {
  return (
    <svg width={96} height={96} viewBox="0 0 96 96" style={{ overflow: 'visible' }}>
      <defs>
        <radialGradient id="jav-bg" cx="50%" cy="50%" r="50%">
          <stop offset="0%"   stopColor="rgba(0,229,255,0.18)" />
          <stop offset="100%" stopColor="rgba(0,50,120,0.04)" />
        </radialGradient>
        <filter id="jav-glow">
          <feGaussianBlur stdDeviation={speaking ? '3' : '1.5'} result="blur" />
          <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>
      </defs>

      {/* Outer pulse rings */}
      {speaking && (
        <>
          <circle cx={48} cy={48} r={46} fill="none" stroke="rgba(0,229,255,0.15)"
            strokeWidth={1} className="radar-ring" style={{ color: '#00e5ff' }} />
          <circle cx={48} cy={48} r={46} fill="none" stroke="rgba(0,229,255,0.1)"
            strokeWidth={1} className="radar-ring radar-ring-delay" style={{ color: '#00e5ff' }} />
        </>
      )}

      {/* Hexagon */}
      <polygon
        points="48,6 84,27 84,69 48,90 12,69 12,27"
        fill="url(#jav-bg)"
        stroke={speaking ? 'rgba(0,229,255,0.8)' : 'rgba(0,229,255,0.35)'}
        strokeWidth="1.5"
        filter="url(#jav-glow)"
      />
      <polygon
        points="48,16 76,32 76,64 48,80 20,64 20,32"
        fill="none"
        stroke="rgba(0,229,255,0.2)"
        strokeWidth="0.8"
      />

      {/* Inner circuit lines */}
      <line x1="28" y1="48" x2="68" y2="48" stroke="rgba(0,229,255,0.2)" strokeWidth="0.6" />
      <line x1="48" y1="22" x2="48" y2="74" stroke="rgba(0,229,255,0.2)" strokeWidth="0.6" />

      {/* "J" letter */}
      <text x="48" y="57" textAnchor="middle"
        style={{
          fontFamily: 'monospace',
          fontSize:   28,
          fontWeight: 900,
          fill:       speaking ? 'rgba(0,229,255,1)' : 'rgba(0,229,255,0.75)',
          filter:     speaking ? 'url(#jav-glow)' : 'none',
          letterSpacing: 2,
        }}
      >
        J
      </text>

      {/* Four corner dots */}
      {[[-1,-1],[1,-1],[1,1],[-1,1]].map(([dx, dy], i) => (
        <circle key={i}
          cx={48 + dx! * 32} cy={48 + dy! * 22} r={2.5}
          fill={speaking ? '#00e5ff' : 'rgba(0,229,255,0.4)'}
        />
      ))}
    </svg>
  );
}

// ── Typewriter text ───────────────────────────────────────────────────────

function TypewriterText({ text, speed = 18 }: { text: string; speed?: number }) {
  const [displayed, setDisplayed] = useState('');
  const idxRef = useRef(0);

  useEffect(() => {
    setDisplayed('');
    idxRef.current = 0;
    if (!text) return;
    const iv = setInterval(() => {
      if (idxRef.current >= text.length) { clearInterval(iv); return; }
      setDisplayed(text.slice(0, ++idxRef.current));
    }, speed);
    return () => clearInterval(iv);
  }, [text, speed]);

  return (
    <p style={{
      fontSize: 12, lineHeight: 1.6, color: 'rgba(160,196,224,0.9)',
      fontFamily: "'Courier New', monospace", whiteSpace: 'pre-wrap',
    }}>
      {displayed}
      {displayed.length < text.length && (
        <span className="type-cursor" style={{ width: 6, height: 12 }} />
      )}
    </p>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────

export function JarvisVoicePanel() {
  const [open,   setOpen]   = useState(false);
  const [topics, setTopics] = useState<Topic[]>(FALLBACK_TOPICS);
  const voice = useJarvisVoice();

  // Load topics from backend
  useEffect(() => {
    api.get<Topic[]>('/api/jarvis/topics')
      .then(r => { if (r.data?.length) setTopics(r.data); })
      .catch(() => {});
  }, []);

  const handleTopic = (id: string) => {
    setOpen(false);
    voice.speak(id);
  };

  const isSpeaking = voice.state === 'speaking';
  const isLoading  = voice.state === 'loading';
  const isActive   = isSpeaking || isLoading;

  return (
    <div style={{ position: 'fixed', bottom: 28, right: 28, zIndex: 1000 }}>

      {/* ── Speaking panel ── */}
      <AnimatePresence>
        {isActive && (
          <motion.div
            initial={{ opacity: 0, y: 20, scale: 0.92 }}
            animate={{ opacity: 1, y: 0,  scale: 1 }}
            exit={{    opacity: 0, y: 20, scale: 0.92 }}
            transition={{ type: 'spring', stiffness: 300, damping: 26 }}
            style={{
              position:     'absolute',
              bottom:       72,
              right:        0,
              width:        340,
              background:   'rgba(2,8,22,0.96)',
              border:       '1px solid rgba(0,229,255,0.25)',
              borderRadius: 16,
              padding:      '20px 18px',
              backdropFilter: 'blur(14px)',
              boxShadow:    '0 0 40px rgba(0,229,255,0.12), 0 8px 32px rgba(0,0,0,0.6)',
            }}
          >
            {/* Header */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <div className="live-dot" style={{ width: 7, height: 7, background: '#00e5ff', color: '#00e5ff' }} />
                <span style={{ fontSize: 9, fontFamily: 'monospace', letterSpacing: '0.25em', color: 'rgba(0,229,255,0.6)', textTransform: 'uppercase' }}>
                  JARVIS VOICE INTERFACE
                </span>
              </div>
              <button
                onClick={voice.stop}
                style={{ background: 'rgba(255,23,68,0.12)', border: '1px solid rgba(255,23,68,0.3)', color: '#ff1744', borderRadius: 6, padding: '3px 10px', fontSize: 10, cursor: 'pointer', letterSpacing: 1, fontFamily: 'monospace' }}
              >
                STOP
              </button>
            </div>

            {/* Avatar + visualizer row */}
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12 }}>
              <motion.div
                animate={isSpeaking ? { scale: [1, 1.04, 1] } : {}}
                transition={{ duration: 1.8, repeat: Infinity, ease: 'easeInOut' }}
              >
                <JarvisAvatar speaking={isSpeaking} />
              </motion.div>

              {isLoading && (
                <div style={{ textAlign: 'center' }}>
                  <div className="radar-sweep" style={{ display: 'inline-block', transformOrigin: 'center', width: 32, height: 32 }}>
                    <svg width={32} height={32} viewBox="0 0 32 32">
                      <circle cx={16} cy={16} r={14} fill="none" stroke="rgba(0,229,255,0.2)" strokeWidth={1.5} />
                      <path d="M16,16 L16,2 A14,14 0 0 1 28,9 Z" fill="rgba(0,229,255,0.4)" />
                      <circle cx={16} cy={16} r={3} fill="#00e5ff" />
                    </svg>
                  </div>
                  <p style={{ fontSize: 11, color: 'rgba(0,229,255,0.6)', fontFamily: 'monospace', marginTop: 6, letterSpacing: 2 }}>
                    GENERATING BRIEFING…
                  </p>
                </div>
              )}

              {isSpeaking && (
                <AudioVisualizer
                  analyser={voice.analyser}
                  isSpeaking={isSpeaking}
                  width={300}
                  height={72}
                />
              )}
            </div>

            {/* Transcript */}
            {voice.script && isSpeaking && (
              <div style={{
                marginTop: 14, padding: '10px 12px',
                background: 'rgba(0,229,255,0.03)',
                border: '1px solid rgba(0,229,255,0.08)',
                borderRadius: 8, maxHeight: 120, overflowY: 'auto',
              }}>
                <TypewriterText text={voice.script} speed={14} />
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Topic selector panel ── */}
      <AnimatePresence>
        {open && !isActive && (
          <motion.div
            initial={{ opacity: 0, y: 12, scale: 0.95 }}
            animate={{ opacity: 1, y: 0,  scale: 1 }}
            exit={{    opacity: 0, y: 12, scale: 0.95 }}
            transition={{ type: 'spring', stiffness: 340, damping: 28 }}
            style={{
              position:     'absolute',
              bottom:       72,
              right:        0,
              width:        300,
              background:   'rgba(2,8,22,0.97)',
              border:       '1px solid rgba(0,229,255,0.2)',
              borderRadius: 16,
              padding:      '16px 14px',
              backdropFilter: 'blur(14px)',
              boxShadow:    '0 0 30px rgba(0,229,255,0.1), 0 8px 24px rgba(0,0,0,0.5)',
            }}
          >
            {/* Panel header */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
              <div>
                <div style={{ fontSize: 11, fontFamily: 'monospace', letterSpacing: '0.2em', color: '#00e5ff', fontWeight: 700 }}>
                  JARVIS BRIEFING
                </div>
                <div style={{ fontSize: 9, color: 'rgba(160,196,224,0.4)', marginTop: 1, letterSpacing: 1 }}>
                  Select a briefing topic
                </div>
              </div>
              <button
                onClick={() => setOpen(false)}
                style={{ background: 'transparent', border: 'none', color: 'rgba(160,196,224,0.4)', fontSize: 16, cursor: 'pointer', padding: '0 4px', lineHeight: 1 }}
              >
                ✕
              </button>
            </div>

            {/* Topic grid */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
              {topics.map(t => (
                <button
                  key={t.id}
                  onClick={() => handleTopic(t.id)}
                  className="hud-corners"
                  style={{
                    background:   'rgba(0,229,255,0.03)',
                    border:       '1px solid rgba(0,229,255,0.12)',
                    borderRadius: 10,
                    padding:      '10px 8px',
                    cursor:       'pointer',
                    textAlign:    'left',
                    transition:   'all 0.2s',
                    '--hud-color': 'rgba(0,229,255,0.4)',
                  } as React.CSSProperties}
                  onMouseEnter={e => {
                    (e.currentTarget as HTMLElement).style.background = 'rgba(0,229,255,0.08)';
                    (e.currentTarget as HTMLElement).style.borderColor = 'rgba(0,229,255,0.3)';
                  }}
                  onMouseLeave={e => {
                    (e.currentTarget as HTMLElement).style.background = 'rgba(0,229,255,0.03)';
                    (e.currentTarget as HTMLElement).style.borderColor = 'rgba(0,229,255,0.12)';
                  }}
                >
                  <div style={{ fontSize: 16, marginBottom: 4 }}>{t.icon}</div>
                  <div style={{ fontSize: 10, fontWeight: 700, color: 'rgba(0,229,255,0.9)', fontFamily: 'monospace', letterSpacing: 0.5 }}>
                    {t.label}
                  </div>
                  <div style={{ fontSize: 9, color: 'rgba(160,196,224,0.45)', marginTop: 2, lineHeight: 1.3 }}>
                    {t.desc}
                  </div>
                </button>
              ))}
            </div>

            {/* Error state */}
            {voice.state === 'error' && (
              <div style={{ marginTop: 10, padding: '8px 10px', background: 'rgba(255,23,68,0.08)', border: '1px solid rgba(255,23,68,0.2)', borderRadius: 8 }}>
                <p style={{ fontSize: 10, color: '#ff1744', fontFamily: 'monospace', margin: 0 }}>
                  ⚠ {voice.error || 'Briefing failed. Check API keys.'}
                </p>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── FAB button ── */}
      <motion.button
        onClick={() => {
          if (isActive) { voice.stop(); } else { setOpen(o => !o); }
        }}
        animate={
          isSpeaking
            ? { scale: [1, 1.12, 1], boxShadow: ['0 0 0px rgba(0,229,255,0)', '0 0 28px rgba(0,229,255,0.7)', '0 0 0px rgba(0,229,255,0)'] }
            : isLoading
              ? { rotate: 360 }
              : {}
        }
        transition={
          isSpeaking
            ? { duration: 1.6, repeat: Infinity, ease: 'easeInOut' }
            : isLoading
              ? { duration: 2, repeat: Infinity, ease: 'linear' }
              : {}
        }
        title={isActive ? 'Stop JARVIS' : open ? 'Close' : 'Ask JARVIS'}
        style={{
          width:        60,
          height:       60,
          borderRadius: '50%',
          background:   isActive
            ? 'linear-gradient(135deg, rgba(0,229,255,0.25), rgba(0,50,150,0.4))'
            : open
              ? 'linear-gradient(135deg, rgba(0,229,255,0.18), rgba(0,30,80,0.5))'
              : 'linear-gradient(135deg, rgba(0,8,30,0.95), rgba(0,20,60,0.95))',
          border:       `1.5px solid ${isActive ? 'rgba(0,229,255,0.7)' : 'rgba(0,229,255,0.3)'}`,
          boxShadow:    isActive ? '0 0 20px rgba(0,229,255,0.4)' : '0 4px 20px rgba(0,0,0,0.4)',
          cursor:       'pointer',
          display:      'flex',
          alignItems:   'center',
          justifyContent: 'center',
          outline:      'none',
        }}
      >
        {isActive ? (
          <svg width={28} height={28} viewBox="0 0 28 28" fill="none">
            {/* Sound wave icon when speaking */}
            <circle cx={14} cy={14} r={13} fill="none" stroke="rgba(0,229,255,0.3)" strokeWidth={1} />
            {[4,7,10].map((r, i) => (
              <circle key={i} cx={14} cy={14} r={r} fill="none" stroke="rgba(0,229,255,0.5)" strokeWidth={1.2} />
            ))}
            <circle cx={14} cy={14} r={3} fill="#00e5ff" />
          </svg>
        ) : (
          <svg width={26} height={26} viewBox="0 0 26 26" fill="none">
            {/* Microphone / JARVIS icon */}
            <polygon points="13,2 22,7.5 22,18.5 13,24 4,18.5 4,7.5"
              fill="rgba(0,229,255,0.08)" stroke="rgba(0,229,255,0.6)" strokeWidth="1.2" />
            <text x="13" y="17.5" textAnchor="middle"
              style={{ fontFamily: 'monospace', fontSize: 11, fontWeight: 900, fill: '#00e5ff' }}>
              J
            </text>
          </svg>
        )}
      </motion.button>
    </div>
  );
}
