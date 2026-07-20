# Trading Strategies & AI Models Reference

**Last Updated:** 2026-07-20  
**System:** JARVIS Algotrading Platform

---

## 📊 Overview

| Component | Strategy | AI Model | Target | Status |
|-----------|----------|----------|--------|--------|
| **Hermes** | Intraday Breakout | Claude Opus 4.8 | 52%+ win rate | ✅ Live |
| **Athena** | Weekly Options | Claude Opus 4.8 | 80% success | ✅ Live Ready |
| **Equity Swing** | Conviction-Based | Claude Haiku 4.5 | 2-4 week holds | ✅ Live |
| **Sector Rotation** | Regime-Based | Vibe-Trading AI | Monthly rebalance | ✅ Live |
| **Stock Analysis** | Conviction Scoring | Claude Haiku 4.5 | Long-term picks | ✅ Live |

---

## 🤖 Hermes - Intraday Trading

### Strategy Type
**Momentum Breakout + Trend Following**

### Instrument
- **NIFTY 50** (Index) - 5-minute timeframe
- **NIFTYBEES** (ETF) - For execution when live

### Entry Criteria
1. **Price breaks previous day high** (bullish breakout)
2. **Strong uptrend:** EMA20 > EMA50 AND price > EMA20
3. **RSI sweet spot:** 45-65 (momentum without overbought)
4. **MACD bullish:** Histogram > 0
5. **Volume confirmation:** >1.5x average (for NIFTYBEES)
6. **Time filter:** Avoid 11:00 AM - 1:30 PM (choppy lunch period)
7. **AI Confidence:** ≥0.75 (75%+)

### Exit Rules
- **Target:** 1.8x ATR (Risk:Reward = 1:1.8)
- **Stop Loss:** 1.5x ATR below entry
- **Time Exit:** 3:15 PM (EOD square-off)
- **Max 3 trades per day**

### AI Model
**Claude Opus 4.8**
- Analyzes: Price action, indicators, volume, market structure
- Output: BUY / WAIT / HOLD + confidence score
- Thinking: Adaptive extended thinking
- Timeout: 45 seconds

### Performance Target
- **Win Rate:** 52-55% (improved from 42.2%)
- **Profit Factor:** 1.6-1.8x (improved from 1.12x)
- **Avg Holding:** 60-75 minutes
- **Capital:** ₹10,000 per trade

### Current Issues
- Original 0.70 confidence threshold → **Raised to 0.75**
- 56% stop loss rate → **Need stricter trend filter**
- Mid-confidence trades (0.70-0.75) lose money → **Now filtered out**

### Key Files
- `backend/services/hermes_agent.py` - AI analysis
- `backend/services/hermes_service.py` - Trade execution
- `backend/api/routes/hermes.py` - API endpoints
- `/tmp/.../HERMES_ACCURACY_REPORT.md` - Backtest results

---

## 🏛️ Athena - Weekly Options Trading

### Strategy Type
**High-Probability Credit Spreads & Iron Condors**

### Instruments
- **BANKNIFTY Weekly Options** (Most liquid)
- **NFO Exchange** (Derivatives)
- **Expiry:** Every Thursday

### Three Strategies

#### 1. Bull Put Spread (Bullish/Neutral)
**When:**
- Uptrend OR ranging with bullish bias
- VIX ≥ 15 (good premium)
- RSI < 70 (not overbought)
- Strong support defined
- PoP ≥ 75%

**Structure:**
- **Sell:** Put at 1σ below spot (≈1 ATR)
- **Buy:** Put at 2-3% below sell strike
- **Max Profit:** Premium received
- **Max Loss:** Spread width - premium

#### 2. Bear Call Spread (Bearish/Neutral)
**When:**
- Downtrend OR ranging with bearish bias
- VIX ≥ 15
- RSI > 30 (not oversold)
- Strong resistance defined
- PoP ≥ 75%

**Structure:**
- **Sell:** Call at 1σ above spot
- **Buy:** Call at 2-3% above sell strike
- **Max Profit:** Premium received
- **Max Loss:** Spread width - premium

