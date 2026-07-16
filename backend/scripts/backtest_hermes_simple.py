"""
Backtest Hermes Intraday Trading Strategy on Historical NIFTYBEES Data
Standalone version - no external dependencies beyond pandas/numpy/yfinance
"""

import pandas as pd
import numpy as np
from datetime import datetime, time, timedelta
import yfinance as yf
from typing import Dict, List, Tuple


class HermesBacktester:
    """Backtest Hermes trading strategy"""

    def __init__(self, capital_per_trade: float = 10000, max_trades_per_day: int = 4):
        self.capital_per_trade = capital_per_trade
        self.max_trades_per_day = max_trades_per_day
        self.min_confidence = 0.7

        # Enhanced features
        self.use_atr_stops = True
        self.atr_multiplier = 1.5
        self.use_trailing_sl = True
        self.trailing_activation_pct = 0.5
        self.trailing_distance_pct = 0.3
        self.require_volume_confirmation = True
        self.volume_multiplier = 1.5

        # Trading hours
        self.market_open = time(9, 15)
        self.market_close = time(15, 10)
        self.avoid_times = [
            (time(9, 15), time(9, 30)),   # Opening volatility
            (time(12, 30), time(13, 30)), # Lunch lull
            (time(15, 0), time(15, 15)),  # Closing chaos
        ]

        # Results
        self.trades = []
        self.daily_stats = []

    def is_good_trading_time(self, current_time: time) -> bool:
        """Check if current time is good for trading"""
        for start, end in self.avoid_times:
            if start <= current_time <= end:
                return False
        return True

    def calculate_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        """Calculate Average True Range"""
        if len(df) < period:
            return 0.0

        high = df['High']
        low = df['Low']
        close = df['Close']

        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())

        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()

        return atr.iloc[-1] if len(atr) > 0 and not pd.isna(atr.iloc[-1]) else 0.0

    def calculate_rsi(self, df: pd.DataFrame, period: int = 14) -> float:
        """Calculate RSI"""
        if len(df) < period:
            return 50.0

        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi.iloc[-1] if len(rsi) > 0 and not pd.isna(rsi.iloc[-1]) else 50.0

    def calculate_macd(self, df: pd.DataFrame) -> float:
        """Calculate MACD histogram"""
        if len(df) < 26:
            return 0.0

        ema12 = df['Close'].ewm(span=12, adjust=False).mean()
        ema26 = df['Close'].ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        histogram = macd_line - signal_line
        return histogram.iloc[-1] if len(histogram) > 0 and not pd.isna(histogram.iloc[-1]) else 0.0

    def check_volume_confirmation(self, current_vol: float, avg_vol: float) -> bool:
        """Check if volume supports the signal"""
        if not self.require_volume_confirmation or avg_vol == 0:
            return True
        volume_ratio = current_vol / avg_vol
        return volume_ratio >= self.volume_multiplier

    def generate_signal(self, market_data: Dict) -> Dict:
        """Generate trading signal based on momentum strategy"""
        rsi = market_data['rsi']
        macd = market_data['macd']
        atr = market_data.get('atr', 0)

        action = "WAIT"
        confidence = 0.5

        # Bullish momentum: RSI oversold + positive MACD
        if 30 <= rsi <= 45 and macd > 0:
            confidence = 0.72 + (45 - rsi) / 100  # Higher confidence when more oversold
            action = "BUY"
        # Strong bullish: Very oversold + strong MACD
        elif rsi < 35 and macd > 0.1:
            confidence = 0.78
            action = "BUY"

        return {
            "action": action,
            "confidence": confidence,
            "setup_type": "momentum_rsi_macd"
        }

    def simulate_position_monitoring(self, position: Dict, current_price: float) -> Tuple[bool, str]:
        """Monitor position for exit conditions"""
        entry = position['entry_price']
        sl = position['stop_loss']
        target = position['target']

        # Update peak price for trailing SL
        if 'peak_price' not in position or current_price > position['peak_price']:
            position['peak_price'] = current_price

        # Trailing stop loss
        if self.use_trailing_sl:
            pnl_pct = ((current_price - entry) / entry) * 100
            if pnl_pct >= self.trailing_activation_pct:
                trailing_sl = position['peak_price'] * (1 - self.trailing_distance_pct / 100)
                if trailing_sl > sl:
                    position['stop_loss'] = trailing_sl
                    sl = trailing_sl

        # Check exit conditions
        if current_price >= target:
            return True, "target_hit"
        elif current_price <= sl:
            return True, "stop_loss_hit"

        return False, "monitoring"

    def backtest_day(self, df_day: pd.DataFrame, date: str) -> Dict:
        """Backtest a single trading day"""
        position = None
        trades_today = []
        daily_pnl = 0.0

        # Filter to trading hours
        df_trading = df_day.between_time(self.market_open, self.market_close)

        if len(df_trading) == 0:
            return {'date': date, 'trades': 0, 'pnl': 0.0, 'trades_data': []}

        for idx, row in df_trading.iterrows():
            current_time = idx.time()
            current_price = row['Close']

            # Monitor existing position
            if position:
                should_exit, reason = self.simulate_position_monitoring(position, current_price)

                if should_exit:
                    # Exit position
                    exit_price = current_price
                    qty = position['qty']
                    pnl = (exit_price - position['entry_price']) * qty

                    trade = {
                        **position,
                        'exit_price': exit_price,
                        'exit_time': idx,
                        'pnl': pnl,
                        'pnl_pct': (pnl / (position['entry_price'] * qty)) * 100,
                        'exit_reason': reason
                    }
                    trades_today.append(trade)
                    daily_pnl += pnl
                    position = None
                continue

            # Check if we can enter new position
            if len(trades_today) >= self.max_trades_per_day:
                continue

            if not self.is_good_trading_time(current_time):
                continue

            # Get recent data for indicators
            lookback_window = min(30, len(df_day.loc[:idx]))
            recent_data = df_day.loc[:idx].tail(lookback_window)

            if len(recent_data) < 14:
                continue

            # Calculate indicators
            atr = self.calculate_atr(recent_data)
            rsi = self.calculate_rsi(recent_data)
            macd = self.calculate_macd(recent_data)
            volume_ma = recent_data['Volume'].tail(10).mean() if len(recent_data) >= 10 else recent_data['Volume'].mean()

            # Prepare market data
            market_data = {
                'price': current_price,
                'rsi': rsi,
                'macd': macd,
                'atr': atr,
                'volume_current': row['Volume'],
                'volume_ma': volume_ma,
            }

            # Get trading signal
            decision = self.generate_signal(market_data)

            if decision['action'] != 'BUY':
                continue

            # Check filters
            if decision['confidence'] < self.min_confidence:
                continue

            if not self.check_volume_confirmation(row['Volume'], volume_ma):
                continue

            # Enter position
            entry_price = current_price

            # ATR-based stop loss
            if self.use_atr_stops and atr > 0:
                stop_loss = entry_price - (self.atr_multiplier * atr)
                target = entry_price + (2 * self.atr_multiplier * atr)
                risk_per_share = self.atr_multiplier * atr
                qty = int(self.capital_per_trade / risk_per_share) if risk_per_share > 0 else int(self.capital_per_trade / entry_price)
            else:
                stop_loss = entry_price * 0.994
                target = entry_price * 1.009
                qty = int(self.capital_per_trade / entry_price)

            if qty == 0:
                continue

            position = {
                'entry_price': entry_price,
                'entry_time': idx,
                'qty': qty,
                'stop_loss': stop_loss,
                'target': target,
                'peak_price': entry_price,
                'setup_type': decision['setup_type'],
                'confidence': decision['confidence']
            }

        # Force exit at market close
        if position:
            exit_price = df_trading.iloc[-1]['Close']
            qty = position['qty']
            pnl = (exit_price - position['entry_price']) * qty

            trade = {
                **position,
                'exit_price': exit_price,
                'exit_time': df_trading.index[-1],
                'pnl': pnl,
                'pnl_pct': (pnl / (position['entry_price'] * qty)) * 100,
                'exit_reason': 'market_close'
            }
            trades_today.append(trade)
            daily_pnl += pnl

        return {
            'date': date,
            'trades': len(trades_today),
            'pnl': daily_pnl,
            'trades_data': trades_today
        }

    def run_backtest(self, start_date: str, end_date: str):
        """Run full backtest"""
        print(f"\n{'='*70}")
        print(f"HERMES INTRADAY BACKTEST - NIFTYBEES")
        print(f"{'='*70}")
        print(f"Period: {start_date} to {end_date}")
        print(f"Capital per trade: ₹{self.capital_per_trade:,.0f}")
        print(f"Max trades/day: {self.max_trades_per_day}")
        print(f"ATR stops: {'ON' if self.use_atr_stops else 'OFF'}")
        print(f"Trailing SL: {'ON' if self.use_trailing_sl else 'OFF'}")
        print(f"Volume filter: {'ON' if self.require_volume_confirmation else 'OFF'}")
        print(f"\nFetching data from Yahoo Finance...")

        # Fetch data
        try:
            df = yf.download('NIFTYBEES.NS', start=start_date, end=end_date, interval='5m', progress=False)
        except Exception as e:
            print(f"❌ Error fetching data: {e}")
            return

        if df.empty:
            print("❌ No data found. Trying alternative ticker...")
            try:
                df = yf.download('NIFTYBEES.BO', start=start_date, end=end_date, interval='5m', progress=False)
            except:
                print("❌ Failed to fetch data. Check internet connection.")
                return

        if df.empty:
            print("❌ No data available for the selected period.")
            return

        print(f"✅ Loaded {len(df)} candles")
        print(f"\nRunning backtest...\n")

        # Group by date
        df.index = pd.to_datetime(df.index)
        dates = df.index.date
        unique_dates = sorted(set(dates))

        for date in unique_dates:
            df_day = df[df.index.date == date]
            result = self.backtest_day(df_day, str(date))

            if result['trades'] > 0:
                self.daily_stats.append(result)
                self.trades.extend(result['trades_data'])

                pnl_color = '🟢' if result['pnl'] > 0 else '🔴'
                print(f"{pnl_color} {date} | Trades: {result['trades']} | P&L: ₹{result['pnl']:>8.2f}")

        self.print_results()

    def print_results(self):
        """Print backtest results"""
        if not self.trades:
            print("\n❌ No trades executed during backtest period")
            print("Note: Yahoo Finance 5-min data may be limited for recent dates")
            return

        df_trades = pd.DataFrame(self.trades)

        total_pnl = df_trades['pnl'].sum()
        total_trades = len(df_trades)
        winning_trades = len(df_trades[df_trades['pnl'] > 0])
        losing_trades = len(df_trades[df_trades['pnl'] < 0])
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0

        avg_win = df_trades[df_trades['pnl'] > 0]['pnl'].mean() if winning_trades > 0 else 0
        avg_loss = df_trades[df_trades['pnl'] < 0]['pnl'].mean() if losing_trades > 0 else 0

        max_win = df_trades['pnl'].max()
        max_loss = df_trades['pnl'].min()

        print(f"\n{'='*70}")
        print(f"BACKTEST RESULTS")
        print(f"{'='*70}")
        print(f"Total Trades:        {total_trades}")
        print(f"Winning Trades:      {winning_trades} ({win_rate:.1f}%)")
        print(f"Losing Trades:       {losing_trades} ({100-win_rate:.1f}%)")
        print(f"\nTotal P&L:           ₹{total_pnl:,.2f}")
        print(f"Average Win:         ₹{avg_win:,.2f}")
        print(f"Average Loss:        ₹{avg_loss:,.2f}")
        print(f"Largest Win:         ₹{max_win:,.2f}")
        print(f"Largest Loss:        ₹{max_loss:,.2f}")

        if avg_loss != 0:
            profit_factor = abs(avg_win / avg_loss)
            print(f"Profit Factor:       {profit_factor:.2f}")

        # Risk-reward
        if total_trades > 0:
            avg_pnl_per_trade = total_pnl / total_trades
            print(f"Avg P&L per Trade:   ₹{avg_pnl_per_trade:,.2f}")

        # Daily stats
        df_daily = pd.DataFrame(self.daily_stats)
        profitable_days = len(df_daily[df_daily['pnl'] > 0])
        total_days = len(df_daily)

        print(f"\nProfitable Days:     {profitable_days}/{total_days} ({profitable_days/total_days*100:.1f}%)")
        print(f"Avg P&L per Day:     ₹{df_daily['pnl'].mean():,.2f}")
        print(f"Best Day:            ₹{df_daily['pnl'].max():,.2f}")
        print(f"Worst Day:           ₹{df_daily['pnl'].min():,.2f}")

        # Exit reason breakdown
        exit_reasons = df_trades['exit_reason'].value_counts()
        print(f"\nExit Reasons:")
        for reason, count in exit_reasons.items():
            print(f"  {reason:20s}: {count} ({count/total_trades*100:.1f}%)")

        print(f"\n{'='*70}")

        # Top 5 trades
        if len(df_trades) >= 5:
            print("\n📈 TOP 5 WINNING TRADES:")
            top_trades = df_trades.nlargest(5, 'pnl')[['entry_time', 'entry_price', 'exit_price', 'pnl', 'exit_reason']]
            for idx, trade in top_trades.iterrows():
                print(f"  {trade['entry_time'].strftime('%Y-%m-%d %H:%M')} | "
                      f"₹{trade['entry_price']:.2f} → ₹{trade['exit_price']:.2f} | "
                      f"P&L: ₹{trade['pnl']:.2f} | {trade['exit_reason']}")

            print("\n📉 TOP 5 LOSING TRADES:")
            worst_trades = df_trades.nsmallest(5, 'pnl')[['entry_time', 'entry_price', 'exit_price', 'pnl', 'exit_reason']]
            for idx, trade in worst_trades.iterrows():
                print(f"  {trade['entry_time'].strftime('%Y-%m-%d %H:%M')} | "
                      f"₹{trade['entry_price']:.2f} → ₹{trade['exit_price']:.2f} | "
                      f"P&L: ₹{trade['pnl']:.2f} | {trade['exit_reason']}")


def main():
    """Run backtest"""
    backtester = HermesBacktester(
        capital_per_trade=10000,
        max_trades_per_day=4
    )

    # Backtest last 1 month
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')

    backtester.run_backtest(start_date, end_date)


if __name__ == "__main__":
    main()
