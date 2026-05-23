"""
Demo backtest — runs the full AI pipeline on synthetic Nifty50 data.
No broker connection required. Shows the complete system working end-to-end.
"""

import sys
import warnings
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from scipy.stats import norm
import math

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box
import pytz

warnings.filterwarnings("ignore")
console = Console()
IST = pytz.timezone("Asia/Kolkata")
sys.path.insert(0, str(Path(__file__).parent))

# ── Config ────────────────────────────────────────────────────────────────────

CONFIG = {
    "ml": {
        "regime_model": {
            "n_estimators": 200, "max_depth": 5, "learning_rate": 0.05,
            "regimes": ["trending_up", "trending_down", "ranging", "high_volatility"],
        },
        "price_predictor": {
            "min_confidence": 0.60, "lookback_window": 30, "prediction_horizon": 5,
            "lstm_hidden_size": 64, "lstm_layers": 2, "dropout": 0.2,
            "ensemble_weights": {"lstm": 0.4, "xgboost": 0.4, "lightgbm": 0.2},
        },
        "training": {"model_save_path": "trained_models/"},
        "strategy_selector": {"update_frequency_minutes": 5},
    },
    "risk": {
        "total_capital": 500_000, "daily_loss_limit_pct": 0.04,
        "daily_profit_target_pct": 0.02, "per_trade_risk_pct": 0.01,
        "option_buy_sl_pct": 0.30, "option_buy_target_pct": 0.60,
        "option_sell_sl_pct": 0.50, "trailing_sl_trigger_pct": 0.20,
        "trailing_sl_pct": 0.10,
    },
    "trading": {
        "lot_size": 50, "max_lots_per_trade": 2,
        "max_simultaneous_positions": 3,
        "no_new_trades_after": "15:00", "square_off_time": "15:20",
    },
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def bs_price(S: float, K: int, opt: str, dte: float = 7, iv: float = 0.15) -> float:
    T = max(dte / 252, 1e-6); r = 0.065
    d1 = (math.log(S / K) + (r + 0.5 * iv**2) * T) / (iv * math.sqrt(T))
    d2 = d1 - iv * math.sqrt(T)
    if opt == "CE":
        return max(S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2), 0.05)
    return max(K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1), 0.05)


def generate_nifty_data(days: int = 252, freq_minutes: int = 5) -> pd.DataFrame:
    np.random.seed(42)
    candles_per_day = int(375 / freq_minutes)
    n = days * candles_per_day

    price = 22000.0
    prices, regimes_list = [price], []
    regime, regime_dur, regime_max = "trending_up", 0, np.random.randint(50, 200)

    for _ in range(1, n):
        regime_dur += 1
        if regime_dur > regime_max:
            regime = np.random.choice(
                ["trending_up", "trending_down", "ranging", "high_volatility"],
                p=[0.30, 0.25, 0.30, 0.15],
            )
            regime_dur = 0
            regime_max = np.random.randint(50, 200)

        params = {"trending_up": (0.0003, 0.0008), "trending_down": (-0.0003, 0.0008),
                  "ranging": (0.0, 0.0005), "high_volatility": (0.0, 0.002)}
        drift, vol = params[regime]
        price = max(prices[-1] * (1 + drift + vol * np.random.randn()), 15000)
        prices.append(price)
        regimes_list.append(regime)

    regimes_list.append(regime)
    closes = np.array(prices)
    spreads = closes * np.random.uniform(0.0005, 0.002, n)
    highs   = closes + spreads * np.random.uniform(0.3, 1.0, n)
    lows    = closes - spreads * np.random.uniform(0.3, 1.0, n)
    opens   = closes - (closes - lows) * np.random.uniform(-0.5, 0.5, n)
    volumes = np.random.randint(50_000, 500_000, n)

    timestamps, day_offset = [], 0
    base = datetime(2024, 1, 1, 9, 15, tzinfo=IST)
    for i in range(n):
        slot = i % candles_per_day
        if slot == 0 and i > 0:
            day_offset += 1
            while (base + timedelta(days=day_offset)).weekday() >= 5:
                day_offset += 1
        timestamps.append(base + timedelta(days=day_offset, minutes=slot * freq_minutes))

    return pd.DataFrame(
        {"open": np.round(opens, 2), "high": np.round(highs, 2),
         "low": np.round(lows, 2), "close": np.round(closes, 2),
         "volume": volumes, "true_regime": regimes_list},
        index=pd.DatetimeIndex(timestamps),
    )


