from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.auth import get_current_user
from backend.services.stock_conviction_service import analyze_conviction

router = APIRouter(prefix="/api/stocks", tags=["conviction"])


class ConvictionRequest(BaseModel):
    ticker: str


@router.post("/conviction")
async def get_stock_conviction(
    req: ConvictionRequest,
    _: str = Depends(get_current_user),
):
    ticker = req.ticker.strip().upper()
    if not ticker:
        raise HTTPException(status_code=400, detail="Ticker is required")

    result = await analyze_conviction(ticker)

    # Surface explicit error returns (e.g. yfinance no data, API key missing)
    if "error" in result:
        raise HTTPException(status_code=502, detail=result["error"])

    # Guard: if Claude returned valid JSON but skipped the conviction block,
    # the frontend would crash on null.score.  Re-run once and hard-fail if
    # still missing so the user sees a clear message instead of a blank screen.
    if not result.get("conviction"):
        raise HTTPException(
            status_code=502,
            detail=f"AI analysis returned incomplete data for {ticker}. Please try again.",
        )

    return result