#### 3. Iron Condor (Range-Bound)
**When:**
- **RANGING market** (NOT trending)
- VIX ≥ 18 (high premium)
- Clear support & resistance
- Expected range-bound for 3-5 days
- PoP ≥ 70%

**Structure:**
- **Sell Put:** Support - 100 points
- **Buy Put:** 200 points lower
- **Sell Call:** Resistance + 100 points
- **Buy Call:** 200 points higher
- **Max Profit:** Total premium
- **Max Loss:** Wider spread - premium

### Entry Filters
1. **AI Confidence:** ≥0.80 (80%+)
2. **Probability of Profit:** ≥0.75 (75%+)
3. **VIX Minimum:** ≥15 (skip if <14)
4. **Days to Expiry:** ≥3 (avoid gamma risk)
5. **Max 3 positions per week**
6. **Premium:** 30-40% of spread width

### Exit Rules
- **Target:** 50% of max profit (exit early, lock gains)
- **Stop Loss:** 100% of premium received (max risk defined)
- **Expiry:** Auto-close at 3:30 PM Thursday
- **Manual:** Can exit anytime via dashboard

### AI Model
**Claude Opus 4.8**
- Analyzes: Spot, VIX, trend, support/resistance, IV rank, PCR
- Output: Strategy + strikes + confidence + PoP + reasoning
- Thinking: Adaptive (5000 token budget)
- Temperature: 0.2 (consistent analysis)
- Timeout: 45 seconds

### Risk Management
- **Capital per Trade:** ₹50,000
- **Lot Size:** BANKNIFTY = 15 qty
- **Max Weekly Trades:** 3
- **Min Confidence:** 80%
- **Min PoP:** 75%

### Performance Target
- **Success Rate:** 80%+
- **Win/Loss Ratio:** 3:1 (3 winners, 1 loser)
- **Avg Win:** ₹750-1,500 per ₹50K position
- **Max Loss:** ₹1,500-3,000 per position

### Key Files
- `backend/services/athena_options_agent.py` - AI analysis
- `backend/services/athena_options_service.py` - Position management
- `backend/models/options_position.py` - Database model
- `data/angel_client.py` - Options execution helpers

---

## 📈 Equity Swing Trading

### Strategy Type
**Conviction-Based Position Trading**

### Instrument
**NSE Equities** (Mid-cap & Large-cap stocks)

### Selection Criteria
1. **Vibe-Trading Alpha Signals:** 461 quant factors
2. **Regime Filter:** Only trade in favorable market regime
3. **Technical Setup:**
   - Strong uptrend (EMA crossovers)
   - Volume confirmation
   - Support/Resistance levels
4. **Fundamental Strength:**
   - Earnings growth
   - Sector leadership
   - Institutional ownership

### AI Conviction Scoring
**Claude Haiku 4.5** (Fast, cost-effective)
- Analyzes: Fundamentals, technicals, news, sentiment
- Output: Conviction score (0-10), reasoning, risk factors
- Models: Haiku for efficiency (lower cost)

### Entry
- **Auto-Pilot:** Top 3 conviction stocks at 3:35 PM daily
- **Manual:** Conviction score ≥7/10
- **Capital:** Variable based on conviction

### Exit
- **Target:** 15-25% profit (2-4 week holding)
- **Stop Loss:** 7-10% below entry
- **Time:** Re-evaluate weekly
- **Trailing Stop:** Move stop to breakeven after 10% gain

### Portfolio Management
- **Max 5 positions** simultaneously
- **Vibe-Trading Portfolio Optimization:**
  - Risk-adjusted allocation
  - Correlation analysis
  - Sharpe ratio maximization

### Key Files
- `backend/services/swing_trade_service.py` - Autopilot logic
- `backend/api/routes/stocks.py` - Stock screening
- `backend/api/routes/conviction.py` - AI conviction analysis
- `backend/services/regime_detection.py` - Market regime filter

---

## 🔄 Sector Rotation Analysis

### Strategy Type
**Regime-Based Sector Allocation**

