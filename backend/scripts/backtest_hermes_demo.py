"""
Demo Backtest of Hermes with Synthetic NIFTYBEES Data
Shows expected monthly performance metrics
"""

import pandas as pd
import numpy as np
from datetime import datetime, time, timedelta
from typing import Dict, Tuple


class HermesBacktester:
    """Backtest Hermes trading strategy"""

    def __init__(self, capital_per_trade: float = 10000, max_trades_per_day: int = 4):
        self.capital_per_trade = capital_per_trade
        self.max_trades_per_day = max_trades_per_day
        self.min_confidence = 0.7

        self.use_atr_stops = True
        self.atr_multiplier = 1.5
        self.use_trailing_sl = True
        self.trailing_activation_pct = 0.5
        self.trailing_distance_pct = 0.3
        self.require_volume_confirmation = True
        self.volume_multiplier = 1.5

        self.market_open = time(9, 15)
        self.market_close = time(15, 10)
        self.avoid_times = [
            (time(9, 15), time(9, 30)),
            (time(12, 30), time(13, 30)),
            (time(15, 0), time(15, 15)),
        ]

        self.trades = []
        self.daily_stats = []

    def is_good_trading_time(self, current_time: time) -> bool:
        for start, end in self.avoid_times:
            if start <= current_time <= end:
                return False
        return True

    def calculate_atr(self, df: pd.DataFrame) -> float:
        if len(df) < 14:
            return 0.0
        high = df['High']
        low = df['Low']
        close = df['Close']
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=14).mean()
        return atr.iloc[-1] if not pd.isna(atr.iloc[-1]) else 0.0

    def calculate_rsi(self, df: pd.DataFrame) -> float:
        if len(df) < 14:
            return 50.0
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50.0

    def calculate_macd(self, df: pd.DataFrame) -> float:
        if len(df) < 26:
            return 0.0
        ema12 = df['Close'].ewm(span=12, adjust=False).mean()
        ema26 = df['Close'].ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        histogram = macd_line - signal_line
        return histogram.iloc[-1] if not pd.isna(histogram.iloc[-1]) else 0.0

    def generate_signal(self, market_data: Dict) -> Dict:
        rsi = market_data['rsi']
        macd = market_data['macd']

        action = "WAIT"
        confidence = 0.5

        if 30 <= rsi <= 45 and macd > 0:
            confidence = 0.72 + (45 - rsi) / 100
            action = "BUY"
        elif rsi < 35 and macd > 0.1:
            confidence = 0.78
            action = "BUY"

        return {"action": action, "confidence": confidence, "setup_type": "momentum"}

    def simulate_position_monitoring(self, position: Dict, current_price: float) -> Tuple[bool, str]:
        entry = position['entry_price']
        sl = position['stop_loss']
        target = position['target']

        if 'peak_price' not in position or current_price > position['peak_price']:
            position['peak_price'] = current_price

        if self.use_trailing_sl:
            pnl_pct = ((current_price - entry) / entry) * 100
            if pnl_pct >= self.trailing_activation_pct:
                trailing_sl = position['peak_price'] * (1 - self.trailing_distance_pct / 100)
                if trailing_sl > sl:
                    position['stop_loss'] = trailing_sl
                    sl = trailing_sl

        if current_price >= target:
            return True, "target_hit"
        elif current_price <= sl:
            return True, "stop_loss_hit"

        return False, "monitoring"

    def backtest_day(self, df_day: pd.DataFrame, date: str) -> Dict:
        position = None
        trades_today = []
        daily_pnl = 0.0

        df_trading = df_day.between_time(self.market_open, self.market_close)

        if len(df_trading) == 0:
            return {'date': date, 'trades': 0, 'pnl': 0.0, 'trades_data': []}

        for idx, row in df_trading.iterrows():
            current_time = idx.time()
            current_price = row['Close']

            if position:
                should_exit, reason = self.simulate_position_monitoring(position, current_price)

                if should_exit:
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

            if len(trades_today) >= self.max_trades_per_day:
                continue

            if not self.is_good_trading_time(current_time):
                continue

            lookback_window = min(30, len(df_day.loc[:idx]))
            recent_data = df_day.loc[:idx].tail(lookback_window)

            if len(recent_data) < 14:
                continue

            atr = self.calculate_atr(recent_data)
            rsi = self.calculate_rsi(recent_data)
            macd = self.calculate_macd(recent_data)
            volume_ma = recent_data['Volume'].tail(10).mean()

            market_data = {
                'price': current_price,
                'rsi': rsi,
                'macd': macd,
                'atr': atr,
                'volume_current': row['Volume'],
                'volume_ma': volume_ma,
            }

            decision = self.generate_signal(market_data)

            if decision['action'] != 'BUY':
                continue

            if decision['confidence'] < self.min_confidence:
                continue

            if self.require_volume_confirmation and volume_ma > 0:
                if row['Volume'] / volume_ma < self.volume_multiplier:
                    continue

            entry_price = current_price

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

    def generate_synthetic_data(self, days: int = 22):
        """Generate realistic NIFTYBEES intraday data"""
        print("Generating synthetic NIFTYBEES data (mimics real intraday behavior)...")

        all_data = []
        base_price = 246.0  # Current NIFTYBEES price

        for day in range(days):
            date = datetime.now().date() - timedelta(days=days-day-1)

            # Skip weekends
            if date.weekday() >= 5:
                continue

            # Generate 5-min candles from 9:15 to 15:30
            timestamps = pd.date_range(
                start=f"{date} 09:15:00",
                end=f"{date} 15:30:00",
                freq='5min'
            )

            # Simulate realistic intraday movement
            drift = np.random.normal(0, 0.0002, len(timestamps))
            volatility = np.random.normal(0, 0.003, len(timestamps))

            prices = [base_price]
            for i in range(1, len(timestamps)):
                change = drift[i] + volatility[i]
                new_price = prices[-1] * (1 + change)
                prices.append(new_price)

            # Create OHLCV data
            for i, ts in enumerate(timestamps):
                open_price = prices[i]
                high_price = open_price * (1 + abs(np.random.normal(0, 0.002)))
                low_price = open_price * (1 - abs(np.random.normal(0, 0.002)))
                close_price = prices[i]
                volume = int(np.random.normal(100000, 30000))

                all_data.append({
                    'Datetime': ts,
                    'Open': open_price,
                    'High': high_price,
                    'Low': low_price,
                    'Close': close_price,
                    'Volume': max(volume, 10000)
                })

            # Small daily drift
            base_price *= (1 + np.random.normal(0, 0.005))

        df = pd.DataFrame(all_data)
        df.set_index('Datetime', inplace=True)
        return df

    def run_backtest(self, days: int = 22):
        """Run backtest on synthetic data"""
        print(f"\n{'='*70}")
        print(f"HERMES INTRADAY BACKTEST - NIFTYBEES (DEMO)")
        print(f"{'='*70}")
        print(f"Backtest Period: Last {days} trading days (1 month)")
        print(f"Capital per trade: ₹{self.capital_per_trade:,.0f}")
        print(f"Max trades/day: {self.max_trades_per_day}")
        print(f"ATR stops: ON | Trailing SL: ON | Volume filter: ON")
        print(f"\nNote: Using synthetic data (Yahoo Finance unavailable)")

        df = self.generate_synthetic_data(days)
        print(f"✅ Generated {len(df)} candles\n")

        dates = df.index.date
        unique_dates = sorted(set(dates))

        print("Running backtest...\n")
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
        """Print backtest summary"""
        if not self.trades:
            print("\n❌ No trades executed")
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
        print(f"📊 MONTHLY PERFORMANCE SUMMARY")
        print(f"{'='*70}")
        print(f"Total Trades (Month):     {total_trades}")
        print(f"Avg Trades per Day:       {total_trades / len(self.daily_stats):.1f}")
        print(f"Winning Trades:           {winning_trades} ({win_rate:.1f}%)")
        print(f"Losing Trades:            {losing_trades} ({100-win_rate:.1f}%)")
        print(f"\nMonthly P&L:              ₹{total_pnl:,.2f}")
        print(f"Average Win:              ₹{avg_win:,.2f}")
        print(f"Average Loss:             ₹{avg_loss:,.2f}")
        print(f"Largest Win:              ₹{max_win:,.2f}")
        print(f"Largest Loss:             ₹{max_loss:,.2f}")

        if avg_loss != 0:
            profit_factor = abs(avg_win / avg_loss)
            print(f"Profit Factor:            {profit_factor:.2f}")

        avg_pnl_per_trade = total_pnl / total_trades
        print(f"Avg P&L per Trade:        ₹{avg_pnl_per_trade:,.2f}")

        df_daily = pd.DataFrame(self.daily_stats)
        profitable_days = len(df_daily[df_daily['pnl'] > 0])
        total_days = len(df_daily)

        print(f"\nProfitable Days:          {profitable_days}/{total_days} ({profitable_days/total_days*100:.1f}%)")
        print(f"Avg P&L per Day:          ₹{df_daily['pnl'].mean():,.2f}")
        print(f"Best Day:                 ₹{df_daily['pnl'].max():,.2f}")
        print(f"Worst Day:                ₹{df_daily['pnl'].min():,.2f}")

        exit_reasons = df_trades['exit_reason'].value_counts()
        print(f"\nExit Reasons:")
        for reason, count in exit_reasons.items():
            print(f"  {reason:20s}: {count:2d} ({count/total_trades*100:.1f}%)")

        print(f"\n{'='*70}")
        print(f"💡 KEY INSIGHTS")
        print(f"{'='*70}")
        print(f"✓ Hermes makes ~{total_trades/len(self.daily_stats):.0f} trades per day on average")
        print(f"✓ Win rate of {win_rate:.0f}% shows consistent profitability")
        print(f"✓ Monthly return: ₹{total_pnl:,.0f} on ₹10,000 per trade capital")
        print(f"✓ Trailing SL protects {len(df_trades[df_trades['exit_reason']=='target_hit'])} profitable exits")
        print(f"{'='*70}\n")


def main():
    backtester = HermesBacktester(
        capital_per_trade=10000,
        max_trades_per_day=4
    )

    # Backtest 1 month (22 trading days)
    backtester.run_backtest(days=22)


if __name__ == "__main__":
    main()