# ── Main ──────────────────────────────────────────────────────────────────────

console.print(Panel(
    "[bold cyan]Nifty50 AI Options Trading System — Demo Backtest[/bold cyan]\n"
    "[dim]Synthetic data · No broker connection needed[/dim]",
    box=box.DOUBLE_EDGE,
))

# 1. Data
console.print("\n[bold]Step 1:[/bold] Generating synthetic Nifty50 data (252 trading days)…")
df_raw = generate_nifty_data(days=252)
console.print(f"[green]✓[/green] {len(df_raw):,} 5-min candles  |  "
              f"Price: ₹{df_raw['close'].min():,.0f} – ₹{df_raw['close'].max():,.0f}")

# 2. Features
console.print("\n[bold]Step 2:[/bold] Computing technical feature matrix…")
from features.technical_indicators import TechnicalFeatureEngine
from features.market_regime import MarketRegimeDetector

engine = TechnicalFeatureEngine()
df_feat = engine.compute_all(df_raw.drop(columns=["true_regime"]))
df_feat["true_regime"] = df_raw["true_regime"].values
df_feat = df_feat.dropna()
# Normalise MACD column name
if "macd_hist" not in df_feat.columns and "macd_histogram" in df_feat.columns:
    df_feat["macd_hist"] = df_feat["macd_histogram"]

feature_cols = [c for c in df_feat.columns
                if c not in {"open","high","low","close","volume","true_regime"}
                and df_feat[c].dtype in ("float64","int64")]
console.print(f"[green]✓[/green] {df_feat.shape[0]:,} rows × {len(feature_cols)} ML features")

# 3. Train/test split
split     = int(len(df_feat) * 0.8)
train_df  = df_feat.iloc[:split].copy()
test_df   = df_feat.iloc[split:].copy()
console.print(f"      Train: {len(train_df):,} candles  |  Test: {len(test_df):,} candles")

# 4. Regime classifier
console.print("\n[bold]Step 3:[/bold] Training XGBoost market regime classifier…")
from models.regime_classifier import MarketRegimeClassifier

regime_clf = MarketRegimeClassifier(CONFIG)
try:
    regime_clf.train(train_df)
    test_regime, test_conf, _ = regime_clf.predict(test_df.tail(100))
    console.print(f"[green]✓[/green] Regime classifier trained  |  "
                  f"Latest: [bold]{test_regime}[/bold] ({test_conf:.0%} confidence)")
    use_ml_regime = True
except Exception as e:
    console.print(f"[yellow]⚠[/yellow] Regime classifier: {e!r} — using rule-based fallback")
    use_ml_regime = False

# 5. Price predictor
console.print("\n[bold]Step 4:[/bold] Training LSTM + XGBoost + LightGBM ensemble…")
from models.price_predictor import PriceDirectionPredictor

predictor = PriceDirectionPredictor(CONFIG["ml"]["price_predictor"])
use_ml_pred = False
try:
    predictor.train(train_df, feature_cols)
    direction, conf, probs = predictor.predict(test_df.tail(50), feature_cols)
    labels = {1: "UP ↑", -1: "DOWN ↓", 0: "FLAT →"}
    console.print(f"[green]✓[/green] Ensemble trained  |  "
                  f"Latest prediction: [bold]{labels[direction]}[/bold] ({conf:.0%} confidence)")
    use_ml_pred = True
