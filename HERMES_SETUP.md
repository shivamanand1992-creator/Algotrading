# Hermes AI Trading Agent - Setup Guide

**🚨 CRITICAL FIX APPLIED:** The system wasn't trading because ANTHROPIC_API_KEY was missing!

---

## 🔥 ROOT CAUSE ANALYSIS

Your Hermes agent was running but NOT making any trades. I found **THREE CRITICAL ISSUES**:

### 1. ❌ Missing Anthropic API Key (BLOCKING)
**Problem:** `ANTHROPIC_API_KEY` environment variable was never configured  
**Impact:** Hermes couldn't call Claude AI for market analysis  
**Evidence:** No "BUY/SELL/HOLD" decisions in logs, agent silently failed  

### 2. ❌ Angel One API Rate Limiting
**Problem:** Fetching historical data every 60 seconds exceeded API rate limits  
**Evidence:** Logs show `b'Access denied because of exceeding access rate'`  
**Impact:** Hermes fell back to demo data, never traded real positions

### 3. ❌ Silent Failure Mode
**Problem:** Agent returned generic HOLD when API key missing instead of crashing  
**Impact:** System appeared "working" but was actually broken  

---

## ✅ FIXES APPLIED

### Fix #1: Anthropic API Key Requirement
**File:** `.env.example`  
**Change:** Added `ANTHROPIC_API_KEY=sk-ant-...` to environment template  
**Now:** System will crash on startup if API key is missing (fail fast!)

### Fix #2: Historical Data Caching
**File:** `backend/services/hermes_intraday_service.py`  
**Change:** Cache historical candle data for 5 minutes  
**Now:** Reduced API calls from ~360/day to ~72/day (80% reduction)

### Fix #3: Loud Failure on Missing API Key
**File:** `backend/services/hermes_agent.py`  
**Change:** Raise `ValueError` on startup if ANTHROPIC_API_KEY not set  
**Now:** Deployment will fail immediately with clear error message

---

## 🚀 IMMEDIATE ACTION REQUIRED

### On Railway (Production):

1. **Add Environment Variable:**
   - Go to Railway dashboard → Variables
   - Click "New Variable"
   - Name: `ANTHROPIC_API_KEY`
   - Value: `sk-ant-api03-YOUR_KEY_HERE` (get from console.anthropic.com)

2. **Redeploy:**
   - Railway will auto-deploy when you add the variable
   - **OR** manually trigger redeploy

3. **Verify in Logs:**
   ```
   ✅ Look for: "[Hermes] Agent initialized with model=claude-haiku-4-5"
   ✅ Look for: "[Hermes] NIFTYBEES: BUY (confidence=0.75) - Bullish breakout..."
   ❌ Should NOT see: "Using demo market data"
   ❌ Should NOT see: "exceeding access rate"
   ```

---

## 📖 How to Get Anthropic API Key

1. Visit https://console.anthropic.com/
2. Sign in (or create account)
3. Go to "API Keys" section
4. Click "Create Key"
5. Copy the key (format: `sk-ant-api03-XXXX`)
6. **Save immediately** - you won't see it again!

**Cost Estimate:**
- Claude Haiku 4.5: $1/1M input tokens, $5/1M output tokens
- Hermes usage: ~1000 tokens per analysis
- Frequency: Every 60 seconds during market hours (6 hours/day)
- **Daily cost: $2-3 USD**
- **Monthly cost: ~$50-75 USD**

---

## 🎯 Verify Hermes is Actually Working

### 1. Check Backend Logs

**Good Signs:**
```
[Hermes] Agent initialized with model=claude-haiku-4-5
[Hermes] Historical data fetched and cached (14 candles)
[Hermes] NIFTYBEES: BUY (confidence=0.78) - Strong breakout above resistance...
[Hermes] ENTRY: NIFTYBEES 100qty @ ₹275.50 | SL @ ₹274.00
```

**Bad Signs:**
```
❌ ANTHROPIC_API_KEY environment variable is required
❌ Using demo market data (broker not connected)
❌ Access denied because of exceeding access rate
❌ [HermesLoop] Cycle: success (but no decision logged)
```

### 2. Check Frontend (Hermes Monitor)

Open `https://your-app.railway.app` → Click "👁️ Hermes Monitor"

