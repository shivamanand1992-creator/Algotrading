"""
ML-Powered Intraday Trading API Routes
Expectancy-optimized stock scoring and signal generation.
ML predicts; Claude only explains.
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from typing import Dict, Optional
from datetime import datetime
from pydantic import BaseModel
from loguru import logger

router = APIRouter(prefix="/api/ml-intraday", tags=["ML Intraday Trading"])


class ExplanationRequest(BaseModel):
    symbol: str
    score: int
    features: Dict[str, int]


def get_service():
    from backend.ml.scoring_service import MLScoringService
    return MLScoringService.get_instance()


@router.get("/status")
async def get_system_status():
    """ML system status, model metadata, and paper-trading performance."""
    try:
        svc = get_service()
        status = svc.get_status()
        # Add progress info
        status["import_progress"] = svc.import_progress
        status["training_progress"] = svc.training_progress
        return status
    except Exception as e:
        logger.error(f"[ML API] status failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/top-stocks")
async def get_top_stocks():
    """Latest ML scores and active signals."""
    try:
        svc = get_service()
        return {
            "stocks": svc.latest_scores,
            "signals": svc.active_signals,
            "last_update": svc.last_update,
        }
    except Exception as e:
        logger.error(f"[ML API] top-stocks failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/paper-trades")
async def get_paper_trades():
    """Paper trading positions and closed trades with P&L."""
    try:
        svc = get_service()
        return {
            "open_positions": svc.paper_positions,
            "closed_trades": svc.paper_trades_closed,
            "total_pnl_pct": round(svc.paper_pnl_pct, 3),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/run-cycle")
async def trigger_cycle(background_tasks: BackgroundTasks):
    """Manually trigger a scoring cycle using cached candles (fast path)."""
    try:
        svc = get_service()

        # NOTE: Live candle updates disabled to avoid Angel One rate limiting
        # System now uses deterministic technical scoring (no API calls needed)

        # Scoring cycle uses cached data from DB - fast, non-blocking
        result = await svc.run_cycle()
        return result
    except Exception as e:
        logger.error(f"[ML API] run-cycle failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/import-data")
async def trigger_import(background_tasks: BackgroundTasks, days: int = 100):
    """Kick off historical data import (default: 100 days for solid ML training on 5-min data)."""
    svc = get_service()

    # Check if already importing
    if svc.import_progress["status"] == "importing":
        return {"status": "already_running", "progress": svc.import_progress}

    def _import():
        from backend.ml.data_importer import run_import
        try:
            svc.import_progress = {
                "status": "importing",
                "message": f"Starting import of {days} days of data...",
                "progress_pct": 0,
                "stocks_done": 0,
                "total_stocks": 50,
            }
            logger.info(f"[ML API] Starting import: {days} days")

            # Progress callback updates UI in real-time
            def update_progress(progress_dict):
                svc.import_progress = progress_dict
                logger.info(f"[ML API] {progress_dict['message']} ({progress_dict['progress_pct']}%)")

            result = run_import(days=days, progress_callback=update_progress)

            svc.import_progress = {
                "status": "complete",
                "message": f"✓ Import complete: {result.get('total_candles', 0)} candles imported",
                "progress_pct": 100,
                "stocks_done": 50,
                "total_stocks": 50,
            }
            logger.info(f"[ML API] Import complete: {result.get('total_candles', 0)} candles")
        except Exception as e:
            svc.import_progress = {
                "status": "failed",
                "message": f"✗ Import failed: {str(e)[:100]}",
                "progress_pct": 0,
                "stocks_done": 0,
                "total_stocks": 50,
            }
            logger.error(f"[ML API] Import failed: {e}")

    background_tasks.add_task(_import)
    return {
        "status": "started",
        "message": f"Importing {days} days of historical data...",
        "progress": svc.import_progress,
        "estimated_time": "10-15 minutes"
    }


@router.post("/train")
async def trigger_training(background_tasks: BackgroundTasks):
    """Train the XGBoost model on imported data (background, ~3-5 min)."""
    svc = get_service()

    # Check if already training
    if svc.training_progress["status"] == "training":
        return {"status": "already_running", "progress": svc.training_progress}

    def _train():
        from backend.ml.train_model import train
        try:
            svc.training_progress = {
                "status": "training",
                "message": "Training XGBoost model on imported data...",
                "progress_pct": 10,
            }
            logger.info("[ML API] Starting model training")

            meta = train()
            svc.reload_model()

            svc.training_progress = {
                "status": "complete",
                "message": f"✓ Model trained: {meta.get('model_version', 'v1')} | Win Rate: {meta.get('win_rate', 0):.1%}",
                "progress_pct": 100,
            }
            logger.info(f"[ML API] Training complete: {meta}")
            logger.info(f"[ML API] Training complete: {meta['model_version']}, "
                        f"test expectancy={meta['test_report']['expectancy']}%")
        except Exception as e:
            svc.training_progress = {
                "status": "failed",
                "message": f"✗ Training failed: {str(e)[:100]}",
                "progress_pct": 0,
            }
            logger.error(f"[ML API] Training failed: {e}")

    background_tasks.add_task(_train)
    return {
        "status": "started",
        "message": "Training XGBoost model on imported data...",
        "progress": svc.training_progress,
        "estimated_time": "3-5 minutes"
    }


@router.get("/backtest-results")
async def get_backtest_results():
    """Out-of-sample test metrics from the last training run."""
    try:
        svc = get_service()
        meta = svc.meta
        if not meta:
            return {"message": "No model trained yet. POST /api/ml-intraday/import-data then /train"}
        return {
            "model_version": meta.get("model_version"),
            "trained_at": meta.get("trained_at"),
            "threshold": meta.get("threshold"),
            "tradeable": meta.get("tradeable"),
            "validation": meta.get("val_report"),
            "test_out_of_sample": meta.get("test_report"),
            "baseline_trade_everything": meta.get("baseline_report"),
            "top_features": dict(sorted(
                (meta.get("feature_importance") or {}).items(),
                key=lambda kv: -kv[1])[:10]),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# NIFTY ML TRADER (trained on 11 years of uploaded multi-timeframe data)
# ============================================================================

class NiftyEnableRequest(BaseModel):
    mode: str = "paper"          # "paper" | "live"
    capital: int = 100000        # ₹ per trade


def get_nifty_trader():
    from backend.ml.nifty_trader import NiftyMLTrader
    return NiftyMLTrader.get_instance()


@router.post("/train-nifty")
async def train_nifty(background_tasks: BackgroundTasks):
    """Auto-train the NIFTY model on the shipped 11-year dataset (background, ~2 min)."""
    def _train():
        from backend.ml.nifty_model import train
        try:
            meta = train()
            get_nifty_trader().reload_model()
            logger.info(f"[ML API] NIFTY training done: {meta['model_version']}, "
                        f"test after-cost expectancy={meta['test_report']['expectancy_after_cost']}%")
        except Exception as e:
            logger.error(f"[ML API] NIFTY training failed: {e}")

    background_tasks.add_task(_train)
    return {"status": "started",
            "message": "Training NIFTY model on 11 years of data (~2 min). Watch /nifty-status."}


@router.get("/nifty-status")
async def nifty_status():
    """NIFTY trader status: model, mode, position, trades, backtest reports."""
    try:
        return get_nifty_trader().get_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/nifty-enable")
async def nifty_enable(req: NiftyEnableRequest):
    """Enable the NIFTY auto-trader. Live mode requires positive after-cost test expectancy."""
    try:
        trader = get_nifty_trader()
        if trader.booster is None:
            raise HTTPException(status_code=400, detail="No model. POST /train-nifty first.")
        if req.mode == "live" and not trader.tradeable:
            raise HTTPException(
                status_code=400,
                detail="LIVE blocked: model's out-of-sample after-cost expectancy is not positive.")
        trader.mode = "live" if req.mode == "live" else "paper"
        trader.capital = max(10000, min(req.capital, 1000000))
        trader.enabled = True
        logger.info(f"[ML API] NIFTY trader ENABLED mode={trader.mode} capital=₹{trader.capital}")
        return {"status": "enabled", "mode": trader.mode, "capital": trader.capital}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/nifty-disable")
async def nifty_disable():
    """Disable the NIFTY trader and square off any open position."""
    try:
        trader = get_nifty_trader()
        trader.enabled = False
        await trader.force_exit()
        return {"status": "disabled"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/nifty-cycle")
async def nifty_cycle():
    """Manually trigger one NIFTY scoring/trading cycle (for testing)."""
    try:
        return await get_nifty_trader().run_cycle()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# NIFTY OPTIONS TRADER (paper → autopilot)
# ============================================================================

def get_nifty_options_trader():
    from backend.ml.nifty_options_trader import NiftyOptionsTrader
    return NiftyOptionsTrader.get_instance()


@router.get("/nifty-options-status")
async def nifty_options_status():
    """NIFTY options trader status: model, mode, position, trades, Greeks."""
    try:
        return get_nifty_options_trader().get_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/nifty-options-enable")
async def nifty_options_enable(req: NiftyEnableRequest):
    """Enable NIFTY options trading. Paper mode by default."""
    try:
        trader = get_nifty_options_trader()
        if trader.booster is None:
            raise HTTPException(status_code=400, detail="No model. POST /train-nifty first.")
        if req.mode == "live" and not trader.tradeable:
            raise HTTPException(
                status_code=400,
                detail="LIVE blocked: model's out-of-sample after-cost expectancy is not positive.")
        trader.mode = "live" if req.mode == "live" else "paper"
        trader.capital = max(50000, min(req.capital, 1000000))
        trader.enabled = True
        logger.info(f"[ML API] NIFTY OPTIONS trader ENABLED mode={trader.mode} capital=₹{trader.capital}")
        return {"status": "enabled", "mode": trader.mode, "capital": trader.capital}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/nifty-options-disable")
async def nifty_options_disable():
    """Disable NIFTY options trader and close any open position."""
    try:
        trader = get_nifty_options_trader()
        trader.enabled = False
        await trader._manage_position(0, datetime.now())
        return {"status": "disabled"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/nifty-options-cycle")
async def nifty_options_cycle():
    """Manually trigger one NIFTY options scoring/trading cycle (for testing)."""
    try:
        return await get_nifty_options_trader().run_cycle()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/explain")
async def explain_signal(request: ExplanationRequest):
    """Claude explains WHY the ML model scored a stock high. Explanation only — no prediction."""
    try:
        svc = get_service()
        stock = next((s for s in svc.latest_scores if s["symbol"] == request.symbol), None)
        signal = next((s for s in svc.active_signals if s["symbol"] == request.symbol), None)

        try:
            import os
            from anthropic import AsyncAnthropic
            client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
            context = {
                "symbol": request.symbol,
                "ml_score": request.score,
                "subscores": request.features,
                "signal": signal,
                "model_test_expectancy": (svc.meta.get("test_report") or {}).get("expectancy"),
                "model_threshold": svc.threshold,
            }
            msg = await client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=600,
                messages=[{
                    "role": "user",
                    "content": (
                        "You explain ML trading signals to a trader. The XGBoost model already made "
                        "the decision — you only explain it. Be concise, factual, structured. "
                        f"Data: {context}\n\n"
                        "Explain in this format:\n"
                        "SYMBOL (Score X/100)\n• Why the model likes it (per subscore)\n"
                        "• Trade setup (entry/SL/target/RR if signal exists)\n"
                        "• Model context (threshold, test expectancy)\n"
                        "Do not invent numbers not in the data."
                    ),
                }],
            )
            return {"explanation": msg.content[0].text}
        except Exception as llm_err:
            logger.warning(f"[ML API] Claude explanation failed, using fallback: {llm_err}")
            f = request.features
            lines = [
                f"{request.symbol} (Score: {request.score}/100)",
                "",
                f"• Trend: {f.get('trend', 0)}/100",
                f"• Momentum: {f.get('momentum', 0)}/100",
                f"• Volume: {f.get('volume', 0)}/100",
                f"• Pattern: {f.get('pattern', 0)}/100",
            ]
            if signal:
                lines += [
                    "",
                    f"Entry: ₹{signal['entry']} | SL: ₹{signal['stop_loss']} | "
                    f"Target: ₹{signal['target']} | R:R 1:{signal['reward_risk']}",
                ]
            return {"explanation": "\n".join(lines)}

    except Exception as e:
        logger.error(f"[ML API] explain failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# OPTIONS STRATEGY ADVISOR (comprehensive monthly income strategy engine)
# ============================================================================

def get_strategy_advisor():
    from backend.ml.options_strategy_advisor import get_strategy_advisor as _get_advisor
    return _get_advisor()


@router.get("/options-strategy-analysis")
async def get_options_strategy_analysis():
    """
    Comprehensive options strategy recommendation for current market.
    Includes: market analysis, spread recommendations, Greeks, entry/exit, breakevens, P&L targets.
    """
    try:
        from backend.dependencies import get_angel_client
        from backend.api.routes.market_data import get_market_service
        import asyncio

        angel = get_angel_client()
        market_svc = get_market_service()

        loop = asyncio.get_event_loop()

        # Fetch current market data
        current_data = await market_svc.get_current_market_data()
        nifty_price = float(current_data.ltp)
        prev_close = nifty_price - float(current_data.change)

        # Fetch OHLCV for technical analysis
        ohlcv = await market_svc.get_ohlcv_data("FIFTEEN_MINUTE", days=1)
        if ohlcv and len(ohlcv) > 0:
            latest = ohlcv[-1]
            range_high = float(latest.get("high", nifty_price))
            range_low = float(latest.get("low", nifty_price))
        else:
            range_high = range_low = nifty_price

        # Fetch technical indicators (RSI, MACD, SMA50, volume)
        # Using ML scoring service for consistency
        scoring_svc = get_service()
        await scoring_svc.update_live_candles()

        # Get calculated features from scoring service
        features = scoring_svc.latest_features or {}

        rsi = features.get("rsi", 50)
        macd_signal = "BULLISH" if features.get("macd_histogram", 0) > 0 else "BEARISH"
        sma50 = features.get("sma_50", nifty_price)
        volume_ratio = features.get("volume_ratio", 1.0)

        # Support/Resistance from service
        support = features.get("support_level", nifty_price - 200)
        resistance = features.get("resistance_level", nifty_price + 200)

        # IV Percentile (0-100)
        # In real implementation, fetch from broker API
        # For now, estimate from ATR
        atr = features.get("atr", 100)
        iv_percentile = min(100, int((atr / nifty_price) * 500))

        # Analyze market
        advisor = get_strategy_advisor()
        market_analysis = advisor.analyze_market(
            nifty_price=nifty_price,
            prev_close=prev_close,
            volatility=iv_percentile,
            rsi=rsi,
            macd_signal=macd_signal,
            sma50=sma50,
            support=support,
            resistance=resistance,
            range_high=range_high,
            range_low=range_low,
            volume_ratio=volume_ratio,
        )

        # Generate strategy recommendation
        recommendation = advisor.recommend_strategy(market_analysis, iv_percentile)

        if not recommendation:
            raise HTTPException(status_code=500, detail="Failed to generate strategy recommendation")

        # Convert to JSON-serializable format
        from dataclasses import asdict

        def serialize_spread(spread):
            return {
                "name": spread.name,
                "description": spread.description,
                "outlook": spread.outlook,
                "legs": spread.legs,
                "max_profit": float(spread.max_profit),
                "max_loss": float(spread.max_loss),
                "breakeven_points": [float(x) for x in spread.breakeven_points],
                "probability_profit": float(spread.probability_profit),
                "capital_required": float(spread.capital_required),
                "reward_risk_ratio": float(spread.reward_risk_ratio),
            }

        return {
            "market_analysis": asdict(market_analysis),
            "primary_strategy": serialize_spread(recommendation.primary_strategy),
            "alternative_strategies": [serialize_spread(s) for s in recommendation.alternative_strategies],
            "rationale": recommendation.rationale,
            "risk_factors": recommendation.risk_factors,
            "profit_targets": {k: float(v) for k, v in recommendation.profit_targets.items()},
            "stop_loss_level": float(recommendation.stop_loss_level),
            "ideal_entry_time": recommendation.ideal_entry_time,
            "expiry_days": recommendation.expiry_days,
            "timestamp": recommendation.timestamp,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Strategy Advisor] analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/options-spread-details/{spread_name}")
async def get_spread_details(spread_name: str):
    """
    Get detailed information for a specific options spread.
    Includes: payoff diagram data, Greeks at different price levels, entry/exit calculations.
    """
    try:
        advisor = get_strategy_advisor()

        # Get current NIFTY price
        from backend.api.routes.market_data import get_market_service
        market_svc = get_market_service()
        current_data = await market_svc.get_current_market_data()
        nifty_price = float(current_data.ltp)

        # Default IV (should be fetched from broker in real implementation)
        iv = 50.0

        # Build the spread
        spread = advisor.build_spread(
            spread_name,
            nifty_price,
            iv,
            days_to_expiry=14,
        )

        if not spread:
            raise HTTPException(status_code=404, detail=f"Spread '{spread_name}' not found or not buildable")

        # Calculate payoff across price range
        import numpy as np
        strike_range = np.arange(nifty_price - 500, nifty_price + 500, 10)
        payoff, stats = advisor.calculate_spread_payoff(
            spread.legs,
            strike_range,
            sum(leg.get("premium", 0) for leg in spread.legs),
        )

        # Calculate Greeks at current price and key levels
        greeks_current = advisor.calculate_spread_Greeks(
            spread.legs, nifty_price, iv, days_to_expiry=14
        )

        from dataclasses import asdict

        return {
            "spread": asdict(spread),
            "payoff_data": {
                "price_levels": [float(p) for p in strike_range],
                "pnl": [float(p) for p in payoff],
                "max_profit": float(stats["max_profit"]),
                "max_loss": float(stats["max_loss"]),
                "breakeven_points": [float(x) for x in stats["breakeven_points"]],
            },
            "current_greeks": {
                "delta": float(greeks_current["delta"]),
                "gamma": float(greeks_current["gamma"]),
                "theta": float(greeks_current["theta"]),
                "vega": float(greeks_current["vega"]),
            },
            "position_sizing": {
                "capital_required": float(spread.capital_required),
                "max_profit_potential": float(spread.max_profit),
                "max_loss_potential": float(spread.max_loss),
                "reward_risk_ratio": float(spread.reward_risk_ratio),
            },
            "entry_exit_guide": {
                "recommended_entry": f"₹{nifty_price:.0f} ± 1% (market order or limit near midpoint)",
                "profit_targets": {
                    "50%": f"₹{greeks_current['net_premium'] * 0.5:.0f}",
                    "75%": f"₹{greeks_current['net_premium'] * 0.75:.0f}",
                    "100%": f"₹{greeks_current['net_premium']:.0f}",
                },
                "stop_loss": f"₹{spread.max_loss * 1.2:.0f} (allow 20% adverse move)",
                "time_stop": "Exit if 50% of expiry time passed with <50% max profit",
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Strategy Advisor] spread details failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
