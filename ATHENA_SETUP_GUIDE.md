# 🏛️ Athena Options Trading System - Live Testing Guide

## Pre-Market Checklist (Before 9:15 AM)

### 1. Run System Validation
```bash
cd /home/user/Algotrading
python3 backend/test_athena.py
```

**Expected Output:**
- ✅ Angel One connected successfully
- ✅ Bank Nifty Spot: ₹XX,XXX
- ✅ India VIX: XX.XX
- ✅ Options chain accessible
- ✅ AI agent working
- ✅ Athena service ready
- ✅ Telegram notification sent

**If any test fails:** Fix the issue before proceeding.

---

### 2. Verify Railway Deployment

**Check deployment status:**
```bash
git log --oneline -1
git status
```

**Ensure latest commit is pushed:**
- Commit hash should match Railway dashboard
- No uncommitted changes

**Open Railway logs:**
- Go to https://railway.app
- Check backend logs for errors
- Verify "Athena service initialized" message

---

### 3. Access Dashboard

**Open browser:**
```
https://your-app-url.up.railway.app
```

**Navigate to:**
- Click 🏛️ icon in sidebar (Athena Options)
- Verify dashboard loads without errors

**Check status card:**
- Status: INACTIVE (initially)
- Mode: paper
- Open Positions: 0
- Trades This Week: 0

---

## Live Testing Workflow

### Phase 1: Paper Trading Validation (9:15 AM - 10:00 AM)

**Step 1: Enable Paper Mode**
1. Click "Enable Paper Trading" button
2. Verify status changes to: `ACTIVE · PAPER`
3. Check Railway logs for confirmation

**Step 2: Run Manual Analysis**
1. Click "Run Analysis" button
2. Wait for AI response (~10-20 seconds)
3. Review analysis result:
   - Action: ENTER / HOLD / WAIT
   - Strategy: Bull Put Spread / Bear Call Spread / Iron Condor / NONE
   - Confidence: XX%
   - PoP (Probability of Profit): XX%
   - Reasoning: Why this decision was made

**Step 3: Verify Position Entry (if ENTER)**
If AI recommends ENTER:
1. Check "Positions" table appears
2. Verify position details:
   - Strategy name
   - Entry time
   - Strikes (Sell/Buy)
   - Premium received
   - Max loss
   - Confidence & PoP
   - Status: OPEN
   - Mode badge: paper

**Step 4: Check Telegram Notification**
- Should receive entry notification on Telegram
- Contains: Strategy, strikes, premium, max loss, confidence, reasoning

**Step 5: Database Verification**
```bash
# Check database has position
sqlite3 backend/data/athena.db "SELECT * FROM options_positions;"
```

---

### Phase 2: Live Market Testing (10:00 AM - 2:30 PM)

⚠️ **ONLY proceed if Paper mode works perfectly**

**Step 1: Disable Paper Mode**
1. Click "Disable" button
2. Verify status: INACTIVE

**Step 2: Review Configuration**
```
Min Confidence: 80%
Min PoP: 75%
Max Positions: 3
Capital per Trade: ₹50,000
Profit Target: 50% of premium
Stop Loss: 100% of premium
```

**Adjust if needed via API:**
```bash
curl -X PATCH https://your-app.railway.app/api/athena/config \
  -H "Content-Type: application/json" \
  -d '{"min_confidence": 0.85, "min_pop": 0.80}'
```

**Step 3: Enable Live Mode**
1. Click "Enable Live Trading" button
2. **CONFIRM** you understand this places real orders
3. Verify status: `ACTIVE · LIVE`
4. Check Angel One broker terminal is ready

**Step 4: Monitor for Trade Signals**
- Click "Run Analysis" periodically (or wait for auto-scan if enabled)
- AI will only recommend trades meeting strict criteria:
  - Confidence ≥ 80%
  - Probability of Profit ≥ 75%
  - VIX ≥ 15 (good premium environment)
  - Clear trend or range-bound setup

**Step 5: Real Order Execution**
When AI signals ENTER in LIVE mode:

1. **Check Angel One terminal IMMEDIATELY:**
   - Verify orders placed (NFO contracts)
   - Confirm fills at expected prices
   - Check margin blocked

2. **Monitor Dashboard:**
   - Position appears in table
   - Entry price matches actual fill
   - Premium & max loss calculated correctly