**Should see:**
- Real-time activity feed updating every 60 seconds
- "Market Analysis" → "BUY Signal" or "HOLD" decisions
- Confidence percentages (e.g., "78%")
- Reasoning text from Claude AI

**If you see:**
- "Waiting for agent activity..." forever → API key issue
- No updates during trading hours (9:15 AM - 3:15 PM IST) → Check logs

### 3. Test API Endpoint

```bash
curl https://your-app.railway.app/api/hermes/status
```

**Expected response:**
```json
{
  "enabled": true,
  "instrument": "NIFTYBEES",
  "position": null,
  "trades_today": 0,
  "daily_pnl": 0.0,
  "last_analysis": "2026-07-20T10:15:23+05:30",
  "capital_per_trade": 10000,
  "max_trades_per_day": 4,
  "min_confidence": 0.7
}
```

---

## 🔧 Configuration (config/config.yaml)

```yaml
hermes:
  enabled: true                      # Master on/off switch
  instrument: "NIFTYBEES"            # Stock symbol to trade
  capital_per_trade: 10000           # ₹10,000 per trade
  max_trades_per_day: 4              # Safety limit
  min_confidence: 0.7                # 70% AI confidence minimum
  check_interval_seconds: 60         # How often to analyze
  
  # Risk Management
  use_atr_stops: true                # Dynamic stop-loss
  atr_multiplier: 1.5                # SL = Entry - (1.5 × ATR)
  use_trailing_sl: true              # Lock in profits
  trailing_activation_pct: 0.5       # Start trailing after +0.5%
  trailing_distance_pct: 0.3         # Trail 0.3% from peak
  
  # Entry Filters
  require_volume_confirmation: true  # Check volume surge
  volume_multiplier: 1.5             # Need 1.5x average volume
  use_ml_consensus: true             # Require ML + LLM agreement
  ml_min_confidence: 0.6             # ML model confidence threshold
```

---

## 🐛 Troubleshooting Guide

### Issue: "ANTHROPIC_API_KEY environment variable is required"
**Cause:** API key not set on Railway  
**Fix:** Add the variable in Railway dashboard → Variables

### Issue: Hermes always says "HOLD"
**Causes (normal behavior):**
1. Market conditions don't meet entry criteria
2. Confidence below 70%
3. Volume too low (<1.5x average)
4. Already hit max trades for the day
5. Avoiding bad times (9:15-9:30 AM, 3:00-3:15 PM)

**Check logs for:**
```
[Hermes] ML Consensus: ❌ LLM=0.75, ML=0.45 (below 0.6 threshold)
[Hermes] Skipping trade - bad time of day
[Hermes] Max trades reached (4)
[Hermes] Volume confirmation: ❌ 1.2x < 1.5x threshold
```

### Issue: "Access denied because of exceeding access rate"
**Cause:** Too many API calls to Angel One  
**Fix:** Already applied (5-minute caching). If persists, increase `check_interval_seconds` to 90.

### Issue: No WebSocket updates on frontend
**Fixes:**
1. Hard refresh browser (Ctrl+Shift+R)
2. Check console for WebSocket errors
3. Verify backend is broadcasting (check logs for "ws_manager.broadcast")

---

## ⚠️ SAFETY & RISK WARNINGS

**Hermes will place REAL trades with REAL money when:**
- `hermes.enabled = true` in config
- `ANGEL_API_KEY` credentials are valid
- Angel One client is connected
- Trading hours (9:15 AM - 3:15 PM IST)

**Before going live:**
1. ✅ Start with small `capital_per_trade` (₹5,000-10,000)
2. ✅ Watch Hermes Monitor for first full trading day
3. ✅ Verify stop-loss orders are placed
4. ✅ Check Telegram alerts are working
5. ✅ Review trades at end of day
6. ✅ Only increase capital after 5-10 successful trading days

**You can always:**
- Manually exit positions via UI
- Set `enabled: false` to pause Hermes
- Check status via `/api/hermes/status`

---

## 📝 Files Changed (2026-07-20)

### Modified:
1. `.env.example` - Added ANTHROPIC_API_KEY requirement
2. `backend/services/hermes_agent.py` - Fail fast if API key missing
3. `backend/services/hermes_intraday_service.py` - Added 5-min caching for historical data

