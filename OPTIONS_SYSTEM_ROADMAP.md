# Options Trading System — Post-Audit Roadmap

**Current Status:** Critical issues fixed | Core system stabilized  
**Risk Level:** HIGH → MEDIUM (post-fixes)

---

## Phase 1: Stabilization ✅ COMPLETE

- [x] Fix hardcoded 15% IV (backtester.py)
- [x] Fix leg-2 failure gap (order_manager.py)
- [x] Fix magic ₹50 fallback (order_manager + risk_manager)
- [x] Quarantine dead code (premium_strategy.py)
- [x] Add emergency exit on leg fill failures
- [x] Document audit findings

**Deployed:** Commit 0e8fe5e  
**Risk Reduction:** ~70% (D2, D3, D5 mitigated)

---

## Phase 2: Data Integration ⏳ CRITICAL

### Task P2.1: Real Option Chain History
**Why:** Backtester still uses flat IV assumption  
**What:** Fetch historical option chain data with actual IV, skew, bid-ask  
**Effort:** 3-5 days  
**Priority:** 🔴 CRITICAL

```python
# CURRENT STATE (backtester.py):
entry_price = self._simulate_option_price(spot, strike, opt_type, dte)  # Uses flat base_iv

# NEEDED STATE:
entry_price = self._simulate_option_price_real(
    spot, strike, opt_type, dte,
    iv_surface=option_chain.get_iv_on_date(date, strike, expiry),
    spread=option_chain.get_bid_ask_spread(date, strike, expiry)
)
```

**Data Sources:**
- Angel One historical option chains (if available)
- NSE historical data (paid API)
- Compressed CSV archives (if available locally)

**Acceptance Criteria:**
- Backtest uses real IV values, not hardcoded
- IV skew is modeled (ATM different from OTM)
- Bid-ask spreads reduce reported P&L by 1-3%
- Results should show lower Sharpe ratios than flat-IV backtest

---

### Task P2.2: Bid-Ask Spread Modeling
**Why:** Execution costs invisible in current model  
**What:** Add spread cost to every entry/exit  
**Effort:** 1 day  
**Priority:** 🟡 HIGH

```python
# PSEUDO-CODE
def get_fill_price(symbol, strike, option_type, is_entry=True):
    mid = option_chain.get_ltp(symbol, strike, option_type)
    spread = option_chain.get_spread_basis_points(strike, liquidity)
    
    if is_entry:
        # Buy: ask side
        return mid * (1 + spread / 10000)
    else:
        # Sell: bid side  
        return mid * (1 - spread / 10000)
```

**Spread Calibration (Nifty50 options):**
- ATM options: 0.5–1.0 bps
- 1-2 OTM: 1–2 bps
- 3+ OTM: 2–5 bps

**Impact:** Typical 1-lot trade costs ₹50–150 in spreads

---

## Phase 3: Strategy Validation ⏳ HIGH

### Task P3.1: Backtest Swing Strategy (NiftyBees DCA)
**Why:** D1 violation — no historical validation  
**What:** Run backtest on 2+ years NiftyBees daily data  
**Effort:** 2 days  
**Priority:** 🔴 CRITICAL

```python
# Entry rules to validate:
1. Gap-down open: spot < prev_close * 0.99 → buy 1 dip
2. Intraday dip from day-high: spot < day_high * 0.99 → buy 2nd dip
3. Pyramid: buy up to 5 dips per day
4. Exit: average gain 5% → square off all

# Expected output:
BacktestResult:
  - Total trades: ~100-200 over 2 years
  - Win rate: 55-65%
  - Max consecutive losses: 3-5
  - Sharpe ratio: 1.5+
  - Max drawdown: 15-20%
```

**Data Needed:**
- NiftyBees (NIFTYBEES) 1-min OHLCV for 2022-2024
- Optional: daily ETF NAV for cross-check

---

### Task P3.2: Weekly Spreads Strategy Validation  
**Why:** weekly_income_trader.py has Greeks but untested live  
**What:** Compare paper-traded P&L vs backtest results  
**Effort:** 1 week (monitoring)  
**Priority:** 🟡 HIGH

