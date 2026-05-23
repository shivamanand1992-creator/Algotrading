"""
models package — ML prediction engine for Nifty50 intraday options trading.

Exports
-------
LSTMModel                  PyTorch LSTM module
PriceDirectionPredictor    Ensemble price-direction predictor (LSTM + XGB + LGBM)
MarketRegimeClassifier     XGBoost-based market-regime classifier
ModelTrainer               Full training pipeline
SignalGenerator            Regime + price prediction → actionable options signal
Signal                     Dataclass carrying a generated trading signal
"""

from models.price_predictor import LSTMModel, PriceDirectionPredictor
from models.regime_classifier import MarketRegimeClassifier
from models.model_trainer import ModelTrainer
from models.signal_generator import SignalGenerator, Signal

__all__ = [
    "LSTMModel",
    "PriceDirectionPredictor",
    "MarketRegimeClassifier",
    "ModelTrainer",
    "SignalGenerator",
    "Signal",
]