### Commit:
```bash
git add .env.example backend/services/hermes_agent.py backend/services/hermes_intraday_service.py
git commit -m "CRITICAL FIX: Hermes not trading - missing ANTHROPIC_API_KEY + rate limit caching

- Add ANTHROPIC_API_KEY requirement to .env.example
- Fail loudly on startup if API key missing (no silent failures)
- Cache historical candle data for 5 minutes (reduce API calls 80%)
- Fixes: No trades, rate limiting, silent demo data fallback"
```

---

## ✅ Deployment Checklist

**Before Monday market open:**

- [ ] 1. Add `ANTHROPIC_API_KEY` to Railway environment variables
- [ ] 2. Verify `ANGEL_API_KEY` credentials are valid
- [ ] 3. Check `hermes.enabled = true` in config.yaml
- [ ] 4. Push code changes to Railway
- [ ] 5. Wait for deployment to complete
- [ ] 6. Check logs for "[Hermes] Agent initialized"
- [ ] 7. Open Hermes Monitor page
- [ ] 8. Verify WebSocket connection (green indicator)
- [ ] 9. Wait for 9:15 AM IST market open
- [ ] 10. Watch for first "Market Analysis" broadcast

---

**Status:** 🟡 Fixes applied, awaiting ANTHROPIC_API_KEY on Railway  
**Next Action:** Add API key → Redeploy → Verify logs  
**Documentation Updated:** 2026-07-20 10:35 AM IST

**Key Features:**
- ✅ Fully automated - no manual intervention needed
- ✅ AI-powered decision making using Groq LLM
- ✅ Intraday only (all positions closed by 3:15 PM)
- ✅ Risk-managed (stop loss, targets, max trades per day)
- ✅ Telegram alerts for all trades
- ✅ Separate from swing trading system

---

## Quick Start

### 1. Get Groq API Key (FREE)

1. Go to https://console.groq.com
2. Sign up (free tier: 30 requests/min)
3. Create API key
4. Copy the key

### 2. Add to Railway Environment Variables

In Railway dashboard → Variables:

```
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxxx
```

### 3. Enable Hermes in Config

Edit `config/config.yaml`:

```yaml
hermes:
  enabled: true  # ← Change to true
  instrument: "NIFTYBEES"  # Stock to trade
  capital_per_trade: 10000  # ₹10,000 per trade
  max_trades_per_day: 4  # Maximum 4 trades
  min_confidence: 0.7  # Only trade if AI is 70%+ confident
```

### 4. Deploy

```bash
git add .
git commit -m "Enable Hermes AI agent"
git push
```

Railway will auto-deploy.

---

## How It Works

### Trading Flow

```
Every 30 seconds (9:15 AM - 3:10 PM):
  ↓
1. Fetch live market data (price, RSI, MACD, volume)
  ↓
2. Send to Hermes AI Agent for analysis
  ↓
3. AI decides: BUY / HOLD / CLOSE_POSITION
  ↓
4. If confidence >= 70% → Execute trade automatically
  ↓
5. Monitor position for SL/target
  ↓
6. Force exit all positions at 3:10 PM
```

### Decision Making

Hermes analyzes:
- **Breakout setup**: Price > previous day high + volume surge
- **Bounce setup**: Price near previous day low + reversal signals
- **Technical indicators**: RSI (30-70), MACD positive, volume >1.3x average
- **Risk management**: Stop loss 0.6%, target 0.9%

### Example Decision

```json
{
  "action": "BUY",
  "confidence": 0.85,
  "entry_price": 100.50,
  "stop_loss": 99.90,
  "target": 101.40,
  "setup_type": "breakout",
  "quantity": 99,
  "reasoning": "Strong breakout above ₹100.40 with 1.7x volume confirmation. RSI at 62, MACD positive."
}
```

---

## API Endpoints

### Get Status
```bash
GET /api/hermes/status
```

Returns:
```json
{
  "enabled": true,
  "instrument": "NIFTYBEES",
  "position": {...},  // Current open position (if any)
  "trades_today": 2,
  "daily_pnl": 450.75
}
```