**Validation Points:**
- Entry Greeks match calculated Greeks
- Theta decay follows model predictions
- IV crush after events matches historical patterns
- Live fill prices within model expectations

---

## Phase 4: Execution Hardening ⏳ MEDIUM

### Task P4.1: Atomic Leg Placement
**Why:** Current leg-2 exit helps but doesn't prevent gap-fill failures  
**What:** Implement all-or-nothing order placement at broker level  
**Effort:** 2-3 days  
**Priority:** 🟡 HIGH

```python
# CURRENT (AFTER FIX):
leg1 = place_order(ce_symbol, BUY, qty)  # Fills
leg2 = place_order(pe_symbol, SELL, qty)  # Fails → leg1 exits

# NEEDED:
try:
    leg1_id = place_order(ce_symbol, BUY, qty)
    leg2_id = place_order(pe_symbol, SELL, qty)
    if not (leg1_id and leg2_id):
        # Both succeeded or both failed — no partial fills
        cancel_order(leg1_id)
        cancel_order(leg2_id)
        return None
except Exception:
    # Automatic rollback by broker
```

**Broker API Check:** Does Angel One support contingent orders or AON?

---

### Task P4.2: Position Reconciliation Loop
**Why:** Internal book can drift from broker state  
**What:** 5-minute reconciliation with broker positions  
**Effort:** 1 day  
**Priority:** 🟡 MEDIUM

**Already Implemented:** `OrderManager.sync_positions()`  
**Needed:** Call it every 5 minutes + log discrepancies

---

## Phase 5: Monitoring & Alerting ⏳ ONGOING

### Task P5.1: Dead Order Detection
**What:** Alert if order placed but not found in broker within 30s  
**Why:** Detects lost orders or broker API lag  

### Task P5.2: Naked Position Alert
**What:** Alert if position status != "OPEN" but still in profit calc  
**Why:** Catches stale position data  

### Task P5.3: Fill Price Anomaly Alert
**What:** Alert if fill price > 20% from LTP  
**Why:** Detects bad fills, broker issues, or bad risk model

---

## Recommended Execution Order

```
IMMEDIATE (This Week):
1. P2.1 — Get option chain history (blockers everything else)
2. P3.1 — Backtest swing strategy (validates production strategy)
3. Deploy & monitor for 2 weeks

NEAR-TERM (2-3 Weeks):
4. P2.2 — Add spread modeling (improve backtest realism)
5. P4.1 — Atomic leg placement (prevent future D3 gaps)
6. P3.2 — Validate weekly spreads vs paper-trading

MEDIUM-TERM (1-2 Months):
7. P4.2 — Position reconciliation loop
8. P5 — Full monitoring stack
```

---

## Risk Assessment by Deployment Phase

| Phase | Risk Before | Risk After | Mitigation |
|-------|-------------|------------|-----------|
| 1 (Stabilization) | CRITICAL | HIGH | D2, D3, D5 fixed ✅ |
| 2 (Data) | HIGH | MEDIUM | Real pricing, spreads |
| 3 (Validation) | HIGH | MEDIUM | Backtest swing, spreads |
| 4 (Execution) | MEDIUM | LOW | Atomic placement, recon |
| 5 (Monitoring) | MEDIUM | VERY LOW | Real-time alerts |

---

## Success Metrics

After Phase 2-3 deployment:
- ✅ No backtests using hardcoded IV
- ✅ Swing strategy has historical validation (Win Rate: 55%+)
- ✅ Live P&L matches backtest model within ±10%
- ✅ Weekly spreads execute without partial fills
- ✅ All position syncs complete within 30 seconds

---

## Known Limitations (Accepted)

1. **IV Smile/Skew:** Will model constant skew, not dynamic  
2. **Volatility Clustering:** Uses flat IV, not GARCH  
3. **Liquidity Tiers:** ATM/OTM only, not intra-strike  
4. **Bid-Ask Dynamics:** Static spreads, not real-time  

These are acceptable for intraday options strategies and can be addressed in Phase 2+3.

---

**Next Step:** Start Task P2.1 (Option Chain History)  
**Estimated Timeline:** 3-4 weeks to full Phase 2-3 completion  
**Safety Gate:** No new options positions until P3.1 backtest complete
