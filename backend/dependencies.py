import os
import sys
from pathlib import Path
from typing import Generator
from loguru import logger

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from data.angel_client import AngelOneClient
from execution.position_manager import PositionManager
from execution.order_manager import OrderManager
from execution.risk_manager import RiskManager
from models.signal_generator import SignalGenerator
from models.price_predictor import PriceDirectionPredictor
from models.regime_classifier import MarketRegimeClassifier
from data.options_chain import OptionsChainAnalyzer
from backend.config import config, DEMO_MODE


# Global instances (initialized on startup)
_angel_client = None
_angel_client_attempted = False   # connect() tried at least once
_position_manager = None
_order_manager = None
_risk_manager = None
_signal_generator = None
_price_predictor = None
_regime_classifier = None
_options_analyzer = None
_sr_service = None


def get_angel_client():
    global _angel_client, _angel_client_attempted
    if DEMO_MODE:
        return None
    if not _angel_client_attempted:
        _angel_client_attempted = True
        try:
            client = AngelOneClient(config.trading_config)
            client.connect()
            _angel_client = client
            logger.info("Angel One connected successfully.")
        except Exception as e:
            logger.warning(
                f"Angel One connection failed ({e}). "
                "Check ANGEL_API_KEY / ANGEL_CLIENT_ID / ANGEL_PASSWORD / ANGEL_TOTP_SECRET "
                "env vars and whitelist your Railway outbound IP in Angel One API settings "
                "(Settings → API → Authorized IPs). "
                "Running without broker — live market data unavailable; paper positions tracked locally."
            )
            _angel_client = None
    return _angel_client


def reset_angel_client():
    """Force a reconnect attempt on the next call to get_angel_client()."""
    global _angel_client, _angel_client_attempted
    _angel_client = None
    _angel_client_attempted = False


def get_position_manager():
    global _position_manager
    if DEMO_MODE:
        return None
    if _position_manager is None:
        _position_manager = PositionManager(config.trading_config)
    return _position_manager


def get_risk_manager():
    global _risk_manager
    if DEMO_MODE:
        return None
    if _risk_manager is None:
        _risk_manager = RiskManager(config.trading_config)
    return _risk_manager


def get_order_manager():
    global _order_manager
    if DEMO_MODE:
        return None
    if _order_manager is None:
        angel_client = get_angel_client()
        risk_manager = get_risk_manager()
        _order_manager = OrderManager(angel_client, risk_manager, config.trading_config)
    return _order_manager


def get_signal_generator():
    global _signal_generator
    if DEMO_MODE:
        return None
    if _signal_generator is None:
        regime_classifier = get_regime_classifier()
        price_predictor = get_price_predictor()
        _signal_generator = SignalGenerator(regime_classifier, price_predictor, config.trading_config)
    return _signal_generator


def _model_save_dir() -> Path:
    """Resolve model save directory: env var → absolute repo-anchored path."""
    default = str(Path(__file__).parent.parent / "trained_models")
    return Path(os.getenv("MODEL_SAVE_PATH", default))


def get_price_predictor():
    global _price_predictor
    if DEMO_MODE:
        return None
    if _price_predictor is None:
        pred = PriceDirectionPredictor(config.trading_config)
        meta_path = _model_save_dir() / "price_predictor_meta.pkl"
        if meta_path.exists():
            try:
                pred.load()
                logger.info("PriceDirectionPredictor loaded from disk.")
            except Exception as e:
                logger.warning(f"Could not load price predictor: {e}")
        _price_predictor = pred
    return _price_predictor


def get_regime_classifier():
    global _regime_classifier
    if DEMO_MODE:
        return None
    if _regime_classifier is None:
        clf = MarketRegimeClassifier(config.trading_config)
        meta_path = _model_save_dir() / "regime_classifier_meta.pkl"
        if meta_path.exists():
            try:
                clf.load()
                logger.info("MarketRegimeClassifier loaded from disk.")
            except Exception as e:
                logger.warning(f"Could not load regime classifier: {e}")
        _regime_classifier = clf
    return _regime_classifier


def reload_ml_models():
    """Reset ML singletons so the next request re-instantiates them from saved weights."""
    global _regime_classifier, _price_predictor, _signal_generator
    _regime_classifier = None
    _price_predictor = None
    _signal_generator = None
    logger.info("ML model singletons reset — will reload from disk on next use.")


def get_options_analyzer():
    global _options_analyzer
    if DEMO_MODE:
        return None
    if _options_analyzer is None:
        angel_client = get_angel_client()
        _options_analyzer = OptionsChainAnalyzer()
    return _options_analyzer


def get_sr_service():
    """Get singleton Support/Resistance service instance."""
    global _sr_service
    if _sr_service is None:
        from backend.services.support_resistance_service import get_sr_service as _get_sr
        angel_client = get_angel_client()
        _sr_service = _get_sr(angel_client)
    return _sr_service


# Clean up on shutdown
def cleanup_dependencies():
    global _angel_client
    if _angel_client:
        # Close any open connections
        pass
