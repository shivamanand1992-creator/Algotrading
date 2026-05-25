/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/**/*.{js,jsx,ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        'jarvis-primary': '#00e5ff',
        'jarvis-secondary': '#1de9b6',
        'jarvis-accent': '#00b0ff',
        'jarvis-bg-dark': '#0a0e1a',
        'jarvis-bg-panel': 'rgba(10, 30, 50, 0.6)',
      },
      animation: {
        'spin-slow': 'spin 3s linear infinite',
        'pulse-glow': 'pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
    },
  },
  plugins: [],
}
