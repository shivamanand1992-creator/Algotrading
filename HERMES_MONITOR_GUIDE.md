# 🤖 HERMES AGENT MONITOR - USER GUIDE

**Status:** ✅ Deployed to Railway  
**Date:** 2026-07-17

---

## 🎯 WHAT IS IT?

The **Hermes Agent Monitor** is a fancy Jarvis-style real-time visualization dashboard that shows **everything** the Hermes AI trading agent is doing, moment by moment.

### Two Views Available:

1. **Hermes Control Panel** (🤖 in sidebar)
   - Start/stop the agent
   - Configure settings (capital, confidence threshold, max trades)
   - View current position
   - See today's trade history
   - Force exit positions

2. **Hermes Monitor** (👁️ in sidebar) ← **NEW!**
   - Real-time agent activity log
   - Live analysis status
   - AI confidence visualization
   - Decision reasoning display
   - Animated status indicators

---

## 🎨 UI FEATURES

### Real-Time Activity Stream

The monitor shows a live feed of **every action** Hermes takes:

```
🧠 Market Analysis
   Analyzing NIFTYBEES for trading opportunities
   [Status: ANALYZING | Time: 12:45:23]

🔍 Low Confidence  
   Setup confidence 65% below threshold 70%
   [Status: WAITING | Confidence: ████░░░░░░ 65%]

⚡ BUY Signal
   Breakout above ₹247.50 with volume confirmation
   [Status: EXECUTING | Confidence: ███████░░░ 78%]
   Decision: BUY | Entry: ₹247.00 | SL: ₹245.50

👁️ Position Monitoring
   Monitoring NIFTYBEES position
   [Status: MONITORING]
```

### Visual Elements

**Status Colors:**
- 🔵 **Analyzing** (Cyan) - Agent is thinking
- 🟠 **Executing** (Orange) - Placing orders
- 🟢 **Monitoring** (Green) - Watching open position
- ⚪ **Waiting** (Gray) - No action, waiting for setup
- 🔴 **Error** (Red) - Something went wrong

**Animated Effects:**
- ✨ Pulse animation when agent is analyzing
- 📊 Confidence bars that fill based on AI certainty
- 🎯 Auto-scrolling to latest activity
- 💫 Smooth slide-in animations for new events

### Live Metrics Dashboard

**Left Panel shows:**
- Current tracking instrument (NIFTYBEES)
- Current price (real-time)
- Today's P&L (animated color based on profit/loss)
- Trades count with progress bar (e.g., 2/4 trades)
- Confidence threshold with visual bar
- Capital per trade
- Active position details (if any)

---

## 📡 HOW IT WORKS

### WebSocket Real-Time Updates

The monitor connects to a WebSocket stream that broadcasts **every Hermes action**:

1. **Agent starts analyzing** → Broadcast: "Analyzing NIFTYBEES..."
2. **AI makes decision** → Broadcast: "BUY Signal with 78% confidence"
3. **ML consensus check** → Broadcast: "ML consensus: ✅ Approved"
4. **Order execution** → Broadcast: "Executing BUY order..."
5. **Position monitoring** → Broadcast: "Monitoring position..."
6. **Target/SL hit** → Broadcast: "Target reached, exiting position"

**Update Frequency:**
- WebSocket: Instant (real-time)
- Metrics refresh: Every 5 seconds
- Hermes analysis cycle: Every 60 seconds

---

## 🔧 TECHNICAL DETAILS

### Frontend Components

**HermesAgentMonitor.tsx** - New component with:
- WebSocket connection for live updates
- Activity log with 50-event buffer
- Auto-scrolling to latest activity
- Responsive 3-column grid layout
- Animated status indicators
- Real-time metrics display

### Backend Changes

**Modified:** `backend/main.py` - `_hermes_intraday_loop()`

Added WebSocket broadcasts for:
- Analysis start/end
- Decision outcomes (BUY, HOLD, WAIT)
- Confidence levels
- ML consensus results
- Position monitoring status
- Market close events
- Error states

**Broadcast Format:**
```python
await ws_manager.broadcast({
    "type": "hermes_activity",
    "action": "Market Analysis",
    "details": "Analyzing NIFTYBEES for trading opportunities",
    "status": "analyzing",  # analyzing|executing|monitoring|waiting|success|error
    "confidence": 0.78,     # Optional: 0.0-1.0
    "decision": {...}       # Optional: Full decision object
})
```

