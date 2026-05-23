"""
Historical backtesting engine for all strategies.
Simulates intraday options trading on historical Nifty50 data.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass, field
from loguru import logger
import pytz

IST = pytz.timezone("Asia/Kolkata")


@dataclass
class BacktestTrade:
    date: str
    entry_time: datetime
    exit_time: Optional[datetime]
    strategy: str
    action: str          # BUY_CE, BUY_PE, etc.
    strike: int
    option_type: str
    expiry: str
    entry_price: float
    exit_price: float
    qty: int
    pnl: float
    pnl_pct: float
    exit_reason: str
    regime: str
    signal_confidence: float


@dataclass
class BacktestResult:
    trades: list = field(default_factory=list)
    total_pnl: float = 0.0
    win_rate: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    profit_factor: float = 0.0
    avg_trade_pnl: float = 0.0
    best_trade: float = 0.0
    worst_trade: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    calmar_ratio: float = 0.0
    daily_returns: list = field(default_factory=list)


class Backtester:
    """
    Event-driven backtester for intraday Nifty50 options strategies.

    Usage:
        backtester = Backtester(config, historical_df, signal_generator)
        result = backtester.run(start_date='2024-01-01', end_date='2024-12-31')
        backtester.print_report(result)
    """

    def __init__(self, config: dict, signal_generator, regime_classifier=None):
        self.config = config
        self.signal_generator = signal_generator
        self.regime_classifier = regime_classifier
        self.capital = config["risk"]["total_capital"]
        self.daily_loss_limit = self.capital * config["risk"]["daily_loss_limit_pct"]
        self.lot_size = config["trading"]["lot_size"]
        self.sl_pct = config["risk"]["option_buy_sl_pct"]
        self.target_pct = config["risk"]["option_buy_target_pct"]
        self.no_new_trades_after = config["trading"]["no_new_trades_after"]
        self.square_off_time = config["trading"]["square_off_time"]

    def _simulate_option_price(
        self, spot: float, strike: int, option_type: str, days_to_expiry: float, iv: float = 0.15
    ) -> float:
        """Black-Scholes approximation for option premium."""
        from scipy.stats import norm
        import math

        S, K, T, r, sigma = spot, strike, max(days_to_expiry / 252, 1e-6), 0.065, iv
        d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        if option_type == "CE":
            price = S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
        else:
            price = K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
        return max(price, 0.05)

    def _get_trading_days(self, df: pd.DataFrame) -> list:
        df.index = pd.to_datetime(df.index)
        return sorted(df.index.normalize().unique().tolist())

    def _get_day_data(self, df: pd.DataFrame, date: pd.Timestamp) -> pd.DataFrame:
        day_str = date.strftime("%Y-%m-%d")
        return df[df.index.strftime("%Y-%m-%d") == day_str].copy()

    def run(self, df: pd.DataFrame, start_date: str = None, end_date: str = None) -> BacktestResult:
        """
        Run backtest on OHLCV DataFrame with DatetimeIndex.
        df must have columns: open, high, low, close, volume
        Returns BacktestResult with all metrics.
        """
        result = BacktestResult()
        df = df.copy()
        df.index = pd.to_datetime(df.index)

        if start_date:
            df = df[df.index >= start_date]
        if end_date:
            df = df[df.index <= end_date]

        trading_days = self._get_trading_days(df)
        logger.info(f"Backtesting over {len(trading_days)} trading days")

        equity_curve = [self.capital]
        current_capital = self.capital

        for day in trading_days:
            day_df = self._get_day_data(df, day)
            if len(day_df) < 10:
                continue

            day_trades, day_pnl = self._simulate_day(day_df, day)
            result.trades.extend(day_trades)
            current_capital += day_pnl
            equity_curve.append(current_capital)
            result.daily_returns.append(day_pnl / self.capital)

        result = self._compute_metrics(result, equity_curve)
        return result

    def _simulate_day(self, day_df: pd.DataFrame, date) -> tuple[list, float]:
        """Simulate one trading day. Returns (trades, day_pnl)."""
        from features.technical_indicators import TechnicalFeatureEngine
        from features.market_regime import MarketRegimeDetector

        trades = []
        day_pnl = 0.0
        open_position = None

        feature_engine = TechnicalFeatureEngine()
        regime_detector = MarketRegimeDetector()

        # Build features on the day's data
        feat_df = feature_engine.compute_all(day_df)
        feat_df = feat_df.dropna()
        if len(feat_df) < 5:
            return trades, day_pnl

        # Walk forward through candles
        for i in range(20, len(feat_df)):
            candle = feat_df.iloc[i]
            candle_time = feat_df.index[i]
            candle_time_str = candle_time.strftime("%H:%M")
            spot = candle["close"]

            # Check square-off time
            if candle_time_str >= self.square_off_time and open_position:
                exit_price = self._simulate_option_price(
                    spot, open_position["strike"], open_position["option_type"],
                    open_position["dte"], 0.15
                )
                pnl = self._calc_pnl(open_position, exit_price)
                day_pnl += pnl
                trades.append(self._make_trade(open_position, exit_price, pnl, "square_off_time", candle_time))
                open_position = None
                continue

            # Manage open position
            if open_position:
                current_premium = self._simulate_option_price(
                    spot, open_position["strike"], open_position["option_type"],
                    open_position["dte"], 0.15
                )
                entry_p = open_position["entry_price"]
                sl = entry_p * (1 - self.sl_pct)
                target = entry_p * (1 + self.target_pct)

                if current_premium <= sl:
                    pnl = self._calc_pnl(open_position, current_premium)
                    day_pnl += pnl
                    trades.append(self._make_trade(open_position, current_premium, pnl, "sl_hit", candle_time))
                    open_position = None
                    continue
                elif current_premium >= target:
                    pnl = self._calc_pnl(open_position, current_premium)
                    day_pnl += pnl
                    trades.append(self._make_trade(open_position, current_premium, pnl, "target_hit", candle_time))
                    open_position = None
                    continue

            # No new trades after cutoff
            if candle_time_str >= self.no_new_trades_after:
                continue

            # Check daily loss limit
            if day_pnl <= -self.daily_loss_limit:
                break

            # Don't stack positions in backtest (1 at a time)
            if open_position:
                continue

            # Generate signal using rule-based regime + indicators
            window = feat_df.iloc[max(0, i - 29): i + 1]
            regime = regime_detector.detect_regime_rules(window)
            signal = self._generate_backtest_signal(window, regime, spot)

            if signal["action"] == "NO_TRADE":
                continue

            # Open position
            strike = signal["strike"]
            opt_type = signal["option_type"]
            dte = signal.get("dte", 7)
            entry_price = self._simulate_option_price(spot, strike, opt_type, dte, 0.15)
            qty = self.lot_size

            open_position = {
                "entry_time": candle_time,
                "entry_price": entry_price,
                "strike": strike,
                "option_type": opt_type,
                "qty": qty,
                "dte": dte,
                "regime": regime,
                "action": signal["action"],
                "strategy": signal["strategy"],
            }

        # Close any leftover position at end of day
        if open_position and len(feat_df) > 0:
            last_spot = feat_df["close"].iloc[-1]
            exit_price = self._simulate_option_price(
                last_spot, open_position["strike"], open_position["option_type"], 0.5, 0.15
            )
            pnl = self._calc_pnl(open_position, exit_price)
            day_pnl += pnl
            trades.append(self._make_trade(open_position, exit_price, pnl, "eod", feat_df.index[-1]))

        return trades, day_pnl

    def _generate_backtest_signal(self, df: pd.DataFrame, regime: str, spot: float) -> dict:
        """Simple rule-based signal generation for backtesting."""
        no_trade = {"action": "NO_TRADE"}
        if len(df) < 5:
            return no_trade

        latest = df.iloc[-1]
        strike_interval = 50
        atm = round(spot / strike_interval) * strike_interval
        dte = 7

        ema9 = latest.get("ema_9", 0)
        ema21 = latest.get("ema_21", 0)
        rsi = latest.get("rsi", 50)
        macd_hist = latest.get("macd_histogram", 0)
        adx = latest.get("adx", 0)

        if adx < 18:
            return no_trade

        if regime == "trending_up" and ema9 > ema21 and rsi > 50 and macd_hist > 0:
            return {"action": "BUY_CE", "option_type": "CE", "strike": atm, "dte": dte, "strategy": "trend"}
        elif regime == "trending_down" and ema9 < ema21 and rsi < 50 and macd_hist < 0:
            return {"action": "BUY_PE", "option_type": "PE", "strike": atm, "dte": dte, "strategy": "trend"}

        return no_trade

    def _calc_pnl(self, position: dict, exit_price: float) -> float:
        entry = position["entry_price"]
        qty = position["qty"]
        return (exit_price - entry) * qty

    def _make_trade(self, position: dict, exit_price: float, pnl: float, reason: str, exit_time) -> BacktestTrade:
        entry = position["entry_price"]
        return BacktestTrade(
            date=position["entry_time"].strftime("%Y-%m-%d"),
            entry_time=position["entry_time"],
            exit_time=exit_time,
            strategy=position.get("strategy", "unknown"),
            action=position.get("action", ""),
            strike=position["strike"],
            option_type=position["option_type"],
            expiry="",
            entry_price=entry,
            exit_price=exit_price,
            qty=position["qty"],
            pnl=pnl,
            pnl_pct=(exit_price - entry) / entry * 100,
            exit_reason=reason,
            regime=position.get("regime", "unknown"),
            signal_confidence=0.0,
        )

    def _compute_metrics(self, result: BacktestResult, equity_curve: list) -> BacktestResult:
        if not result.trades:
            return result

        pnls = [t.pnl for t in result.trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        result.total_trades = len(pnls)
        result.winning_trades = len(wins)
        result.losing_trades = len(losses)
        result.total_pnl = sum(pnls)
        result.win_rate = len(wins) / len(pnls) * 100 if pnls else 0
        result.avg_trade_pnl = np.mean(pnls) if pnls else 0
        result.best_trade = max(pnls) if pnls else 0
        result.worst_trade = min(pnls) if pnls else 0
        result.avg_win = np.mean(wins) if wins else 0
        result.avg_loss = np.mean(losses) if losses else 0

        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        result.profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # Max drawdown
        eq = np.array(equity_curve)
        peak = np.maximum.accumulate(eq)
        drawdown = (eq - peak) / peak
        result.max_drawdown = abs(drawdown.min()) * 100

        # Sharpe ratio (annualized, assuming 252 trading days)
        daily_ret = np.array(result.daily_returns)
        if daily_ret.std() > 0:
            result.sharpe_ratio = (daily_ret.mean() / daily_ret.std()) * np.sqrt(252)

        # Calmar ratio
        if result.max_drawdown > 0:
            annual_return = (result.total_pnl / self.capital) * (252 / max(len(result.daily_returns), 1)) * 100
            result.calmar_ratio = annual_return / result.max_drawdown

        return result

    def print_report(self, result: BacktestResult):
        from rich.console import Console
        from rich.table import Table
        from rich import box

        con = Console()
        con.print("\n[bold blue]═══ BACKTEST REPORT ═══[/bold blue]")

        t = Table(box=box.SIMPLE_HEAVY)
        t.add_column("Metric", style="cyan")
        t.add_column("Value", style="white")
        t.add_row("Total P&L", f"₹{result.total_pnl:+,.0f}")
        t.add_row("Total Trades", str(result.total_trades))
        t.add_row("Win Rate", f"{result.win_rate:.1f}%")
        t.add_row("Profit Factor", f"{result.profit_factor:.2f}")
        t.add_row("Sharpe Ratio", f"{result.sharpe_ratio:.2f}")
        t.add_row("Calmar Ratio", f"{result.calmar_ratio:.2f}")
        t.add_row("Max Drawdown", f"{result.max_drawdown:.2f}%")
        t.add_row("Avg Trade P&L", f"₹{result.avg_trade_pnl:,.0f}")
        t.add_row("Best Trade", f"₹{result.best_trade:,.0f}")
        t.add_row("Worst Trade", f"₹{result.worst_trade:,.0f}")
        t.add_row("Avg Win", f"₹{result.avg_win:,.0f}")
        t.add_row("Avg Loss", f"₹{result.avg_loss:,.0f}")
        con.print(t)

    def to_dataframe(self, result: BacktestResult) -> pd.DataFrame:
        return pd.DataFrame([vars(t) for t in result.trades])