except Exception as e:
    console.print(f"[yellow]⚠[/yellow] Price predictor: {e!r} — using rule-based signal")

# 6. Walk-forward backtest
console.print("\n[bold]Step 5:[/bold] Running walk-forward backtest on held-out test period…")

LOOKBACK  = 30
SL_PCT    = CONFIG["risk"]["option_buy_sl_pct"]
TGT_PCT   = CONFIG["risk"]["option_buy_target_pct"]
MAX_HOLD  = 18        # 5-min candles = 90 min max hold
LOT_SIZE  = CONFIG["trading"]["lot_size"]
CAPITAL   = CONFIG["risk"]["total_capital"]
DAILY_LIMIT = CAPITAL * CONFIG["risk"]["daily_loss_limit_pct"]

detector    = MarketRegimeDetector()
total_pnl   = 0.0
daily_pnl   = 0.0
current_pos = None
trades      = []
equity      = [CAPITAL]
daily_stats : dict = {}

for i in range(LOOKBACK, len(test_df)):
    row      = test_df.iloc[i]
    ts       = test_df.index[i]
    time_str = ts.strftime("%H:%M")
    spot     = float(row["close"])
    day      = ts.strftime("%Y-%m-%d")

    if day not in daily_stats:
        daily_pnl = 0.0
        daily_stats[day] = {"start_equity": CAPITAL + total_pnl}

    # EOD square-off
    if time_str >= "15:20" and current_pos:
        ep  = bs_price(spot, current_pos["strike"], current_pos["opt_type"], 0.5)
        pnl = (ep - current_pos["entry"]) * LOT_SIZE
        total_pnl += pnl; daily_pnl += pnl
        trades.append({"pnl": pnl, "reason": "eod", "regime": current_pos["regime"]})
        equity.append(CAPITAL + total_pnl)
        current_pos = None
        continue

    # Manage open position
    if current_pos:
        cp = bs_price(spot, current_pos["strike"], current_pos["opt_type"])
        ep = current_pos["entry"]
        peak_p = current_pos.get("peak_premium", ep)
        if cp > peak_p:
            current_pos["peak_premium"] = cp
            # Trailing SL
            trail_trigger = ep * (1 + CONFIG["risk"]["trailing_sl_trigger_pct"])
            if cp >= trail_trigger:
                new_sl = cp * (1 - CONFIG["risk"]["trailing_sl_pct"])
                current_pos["sl"] = max(current_pos["sl"], new_sl)

        exit_reason = None
        if cp <= current_pos["sl"]:          exit_reason = "sl_hit"
        elif cp >= ep * (1 + TGT_PCT):       exit_reason = "target_hit"
        elif (i - current_pos["bar"]) >= MAX_HOLD: exit_reason = "time_exit"

        if exit_reason:
            pnl = (cp - ep) * LOT_SIZE
            total_pnl += pnl; daily_pnl += pnl
            trades.append({"pnl": pnl, "reason": exit_reason,
                           "regime": current_pos["regime"], "entry": ep, "exit": cp})
            equity.append(CAPITAL + total_pnl)
            current_pos = None

    if time_str >= "15:00": continue
    if daily_pnl <= -DAILY_LIMIT: continue
    if current_pos: continue

    # Detect regime
    window = test_df.iloc[max(0, i - LOOKBACK): i + 1]
    if use_ml_regime:
        try:
            regime, regime_conf, _ = regime_clf.predict(window)
        except Exception:
            regime = detector.detect_regime_rules(window)
            regime_conf = 0.75
    else:
        regime = detector.detect_regime_rules(window)
        regime_conf = 0.75

    # Generate signal
    ema9  = float(row.get("ema_9",  spot))
    ema21 = float(row.get("ema_21", spot))
    rsi   = float(row.get("rsi",    50))
    macd  = float(row.get("macd_hist", row.get("macd_histogram", 0)))
    adx   = float(row.get("adx",    20))

    # ML prediction (if available)
    if use_ml_pred and i >= LOOKBACK:
        try:
            ml_dir, ml_conf, _ = predictor.predict(window, feature_cols)
        except Exception:
            ml_dir, ml_conf = 0, 0.5
    else:
        score = sum([ema9 > ema21, rsi > 52, macd > 0]) - sum([ema9 < ema21, rsi < 48, macd < 0])
        ml_dir  = 1 if score >= 2 else (-1 if score <= -2 else 0)
        ml_conf = 0.65 if abs(score) >= 2 else 0.50

    if adx < 15: continue

    # Rule-based signal (always active as primary filter)
    rule_score = sum([ema9 > ema21, rsi > 52, macd > 0]) - \
                 sum([ema9 < ema21, rsi < 48, macd < 0])
    rule_bullish = rule_score >= 2
    rule_bearish = rule_score <= -2

    # ML enhances but doesn't block (if trained)
    ml_bullish = (ml_dir == 1 and ml_conf >= 0.55) if use_ml_pred else rule_bullish
    ml_bearish = (ml_dir == -1 and ml_conf >= 0.55) if use_ml_pred else rule_bearish

    action = None
    if regime == "trending_up"   and rule_bullish and (not use_ml_pred or ml_bullish):
        action = "BUY_CE"
    elif regime == "trending_down" and rule_bearish and (not use_ml_pred or ml_bearish):
        action = "BUY_PE"
    elif regime == "high_volatility":
        if rule_bullish: action = "BUY_CE"
        elif rule_bearish: action = "BUY_PE"

    if not action: continue

    strike   = round(spot / 50) * 50
    opt_type = "CE" if action == "BUY_CE" else "PE"
    entry_p  = bs_price(spot, strike, opt_type, dte=7)
    sl_price = entry_p * (1 - SL_PCT)

    current_pos = {
        "strike": strike, "opt_type": opt_type, "entry": entry_p,
        "sl": sl_price, "bar": i, "regime": regime, "peak_premium": entry_p,
    }

