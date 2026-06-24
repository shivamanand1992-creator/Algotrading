from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.services.stock_conviction_service import analyze_conviction

router = APIRouter(prefix="/api/stocks", tags=["conviction"])


class ConvictionRequest(BaseModel):
    ticker: str


@router.post("/conviction")
async def get_stock_conviction(req: ConvictionRequest):
    ticker = req.ticker.strip().upper()
    if not ticker:
        raise HTTPException(status_code=400, detail="Ticker is required")
    result = await analyze_conviction(ticker)
    if "error" in result and len(result) <= 3:
        raise HTTPException(status_code=404, detail=result["error"])
    return result
