# 🚀 START HERE — One Command Setup

## **Just Run This**

```bash
python setup_breeze_and_backtest.py
```

That's it. The script does everything.

---

## **What It Does Automatically**

1. ✅ Asks for your Breeze API credentials
2. ✅ Tests if it works
3. ✅ Downloads 2 years of REAL market data
4. ✅ Runs backtests on your strategies
5. ✅ Shows you the results
6. ✅ Optionally saves your credentials for next time

---

## **Step by Step (What You'll See)**

### **Step 1: Enter Credentials**
```
API Key: [paste your key]
API Secret: [paste your secret]
```

### **Step 2: Connection Test**
```
✅ Connected to Breeze API!
✅ RELIANCE quote: ₹2,840
```

### **Step 3: Download Data**
```
Fetching NiftyBees ETF... ✓ (730 bars)
Fetching INFY... ✓ (730 bars)
Fetching TCS... ✓ (730 bars)
...
✅ Downloaded 6 stocks
```

### **Step 4: Backtest Results**
```
═════════════════════════════════════════════════════
                  BACKTEST RESULTS
═════════════════════════════════════════════════════

NiftyBees DCA
  Trades: 145
  Win Rate: 58.6%
  Total P&L: ₹85,000
  Sharpe Ratio: 0.95
  Max Drawdown: 18.5%

INFY Swing
  Trades: 89
  Win Rate: 62.1%
  Total P&L: ₹42,500
  ...
```

### **Step 5: Save Credentials?**
```
Save credentials for next time? (y/n): y
✅ Credentials saved
```

---

## **That's All**

Once done, you have:
- ✅ 2 years of REAL market data (cached locally)
- ✅ Backtest results showing which strategies work
- ✅ Ready to paper trade or go live

---

## **If You Get Errors**

### **Error: "breeze_connect not installed"**
→ The script will install it automatically

### **Error: "Connection failed"**
→ Check your API key/secret are correct

### **Error: "No data found"**
→ Breeze API might be down, try again later

---

## **Next Steps (After Running)**

1. **Look at the results**
   - Which strategies have >55% win rate?
   - Which have positive Sharpe ratio?
   - Those are the ones that work

2. **Paper trade for 2-4 weeks**
   - Does real trading match the backtest?
   - If yes → ready for real money
   - If no → something's wrong

3. **Start small with real money**
   - ₹5,000-10,000 first
   - Scale up if it works

---

## **That's It!**

Just run:
```bash
python setup_breeze_and_backtest.py
```

It will do everything for you automatically. No coding required. No manual steps.

**Go run it now!** 🎯
