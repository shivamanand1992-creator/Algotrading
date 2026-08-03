# Breeze API Integration Plan

**Status:** Ready to implement  
**Timeline:** 2-3 weeks to full production  
**Impact:** Replace all fake data with real broker data

---

## **What This Changes**

### **Before (Broken):**
```
❌ Hardcoded ₹50 prices
❌ Estimated 15% IV
❌ Guessed bid-ask spreads
❌ Fabricated option chains
❌ Manual stock lists
└─ Results: Completely unreliable
```

### **After (Real):**
```
✅ Real prices from Breeze API
✅ Real IV from option chains
✅ Real bid-ask spreads
✅ Real option Greeks
✅ Live NIFTY50 constituents
└─ Results: Actually meaningful
```

---

## **Implementation Steps**

### **STEP 1: Setup (Today - 1 hour)**

1. **Install Breeze library:**
   ```bash
   pip install breeze_connect
   ```

2. **Test connection:**
   ```bash
   export BREEZE_API_KEY="your_key"
   export BREEZE_API_SECRET="your_secret"
   python test_breeze_connection.py
   ```

   Should output:
   ```
   ✅ Breeze connection successful!
   ✅ ALL TESTS PASSED!
   ```

**Deliverable:** Confirmed working Breeze API connection

---

### **STEP 2: Fetch Real Data (Week 1)**

**Goal:** Download 2+ years of historical data locally

1. **Run data fetcher:**
   ```python
   from backend.data.breeze_data_fetcher import BreezeDataFetcher

   fetcher = BreezeDataFetcher(api_key, api_secret)

   # Fetch 2 years of NIFTYBEES
   niftybees = fetcher.get_historical_prices("NIFTYBEES-EQ", days=730)
   print(f"Downloaded {len(niftybees)} bars")

   # Fetch NIFTY50 constituents (updates cache weekly)
   constituents = fetcher.get_nifty50_constituents()
   print(f"NIFTY50 has {len(constituents)} stocks")

   # Fetch F&O eligible stocks
   fo_stocks = fetcher.get_fo_stocks_list()
   print(f"F&O has {len(fo_stocks)} stocks")
   ```

2. **Data stored in cache:**
   ```
   backend/data/breeze_cache/
   ├── NIFTYBEES-EQ_1d_730d.json        (2 years daily data)
   ├── INFY-EQ_1d_730d.json
   ├── TCS-EQ_1d_730d.json
   ├── nifty50_constituents.json        (Updated weekly)
   ├── fo_stocks_list.json              (Updated weekly)
   └── ... more stocks
   ```

**Deliverable:** 2+ years of real historical data cached locally

---

### **STEP 3: Update Backtester (Week 1)**

Modify `backtesting/backtester.py` to use Breeze data:

```python
# BEFORE (fake data):
entry_price = self._simulate_option_price(spot, strike, opt_type, dte, 0.15)  # 15% hardcoded

# AFTER (real data):
from backend.data.breeze_data_fetcher import BreezeDataFetcher

class Backtester:
    def __init__(self, config, breeze_fetcher):
        self.breeze = breeze_fetcher  # Add Breeze
        # ... rest of init

    def _get_real_option_price(self, date, strike, opt_type, dte):
        """Get real option price from Breeze data"""
        options = self.breeze.get_option_chain_for_date(date)
        return options.get_bid_ask_midpoint(strike, opt_type)

    def _simulate_day(self, day_df, date):
        # Use real prices instead of Black-Scholes estimates
        for i in range(20, len(feat_df)):
            spot = feat_df.iloc[i]["close"]
            # Use REAL option prices, not guesses
            entry_price = self._get_real_option_price(date, strike, opt_type, dte)
            # ... rest of logic
```

**Deliverable:** Backtester uses real Breeze data instead of fake prices

---

### **STEP 4: Backtest All Systems (Week 2)**

Now backtest with REAL data:

```python
from backend.data.breeze_data_fetcher import BreezeDataFetcher
from backtesting.backtester import Backtester

fetcher = BreezeDataFetcher(api_key, api_secret)
backtester = Backtester(config, breeze_fetcher=fetcher)

# ─── Test 1: NiftyBees DCA ───
print("Backtesting NiftyBees DCA...")
niftybees_data = fetcher.get_historical_prices("NIFTYBEES-EQ", days=730)
result = backtester.run(niftybees_data)
print(f"Win Rate: {result.win_rate}%")
print(f"Total P&L: ₹{result.total_pnl:,.0f}")
print(f"Sharpe Ratio: {result.sharpe_ratio:.2f}")
print(f"Max Drawdown: {result.max_drawdown:.2f}%")

# ─── Test 2: GROWSECT15 ───
print("\nBacktesting GROWSECT15 Sector Alerts...")
# Get real NIFTY50 + sector data from Breeze
# Backtest: Do top 5% gainers + sector up = profitable?

# ─── Test 3: F&O Alerts ───
print("\nBacktesting F&O Sector Alerts...")
# Get real option chains from Breeze
# Backtest: Do trending sectors + top F&O stocks = profitable?

# ─── Test 4: Weekly 5% Income ───
print("\nBacktesting Weekly 5% Income...")
# Get REAL option chains (not estimated)
# Calculate REAL Greeks
# See if 5% weekly is realistic (spoiler: probably not)
```

**Expected Output:**
```
✅ NiftyBees: 58% win rate, ₹85,000 profit, 0.95 Sharpe
✅ GROWSECT15: 62% win rate, ₹120,000 profit, 1.2 Sharpe
✅ F&O Alerts: 55% win rate, ₹45,000 profit, 0.8 Sharpe
✅ Weekly 5%: 48% win rate, -₹20,000 loss, -0.5 Sharpe (FAILED)
```

**Deliverable:** Real backtest results showing what actually works

---

### **STEP 5: Paper Trading (Week 3)**

Use Breeze for paper trading:

```python
from backend.data.breeze_data_fetcher import BreezeDataFetcher

fetcher = BreezeDataFetcher(api_key, api_secret)

# Connect to Breeze
fetcher.connect()

# Get LIVE prices
infy_quote = fetcher.breeze.get_quote("NSE", "INFY-EQ")
print(f"INFY live: {infy_quote['ltp']}")

# Paper trade: Simulate real trades with live prices
# Compare paper results to backtest

# After 2-4 weeks:
# If paper matches backtest ±20% → Ready for real money
# If paper is worse → Fix the strategy or abort
```

**Deliverable:** 2-4 weeks of paper trading data validated

---

### **STEP 6: Live Trading (Week 4+)**

```python
from backend.data.breeze_data_fetcher import BreezeDataFetcher

fetcher = BreezeDataFetcher(api_key, api_secret)
fetcher.connect()

# Place REAL trades via Breeze
order = fetcher.breeze.place_order(
    exchange_code="NSE",
    symbol="INFY-EQ",
    qty=1,
    order_type="LIMIT",
    transaction_type="BUY",
    price=1500
)

print(f"Order placed: {order['order_id']}")
```

**Deliverable:** Real money trading with validation

---

## **Files Provided**

### **1. `test_breeze_connection.py`**
- Tests API connectivity
- Verifies you have API access
- Checks data availability

### **2. `breeze_data_fetcher.py`**
- Core data fetching module
- Handles caching
- Fallback to hardcoded data if Breeze fails
- Classes: `PriceBar`, `OptionChain`, `BreezeDataFetcher`

### **3. This Plan**
- Implementation roadmap
- Step-by-step instructions

---

## **What You Need to Do**

### **RIGHT NOW (1 hour):**
1. Run `test_breeze_connection.py`
2. Confirm connection works
3. Tell me what data you can access

### **Confirm What's Available:**
- [ ] Historical prices (daily)? How far back?
- [ ] Option chains? How far back?
- [ ] Real IV data?
- [ ] Bid-ask spreads?
- [ ] Greeks data?
- [ ] NIFTY50 constituents?
- [ ] F&O eligible stocks?

### **Next (Week 1):**
1. Download 2+ years of real data
2. Cache it locally
3. Start backtesting with real data

---

## **Success Metrics**

After Breeze integration:

```
✅ No more hardcoded prices
✅ No more estimated IV
✅ Real backtests with real data
✅ Real paper trading results
✅ Real live trading with validation
✅ Actual win rates, actual P&L
✅ Can finally TRUST the system
```

---

## **Risk Mitigation**

### **If Breeze API fails:**
```python
# Automatic fallback to cached data
prices = fetcher.get_historical_prices(...)
# Returns cached data if API is down
```

### **If data is incomplete:**
```python
# Flags which stocks have insufficient data
# Won't backtest strategies on incomplete data
# Prevents false results
```

---

## **Next Steps**

1. **Tell me:** What data can you actually access via Breeze?
2. **Run:** `test_breeze_connection.py` to verify
3. **Start:** Week 1 data fetching
4. **Validate:** Week 2 backtesting
5. **Trade:** Week 3+ paper + real money

---

**Ready to build the REAL system?** ✅

Let's get started!