3. **Verify Telegram Alert:**
   - Entry notification received
   - Details match Angel One orders

**Step 6: Position Monitoring**
- Click "Monitor Positions" button regularly
- Check P&L updates
- Watch for auto-exit triggers:
  - ✅ Target Hit: 50% profit (exit automatically)
  - 🛑 Stop Loss: 100% loss (exit automatically)
  - 📅 Expiry: Expire worthless (close automatically)

**Step 7: Manual Exit (if needed)**
If you need to close position manually:
```bash
# Via Angel One terminal directly
# Or future API endpoint (not yet implemented)
```

---

## Safety Limits

### Hard Limits (Enforced by Code)
- **Max 3 positions per week** - Cannot exceed
- **Min 80% confidence** - Below this = HOLD
- **Min 75% PoP** - Below this = HOLD
- **Capital per trade: ₹50,000** - Fixed lot size

### Market Conditions Filter
AI will return `NONE` if:
- VIX < 14 (premium too low, not worth risk)
- Trend unclear or choppy
- Days to expiry < 3 (gamma risk)
- Major event risk detected

### Emergency Stop
**To immediately stop all trading:**
1. Click "Disable" button in dashboard
2. Or via API:
```bash
curl -X POST https://your-app.railway.app/api/athena/disable
```
3. Manually close positions in Angel One if needed

---

## Monitoring & Alerts

### What to Watch

**Dashboard (refresh every 5-10 minutes):**
- Open positions count
- Weekly P&L
- Latest analysis result

**Telegram Notifications:**
- 🏛️ ATHENA ENTRY - New position opened
- 🏛️ ATHENA EXIT - Position closed (target/stop/expiry)

**Railway Logs:**
```
[Athena] 🤖 Calling Claude AI for options analysis...
[Athena] 📊 Decision: BULL_PUT_SPREAD (confidence=85%, PoP=78%)
[Athena] 🚀 Executing BULL_PUT_SPREAD: Sell 51800, Buy 51500
[Athena] Order placed successfully. order_id=XXXXX
```

**Angel One Terminal:**
- Order book (verify fills)
- Position book (check margins)
- P&L tracking

---

## Common Issues & Fixes

### Issue 1: "No usage data yet" on Claude API Usage
- **Expected** - No API calls made yet
- Will populate after first AI analysis

### Issue 2: Analysis returns "NONE" repeatedly
- **Normal** - AI is being selective
- Only 1-3 high-quality trades per week expected
- VIX too low or market conditions not ideal

### Issue 3: Order placement fails
- Check Angel One connection in logs
- Verify sufficient margin in account
- Check options contracts exist (expiry/strike valid)

### Issue 4: Position not appearing in dashboard
- Refresh page
- Check browser console for errors
- Verify database has entry: `sqlite3 backend/data/athena.db "SELECT * FROM options_positions;"`

### Issue 5: Telegram not sending
- Check TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in Railway variables
- Test with: `python3 backend/test_athena.py`

---

## Expected Trading Behavior

### Weekly Trading Pattern
- **1-3 trades per week** (not every day)
- **High selectivity** - Most days will return HOLD/NONE
- **Best times:**
  - Monday/Tuesday: Fresh week, clear trends
  - Wednesday: Mid-week consolidation (Iron Condors)
  - Avoid Friday (expiry day gamma risk)

### Typical Trade Flow
1. **9:15-10:30 AM:** AI scans for setups
2. **Entry:** If high-conviction signal (80%+ confidence)
3. **Monitor:** Check P&L every 30-60 minutes
4. **Exit:** Usually 1-3 days later
   - Target: 50% profit (~₹7,500 per ₹50K position)
   - Stop: 100% loss (~₹15,000 max)

### Success Metrics (Week 1)
- **Target:** 1-2 trades placed
- **Win Rate:** Aim for 75%+ (at least 1 winner)
- **P&L:** Positive or breakeven
- **No errors:** All systems working smoothly

---

## Post-Market Checklist (After 3:30 PM)

### Daily Review
1. **Check Telegram EOD report** - Includes Athena positions
2. **Review Railway logs** - Any errors?
3. **Dashboard sanity check:**
   - Open positions count accurate?
   - Weekly P&L matches expectations?
