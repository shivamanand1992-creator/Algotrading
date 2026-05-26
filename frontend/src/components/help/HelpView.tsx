import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

interface Section {
  id: string;
  title: string;
  icon: string;
  content: React.ReactNode;
}

function AccordionSection({ section, isOpen, onToggle }: {
  section: Section;
  isOpen: boolean;
  onToggle: () => void;
}) {
  return (
    <div
      className="rounded-xl overflow-hidden"
      style={{ border: '1px solid rgba(0,229,255,0.2)', background: 'rgba(0,20,40,0.6)' }}
    >
      <button
        className="w-full px-6 py-4 flex items-center justify-between text-left transition-colors hover:bg-jarvis-primary/5"
        onClick={onToggle}
      >
        <div className="flex items-center gap-3">
          <span className="text-2xl">{section.icon}</span>
          <span className="text-jarvis-primary font-bold tracking-wider uppercase text-sm">{section.title}</span>
        </div>
        <motion.span
          className="text-jarvis-primary text-lg"
          animate={{ rotate: isOpen ? 180 : 0 }}
          transition={{ duration: 0.2 }}
        >
          ▼
        </motion.span>
      </button>
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: 'easeInOut' }}
            style={{ overflow: 'hidden' }}
          >
            <div className="px-6 pb-6 pt-2 text-jarvis-text-secondary text-sm leading-relaxed border-t border-jarvis-primary/10">
              {section.content}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function Step({ n, text }: { n: number; text: string }) {
  return (
    <div className="flex items-start gap-3 py-2">
      <div
        className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0 mt-0.5"
        style={{ background: 'rgba(0,229,255,0.15)', border: '1px solid rgba(0,229,255,0.4)', color: '#00e5ff' }}
      >
        {n}
      </div>
      <p className="text-jarvis-text-secondary">{text}</p>
    </div>
  );
}

