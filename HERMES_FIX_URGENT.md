# 🚨 HERMES URGENT FIX REQUIRED

## Current Status: ❌ BROKEN - NOT TRADING

**Date**: 2026-07-17 09:15 AM IST  
**Issue**: Hermes running but completely non-functional  
**Impact**: Zero trades possible until fixed

---

## 🔍 ROOT CAUSES IDENTIFIED

### Problem 1: Missing GROQ_API_KEY ⚠️⚠️⚠️
**Symptom:**
```
[Hermes] Analysis failed: Client error '400 Bad Request' 
for url 'https://api.groq.com/openai/v1/chat/completions'
```

**Root Cause:**
- Hermes uses Groq LLM for AI trading decisions
- `GROQ_API_KEY` environment variable is **NOT SET** in Railway
- Every LLM call returns 400 Bad Request
- Without LLM analysis, Hermes cannot make ANY trading decisions

**Location:** `backend/services/hermes_agent.py` line 27
```python
self.api_key = api_key or os.getenv("GROQ_API_KEY")
```

---

### Problem 2: Angel One API Rate Limiting ⚠️
**Symptom:**
```
[Hermes] Failed to fetch live data: 
'Access denied because of exceeding access rate'
[Hermes] Using demo market data (broker not connected)
```

**Root Cause:**
- Hermes calls Angel One API every 30 seconds
- **PLUS** other services also calling:
  - SessionWatchdog: every 5 min
  - ETF Holdings: every 10 min
  - Balance check: every 30 min
  - Historical data: on every Hermes cycle
- **Total API calls**: ~200-300 per hour
- Angel One limit: ~100 requests/hour for free tier

**Result:**
- Hermes falls back to FAKE demo data (₹100 price)
- Cannot get real NIFTYBEES prices
- Cannot execute real trades

---

## 🔧 FIXES REQUIRED (IN ORDER)

### Fix 1: Add GROQ_API_KEY to Railway ⚡ CRITICAL
**Action:** Add environment variable in Railway dashboard

1. Go to Railway dashboard
2. Select your Algotrading project
3. Go to Variables tab
4. Add new variable:
   ```
   GROQ_API_KEY = gsk_YOUR_ACTUAL_KEY_HERE
   ```

**Get Groq API Key:**
- Sign up at https://console.groq.com/
- Free tier: 14,400 requests/day (more than enough)
- Copy API key starting with `gsk_...`

**After adding:**
- Railway will auto-redeploy
- Hermes will start working immediately
- Check logs for: `[Hermes] NIFTYBEES: BUY/HOLD (confidence=0.XX)`

---

### Fix 2: Reduce Angel One API Calls ⚡ HIGH PRIORITY

**Option A: Increase Hermes Interval (Quick Fix)**

Edit `config/config.yaml`:
```yaml
hermes:
  check_interval_seconds: 60  # Change from 30 to 60 seconds
```

**Impact:**
- Cuts Hermes API calls by 50%
- Still analyzes market every minute (acceptable)
- Less chance of rate limiting

**Option B: Cache Historical Data (Better Fix)**

Modify `backend/services/hermes_intraday_service.py`:

Add caching to `_fetch_market_data()`:
```python
# Add at class level
self._market_data_cache = None
self._cache_timestamp = None
self._cache_ttl = 30  # 30 seconds

# In _fetch_market_data():
now = datetime.now(_IST)
if self._market_data_cache and self._cache_timestamp:
    if (now - self._cache_timestamp).total_seconds() < self._cache_ttl:
        return self._market_data_cache

# ... fetch data ...
self._market_data_cache = market_data
self._cache_timestamp = now
return market_data
```

**Impact:**
- Reuses data for 30 seconds
- Reduces API calls by ~50%
- No degradation in trading quality

---

### Fix 3: Fallback to Yahoo Finance (Alternative)

If Angel One keeps rate limiting, use Yahoo Finance for price data:

**Modify `_fetch_market_data()` to try Yahoo first:**
```python
try:
    # Try Yahoo Finance first (no rate limits)
    import yfinance as yf
    ticker = yf.Ticker("NIFTYBEES.NS")
    hist = ticker.history(period="1d", interval="5m")
    if not hist.empty:
        current_price = hist['Close'].iloc[-1]
        # Use this price instead
except:
    # Fall back to Angel One
    pass
```

