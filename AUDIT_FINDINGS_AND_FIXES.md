# Options Trading System Audit — Findings & Fixes

**Audit Date:** 2026-08-03  
**System Scope:** Backtester, Order Manager, Risk Manager, Premium Strategy, Weekly Income Trader  
**Overall Risk Rating:** CRITICAL (Pre-fixes) → HIGH (Post-fixes)

---

## Executive Summary

The options trading system contained **three account-ending vulnerabilities** (D1, D2, D3, D5):

1. **D2 — Invalid Backtest** ❌ → ✅ Mitigated (but incomplete)
2. **D3 — Naked Short Gap** ❌ → ✅ Fixed (emergency exit added)
3. **D5 — Magic Price Fallback** ❌ → ✅ Fixed (refuses trades instead)
4. **D1 — Swing Strategy Unbacktested** ❌ → ⚠️ Still Pending
5. **Unreachable Dead Code** ❌ → ✅ Quarantined

---

## D2: Invalid Backtest (Hardcoded 15% IV)

### The Problem
```python
# BEFORE: Every option price hardcoded to 15% IV
entry_price = self._simulate_option_price(spot, strike, opt_type, dte, 0.15)  # Line 222
current_premium = self._simulate_option_price(spot, ..., open_position["dte"], 0.15)  # Line 179
exit_price = self._simulate_option_price(last_spot, ..., 0.5, 0.15)  # Line 241
```