function Badge({ label, color }: { label: string; color: 'green' | 'yellow' | 'red' | 'cyan' }) {
  const colors = {
    green:  'bg-green-400/15 text-green-400 border-green-400/30',
    yellow: 'bg-yellow-400/15 text-yellow-400 border-yellow-400/30',
    red:    'bg-red-400/15 text-red-400 border-red-400/30',
    cyan:   'bg-jarvis-primary/15 text-jarvis-primary border-jarvis-primary/30',
  };
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-bold border mr-1 ${colors[color]}`}>
      {label}
    </span>
  );
}

function Metric({ term, def }: { term: string; def: string }) {
  return (
    <div className="py-2 border-b border-jarvis-primary/10 last:border-0">
      <span className="text-jarvis-primary font-mono font-bold">{term}</span>
      <span className="text-jarvis-text-secondary ml-3">{def}</span>
    </div>
  );
}

const sections: Section[] = [
  {
    id: 'quickstart',
    title: 'Quick Start — Get Running in 5 Steps',
    icon: '🚀',
    content: (
      <div>
        <Step n={1} text="Open the Dashboard. Check the top-right header — it shows SYSTEM HEALTHY and the current mode (PAPER or DEMO)." />
        <Step n={2} text="Go to the System page or call POST /api/system/status. Confirm broker_connected: true. If not, add your Railway outbound IP (from /api/system/my-ip) to Angel One API → Settings → Authorized IPs, then hit POST /api/system/reconnect." />
        <Step n={3} text="On the Dashboard, find the 'Model Training' panel. Click 'Train Now (60 days)'. Wait ~10–15 minutes. The progress bar will advance through 5 steps. Once complete, the panel turns green." />
        <Step n={4} text="Navigate to Strategies. Click 'START (PAPER)' on any strategy. It will turn green and show RUNNING." />
        <Step n={5} text="Return to Dashboard. Within 5 minutes you'll see signals count increase and the Nifty chart and ML predictions updating live." />
      </div>
    ),
  },
  {
    id: 'modes',
    title: 'Modes — Demo, Paper, and Live',
    icon: '🔄',
    content: (
      <div className="space-y-4">
        <div>
          <div className="flex items-center gap-2 mb-1"><Badge label="DEMO" color="yellow" /><span className="font-bold text-jarvis-primary">Demo Mode</span></div>
          <p>Set <code className="text-jarvis-accent bg-black/30 px-1 rounded">DEMO_MODE=true</code> in Railway environment variables. No Angel One credentials needed. All data is synthetic — useful for exploring the UI without a broker account. Signals are fake and no orders are ever placed.</p>
        </div>
        <div>
          <div className="flex items-center gap-2 mb-1"><Badge label="PAPER" color="cyan" /><span className="font-bold text-jarvis-primary">Paper Mode (default)</span></div>
          <p>Real market data from Angel One. Strategies generate real signals based on live Nifty data and ML predictions. <strong>No real orders are placed</strong> — positions are tracked locally in memory. Ideal for validating strategy performance before going live.</p>
        </div>
        <div>
          <div className="flex items-center gap-2 mb-1"><Badge label="LIVE" color="red" /><span className="font-bold text-jarvis-primary">Live Mode</span></div>
          <p>Real orders placed via Angel One SmartAPI. Use with extreme caution. Start with small capital. Ensure your risk limits (daily loss limit, per-trade risk) are set conservatively in <code className="text-jarvis-accent bg-black/30 px-1 rounded">config/config.yaml</code> before switching.</p>
        </div>
        <p className="text-xs text-jarvis-text-secondary/70 mt-2">Switch mode via the PAPER dropdown in the top-right header, or via <code className="text-jarvis-accent bg-black/30 px-1 rounded">POST /api/system/mode</code>.</p>
      </div>
    ),
  },
  {
    id: 'training',
    title: 'Training the ML Models',
    icon: '🧠',
    content: (
      <div className="space-y-3">
        <p><strong className="text-jarvis-primary">Why training is needed:</strong> The system uses two ML models to generate signals — a Market Regime Classifier (XGBoost) and a Price Direction Predictor (LSTM + XGBoost + LightGBM ensemble). Without trained weights, strategies run but generate zero signals.</p>
        <p><strong className="text-jarvis-primary">What happens during training:</strong></p>
        <div className="space-y-1 pl-3 border-l-2 border-jarvis-primary/30">
          <p>Step 1/5 — Fetch 60 days of Nifty 5-minute OHLCV candles from Angel One (batched in 30-day chunks)</p>
          <p>Step 2/5 — Compute ~30 technical features: EMA, RSI, MACD, ADX, SuperTrend, Bollinger Bands, ATR, OBV</p>
          <p>Step 3/5 — Auto-label market regimes (trending_up / trending_down / ranging / high_volatility) and train XGBoost classifier</p>
          <p>Step 4/5 — Label price direction (+1/0/-1) with 5-candle horizon, train LSTM + XGBoost + LightGBM, save ensemble weights</p>
          <p>Step 5/5 — Evaluate on 20% holdout, log accuracy and confusion matrix</p>
        </div>
        <p><strong className="text-jarvis-primary">Training time:</strong> ~10–15 minutes on Railway (mostly data fetch + LSTM training). Use 60 days to start, 252 days for production quality.</p>
        <p><strong className="text-jarvis-primary">Weights persist across deploys?</strong> No — Railway's filesystem is ephemeral. Retrain after each deploy, or upgrade to a Railway Volume for persistence.</p>
        <p><strong className="text-jarvis-primary">How to retrain:</strong> Click "Train Now" on the Dashboard, or call <code className="text-jarvis-accent bg-black/30 px-1 rounded">POST /api/system/train?days=60</code>.</p>
      </div>
    ),
  },
  {
    id: 'strategies',
    title: 'The Three Strategies',
    icon: '⚡',
    content: (
      <div className="space-y-5">
        <div>
          <p className="text-jarvis-primary font-bold mb-1">Trend Following</p>
          <p><strong>Best regime:</strong> <Badge label="trending_up" color="green" /> <Badge label="trending_down" color="red" /></p>
          <p className="mt-1">Buys Nifty Call options (CE) on confirmed uptrends, Put options (PE) on downtrends. Uses EMA crossover (9/21), RSI zone, MACD histogram, VWAP position, SuperTrend direction, and ADX strength filter. Stop-loss is ATR-based (2×ATR), target at 2:1 reward-to-risk.</p>
        </div>
        <div>
          <p className="text-jarvis-primary font-bold mb-1">Premium Selling</p>
          <p><strong>Best regime:</strong> <Badge label="ranging" color="yellow" /></p>
          <p className="mt-1">Sells short strangles (OTM CE + OTM PE) when IV is elevated and PCR near equilibrium. Profits from time decay (theta). Exits when premium decays by the profit target or a stop-loss on the net credit is triggered. Requires careful risk management due to unlimited theoretical risk on short options.</p>
        </div>
        <div>
          <p className="text-jarvis-primary font-bold mb-1">Scalping</p>
          <p><strong>Best regime:</strong> <Badge label="any" color="cyan" /></p>
          <p className="mt-1">High-frequency 1-2 minute scalps using 5-minute candles for support/resistance context and 1-minute candles for entry triggers. Targets 15–20 point option premium moves from intraday S/R bounces with volume confirmation. Tight stop-losses essential.</p>
        </div>
      </div>
    ),
  },
  {
    id: 'metrics',
    title: 'Understanding the Metrics',
    icon: '📊',
    content: (
      <div>
        <Metric term="LTP" def="Last Traded Price of Nifty 50 spot index from Angel One" />
        <Metric term="Market Regime" def="ML-classified market state: trending_up, trending_down, ranging, or high_volatility. Determines which strategies activate." />
        <Metric term="IV Percentile" def="Implied Volatility Percentile — how expensive options are today vs the past year. High IV (>70%) favours premium selling; low IV (<30%) favours buying options." />
        <Metric term="PCR" def="Put-Call Ratio — total put OI / total call OI. >1.2 is bearish sentiment; <0.7 is bullish. Near 1.0 is neutral/ranging." />
        <Metric term="Confidence" def="0–1 score from the ML ensemble indicating certainty of the predicted direction or regime. Values <0.65 are filtered out and result in NO_TRADE." />
        <Metric term="Total P&L" def="Sum of unrealized P&L across all open positions." />
        <Metric term="Daily P&L" def="Net realised + unrealised gain/loss since midnight. Counted against the daily loss limit." />
        <Metric term="Capital Used %" def="(sum of entry_price × qty for open positions) / total_capital. High usage = higher risk." />
        <Metric term="Signals Today" def="Number of trade signals generated by a strategy since market open, including NO_TRADE signals." />
      </div>
    ),
  },
  {
    id: 'risk',
    title: 'Risk Management',
    icon: '🛡️',
    content: (
      <div className="space-y-3">
        <p>All risk parameters are in <code className="text-jarvis-accent bg-black/30 px-1 rounded">config/config.yaml</code> under <code className="text-jarvis-accent bg-black/30 px-1 rounded">risk_management</code>.</p>
        <div className="space-y-2">
          <div className="p-3 rounded-lg" style={{ background: 'rgba(0,229,255,0.05)', border: '1px solid rgba(0,229,255,0.15)' }}>
            <p className="text-jarvis-primary font-bold text-xs uppercase">Daily Loss Limit</p>
            <p>Default ₹20,000. If total daily P&L drops below −₹20,000, all strategies auto-stop. Shown in the Risk page as a progress bar.</p>
          </div>
          <div className="p-3 rounded-lg" style={{ background: 'rgba(0,229,255,0.05)', border: '1px solid rgba(0,229,255,0.15)' }}>
            <p className="text-jarvis-primary font-bold text-xs uppercase">Per-Trade Risk %</p>
            <p>Default 1% of capital per trade. Determines position sizing — number of lots = (capital × risk%) / (entry − stop-loss).</p>
          </div>
          <div className="p-3 rounded-lg" style={{ background: 'rgba(0,229,255,0.05)', border: '1px solid rgba(0,229,255,0.15)' }}>
            <p className="text-jarvis-primary font-bold text-xs uppercase">Max Open Positions</p>
            <p>Default 5. New signals are rejected if this count is reached. Visible in the Dashboard circular widget.</p>
          </div>
        </div>
        <p className="text-xs text-jarvis-text-secondary/70">In paper mode, risk limits are enforced on the simulated portfolio. In live mode, they gate actual orders.</p>
      </div>
    ),
  },
  {
    id: 'troubleshooting',
    title: 'Troubleshooting',
    icon: '🔧',
    content: (
      <div className="space-y-4">
        <div>
          <p className="text-yellow-400 font-bold">❌ Broker Not Connected</p>
          <p className="mt-1">1. Check Railway env vars: <code className="text-jarvis-accent bg-black/30 px-1 rounded">ANGEL_API_KEY</code>, <code className="text-jarvis-accent bg-black/30 px-1 rounded">ANGEL_CLIENT_ID</code>, <code className="text-jarvis-accent bg-black/30 px-1 rounded">ANGEL_PASSWORD</code>, <code className="text-jarvis-accent bg-black/30 px-1 rounded">ANGEL_TOTP_SECRET</code>.</p>
          <p>2. Get Railway's outbound IP: <code className="text-jarvis-accent bg-black/30 px-1 rounded">GET /api/system/my-ip</code></p>
          <p>3. Add that IP to Angel One portal → Settings → API → Authorized IPs.</p>
          <p>4. Force reconnect: <code className="text-jarvis-accent bg-black/30 px-1 rounded">POST /api/system/reconnect</code></p>
        </div>
        <div>
          <p className="text-yellow-400 font-bold">❌ Strategy Running but 0 Signals</p>
          <p className="mt-1">Models are not trained. Click "Train Now" on the Dashboard. After training completes (~15 min), signals will appear on the next 5-minute cycle.</p>
        </div>
        <div>
          <p className="text-yellow-400 font-bold">❌ Training Failed</p>
          <p className="mt-1">Check the error message in the training widget. Common causes: broker not connected (no data to fetch), Railway memory limit hit (reduce days to 30). Try again with fewer days first.</p>
        </div>
        <div>
          <p className="text-yellow-400 font-bold">❌ Chart Shows No Data</p>
          <p className="mt-1">Angel One only provides data during and near market hours (9:15–15:30 IST, weekdays). Outside market hours the chart may be empty or show only prior-day data.</p>
        </div>
        <div>
          <p className="text-yellow-400 font-bold">❌ "Failed to start strategy"</p>
          <p className="mt-1">Check that the broker is connected first. In paper mode the strategy service requires a valid signal generator, which requires trained models.</p>
        </div>
      </div>
    ),
  },
];

export function HelpView() {
  const [openSections, setOpenSections] = useState<Set<string>>(new Set(['quickstart']));

  const toggle = (id: string) => {
    setOpenSections(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <motion.div
      className="space-y-4 max-w-4xl mx-auto"
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
    >
      <div className="flex items-center justify-between mb-2">
        <div>
          <h2 className="text-2xl font-black text-jarvis-primary glow-text tracking-widest uppercase">
            Help & Documentation
          </h2>
          <p className="text-xs text-jarvis-text-secondary mt-1 tracking-wider">
            Everything you need to understand and operate the Shivam Trading System
          </p>
        </div>
        <button
          className="text-xs text-jarvis-text-secondary hover:text-jarvis-primary transition-colors px-3 py-1.5 rounded border border-jarvis-primary/20 hover:border-jarvis-primary/50"
          onClick={() => setOpenSections(new Set(sections.map(s => s.id)))}
        >
          Expand All
        </button>
      </div>

      {sections.map(section => (
        <AccordionSection
          key={section.id}
          section={section}
          isOpen={openSections.has(section.id)}
          onToggle={() => toggle(section.id)}
        />
      ))}
    </motion.div>
  );
}