### Analysis Framework
**Vibe-Trading Regime Detection**
- Identifies: Bull, Bear, High Vol, Low Vol regimes
- Data: Multi-market indicators (equity, bond, commodity, FX)
- Output: Current regime + transition probabilities

### Sector Ranking
1. **Relative Strength:** vs NIFTY 50
2. **Momentum:** 1M, 3M, 6M performance
3. **Volume Trends:** Institutional flows
4. **Earnings Revisions:** Sector-wide upgrades/downgrades

### AI Model
**Claude Haiku 4.5**
- Analyzes: Sector performance, regime context, macro trends
- Output: Top 3 sectors to overweight, bottom 3 to avoid
- Focus: Quick, cost-effective analysis

### Rebalancing
- **Frequency:** Monthly
- **Trigger:** Major regime shift (e.g., Bull → Bear)
- **Allocation:** Top sectors get 2x weight vs bottom sectors

### ETF Execution
- **NIFTYBEES** - NIFTY 50 ETF (core holding)
- **Sector ETFs** - Overweight/underweight via sector-specific ETFs

### Key Files
- `backend/api/routes/sector_analysis.py` - Sector ranking
- `backend/services/regime_detection.py` - Market regime
- `backend/api/routes/etf_holdings.py` - ETF composition

---

## 🔍 Stock Analysis & Conviction Scoring

### Analysis Type
**Multi-Factor AI Conviction Model**

### AI Model
**Claude Haiku 4.5**
- **Speed:** ~2-3 seconds per analysis
- **Cost:** $1/1M input, $5/1M output tokens
- **Use Case:** High-volume stock screening

### Analysis Inputs
1. **Fundamentals:**
   - P/E, P/B, ROE, ROCE
   - Debt/Equity, Current Ratio
   - Revenue & profit growth (QoQ, YoY)
   - Promoter holding, pledging

2. **Technicals:**
   - Price vs 50/200 DMA
   - RSI, MACD signals
   - Volume trends
   - Support/Resistance levels

3. **Sentiment:**
   - News sentiment (positive/negative/neutral)
   - Analyst ratings & target prices
   - Institutional activity (buying/selling)

4. **Sector Context:**
   - Sector performance vs market
   - Peer comparison
   - Industry tailwinds/headwinds

### Output Format
```json
{
  "conviction_score": 8.5,  // 0-10 scale
  "rating": "STRONG_BUY",   // STRONG_BUY, BUY, HOLD, SELL, STRONG_SELL
  "reasoning": "Strong earnings growth, technical breakout...",
  "risk_factors": ["High debt", "Sector headwinds"],
  "target_price": 1250,
  "stop_loss": 950,
  "time_horizon": "3-6 months"
}
```

### Conviction Thresholds
- **9-10:** STRONG_BUY - High conviction, large position
- **7-8:** BUY - Good setup, standard position
- **5-6:** HOLD - Wait for better entry
- **3-4:** AVOID - Weak setup
- **0-2:** SELL - Strong sell signal

### Key Files
- `backend/api/routes/conviction.py` - Conviction analysis API
- `backend/services/stock_analysis.py` - Multi-factor scoring

---

## 🤖 AI Models Summary

### Model Selection by Use Case

| Model | Use Case | Speed | Cost | Reasoning |
|-------|----------|-------|------|-----------|
| **Claude Opus 4.8** | Hermes intraday | ~15s | $5 input, $25 output | Complex market analysis, high accuracy needed |
| **Claude Opus 4.8** | Athena options | ~20s | $5 input, $25 output | Options math, multi-leg strategies, extended thinking |
| **Claude Haiku 4.5** | Stock conviction | ~2-3s | $1 input, $5 output | High-volume screening, fast decisions |
| **Claude Haiku 4.5** | Sector rotation | ~3-5s | $1 input, $5 output | Monthly analysis, cost-effective |
| **Vibe-Trading AI** | Regime detection | ~1s | Included | 461 quant factors, specialized for regimes |

### Total Monthly AI Cost Estimate
**Assumptions:**
- Hermes: 50 analyses/month × ~2000 tokens = 100K tokens
- Athena: 20 analyses/month × ~3000 tokens = 60K tokens
- Stock screening: 200 stocks/month × ~1500 tokens = 300K tokens
- Sector: 4 analyses/month × ~2000 tokens = 8K tokens