---

## 📊 VERIFICATION STEPS

### After Fix 1 (Groq API Key):
1. **Check Railway logs:**
   ```
   ✅ Look for: [Hermes] NIFTYBEES: BUY (confidence=0.75)
   ❌ Should NOT see: Client error '400 Bad Request'
   ```

2. **Check Hermes dashboard:**
   - Go to UI → HERMES AI
   - Should show live analysis
   - Confidence scores visible

### After Fix 2 (Rate Limiting):
1. **Check Railway logs:**
   ```
   ✅ Look for: Historical data: NSE/10576 interval=FIVE_MINUTE
   ❌ Should NOT see: Access denied because of exceeding access rate
   ❌ Should NOT see: Using demo market data
   ```

2. **Verify real data:**
   - Price should be ~₹245-275 (real NIFTYBEES range)
   - NOT ₹100.00 (demo data)

---

## 🎯 PRIORITY ORDER

**RIGHT NOW (Next 5 minutes):**
1. Add `GROQ_API_KEY` to Railway
2. Wait for auto-deploy (~2 min)
3. Check logs for successful LLM calls

**TODAY (Next 1 hour):**
4. Change `check_interval_seconds` to 60
5. Commit and push
6. Monitor for rate limiting

**THIS WEEK:**
7. Implement data caching (Option B)
8. Add Yahoo Finance fallback
9. Test with real trades (₹5,000 capital)

---

## 📝 CURRENT CONFIGURATION

**What's Working:**
- ✅ Angel One authentication
- ✅ Session refresh
- ✅ Balance tracking (₹38,158)
- ✅ Hermes loop running
- ✅ All 6 trading enhancements deployed

**What's Broken:**
- ❌ Groq LLM calls (no API key)
- ❌ Real market data (rate limited)
- ❌ Trading decisions (can't analyze without LLM)
- ❌ Trade execution (no valid signals)

---

## 🔑 GROQ API KEY SETUP

**Step by step:**

1. **Sign up for Groq:**
   - Visit: https://console.groq.com/
   - Sign up with email
   - Verify email

2. **Create API Key:**
   - Go to API Keys section
   - Click "Create API Key"
   - Name it: "Hermes Trading Bot"
   - Copy the key (starts with `gsk_...`)

3. **Add to Railway:**
   - Railway Dashboard → Your Project
   - Variables tab
   - Add Variable:
     ```
     Name: GROQ_API_KEY
     Value: gsk_YOUR_KEY_HERE
     ```
   - Click "Add"
   - Railway auto-deploys

4. **Verify:**
   - Wait 2 minutes for deployment
   - Check logs for:
     ```
     [Hermes] NIFTYBEES: BUY (confidence=0.75) - RSI oversold, volume confirmation
     ```

---

## 🚀 EXPECTED BEHAVIOR AFTER FIX

**Every 30-60 seconds during market hours (9:15 AM - 3:15 PM):**

```
✅ [Hermes] Fetching market data...
✅ Historical data: NSE/10576 (real prices)
✅ [Hermes] Analyzing market conditions...
✅ [Hermes] NIFTYBEES: HOLD (confidence=0.65) - No clear setup, waiting
```

**When a valid setup appears:**

```
✅ [Hermes] NIFTYBEES: BUY (confidence=0.78) - Breakout above resistance
✅ [Hermes] Entry order placed: ORD123456
✅ [Hermes] SL order placed @ ₹245.50: SL123456
🟢 Telegram: HERMES ENTRY | NIFTYBEES 40qty @ ₹247.00
```

---

## 📞 SUPPORT

**If still not working after Fix 1:**
- Share Railway logs (last 100 lines)
- Share Groq API key first 10 characters: `gsk_XXXXXX...`
- Check Groq dashboard for usage/errors

**Contact:**
- Railway logs: `railway logs --tail 100`
- This file: `/home/user/Algotrading/HERMES_FIX_URGENT.md`