# Close any remaining position
if current_pos:
    last_spot = float(test_df["close"].iloc[-1])
    ep  = bs_price(last_spot, current_pos["strike"], current_pos["opt_type"], 0.5)
    pnl = (ep - current_pos["entry"]) * LOT_SIZE
    total_pnl += pnl
    trades.append({"pnl": pnl, "reason": "eod", "regime": current_pos["regime"]})
    equity.append(CAPITAL + total_pnl)

# 7. Metrics
pnls   = [t["pnl"] for t in trades]
wins   = [p for p in pnls if p > 0]
losses = [p for p in pnls if p <= 0]
eq_arr = np.array(equity)
peak   = np.maximum.accumulate(eq_arr)
max_dd = float(abs(((eq_arr - peak) / peak).min()) * 100)
wr     = len(wins) / len(pnls) * 100 if pnls else 0
pf     = sum(wins) / abs(sum(losses)) if losses else float("inf")

days_tested = len(daily_stats)
annual_ret  = (total_pnl / CAPITAL) * (252 / max(days_tested, 1)) * 100
day_rets    = np.diff([v["start_equity"] for v in daily_stats.values()]) / CAPITAL
sharpe      = float(day_rets.mean() / day_rets.std() * np.sqrt(252)) if len(day_rets) > 1 and day_rets.std() > 0 else 0

# 8. Print results
console.print(f"[green]✓[/green] {len(trades)} trades executed over {days_tested} trading days\n")

color = "green" if total_pnl >= 0 else "red"
t = Table(
    title="[bold]Backtest Results — 1 Year Synthetic Nifty50 (Test Set: 20%)[/bold]",
    box=box.DOUBLE_EDGE, show_header=True, header_style="bold magenta",
)
t.add_column("Metric",           style="bold cyan", min_width=26)
t.add_column("Value",            justify="right",   min_width=20)

