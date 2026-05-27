import React, { useState } from 'react';
import ReactDOM from 'react-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { systemApi } from '../../api/client';

interface ModeToggleProps {
  currentMode: string;
  onModeChange?: (mode: string) => void;
}

const MODES = [
  { id: 'demo',  label: 'DEMO',  dot: '#ffd600', ring: 'rgba(255,214,0,0.4)',  bg: 'rgba(255,214,0,0.1)',  desc: 'Mock data — no broker' },
  { id: 'paper', label: 'PAPER', dot: '#00b0ff', ring: 'rgba(0,176,255,0.4)',  bg: 'rgba(0,176,255,0.1)',  desc: 'Real broker — no orders' },
  { id: 'live',  label: 'LIVE',  dot: '#00e676', ring: 'rgba(0,230,118,0.4)',  bg: 'rgba(0,230,118,0.1)',  desc: 'Real broker — real orders' },
];

export function ModeToggle({ currentMode, onModeChange }: ModeToggleProps) {
  const [open, setOpen] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [confirm, setConfirm] = useState<string | null>(null);

  const current = MODES.find(m => m.id === currentMode) ?? MODES[0];

  const handleSelect = (mode: typeof MODES[0]) => {
    if (mode.id === currentMode) { setOpen(false); return; }
    if (mode.id === 'live') {
      setConfirm(mode.id);
      setOpen(false);
      return;
    }
    applyMode(mode.id);
  };

  const applyMode = async (modeId: string) => {
    setSwitching(true);
    setConfirm(null);
    setOpen(false);
    try {
      if (modeId !== 'demo') {
        await systemApi.setMode(modeId as 'paper' | 'live' | 'backtest');
      }
      onModeChange?.(modeId);
    } catch (e) {
      console.error('Mode switch failed', e);
    } finally {
      setSwitching(false);
    }
  };

  return (
    <>
      {/* Trigger badge */}
      <div className="relative">
        <motion.button
          onClick={() => setOpen(o => !o)}
          disabled={switching}
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-bold uppercase tracking-widest cursor-pointer transition-all"
          style={{
            background: current.bg,
            borderColor: current.ring,
            color: current.dot,
          }}
          whileHover={{ scale: 1.04 }}
          whileTap={{ scale: 0.97 }}
        >
          {/* Dot */}
          <motion.span
            className="inline-block w-2 h-2 rounded-full"
            style={{ background: current.dot, boxShadow: `0 0 8px ${current.dot}` }}
            animate={currentMode === 'live' ? { opacity: [1, 0.3, 1] } : { opacity: 1 }}
            transition={{ duration: 1, repeat: Infinity }}
          />
          {switching ? 'Switching…' : current.label}
          <svg className={`w-3 h-3 transition-transform ${open ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </motion.button>

        {/* Dropdown */}
        <AnimatePresence>
          {open && (
            <motion.div
              className="absolute right-0 top-full mt-2 w-52 glass-panel py-2 z-50 neon-border"
              initial={{ opacity: 0, y: -8, scale: 0.96 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -8, scale: 0.96 }}
              transition={{ duration: 0.15 }}
            >
              {MODES.map(mode => (
                <button
                  key={mode.id}
                  onClick={() => handleSelect(mode)}
                  className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-white/5 transition-colors"
                  disabled={mode.id === 'demo' && currentMode !== 'demo'}
                >
                  <span
                    className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                    style={{
                      background: mode.dot,
                      boxShadow: mode.id === currentMode ? `0 0 10px ${mode.dot}` : 'none',
                    }}
                  />
                  <div>
                    <div
                      className="text-xs font-bold uppercase tracking-wider"
                      style={{ color: mode.id === currentMode ? mode.dot : '#8aa5c0' }}
                    >
                      {mode.label}
                      {mode.id === currentMode && (
                        <span className="ml-2 text-xs font-normal normal-case tracking-normal opacity-60">active</span>
                      )}
                    </div>
                    <div className="text-xs text-jarvis-text-secondary mt-0.5">{mode.desc}</div>
                  </div>
                </button>
              ))}

              {currentMode === 'demo' && (
                <div className="px-4 py-2 border-t border-jarvis-primary/10 mt-1">
                  <p className="text-xs text-jarvis-text-secondary">
                    Set <code className="text-yellow-400">DEMO_MODE=false</code> on Railway to unlock Paper/Live
                  </p>
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Live mode confirmation modal — rendered via portal to escape header's CSS transform context */}
      {confirm && ReactDOM.createPortal(
        <AnimatePresence>
          <motion.div
            className="fixed inset-0 flex items-center justify-center"
            style={{ zIndex: 99999 }}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          >
            <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setConfirm(null)} />
            <motion.div
              className="glass-panel neon-border p-8 max-w-md w-full mx-4 relative"
              style={{ zIndex: 100000 }}
              initial={{ scale: 0.9, y: 20 }}
              animate={{ scale: 1, y: 0 }}
              exit={{ scale: 0.9, y: 20 }}
            >
              <div className="text-red-400 text-4xl mb-4 text-center">⚠</div>
              <h3 className="text-lg font-bold text-red-400 text-center mb-2 uppercase tracking-widest">
                Switch to Live Trading?
              </h3>
              <p className="text-jarvis-text-secondary text-sm text-center mb-6">
                This will enable <span className="text-white font-semibold">real money orders</span> through Angel One.
                Ensure your risk settings are correct before proceeding.
              </p>
              <div className="flex gap-3">
                <button
                  onClick={() => setConfirm(null)}
                  className="flex-1 jarvis-button-outline text-center"
                >
                  Cancel
                </button>
                <button
                  onClick={() => applyMode('live')}
                  className="flex-1 py-2.5 rounded-lg font-bold uppercase tracking-wider text-sm transition-all"
                  style={{
                    background: 'rgba(255,23,68,0.15)',
                    border: '1px solid rgba(255,23,68,0.5)',
                    color: '#ff1744',
                  }}
                >
                  Confirm Live
                </button>
              </div>
            </motion.div>
          </motion.div>
        </AnimatePresence>,
        document.body
      )}
    </>
  );
}
