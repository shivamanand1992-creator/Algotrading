import React, { useState, useEffect } from 'react';
import axios from 'axios';

interface LoginViewProps {
  onLoginSuccess: (token: string) => void;
}

export function LoginView({ onLoginSuccess }: LoginViewProps) {
  const [password, setPassword] = useState('');
  const [status, setStatus] = useState<'idle' | 'loading' | 'granted' | 'denied'>('idle');
  const [errorMsg, setErrorMsg] = useState('');
  const [dots, setDots] = useState('');

  // Animated dots for loading state
  useEffect(() => {
    if (status !== 'loading') return;
    const iv = setInterval(() => setDots(d => d.length >= 3 ? '' : d + '.'), 400);
    return () => clearInterval(iv);
  }, [status]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!password.trim()) return;
    setStatus('loading');
    setErrorMsg('');

    try {
      const form = new URLSearchParams();
      form.append('username', 'admin');
      form.append('password', password);

      const res = await axios.post('/api/auth/login', form, {
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      });

      setStatus('granted');
      setTimeout(() => onLoginSuccess(res.data.access_token), 900);
    } catch {
      setStatus('denied');
      setErrorMsg('ACCESS DENIED — INVALID CREDENTIALS');
      setTimeout(() => setStatus('idle'), 2000);
    }
  };

  return (
    <div style={styles.root}>
      {/* Animated grid background */}
      <div style={styles.grid} />

      <div style={styles.card}>
        {/* Top accent line */}
        <div style={styles.accentLine} />

        {/* Lock icon */}
        <div style={styles.iconWrap}>
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none">
            <rect x="3" y="11" width="18" height="11" rx="2" stroke="#00e5ff" strokeWidth="1.5"/>
            <path d="M7 11V7a5 5 0 0110 0v4" stroke="#00e5ff" strokeWidth="1.5"/>
            <circle cx="12" cy="16" r="1.5" fill="#00e5ff"/>
          </svg>
        </div>

        <h1 style={styles.title}>ALGO SYSTEM</h1>
        <p style={styles.subtitle}>RESTRICTED ACCESS — AUTHORISED USERS ONLY</p>

        <div style={styles.divider} />

        <form onSubmit={handleSubmit} style={styles.form}>
          <label style={styles.label}>USER IDENTITY</label>
          <div style={styles.staticField}>ADMIN</div>

          <label style={styles.label}>ACCESS KEY</label>
          <input
            type="password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            placeholder="Enter access key"
            style={{
              ...styles.input,
              ...(status === 'denied' ? styles.inputError : {}),
              ...(status === 'granted' ? styles.inputSuccess : {}),
            }}
            autoFocus
            disabled={status === 'loading' || status === 'granted'}
          />

          {errorMsg && (
            <p style={styles.errorText}>{errorMsg}</p>
          )}

          <button
            type="submit"
            disabled={status === 'loading' || status === 'granted' || !password}
            style={{
              ...styles.button,
              ...(status === 'granted' ? styles.buttonSuccess : {}),
              ...(status === 'denied' ? styles.buttonError : {}),
            }}
          >
            {status === 'loading' && `AUTHENTICATING${dots}`}
            {status === 'granted' && '✓ ACCESS GRANTED'}
            {status === 'denied' && '✗ ACCESS DENIED'}
            {(status === 'idle') && 'AUTHENTICATE'}
          </button>
        </form>

        <div style={styles.footer}>
          <span style={styles.footerDot} />
          ALGO TRADING SYSTEM v1.0
          <span style={styles.footerDot} />
        </div>

        {/* Bottom accent line */}
        <div style={{ ...styles.accentLine, marginTop: 4 }} />
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  root: {
    minHeight: '100vh',
    background: '#050d1a',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontFamily: "'Courier New', monospace",
    position: 'relative',
    overflow: 'hidden',
  },
  grid: {
    position: 'absolute',
    inset: 0,
    backgroundImage: `
      linear-gradient(rgba(0,229,255,0.03) 1px, transparent 1px),
      linear-gradient(90deg, rgba(0,229,255,0.03) 1px, transparent 1px)
    `,
    backgroundSize: '40px 40px',
    pointerEvents: 'none',
  },
  card: {
    width: 400,
    padding: '32px 36px',
    background: 'rgba(5, 20, 40, 0.92)',
    border: '1px solid rgba(0,229,255,0.25)',
    boxShadow: '0 0 40px rgba(0,229,255,0.08), inset 0 0 40px rgba(0,229,255,0.03)',
    position: 'relative',
  },
  accentLine: {
    width: '100%',
    height: 1,
    background: 'linear-gradient(90deg, transparent, #00e5ff, transparent)',
    marginBottom: 24,
  },
  iconWrap: {
    textAlign: 'center',
    marginBottom: 16,
    filter: 'drop-shadow(0 0 10px rgba(0,229,255,0.6))',
  },
  title: {
    color: '#00e5ff',
    fontSize: 22,
    letterSpacing: 8,
    textAlign: 'center',
    margin: '0 0 6px 0',
    textShadow: '0 0 20px rgba(0,229,255,0.5)',
    fontWeight: 700,
  },
  subtitle: {
    color: 'rgba(0,229,255,0.4)',
    fontSize: 9,
    letterSpacing: 3,
    textAlign: 'center',
    margin: '0 0 20px 0',
  },
  divider: {
    height: 1,
    background: 'rgba(0,229,255,0.12)',
    marginBottom: 24,
  },
  form: {
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
  },
  label: {
    color: 'rgba(0,229,255,0.6)',
    fontSize: 10,
    letterSpacing: 3,
    marginBottom: 4,
  },
  staticField: {
    color: '#00e5ff',
    fontSize: 13,
    letterSpacing: 4,
    padding: '10px 14px',
    border: '1px solid rgba(0,229,255,0.15)',
    background: 'rgba(0,229,255,0.04)',
    marginBottom: 16,
  },
  input: {
    background: 'rgba(0,229,255,0.05)',
    border: '1px solid rgba(0,229,255,0.25)',
    color: '#00e5ff',
    padding: '12px 14px',
    fontSize: 14,
    letterSpacing: 2,
    outline: 'none',
    marginBottom: 6,
    transition: 'border-color 0.2s, box-shadow 0.2s',
    fontFamily: "'Courier New', monospace",
    width: '100%',
    boxSizing: 'border-box',
  } as React.CSSProperties,
  inputError: {
    borderColor: '#ff4444',
    boxShadow: '0 0 12px rgba(255,68,68,0.2)',
  },
  inputSuccess: {
    borderColor: '#00ff88',
    boxShadow: '0 0 12px rgba(0,255,136,0.2)',
  },
  errorText: {
    color: '#ff4444',
    fontSize: 10,
    letterSpacing: 2,
    margin: '4px 0 10px 0',
    textShadow: '0 0 8px rgba(255,68,68,0.5)',
  },
  button: {
    marginTop: 8,
    padding: '13px',
    background: 'transparent',
    border: '1px solid #00e5ff',
    color: '#00e5ff',
    fontSize: 12,
    letterSpacing: 4,
    cursor: 'pointer',
    transition: 'all 0.2s',
    fontFamily: "'Courier New', monospace",
    boxShadow: '0 0 16px rgba(0,229,255,0.15)',
  },
  buttonSuccess: {
    borderColor: '#00ff88',
    color: '#00ff88',
    boxShadow: '0 0 20px rgba(0,255,136,0.3)',
  },
  buttonError: {
    borderColor: '#ff4444',
    color: '#ff4444',
    boxShadow: '0 0 20px rgba(255,68,68,0.2)',
  },
  footer: {
    marginTop: 28,
    color: 'rgba(0,229,255,0.25)',
    fontSize: 9,
    letterSpacing: 3,
    textAlign: 'center',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 10,
  },
  footerDot: {
    width: 4,
    height: 4,
    borderRadius: '50%',
    background: 'rgba(0,229,255,0.25)',
    display: 'inline-block',
  },
};