### Update Config
```bash
POST /api/hermes/config
{
  "enabled": true,
  "instrument": "NIFTYBEES",
  "capital_per_trade": 15000,
  "max_trades_per_day": 3,
  "min_confidence": 0.75
}
```

### Get Today's Trades
```bash
GET /api/hermes/trades/today
```

### Manual Exit
```bash
POST /api/hermes/force-exit
```

---

## Monitoring

### Logs

Check Railway logs for:

```
[Hermes] ENTRY: NIFTYBEES 99qty @ ₹100.50
[Hermes] EXIT: NIFTYBEES @ ₹101.35 | P&L=₹84.15
[Hermes] Analysis: BUY (confidence=0.85) - Strong breakout...
```

### Telegram Alerts

You'll receive alerts for:
- 🟢 **Entry**: Stock, qty, entry price, SL, target
- 🔴 **Exit**: P&L, exit reason
- 📊 **Daily Summary**: Total trades, P&L

---

## Safety Features

### Built-in Risk Controls

1. **Max Trades**: Default 4/day (configurable)
2. **Stop Loss**: 0.6% of entry price
3. **Target**: 0.9% profit
4. **Time Window**: Only trades 9:15 AM - 3:10 PM
5. **Force Exit**: All positions closed by 3:15 PM
6. **Confidence Gate**: Only executes if AI >=70% confident

### Disable Anytime

```bash
POST /api/hermes/config
{
  "enabled": false
}
```

Or edit `config.yaml` and redeploy.

---

## Testing

### Paper Mode (Recommended First Week)

Hermes automatically runs in paper mode if Angel One is not connected. Test the decision-making logic without real money.

### Live Mode

Once confident:
1. Ensure Angel One API credentials are set
2. Verify `GROQ_API_KEY` is configured
3. Set `enabled: true`
4. Monitor first day closely

---

## Costs

### Groq API (FREE Tier)
- 30 requests/minute
- Hermes uses ~120 requests/day (1 every 30s for 1 hour)
- **Cost: ₹0** (free tier sufficient)

### Brokerage
- Angel One MIS intraday: ~₹20/order
- 4 trades/day = ₹80/day
- **Cost: Minimal**

---

## Troubleshooting

### Issue: "Hermes always returns HOLD"

**Cause**: Market conditions don't meet setup criteria
**Fix**: Normal behavior - Hermes is conservative. Try during volatile market hours (9:30-10:30 AM).

### Issue: "No GROQ_API_KEY configured"

**Cause**: Environment variable missing
**Fix**: Add `GROQ_API_KEY` to Railway variables and redeploy.

### Issue: "Low confidence (0.35)"

**Cause**: AI doesn't see clear setup
**Fix**: This is correct behavior - prevents bad trades.

### Issue: "Order placement failed"

**Cause**: Broker connection issue or stock under restriction
**Fix**: Check Angel One connection, ensure stock is tradeable.

---

## Advanced Configuration

### Change Trading Instrument

```yaml
hermes:
  instrument: "SBIN"  # State Bank of India
```

### Adjust Risk Per Trade

```yaml
hermes:
  capital_per_trade: 20000  # ₹20k per trade (higher position size)
```

### Increase Confidence Threshold

```yaml
hermes:
  min_confidence: 0.80  # Only trade if 80%+ confident (more selective)
```

---

## Comparison: Swing vs Hermes

| Feature | Swing Autopilot | Hermes Intraday |
|---------|----------------|-----------------|
| **Timeframe** | Multi-day (CNC) | Same-day only (MIS) |
| **Decision** | Technical screener (rule-based) | AI reasoning (LLM) |
| **Frequency** | Once/day (9:20 AM) | Every 30 seconds |
| **Universe** | 50 Nifty stocks | Single stock (NIFTYBEES default) |
| **Max Trades** | 3 positions held | 4 trades/day |
| **Capital** | ₹10k/position | ₹10k/trade |
| **Exit** | SL/target hit (days) | 3:15 PM force exit |

Both can run **simultaneously** without interfering.

---

## Next Steps

1. ✅ Add `GROQ_API_KEY` to Railway
2. ✅ Enable Hermes in config
3. ✅ Deploy and monitor logs
4. ✅ Test in paper mode for 1 week
5. ✅ Go live when confident

**Questions?** Check logs or Telegram alerts for agent decisions.
