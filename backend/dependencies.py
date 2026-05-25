import sys
from pathlib import Path
from typing import Generator

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
_position_manager = None
_order_manager = None
_risk_manager = None
_signal_generator = None
_price_predictor = None
_regime_classifier = None
_options_analyzer = None


def get_angel_client():
    global _angel_client
    if DEMO_MODE:
        return None
    if _angel_client is None:
        _angel_client = AngelOneClient(config.trading_config)
    return _angel_client


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


def get_price_predictor():
    global _price_predictor
    if DEMO_MODE:
        return None
    if _price_predictor is None:
        _price_predictor = PriceDirectionPredictor(config.trading_config)
    return _price_predictor


def get_regime_classifier():
    global _regime_classifier
    if DEMO_MODE:
        return None
    if _regime_classifier is None:
        _regime_classifier = MarketRegimeClassifier(config.trading_config)
    return _regime_classifier


def get_options_analyzer():
    global _options_analyzer
    if DEMO_MODE:
        return None
    if _options_analyzer is None:
        angel_client = get_angel_client()
        _options_analyzer = OptionsChainAnalyzer()
    return _options_analyzer


# Clean up on shutdown
def cleanup_dependencies():
    global _angel_client
    if _angel_client:
        # Close any open connections
        pass