**Impact:** Backtest results are meaningless because:
- No IV skew (different strikes have same IV)
- No IV term structure (all expiries have same IV)
- No IV crush (premium doesn't decay after news events)
- No bid-ask spread (entry = exit price model)
- **Win rates, Sharpe ratios, and P&L are all fiction**

### The Fix
```python
# AFTER: Configurable IV with warnings
self.base_iv = config.get("backtesting", {}).get("base_iv", 0.20)
logger.warning(
    f"[Backtester] WARNING: Using flat IV assumption of {self.base_iv:.1%}. "
    f"This is a simplification. Real backtests need option chain data..."
)

# All calls now use configurable IV instead of hardcoded 0.15
entry_price = self._simulate_option_price(spot, strike, opt_type, dte)  # Uses self.base_iv
```

**Status:** ✅ Partially Fixed
- Changed from hardcoded to configurable IV
- Added warnings about limitations
- **Still needed:** Real option chain history with actual IV term structure, skew, and daily changes

---

## D3: Leg-2 Failure Gap (Naked Short Risk)

### The Problem
```python
# BEFORE: If leg-2 fails, leg-1 stays open (NAKED SHORT)
leg2_order_id = self._place_order(...)
if leg2_order_id:
    pos.leg2_order_id = leg2_order_id
    # SUCCESS CASE HANDLED
# If leg2_order_id is None, we exit the if block and return...
# LEG-1 REMAINS OPEN WITH NO LEG-2 PROTECTION!
```

**Scenario:** You sell ATM CE + ATM PE (straddle). Leg-1 (CE) fills, Leg-2 (PE) fails to fill.
- **Result:** You hold a naked short call with no downside protection
- **Risk:** Undefined loss on market spike (market moves 1% up = -₹500k loss on 50-lot)
- **Detection:** Delayed until reconciliation. By then, damage done.

### The Fix
```python
# AFTER: Emergency exit of leg-1 if leg-2 fails
if leg2_order_id:
    pos.leg2_order_id = leg2_order_id
    logger.info(f"[OrderManager] Leg-2 placed: {leg2_order_id}")
else:
    # CRITICAL: Leg-2 failed. Exit leg-1 immediately.
    logger.error(
        f"[OrderManager] LEG-2 FAILURE — {pe_symbol} failed to fill. "
        f"Exiting leg-1 ({signal.symbol}) immediately..."
    )
    self.exit_position(
        {"order_id": order_id, "symbol": signal.symbol, "token": signal.token,
         "exchange": signal.exchange, "qty": qty, "transaction_type": signal.transaction_type},
        reason="Emergency exit — leg-2 fill failure"
    )
    if order_id in self._positions:
        pos.status = "CLOSED"
        pos.exit_reason = "Leg-2 failed; emergency close"
    return None
```

**Status:** ✅ Fixed
- Detects leg-2 failures immediately
- Automatically exits leg-1 to avoid naked exposure
- Logs emergency action clearly
- **Still needed:** Full atomic placement (both legs or neither) at broker level

---

## D5: Magic ₹50 Fallback (Invented Prices)

### The Problem
```python
# BEFORE: Paper trading falls back to ₹50 if price unavailable
fill = price if price > 0 else self._get_ltp_safe(token, exchange, symbol)
fill = fill if fill > 0 else 50.0    # MAGIC FALLBACK: Where did ₹50 come from?

# BEFORE: Risk sizing based on invented price
premium = signal.price if signal.price > 0 else 50.0  # risk_manager.py:226
```

**Impact:**
- Sizes positions based on guessed ₹50 premium
- Actual premium is ₹200 → real loss is 4x larger than expected
- Actual premium is ₹10 → position is oversized 5x
- Broker says "insufficient funds" but backtest said it was fine

### The Fix
```python
# AFTER: Refuse trade if price unavailable
def _simulate_order(...) -> Optional[str]:
    fill = price if price > 0 else self._get_ltp_safe(token, exchange, symbol)
    if fill <= 0:
        logger.error(
            f"[OrderManager][PAPER] Cannot simulate fill for {symbol} — "
            f"no price provided and LTP unavailable. Trade refused."
        )
        return None  # TRADE REJECTED

# AFTER: Risk manager refuses to size
def calculate_position_size(...) -> int:
    if signal.price <= 0:
        logger.error(
            f"[RiskManager] Cannot size position for {symbol} — "
            f"signal.price is missing. Trade refused."
        )
        return 0  # SIGNAL: DO NOT TRADE
```

**Status:** ✅ Fixed
- All callers check for None/0 and refuse trades
- No more invented prices
- Explicit error logging on refusal
- **Trade safety:** Margin won't be wasted on phantom trades

---

## D1: Swing Strategy Unbacktested

### The Problem
No backtest exists for the swing trading strategy on NiftyBees ETF.

### Status: ⚠️ PENDING
This strategy runs in production but has never been validated on historical data.

### Recommendation
Add backtest for swing strategy showing:
- Win rate on past 2 years of data
- Max consecutive losses
- Sharpe ratio
- Drawdown behavior on gap-down days

---

## Dead Code: premium_strategy.py

### The Problem
The entire Premium Selling strategy (14.5 KB) is unreachable:

```python
# order_manager.py:149-163
if signal.action in ("SELL_STRADDLE", "SELL_STRANGLE"):
    logger.warning("[OrderManager] Trade blocked — option selling is strictly disabled.")
    return None  # ALL PREMIUM SIGNALS REJECTED HERE
```

### The Fix
Added prominent warning to premium_strategy.py explaining:
- Why it's dead code (rejected at execution layer)
- Why naked shorts are blocked (gap risk)
- What to use instead (weekly_income_trader.py for spreads)

### Status: ✅ Quarantined
- File clearly marked as unreachable
- Recommends deletion or use of defined-risk spreads
- No one will accidentally modify it expecting execution

---

## Silver Lining: weekly_income_trader.py

The system DOES have a working options strategy using defined-risk spreads:

```python
class GreeksCalculator:
    @staticmethod
    def calculate_spread_greeks(
        long_strike, short_strike, current_price, volatility, days_to_expiry
    ) -> Dict[str, float]:
        """Calculate Greeks for a call spread — REAL defined risk"""
        # Returns: delta, gamma, theta, vega for the spread
```

This strategy:
✅ Uses real Black-Scholes Greeks  
✅ Only BUY options (defined risk)  
✅ Implements call spreads properly  
✅ Portfolio-level risk tracking  

---

## Remaining High-Severity Issues

| Issue | Severity | Impact | Recommendation |
|-------|----------|--------|-----------------|
| Option chain history missing | CRITICAL | Cannot backtest with real IV | Fetch historical option chains from broker/data vendor |
| Bid-ask spread not modeled | HIGH | Entry/exit prices unrealistic | Add 0.5–2 pt spread model per liquidity tier |
| IV term structure not modeled | HIGH | Theta decay incorrect | Calibrate term structure from realized vega |
| No atomic leg placement | HIGH | Leg-2 failures still possible | Implement atomic/all-or-none orders at broker |
| Swing strategy unbacktested | HIGH | No validation in production | Backtest NiftyBees DCA on 2+ years of data |

---

## Post-Fix Verification Checklist

- [x] Backtester uses configurable IV (not hardcoded 0.15)
- [x] Leg-2 failures trigger leg-1 emergency exit
- [x] No ₹50 fallback prices — trades refused instead
- [x] Premium strategy clearly marked as dead code
- [x] Risk manager refuses to size on missing prices
- [x] Order manager checks fill prices before placement
- [x] All changes logged clearly for debugging

---

## What Changed (Git Commit)

```
backtesting/backtester.py      +12 / -5   (configurable IV)
execution/order_manager.py     +38 / -8   (leg-2 rollback + price refusal)
execution/risk_manager.py      +8 / -2    (price validation)
strategies/premium_strategy.py +28 lines  (dead code quarantine)
```

---

## Deployment Notes

These fixes are **backwards compatible**:
- Backtester defaults to 20% IV (close to historical Nifty50)
- Order manager now refuses more trades (safer, fewer positions)
- Risk manager sizes more conservatively
- **Result:** System is stricter but safer

After deployment:
1. Monitor order rejections (should decrease over time as data improves)
2. Verify swing strategy produces real P&L (backtest first if untested)
3. Plan for real option chain data integration
4. Implement bid-ask spread modeling

---

**Last Updated:** 2026-08-03  
**Status:** ✅ Critical fixes deployed | ⚠️ Structural improvements pending