---

## 🎮 HOW TO USE

### Access the Monitor

1. **Login** to the trading dashboard
2. Click **👁️ Hermes Monitor** in the sidebar
3. Watch the real-time activity log populate

### What You'll See

**When Market is Open (9:15 AM - 3:15 PM IST):**
- Activity every 60 seconds
- "Analyzing market..." messages
- AI confidence scores
- Buy/Sell signals
- Position monitoring updates

**When Position is Open:**
- Continuous monitoring messages
- Real-time P&L updates
- Trailing stop-loss adjustments
- Target/SL hit notifications

**When Market is Closed:**
- "Market closed - force-exiting positions"
- Daily summary

---

## 📊 ACTIVITY LOG EXAMPLES

### Successful Trade Flow:

```
12:30:15 🧠 Market Analysis
         Analyzing NIFTYBEES for trading opportunities
         [ANALYZING]

12:30:18 ⚡ BUY Signal
         Breakout above ₹247.50 with strong volume
         [EXECUTING | Confidence: ███████░░░ 78%]
         Decision: BUY | Reasoning: "Price broke above previous day high..."

12:30:20 ✅ Order Executed
         Entry: ₹247.00 | Qty: 40 | SL: ₹245.50 | Target: ₹248.20
         [SUCCESS]

12:31:15 👁️ Position Monitoring
         Monitoring NIFTYBEES position
         [MONITORING]

12:32:15 👁️ Position Monitoring
         Monitoring NIFTYBEES position
         [MONITORING]

12:35:20 ✅ Target Hit
         Target reached at ₹248.25, exiting position
         [EXECUTING]
```

### Low Confidence Rejection:

```
14:15:20 🧠 Market Analysis
         Analyzing NIFTYBEES for trading opportunities
         [ANALYZING]

14:15:23 ⏸️ Low Confidence
         Setup confidence 62% below threshold 70%
         [WAITING | Confidence: ██████░░░░ 62%]
```

### ML Consensus Failure:

```
10:45:15 🧠 Market Analysis
         Analyzing NIFTYBEES for trading opportunities
         [ANALYZING]

10:45:18 ⏸️ ML Consensus Failed
         LLM confidence 75% but ML model disagrees (ML=45%)
         [WAITING | Confidence: ███████░░░ 75%]
```

---

## 🚀 DEPLOYMENT

**Code pushed to:** `claude/tender-mendel-R2h2U` branch  
**Railway auto-deploy:** ~2 minutes  

**After deployment:**
1. Visit your Railway dashboard URL
2. Login
3. Navigate to 👁️ Hermes Monitor
4. Watch the magic happen! ✨

---

## 🎯 KEY BENEFITS

### For Traders:
- ✅ **Full transparency** - See exactly what AI is thinking
- ✅ **Confidence scores** - Know how certain the AI is
- ✅ **Decision reasoning** - Understand WHY trades happen
- ✅ **Real-time monitoring** - Track positions live
- ✅ **No surprises** - Every action is logged and visible

### For Debugging:
- ✅ **Instant feedback** - See errors immediately
- ✅ **Activity history** - Review what happened
- ✅ **Confidence tracking** - Identify threshold issues
- ✅ **ML consensus visibility** - See when models disagree

---

## 📝 NOTES

- Activity log keeps **last 50 events** (auto-scrolls)
- WebSocket reconnects automatically if disconnected
- Works on mobile (responsive design)
- Jarvis theme with cyan/green/red color scheme
- Updates continue even when not viewing the page (background WebSocket)

---

## 🎨 DESIGN PHILOSOPHY

Inspired by **JARVIS from Iron Man:**
- High-tech, futuristic aesthetic
- Real-time data visualization
- Color-coded status indicators
- Smooth animations
- Clear, readable typography (monospace fonts)
- Dark theme with glowing accents
- Informative without clutter

---

**Built with:** React + TypeScript + WebSocket + Tailwind  
**AI Model:** Claude Haiku 4.5 (upgraded from retired 3.5 Haiku)  
**Status:** ✅ Production Ready

Enjoy watching your AI trading agent work in real-time! 🚀
