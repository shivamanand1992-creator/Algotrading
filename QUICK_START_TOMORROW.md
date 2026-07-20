# 🏛️ Athena - Quick Start for Tomorrow Morning

## ⏰ Pre-Market (Before 9:15 AM)

### 1️⃣ Run Validation Test (5 minutes)
```bash
cd /home/user/Algotrading
python3 backend/test_athena.py
```

**Look for:** All ✅ green checkmarks

**If any test fails:** Don't proceed with live mode

---

### 2️⃣ Open Dashboard
```
https://your-railway-app.up.railway.app
```

Click: 🏛️ icon in sidebar

**Should see:**
- Status: INACTIVE
- 0 Open Positions
- Clean interface

---

## 🎯 9:15 AM - Market Open

### Paper Trading First (Recommended)

1. **Click:** "Enable Paper Trading"
2. **Wait:** Status shows `ACTIVE · PAPER`
3. **Click:** "Run Analysis"
4. **Wait:** 10-20 seconds for AI response

**If ENTER signal:**
- Position appears in table
- Telegram notification arrives
- Check Railway logs: "[Athena] Position saved: X"

**If HOLD/NONE:**
- Normal - AI is selective
- Try again in 30 minutes

---

### Going Live (After Paper Works)

⚠️ **ONLY if paper mode worked perfectly**

1. **Click:** "Disable"
2. **Verify:** Angel One terminal ready
3. **Check:** Sufficient margin (₹50K+ available)
4. **Click:** "Enable Live Trading"
5. **Click:** "Run Analysis"

**When ENTER in LIVE mode:**
- ⚡ Orders sent to Angel One immediately
- Check Angel One terminal for fills
- Position appears in dashboard
- Telegram alert with details

---

## 📊 Monitoring (Throughout Day)

### Every 30 Minutes
- Refresh dashboard
- Check Weekly P&L
- Look for position updates

### What to Expect
- **Most analyses:** HOLD or NONE (AI is selective)
- **1-3 trades per week** (not daily)
- **High confidence only:** 80%+ confidence, 75%+ PoP

### Auto-Exit Triggers
- ✅ **Target Hit:** 50% profit → Auto close
- 🛑 **Stop Loss:** 100% loss → Auto close  
- 📅 **Expiry:** Thursday 3:30 PM → Auto close

---

## 🚨 Emergency Stop

**To stop immediately:**

Dashboard: Click "Disable" button

**Or via command:**
```bash
curl -X POST https://your-app.railway.app/api/athena/disable
```

**Then:** Manually close positions in Angel One if needed

---

## ✅ Success Indicators

### Green Flags
- AI analysis completes without errors
- Positions save to database
- Telegram notifications arrive
- Angel One orders fill as expected
- Dashboard updates in real-time

### Red Flags
- Analysis returns errors
- Orders fail to place
- No Telegram notifications
- Dashboard shows wrong data
- → **DISABLE and debug**

---

## 📞 Quick Help

### Check Logs
```bash
railway logs | grep Athena
```

### Database Check
```bash
sqlite3 backend/data/athena.db "SELECT * FROM options_positions;"
```

### API Status
```bash
curl https://your-app.railway.app/api/athena/status
```

---

## 💡 Remember

1. **Start Paper** - Validate before live
2. **Be Patient** - Quality > Quantity
3. **Trust AI** - 80% confidence filter works
4. **Monitor** - Check every 30 mins
5. **Stop if Unsure** - Better safe than sorry

---

## 🎯 Day 1 Goal

**Not:**
- Make huge profits
- Execute many trades
- Test all features

**But:**
- System runs smoothly
- No crashes or errors
- 1 successful trade (even small)
- Build confidence in automation

---

**Good luck! 🏛️**

**Full guide:** See `ATHENA_SETUP_GUIDE.md` for details
