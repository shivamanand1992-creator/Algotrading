# Hermes Agent - Monitoring & Testing Guide

## ✅ Hermes is Now ENABLED

Current status: **Paper Mode** (simulated trades)

---

## What Will Happen Now

### During Market Hours (9:15 AM - 3:15 PM IST)

**Every 30 seconds**, Hermes will:

1. ✅ Fetch NIFTYBEES market data (price, RSI, MACD, volume)
2. ✅ Analyze market conditions using demo data (no Groq API needed yet)
3. ✅ Make decision: BUY / HOLD / CLOSE_POSITION
4. ✅ Log decision to Railway logs
5. ✅ Track paper positions (simulated P&L)

**No real orders placed** - this is paper trading mode.

---

## How to Monitor

### 1. Check Railway Logs

Look for these log entries:

```bash
# Hermes started
[HermesLoop] Starting Hermes intraday trading loop

# Analysis cycles
[Hermes] NIFTYBEES: HOLD (confidence=0.35) - No clear setup

# Entry signals
[Hermes] PAPER ENTRY: NIFTYBEES 100qty @ ₹100.50

# Exit signals
[Hermes] PAPER EXIT: NIFTYBEES @ ₹101.25 | P&L=₹75.00

# Daily summary
[Hermes] Today: 3 trades, P&L=₹425.50
```

### 2. Check API Status

```bash
curl https://your-app.railway.app/api/hermes/status
```

Response:
```json
{
  "enabled": true,
  "instrument": "NIFTYBEES",
  "position": null,  // or current position details
  "trades_today": 2,
  "daily_pnl": 150.75,
  "last_analysis": "2026-07-16T10:30:45+05:30"
}
```

### 3. Check Today's Trades

```bash
curl https://your-app.railway.app/api/hermes/trades/today
```

---

## What to Look For

### ✅ Good Signs

1. **Hermes is analyzing regularly**:
   ```
   [HermesLoop] Cycle: success
   ```

2. **Conservative decisions** (low confidence = HOLD):
   ```
   [Hermes] HOLD (confidence=0.45) - Waiting for clearer setup
   ```

3. **High confidence when it acts**:
   ```
   [Hermes] BUY (confidence=0.82) - Strong breakout confirmed
   ```

4. **Reasonable P&L** in paper mode:
   ```
   [Hermes] Daily P&L: ₹320.50 (3 trades)
   ```

### ⚠️ Warning Signs

1. **No activity during market hours**:
   - Check if enabled: `/api/hermes/status`
   - Check Railway logs for errors

2. **Always HOLD (never trades)**:
   - Normal if market conditions are choppy
   - Expected without GROQ_API_KEY (uses demo logic)

3. **Errors in logs**:
   ```
   [HermesLoop] Error: ...
   ```
   Report these for investigation

---

## Next Steps to Enable LIVE Trading

### Current State: Paper Mode ✓
- Uses demo market data
- No real AI reasoning (demo logic only)
- No real orders placed

### To Enable Real AI + Live Orders:

**Step 1: Add Groq API Key**
```bash
# Get FREE key at https://console.groq.com
# Add to Railway environment variables:
GROQ_API_KEY=gsk_xxxxxxxxxxxxx
```

**Step 2: Verify Angel One Connection**
- Ensure Angel One API credentials are set
- Check logs for: `Angel One connected successfully`

**Step 3: Deploy**
- Railway auto-deploys on environment variable change
- Hermes will now use:
  - ✅ Real AI analysis (Groq LLM)
  - ✅ Real market data (Angel One)
  - ✅ Real order placement (MIS intraday)

---

## Testing Timeline

### Week 1: Paper Mode (Current)
- Monitor Hermes decisions in logs
- Check if AI is being conservative (good!)
- Verify no crashes or errors

### Week 2: Add GROQ_API_KEY
- See real AI reasoning in logs
- Still paper mode (no real orders)
- Validate decision quality improves

### Week 3+: Go Live (Optional)
- If confident in AI decisions
- Start with small capital (₹5,000/trade)
- Monitor first day closely

---

## Manual Controls

### Disable Hermes Anytime

**Option 1: API**
```bash
curl -X POST https://your-app.railway.app/api/hermes/config \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}'
```

**Option 2: Config File**
Edit `config/config.yaml`:
```yaml
hermes:
  enabled: false
```
Then redeploy.

### Force Exit Position

```bash
curl -X POST https://your-app.railway.app/api/hermes/force-exit
```

### Run Manual Analysis

```bash
curl -X POST https://your-app.railway.app/api/hermes/run-analysis
```

---

## Expected Behavior

### Normal Day

```
09:15 - Hermes starts analyzing
09:20 - Several HOLD decisions (waiting for setup)
10:05 - BUY signal (confidence 0.78) → Paper entry
10:45 - Position monitoring
11:20 - Target hit → Paper exit (P&L +₹85)
12:00 - More HOLD decisions
14:30 - Another BUY signal
15:10 - Force exit all positions (market close)
15:15 - Hermes pauses until next trading day
```

### Choppy/Sideways Day

```
09:15 - Hermes starts
09:20 - 15:10 - All HOLD decisions (no clear setups)
15:10 - No trades executed
15:15 - Hermes pauses

Daily P&L: ₹0 (0 trades)
```
**This is correct** - Hermes is conservative!

---

## FAQ

### Q: Why isn't Hermes trading?
**A**: Without GROQ_API_KEY, it uses simple demo logic. Also, Hermes is intentionally conservative - it only trades when confidence ≥ 70%.

### Q: How often should it trade?
**A**: Varies by market. Expected: 1-4 trades/day. Some days: 0 trades (choppy market).

### Q: Will it lose money?
**A**: Paper mode = no real money. Live mode has stop loss (0.6%) per trade.

### Q: Can I test with real AI without real money?
**A**: Yes! Add GROQ_API_KEY but keep it in paper mode. You'll see real AI decisions without executing real orders.

---

## Summary

**Current Status**: ✅ Hermes ENABLED in paper mode

**What's Happening**: 
- Analyzing NIFTYBEES every 30 seconds
- Logging all decisions to Railway
- Tracking simulated trades

**What You Should Do**:
1. Monitor Railway logs for Hermes activity
2. Check `/api/hermes/status` endpoint
3. Let it run for 1 week in paper mode
4. Add GROQ_API_KEY when confident
5. Go live when ready

**No action required** - Hermes is running automatically! 🤖
