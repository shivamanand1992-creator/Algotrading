"""
models package — ML prediction engine for Nifty50 intraday options trading.

Public API
----------
LSTMModel                  PyTorch LSTM module
PriceDirectionPredictor    Ensemble price-direction predictor (LSTM + XGB + LGBM)
MarketRegimeClassifier     XGBoost-based market-regime classifier
ModelTrainer               Full training pipeline (lazy import — needs AngelOneClient)
SignalGenerator            Regime + price prediction → actionable options signal
Signal                     Dataclass carrying a generated trading signal

Note: ModelTrainer is not eagerly imported here because it depends on
data.angel_client which requires broker-specific packages (smartapi-python,
pyotp).  Import it explicitly when needed:
    from models.model_trainer import ModelTrainer
"""

from models.price_predictor import LSTMModel, PriceDirectionPredictor
from models.regime_classifier import MarketRegimeClassifier
from models.signal_generator import SignalGenerator, Signal

__all__ = [
    "LSTMModel",
    "PriceDirectionPredictor",
    "MarketRegimeClassifier",
    "ModelTrainer",   # available via: from models.model_trainer import ModelTrainer
    "SignalGenerator",
    "Signal",
]


def __getattr__(name: str):
    """Lazy import for ModelTrainer to avoid eager broker-SDK dependency."""
    if name == "ModelTrainer":
        from models.model_trainer import ModelTrainer
        return ModelTrainer
    raise AttributeError(f"module 'models' has no attribute {name!r}")