4. **Angel One reconciliation:**
   - Positions match dashboard
   - Margin utilization reasonable

### Database Backup
```bash
# Optional - backup positions database
cp backend/data/athena.db backend/data/athena_backup_$(date +%Y%m%d).db
```

---

## Week 1 Goals

### ✅ Success Criteria
- [ ] System runs without crashes
- [ ] AI analysis completes successfully
- [ ] Paper trades recorded correctly
- [ ] Live orders execute as expected
- [ ] Telegram notifications working
- [ ] At least 1 winning trade
- [ ] No manual intervention needed

### 📊 Metrics to Track
- Total trades: ___
- Winners: ___
- Losers: ___
- Win rate: ____%
- Total P&L: ₹_____
- Avg confidence of trades: ____%
- Avg PoP of trades: ____%

---

## Support & Debugging

### Railway Logs
```bash
# View live logs
railway logs

# Filter Athena only
railway logs | grep Athena
```

### API Endpoints for Debugging
```bash
# Check status
curl https://your-app.railway.app/api/athena/status

# Get all positions
curl https://your-app.railway.app/api/athena/positions

# Run manual analysis
curl -X POST https://your-app.railway.app/api/athena/analyze
```

### Database Queries
```sql
-- View all positions
SELECT * FROM options_positions ORDER BY entry_date DESC;

-- This week's trades
SELECT * FROM options_positions 
WHERE entry_date >= date('now', '-7 days')
ORDER BY entry_date DESC;

-- Open positions only
SELECT * FROM options_positions WHERE status = 'OPEN';

-- P&L summary
SELECT 
  status,
  COUNT(*) as count,
  SUM(realized_pnl) as total_pnl,
  AVG(confidence) as avg_confidence
FROM options_positions
GROUP BY status;
```

---

## Quick Reference

### Dashboard Actions
- **Enable Paper Trading** - Start testing without real orders
- **Enable Live Trading** - ⚠️ Places real orders on Angel One
- **Disable** - Stop all trading immediately
- **Run Analysis** - Trigger manual AI scan
- **Send to Telegram** - Force Telegram report

### Configuration Defaults
```python
'symbol': 'BANKNIFTY',
'max_positions': 3,
'capital_per_trade': 50000,  # ₹50K
'profit_target_pct': 50,     # Exit at 50% profit
'stop_loss_pct': 100,        # Exit at 100% loss
'min_confidence': 0.80,      # 80% min
'min_pop': 0.75,             # 75% min PoP
```

### Lot Sizes
- **BANKNIFTY:** 15 qty per lot
- **NIFTY:** 25 qty per lot

### Trade Example
```
Strategy: BULL PUT SPREAD
Sell: 52000 PE @ ₹150
Buy: 51700 PE @ ₹50
Premium: ₹100 × 15 = ₹1,500
Max Loss: (300 point spread - 100 premium) × 15 = ₹3,000
Target: 50% profit = ₹750
Stop: 100% loss = ₹1,500
Risk/Reward: 1:2 (good)
```

---

## Final Pre-Launch Checklist

### Infrastructure
- [ ] Railway deployment is green
- [ ] Database initialized (athena.db exists)
- [ ] Angel One API connected
- [ ] Telegram bot configured
- [ ] Frontend loads without errors

### Testing
- [ ] Ran `test_athena.py` - all tests passed
- [ ] Paper mode tested successfully
- [ ] Manual analysis works
- [ ] Position created in database
- [ ] Telegram notification received

### Safety
- [ ] Reviewed configuration limits
- [ ] Understand how to disable immediately
- [ ] Know where to check Angel One orders
- [ ] Have backup plan for manual intervention

### Go/No-Go Decision
**Proceed with LIVE mode ONLY if:**
- ✅ All infrastructure tests passed
- ✅ Paper mode works flawlessly
- ✅ You understand the risk limits
- ✅ Sufficient margin in Angel One account
- ✅ Monitoring plan in place

---

**Good luck with tomorrow's live testing! 🏛️**

**Remember:**
- Start with Paper mode
- Be patient - high-quality setups are rare
- Trust the AI filters (80% confidence, 75% PoP)
- Monitor closely during first week
- Stop immediately if anything unexpected happens

Let Athena do what it was designed for: **Find high-probability options setups with AI precision and execute them with disciplined risk management.**
