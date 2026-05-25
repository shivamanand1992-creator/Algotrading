/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{js,jsx,ts,tsx}"],
  theme: {
    extend: {
      colors: {
        'jarvis-primary':       '#00e5ff',
        'jarvis-secondary':     '#1de9b6',
        'jarvis-accent':        '#00b0ff',
        'jarvis-bg-dark':       '#04080f',
        'jarvis-bg-panel':      'rgba(4, 14, 26, 0.75)',
        'jarvis-text-primary':  '#e2f0ff',
        'jarvis-text-secondary':'#4d7a9e',
      },
      animation: {
        'spin-slow':   'spin 10s linear infinite',
        'pulse-glow':  'pulseGlow 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'float':       'float 4s ease-in-out infinite',
        'scan':        'scanDown 6s ease-in-out infinite',
        'flicker':     'neonFlicker 5s infinite',
        'ring-expand': 'ringExpand 2s ease-out infinite',
      },
      keyframes: {
        pulseGlow: {
          '0%,100%': { boxShadow: '0 0 5px rgba(0,229,255,0.6), 0 0 10px rgba(0,229,255,0.3)' },
          '50%':     { boxShadow: '0 0 12px rgba(0,229,255,1), 0 0 28px rgba(0,229,255,0.6)' },
        },
        float: {
          '0%,100%': { transform: 'translateY(0)' },
          '50%':     { transform: 'translateY(-8px)' },
        },
        scanDown: {
          '0%':   { top: '0%',   opacity: '0' },
          '5%':   { opacity: '0.7' },
          '95%':  { opacity: '0.7' },
          '100%': { top: '100%', opacity: '0' },
        },
        ringExpand: {
          '0%':   { transform: 'scale(1)', opacity: '0.6' },
          '100%': { transform: 'scale(1.7)', opacity: '0' },
        },
      },
      fontFamily: {
        mono: ['Roboto Mono', 'Courier New', 'monospace'],
      },
      boxShadow: {
        'neon':        '0 0 10px rgba(0,229,255,0.5), 0 0 30px rgba(0,229,255,0.2)',
        'neon-intense':'0 0 8px #00e5ff, 0 0 20px rgba(0,229,255,0.6), 0 0 50px rgba(0,229,255,0.3)',
        'panel':       '0 8px 32px rgba(0,0,0,0.5), inset 0 1px 0 rgba(0,229,255,0.08)',
      },
    },
  },
  plugins: [],
};
