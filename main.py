"""
Nifty50 AI Intraday Options Trading System
Entry point: coordinates data, ML, strategies, execution, and monitoring.

Usage:
    python main.py --mode live          # Live trading
    python main.py --mode paper         # Paper trading (no real orders)
    python main.py --mode backtest      # Run backtest
    python main.py --mode train         # Train/retrain ML models
    python main.py --mode dashboard     # Watch-only dashboard
"""

import argparse
import sys
import time
import threading
from datetime import datetime, timedelta
from pathlib import Path

import pytz
from loguru import logger

# ── project imports (populated by sub-agents) ─────────────────────────────────
from config import load_config
from data.angel_client import AngelOneClient
from data.live_feed import LiveFeed
from data.options_chain import OptionsChainAnalyzer
from features.technical_indicators import TechnicalFeatureEngine
from features.market_regime import MarketRegimeDetector, MarketRegimeClassifier
from models.price_predictor import PriceDirectionPredictor
from models.signal_generator import SignalGenerator
from models.model_trainer import ModelTrainer
from strategies.trend_strategy import TrendFollowingStrategy
from strategies.premium_strategy import PremiumSellingStrategy
from strategies.scalping_strategy import ScalpingStrategy
from execution.risk_manager import RiskManager
from execution.order_manager import OrderManager
from execution.position_manager import PositionManager
from monitoring.dashboard import TradingDashboard
from monitoring.alerts import AlertManager
from backtesting.backtester import Backtester


IST = pytz.timezone("Asia/Kolkata")
NIFTY_SPOT_TOKEN = "26000"          # Angel One token for Nifty50 spot index
NIFTY_SPOT_EXCHANGE = "NSE"

# ── Logging setup ─────────────────────────────────────────────────────────────
def setup_logging(config: dict):
    log_cfg = config.get("logging", {})
    logger.remove()
    logger.add(sys.stdout, level=log_cfg.get("level", "INFO"), colorize=True,
               format="<green>{time:HH:mm:ss}</green> | <level>{level}</level> | {message}")
    Path("logs").mkdir(exist_ok=True)
    logger.add(
        log_cfg.get("file", "logs/trading.log"),
        level=log_cfg.get("level", "INFO"),
        rotation=log_cfg.get("rotation", "1 day"),
        retention=log_cfg.get("retention", "30 days"),
        compression="zip",
    )


# ── Market hours guard ────────────────────────────────────────────────────────
def is_market_open(config: dict) -> bool:
    now = datetime.now(IST)
    if now.weekday() >= 5:   # Saturday=5, Sunday=6
        return False
    open_t = config["trading"]["market_open"]
    close_t = config["trading"]["market_close"]
    now_str = now.strftime("%H:%M")
    return open_t <= now_str <= close_t


def wait_for_market_open(config: dict):
    while not is_market_open(config):
        now = datetime.now(IST)
        logger.info(f"Market closed. Current time: {now.strftime('%H:%M:%S IST')}. Waiting…")
        time.sleep(60)