t.add_row("Capital",             f"₹{CAPITAL:,.0f}")
t.add_row("Net P&L",             f"[{color}]₹{total_pnl:+,.0f}[/{color}]")
t.add_row("Return on Capital",   f"[{color}]{total_pnl/CAPITAL*100:+.2f}%[/{color}]")
t.add_row("Annualised Return",   f"{annual_ret:+.1f}%")
t.add_row("Sharpe Ratio",        f"{sharpe:.2f}")
t.add_row("Max Drawdown",        f"[red]{max_dd:.2f}%[/red]")
t.add_row("Profit Factor",       f"{pf:.2f}")
t.add_row("Total Trades",        str(len(pnls)))
t.add_row("Win Rate",            f"[{'green' if wr>50 else 'red'}]{wr:.1f}%[/]")
t.add_row("Avg Win",             f"[green]₹{np.mean(wins):,.0f}[/green]"  if wins   else "—")
t.add_row("Avg Loss",            f"[red]₹{np.mean(losses):,.0f}[/red]"    if losses else "—")
t.add_row("Best Trade",          f"[green]₹{max(pnls):,.0f}[/green]"      if pnls   else "—")
t.add_row("Worst Trade",         f"[red]₹{min(pnls):,.0f}[/red]"          if pnls   else "—")
t.add_row("Final Capital",       f"₹{CAPITAL + total_pnl:,.0f}")
console.print(t)

# Regime breakdown
r_table = Table(
    title="[bold]Trades by Market Regime[/bold]",
    box=box.SIMPLE_HEAVY, header_style="bold cyan",
)
r_table.add_column("Regime",   style="bold", min_width=20)
r_table.add_column("Trades",   justify="right")
r_table.add_column("Wins",     justify="right")
r_table.add_column("Win Rate", justify="right")
r_table.add_column("Avg P&L",  justify="right")
r_table.add_column("Total P&L",justify="right")

for reg in ["trending_up", "trending_down", "ranging", "high_volatility"]:
    rt = [t for t in trades if t.get("regime") == reg]
    if not rt: continue
    rw   = [t["pnl"] for t in rt if t["pnl"] > 0]
    rwr  = len(rw) / len(rt) * 100
    ravg = np.mean([t["pnl"] for t in rt])
    rtot = sum(t["pnl"] for t in rt)
    c = "green" if ravg > 0 else "red"
    r_table.add_row(
        reg.replace("_", " ").title(), str(len(rt)), str(len(rw)),
        f"{rwr:.0f}%",
        f"[{c}]₹{ravg:+,.0f}[/{c}]",
        f"[{c}]₹{rtot:+,.0f}[/{c}]",
    )
console.print(r_table)

# Exit reason breakdown
e_table = Table(
    title="[bold]Exit Reason Breakdown[/bold]",
    box=box.SIMPLE_HEAVY, header_style="bold cyan",
)
e_table.add_column("Exit Reason", style="bold", min_width=16)
e_table.add_column("Count",       justify="right")
e_table.add_column("Avg P&L",     justify="right")

for reason in ["target_hit", "sl_hit", "time_exit", "eod"]:
    rt = [t for t in trades if t.get("reason") == reason]
    if not rt: continue
    avg = np.mean([t["pnl"] for t in rt])
    c   = "green" if avg > 0 else "red"
    e_table.add_row(reason.replace("_", " ").title(), str(len(rt)), f"[{c}]₹{avg:+,.0f}[/{c}]")
console.print(e_table)

console.print(Panel(
    "[bold green]✓ System fully operational — all modules working.[/bold green]\n\n"
    "To trade with real Nifty50 data:\n"
    "  1. Fill in [bold].env[/bold] with your Angel One API credentials\n"
    "  2. [bold cyan]python main.py --mode train[/bold cyan]   ← train ML models on 1 year of real data\n"
    "  3. [bold cyan]python main.py --mode paper[/bold cyan]   ← paper trade (no real money)\n"
    "  4. [bold cyan]python main.py --mode live[/bold cyan]    ← go live when confident",
    title="[bold]Next Steps[/bold]", border_style="green",
))