**Total:** ~470K tokens/month ≈ **$5-10/month** (mostly Haiku for volume work)

### Extended Thinking Usage
- **Hermes:** Adaptive thinking (complex market patterns)
- **Athena:** Adaptive thinking with 5000 token budget (options math)
- **Conviction:** No extended thinking (fast screening)

---

## 📊 Performance Tracking

### Hermes (Intraday)
**Current (6-month backtest):**
- Win Rate: 42.2%
- Profit Factor: 1.12x
- Total P&L: ₹63,582 (1 lot NIFTY 50)

**Target (after improvements):**
- Win Rate: 52-55%
- Profit Factor: 1.6-1.8x
- Monthly P&L: ₹25,000-30,000 (1 lot)

### Athena (Options)
**Target (Week 1):**
- 1-3 trades placed
- 75%+ win rate
- Positive P&L
- No execution errors

**Target (Month 1):**
- 8-12 trades total
- 80%+ success rate
- ₹20,000-40,000 profit (across all trades)

### Equity Swing
**Current:**
- 3-5 positions active
- 2-4 week holding period
- 15-25% target per trade

---

## 🎯 Capital Allocation

| Strategy | Capital | Risk per Trade | Max Positions |
|----------|---------|----------------|---------------|
| **Hermes Intraday** | ₹10,000 | 1.5% (₹150) | 3/day |
| **Athena Options** | ₹50,000 | 3-6% (₹1,500-3,000) | 3/week |
| **Equity Swing** | Variable | 7-10% | 5 total |
| **NIFTYBEES DCA** | ₹10,000/day | None (long-term) | Unlimited |

**Total Deployed Capital:** ₹200,000-300,000
**Emergency Reserve:** ₹100,000 (always available)

---

## 🔐 Safety & Risk Controls

### Position Limits
- **Intraday:** Max 3 trades/day, ₹30,000 total exposure
- **Options:** Max 3 positions/week, ₹150,000 margin
- **Swing:** Max 5 stocks, ₹100,000-150,000 deployed
- **Overall:** 60% max capital deployment at any time

### Stop Loss Discipline
- **Hermes:** Auto 1.5x ATR stop (no exceptions)
- **Athena:** Auto 100% premium stop (max loss defined)
- **Swing:** Manual 7-10% stop (re-evaluate weekly)

### Circuit Breakers
- **Market crash (>3% down):** Auto-exit all intraday
- **High volatility (VIX >30):** Reduce position sizes 50%
- **Losing streak (3 losses):** Pause strategy, review
- **Weekly loss limit:** -₹10,000 → Stop all trading

---

## 📁 Key Files Reference

### AI Analysis Engines
- `backend/services/hermes_agent.py` - Intraday AI
- `backend/services/athena_options_agent.py` - Options AI
- `backend/services/stock_analysis.py` - Conviction scoring

### Trade Execution
- `backend/services/hermes_service.py` - Intraday execution
- `backend/services/athena_options_service.py` - Options execution
- `backend/services/swing_trade_service.py` - Swing autopilot
- `backend/services/niftybees_service.py` - ETF DCA

### Data & Broker Integration
- `data/angel_client.py` - Angel One SmartAPI
- `backend/services/market_data_service.py` - Real-time data
- `backend/services/regime_detection.py` - Vibe-Trading integration

### API Routes
- `backend/api/routes/hermes.py` - Intraday endpoints
- `backend/api/routes/athena.py` - Options endpoints
- `backend/api/routes/stocks.py` - Swing trading
- `backend/api/routes/conviction.py` - Stock analysis
- `backend/api/routes/sector_analysis.py` - Sector rotation

### Database Models
- `backend/models/options_position.py` - Options positions
- `backend/services/swing_trade_service.py` - Swing positions (in-file)
- `backend/services/niftybees_service.py` - ETF position (in-file)

---

**End of Reference** | Version 1.0 | 2026-07-20