# ── Main trading loop ─────────────────────────────────────────────────────────
class TradingEngine:
    def __init__(self, config: dict, paper_trading: bool = False):
        self.config = config
        self.paper_trading = paper_trading
        self._running = False

        logger.info("Initialising trading engine…")
        self.client = AngelOneClient(config)
        self.options_analyzer = OptionsChainAnalyzer()
        self.feature_engine = TechnicalFeatureEngine()
        self.regime_detector = MarketRegimeDetector()

        # Load trained ML models (if available)
        self.regime_classifier = MarketRegimeClassifier(config["ml"]["regime_model"])
        self.price_predictor = PriceDirectionPredictor(config["ml"]["price_predictor"])
        self._try_load_models()

        self.signal_generator = SignalGenerator(self.regime_classifier, self.price_predictor, config)

        # Strategies
        self.strategies = {
            "trend": TrendFollowingStrategy(config, "trend_following"),
            "premium": PremiumSellingStrategy(config, "premium_selling"),
            "scalp": ScalpingStrategy(config, "scalping"),
        }

        # Execution layer
        self.risk_manager = RiskManager(config)
        self.position_manager = PositionManager(config)
        self.order_manager = OrderManager(self.client, self.risk_manager, config, paper_trading)

        # Monitoring
        self.dashboard = TradingDashboard(config)
        self.alert_manager = AlertManager(config)

        # Live data buffers (keyed by symbol_token)
        self._tick_data: dict = {}
        self._candle_data_5m: dict = {}

    def _try_load_models(self):
        model_path = Path("trained_models")
        try:
            regime_path = model_path / "regime_model.pkl"
            if regime_path.exists():
                self.regime_classifier.load_model(str(regime_path))
                logger.info("Loaded regime classifier")
        except Exception as e:
            logger.warning(f"Could not load regime model: {e}")

        try:
            pred_path = model_path / "price_predictor"
            if pred_path.exists():
                self.price_predictor.load()
                logger.info("Loaded price predictor")
        except Exception as e:
            logger.warning(f"Could not load price predictor: {e}")

    def connect(self):
        logger.info("Connecting to Angel One…")
        self.client.connect()
        logger.success("Connected to Angel One SmartAPI")

    def _on_tick(self, tick: dict):
        """Callback from live WebSocket feed."""
        token = tick.get("token")
        self._tick_data[token] = tick

    def _start_live_feed(self, tokens: list[dict]):
        self.live_feed = LiveFeed(self.client, tokens)
        self.live_feed.subscribe(self._on_tick)
        feed_thread = threading.Thread(target=self.live_feed.start, daemon=True)
        feed_thread.start()
        logger.info("Live feed started")

    def _get_latest_spot(self) -> float:
        tick = self._tick_data.get(NIFTY_SPOT_TOKEN)
        if tick:
            return tick.get("ltp", 0.0)
        try:
            return self.client.get_ltp(NIFTY_SPOT_EXCHANGE, "Nifty 50", NIFTY_SPOT_TOKEN)
        except Exception:
            return 0.0

    def _fetch_5min_candles(self, n_candles: int = 100) -> "pd.DataFrame":
        import pandas as pd
        from_dt = (datetime.now(IST) - timedelta(minutes=n_candles * 5)).strftime("%Y-%m-%d %H:%M")
        to_dt = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
        try:
            df = self.client.get_historical_data(
                exchange=NIFTY_SPOT_EXCHANGE,
                symbol_token=NIFTY_SPOT_TOKEN,
                interval="FIVE_MINUTE",
                from_date=from_dt,
                to_date=to_dt,
            )
            return df
        except Exception as e:
            logger.error(f"Failed to fetch candles: {e}")
            return pd.DataFrame()

    def _run_signal_cycle(self):
        """One cycle of: fetch data → compute features → generate signal → execute."""
        import pandas as pd

        spot = self._get_latest_spot()
        if spot <= 0:
            logger.warning("Could not get spot price, skipping cycle")
            return

        df = self._fetch_5min_candles(100)
        if df.empty:
            return

        feat_df = self.feature_engine.compute_all(df)
        feat_df = feat_df.dropna()
        if len(feat_df) < 30:
            return

        # Fetch options chain
        expiry = self.options_analyzer.get_nearest_expiry()
        try:
            raw_chain = self.client.get_option_chain("NIFTY", expiry, int(spot))
            chain_df = self.options_analyzer.build_option_chain_df(raw_chain)
        except Exception as e:
            logger.warning(f"Options chain fetch failed: {e}")
            chain_df = pd.DataFrame()

        # Generate AI signal
        market_data = {"spot": spot, "expiry": expiry}
        signal = self.signal_generator.generate_signal(feat_df, chain_df if not chain_df.empty else None)

        # Update dashboard
        self.dashboard.update(
            nifty_spot=spot,
            regime=signal.regime if hasattr(signal, "regime") else "unknown",
            regime_confidence=signal.confidence if hasattr(signal, "confidence") else 0.0,
            signal=signal.action if hasattr(signal, "action") else "NO_TRADE",
            signal_confidence=signal.confidence if hasattr(signal, "confidence") else 0.0,
        )

        if not hasattr(signal, "action") or signal.action == "NO_TRADE":
            return

        # Risk check
        open_positions = self.position_manager.get_open_positions()
        daily_pnl = self.position_manager.get_daily_pnl()
        can_trade, reason = self.risk_manager.can_place_trade(open_positions, daily_pnl, signal)

        if not can_trade:
            logger.info(f"Trade blocked by risk manager: {reason}")
            return

        # Complete signal with entry details
        from models.signal_generator import Signal
        detailed_signal = self.signal_generator.compute_entry_details(signal, spot, chain_df)

        # Execute
        logger.info(f"Executing signal: {signal.action} | Strike: {signal.strike} | Conf: {signal.confidence:.0%}")
        order_id = self.order_manager.execute_signal(detailed_signal)
        if order_id:
            fill_price = detailed_signal.price
            self.position_manager.add_position(order_id, detailed_signal, fill_price, detailed_signal.qty)
            self.alert_manager.trade_entry(
                detailed_signal.symbol, detailed_signal.action, detailed_signal.qty,
                fill_price, detailed_signal.strike, detailed_signal.expiry, "AI"
            )

    def _manage_open_positions(self):
        """Check SL/target on all open positions and exit as needed."""
        open_positions = self.position_manager.get_open_positions()
        spot = self._get_latest_spot()

        for pos in open_positions:
            token = pos.token
            tick = self._tick_data.get(token)
            ltp = tick["ltp"] if tick else 0

            if ltp <= 0:
                try:
                    ltp = self.client.get_ltp("NFO", pos.symbol, token)
                except Exception:
                    continue

            self.position_manager.update_position_pnl(token, ltp)

            # Check SL
            if ltp <= pos.sl_price:
                logger.warning(f"SL hit: {pos.symbol} @ ₹{ltp:.2f} (SL: ₹{pos.sl_price:.2f})")
                order_id = self.order_manager.exit_position(pos, "sl_hit")
                if order_id:
                    realized = (ltp - pos.entry_price) * pos.qty
                    self.position_manager.close_position(pos.order_id, ltp)
                    self.alert_manager.sl_hit(pos.symbol, pos.sl_price, realized)
                continue

            # Check target
            if ltp >= pos.target_price:
                logger.info(f"Target hit: {pos.symbol} @ ₹{ltp:.2f} (Target: ₹{pos.target_price:.2f})")
                order_id = self.order_manager.exit_position(pos, "target_hit")
                if order_id:
                    realized = (ltp - pos.entry_price) * pos.qty
                    self.position_manager.close_position(pos.order_id, ltp)
                    self.alert_manager.target_hit(pos.symbol, pos.target_price, realized)
                continue

            # Trailing SL update
            updated_sl = self.risk_manager.update_trailing_sl(pos, ltp)
            if updated_sl != pos.sl_price:
                pos.sl_price = updated_sl

    def _daily_square_off(self):
        """Force-exit all positions at day end."""
        open_positions = self.position_manager.get_open_positions()
        if not open_positions:
            return
        logger.info(f"Squaring off {len(open_positions)} position(s) at end of day")
        self.order_manager.exit_all_positions("eod_square_off")
        for pos in open_positions:
            self.position_manager.close_position(pos.order_id, 0)  # price updated separately

    def _update_dashboard_pnl(self):
        daily_pnl = self.position_manager.get_daily_pnl()
        realized = self.position_manager.get_realized_pnl()
        open_pos = self.position_manager.get_open_positions()
        self.dashboard.update(
            daily_pnl=daily_pnl,
            realized_pnl=realized,
            unrealized_pnl=daily_pnl - realized,
            positions=[vars(p) for p in open_pos],
            status="RUNNING",
        )

    def run(self):
        """Main trading loop."""
        self._running = True
        signal_interval = self.config["ml"]["strategy_selector"]["update_frequency_minutes"] * 60
        last_signal_time = 0

        # Start dashboard in background thread
        dash_thread = threading.Thread(target=self.dashboard.run_live, daemon=True)
        dash_thread.start()

        try:
            wait_for_market_open(self.config)
            self.connect()

            tokens = [{"exchange_type": 1, "token": NIFTY_SPOT_TOKEN}]
            self._start_live_feed(tokens)

            logger.info("Trading engine started. Entering main loop…")
            while self._running:
                now = datetime.now(IST)
                now_str = now.strftime("%H:%M")

                if not is_market_open(self.config):
                    logger.info("Market closed. Stopping.")
                    break

                # Manage existing positions every tick cycle
                self._manage_open_positions()

                # Generate new signals at configured frequency
                if time.time() - last_signal_time >= signal_interval:
                    now_str_hm = now.strftime("%H:%M")
                    if now_str_hm < self.config["trading"]["no_new_trades_after"]:
                        self._run_signal_cycle()
                    last_signal_time = time.time()

                # Force square-off at configured time
                if now_str >= self.config["trading"]["square_off_time"]:
                    self._daily_square_off()
                    break

                # Check daily loss limit
                daily_pnl = self.position_manager.get_daily_pnl()
                loss_limit = -self.config["risk"]["total_capital"] * self.config["risk"]["daily_loss_limit_pct"]
                if daily_pnl <= loss_limit:
                    logger.error(f"Daily loss limit hit! P&L: ₹{daily_pnl:,.0f}")
                    self.alert_manager.daily_loss_limit(daily_pnl, abs(loss_limit))
                    self._daily_square_off()
                    break

                # Update dashboard
                self._update_dashboard_pnl()
                time.sleep(5)

        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        except Exception as e:
            logger.exception(f"Fatal error in trading engine: {e}")
            self.alert_manager.system_error(str(e))
        finally:
            self._running = False
            self._daily_square_off()
            stats = {
                "daily_pnl": self.position_manager.get_daily_pnl(),
                "trades": self.position_manager._trade_count_today,
                "wins": self.position_manager._wins_today,
                "losses": self.position_manager._losses_today,
            }
            self.alert_manager.daily_summary(stats)
            logger.info("Trading engine shut down.")


