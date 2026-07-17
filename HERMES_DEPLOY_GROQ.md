# 🚀 HERMES DEPLOYMENT GUIDE - GROQ (FREE)

**Date**: 2026-07-17  
**Status**: ✅ CODE READY - Using Groq (FREE tier)

---

## 💰 WHY GROQ?

**Cost Comparison:**
- **Groq**: FREE (14,400 requests/day)
- **Anthropic**: ~$13/month

**Hermes Usage:**
- ~360 API calls/day during market hours (9:15 AM - 3:15 PM)
- Well within Groq's free tier
- **Annual Savings: $156/year** ✅

---

## ✅ WHAT'S FIXED

All code changes are committed and ready:

1. ✅ **Switch to Groq** - Using official AsyncGroq SDK
2. ✅ **60s check interval** - Reduced from 30s (prevents rate limiting)
3. ✅ **Model**: mixtral-8x7b-32768 (fast, good for structured JSON)
4. ✅ **Error handling** - Proper exception handling and logging

---

## 🔑 STEP 1: GET GROQ API KEY

1. **Sign up at Groq Console:**
   - Visit: https://console.groq.com/
   - Sign up with your email (free)
   - Verify your email

2. **Create API Key:**
   - Go to "API Keys" section
   - Click "Create API Key"
   - Name it: "Hermes Trading Bot"
   - Copy the key (starts with `gsk_...`)
   - **Important**: Copy the FULL key immediately - you can't see it again!

3. **Verify Free Tier Limits:**
   - 14,400 requests/day (RPD)
   - 30 requests/minute (RPM)
   - More than enough for Hermes (360 requests/day)

---

## 🔧 STEP 2: ADD GROQ_API_KEY TO RAILWAY

1. **Go to Railway Dashboard:**
   - Visit: https://railway.app/dashboard
   - Select your Algotrading project

2. **Add Environment Variable:**
   - Click on "Variables" tab
   - Click "+ New Variable"
   - Add:
     ```
     Name: GROQ_API_KEY
     Value: gsk_YOUR_ACTUAL_KEY_HERE
     ```
   - Click "Add"

3. **Railway will auto-redeploy:**
   - Wait ~2 minutes for deployment to complete
   - Check logs for successful initialization

---

## 🚀 STEP 3: DEPLOY CODE CHANGES

**Option A: From your local machine (Recommended)**
```bash
cd ~/Algotrading
git fetch origin claude/tender-mendel-R2h2U
git checkout claude/tender-mendel-R2h2U
git pull origin claude/tender-mendel-R2h2U

# Verify commits
git log --oneline -5
# Should see:
# a5eec54 Switch Hermes back to Groq for cost savings
# 7ec19b5 Add Hermes troubleshooting documentation
# d114290 Fix Hermes by using official Anthropic SDK instead of httpx
# 7fceff7 Add detailed error logging to Hermes Anthropic API calls
# 49333a9 Fix Hermes rate limiting - reduce API call frequency

# Push to Railway
git push origin claude/tender-mendel-R2h2U
```

**Option B: Direct Railway CLI**
```bash
railway up
```

**Option C: Railway GitHub integration**
- Push branch to GitHub
- Railway auto-deploys from GitHub

---

## ✅ STEP 4: VERIFY DEPLOYMENT

**Check Railway Logs for:**

### During Startup:
```
✅ [Hermes] Hermes Agent initialized
✅ [Hermes] Starting intraday trading loop...
```

### During Market Hours (9:15 AM - 3:15 PM IST):
```
✅ [Hermes] Fetching market data...
✅ [Hermes] Analyzing market conditions...
✅ [Hermes] NIFTYBEES: HOLD (confidence=0.65) - No clear setup, RSI neutral
```

### When Valid Setup Appears:
```
✅ [Hermes] NIFTYBEES: BUY (confidence=0.78) - Breakout above ₹247.50
✅ [Hermes] Entry order placed: ORD123456
✅ [Hermes] SL order placed @ ₹245.50: SL123456
🟢 Telegram: HERMES ENTRY | NIFTYBEES 40qty @ ₹247.00
```

### ❌ Should NOT See:
```
❌ [Hermes] No GROQ_API_KEY found - agent will not work
❌ [Hermes] Groq API error: ...
❌ Client error '404 Not Found'
```

---

## 📊 EXPECTED BEHAVIOR

**Timeline:**

