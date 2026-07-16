# Hermes AI Agent - Setup Guide

## What is Hermes?

Hermes is a **fully automated intraday trading agent** powered by AI (LLM reasoning). It analyzes market conditions every 30 seconds and autonomously makes buy/sell decisions for intraday (MIS) trades.

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