# ── CLI ───────────────────────────────────────────────────────────────────────
def parse_args():
    parser = argparse.ArgumentParser(description="Nifty50 AI Options Trading System")
    parser.add_argument("--mode", choices=["live", "paper", "backtest", "train", "dashboard"],
                        default="paper", help="Run mode")
    parser.add_argument("--start", default=None, help="Backtest start date YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="Backtest end date YYYY-MM-DD")
    parser.add_argument("--config", default=None, help="Path to custom config.yaml")
    return parser.parse_args()


def main():
    args = parse_args()
    config = load_config(args.config)
    setup_logging(config)

    logger.info(f"Starting Nifty50 AI Trading System in [{args.mode.upper()}] mode")

    if args.mode == "train":
        client = AngelOneClient(config)
        client.connect()
        trainer = ModelTrainer(client, config)
        trainer.train_all_models()

    elif args.mode == "backtest":
        client = AngelOneClient(config)
        client.connect()
        trainer = ModelTrainer(client, config)
        df = trainer.fetch_training_data(days=252)
        feat_df = trainer.build_feature_matrix(df)

        regime_clf = MarketRegimeClassifier(config["ml"]["regime_model"])
        price_pred = PriceDirectionPredictor(config["ml"]["price_predictor"])
        signal_gen = SignalGenerator(regime_clf, price_pred, config)

        backtester = Backtester(config, signal_gen)
        result = backtester.run(feat_df, start_date=args.start, end_date=args.end)
        backtester.print_report(result)

        out_path = Path("logs") / "backtest_trades.csv"
        out_path.parent.mkdir(exist_ok=True)
        backtester.to_dataframe(result).to_csv(out_path, index=False)
        logger.info(f"Backtest trades saved to {out_path}")

    elif args.mode == "dashboard":
        config_for_dash = config
        client = AngelOneClient(config_for_dash)
        client.connect()
        dashboard = TradingDashboard(config_for_dash)
        dashboard.update(status="WATCH ONLY")
        dashboard.run_live()

    elif args.mode in ("live", "paper"):
        paper = args.mode == "paper"
        if paper:
            logger.info("PAPER TRADING MODE — no real orders will be placed")
        engine = TradingEngine(config, paper_trading=paper)
        engine.run()


if __name__ == "__main__":
    main()