| Time | Action |
|------|--------|
| Before 9:15 AM | Hermes waiting (market closed) |
| 9:15 AM | Market opens, Hermes starts analyzing |
| 9:15 AM - 3:15 PM | Analysis every 60 seconds (~360 calls/day) |
| 3:15 PM | No new trades (cutoff time) |
| 3:20 PM | Force exit all positions |
| After 3:30 PM | Hermes stops (market closed) |

**API Usage:**
- ~360 Groq API calls per trading day
- ~7,200 calls per month (20 trading days)
- **Well within free tier** (14,400/day limit)

---

## 🔍 TROUBLESHOOTING

### Error: "No GROQ_API_KEY found"
**Fix:** Add `GROQ_API_KEY` environment variable in Railway

### Error: "Rate limit exceeded"
**Cause:** Unlikely with 60s interval (~360/day vs 14,400/day limit)
**Fix:** If happens, increase `check_interval_seconds` to 90 in config.yaml

### Error: "Invalid API key"
**Fix:** 
1. Verify key starts with `gsk_`
2. No extra spaces or newlines
3. Generate a new key at https://console.groq.com/

### Hermes not analyzing during market hours
**Check:**
1. Market is open (9:15 AM - 3:30 PM IST Mon-Fri)
2. GROQ_API_KEY is set in Railway
3. Angel One session is active (check watchdog logs)
4. No rate limiting from Angel One API

---

## 💡 OPTIMIZATION TIPS

### If Angel One Rate Limiting Continues:
1. Increase `check_interval_seconds` to 90-120 in config.yaml
2. Cache market data for 30-60 seconds
3. Use Yahoo Finance as fallback for price data

### Monitor Groq Usage:
- Check https://console.groq.com/usage
- Free tier resets daily
- Upgrade to paid if you add more instruments

### Future Enhancements:
- Add multiple instruments (use budget accordingly)
- Implement data caching layer
- Use Groq for other AI features (sentiment analysis, news summaries)

---

## 📈 COST SAVINGS

**Annual Cost Comparison:**

| Provider | Monthly | Annual | Free Tier |
|----------|---------|--------|-----------|
| Groq | **$0** | **$0** | 14,400 req/day ✅ |
| Anthropic Claude Haiku | $13 | $156 | None |
| OpenAI GPT-3.5 | $8 | $96 | $5 credit |
| OpenAI GPT-4 | $45 | $540 | $5 credit |

**Hermes with Groq = FREE FOREVER** (within free tier limits) 🎉

---

## 📋 DEPLOYMENT CHECKLIST

- [ ] Get Groq API key from https://console.groq.com/
- [ ] Add `GROQ_API_KEY` to Railway environment variables
- [ ] Pull latest code from `claude/tender-mendel-R2h2U` branch
- [ ] Push to Railway (or let Railway auto-deploy)
- [ ] Wait 2 minutes for deployment
- [ ] Check Railway logs for successful initialization
- [ ] Verify Hermes analyzing during market hours
- [ ] Monitor first few trading decisions
- [ ] Confirm trades executing (if valid setups appear)
- [ ] Check Telegram notifications working

---

## 🎯 SUCCESS CRITERIA

✅ **Deployment Successful When:**
1. Railway logs show: `[Hermes] Hermes Agent initialized`
2. During market hours: `[Hermes] NIFTYBEES: HOLD/BUY`
3. Confidence scores visible (0.XX)
4. Real prices showing (₹245-275 range)
5. No API errors in logs
6. Groq usage dashboard shows requests

---

## 📞 SUPPORT

**If issues persist:**
1. Check Railway logs (last 100 lines)
2. Verify GROQ_API_KEY in Railway variables
3. Check Groq console usage dashboard
4. Test API key manually with curl:
   ```bash
   curl https://api.groq.com/openai/v1/chat/completions \
     -H "Authorization: Bearer $GROQ_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{"model":"mixtral-8x7b-32768","messages":[{"role":"user","content":"test"}]}'
   ```

**Key Files:**
- `/home/user/Algotrading/backend/services/hermes_agent.py` (main code)
- `/home/user/Algotrading/config/config.yaml` (60s interval)
- `/home/user/Algotrading/requirements.txt` (groq>=0.11.0)

---

**Status**: ✅ Ready to deploy  
**Cost**: FREE (Groq free tier)  
**Next Step**: Add GROQ_API_KEY to Railway and deploy!
