"""
Claude API Usage Monitoring - API Routes
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta, timezone
from loguru import logger

from backend.services import claude_usage_service
from backend.services import telegram_service


router = APIRouter(prefix="/api/claude-usage", tags=["Claude Usage"])

_IST = timezone(timedelta(hours=5, minutes=30))


class UsageDateRange(BaseModel):
    start_date: Optional[str] = None  # YYYY-MM-DD
    end_date: Optional[str] = None    # YYYY-MM-DD


@router.get("/report")
async def get_usage_report():
    """Get comprehensive Claude API usage report"""
    if not claude_usage_service.is_configured():
        raise HTTPException(
            status_code=503,
            detail="ANTHROPIC_API_KEY not configured"
        )

    report = claude_usage_service.get_comprehensive_report()

    if not report:
        raise HTTPException(
            status_code=500,
            detail="Failed to fetch usage data from Claude API"
        )

    return report


@router.post("/usage")
async def get_usage_by_date(date_range: UsageDateRange):
    """Get usage data for specific date range"""
    if not claude_usage_service.is_configured():
        raise HTTPException(
            status_code=503,
            detail="ANTHROPIC_API_KEY not configured"
        )

    usage_data = claude_usage_service.get_usage_summary(
        start_date=date_range.start_date,
        end_date=date_range.end_date
    )

    if not usage_data:
        raise HTTPException(
            status_code=500,
            detail="Failed to fetch usage data"
        )

    analytics = claude_usage_service.analyze_usage(usage_data)

    return {
        "raw_data": usage_data,
        "analytics": analytics
    }


@router.get("/billing")
async def get_billing_info():
    """Get billing and balance information"""
    if not claude_usage_service.is_configured():
        raise HTTPException(
            status_code=503,
            detail="ANTHROPIC_API_KEY not configured"
        )

    billing_data = claude_usage_service.get_billing_info()

    if not billing_data:
        raise HTTPException(
            status_code=500,
            detail="Failed to fetch billing data"
        )

    return billing_data


@router.post("/send-telegram-report")
async def send_telegram_report():
    """Send current usage report to Telegram"""
    if not telegram_service.is_configured():
        raise HTTPException(
            status_code=503,
            detail="Telegram not configured (TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing)"
        )

    if not claude_usage_service.is_configured():
        raise HTTPException(
            status_code=503,
            detail="ANTHROPIC_API_KEY not configured"
        )

    # Get report
    report = claude_usage_service.get_comprehensive_report()
    if not report:
        raise HTTPException(
            status_code=500,
            detail="Failed to generate usage report"
        )

    # Format and send
    message = claude_usage_service.format_telegram_report(report)
    success = telegram_service.send(message, parse_mode="HTML")

    if not success:
        raise HTTPException(
            status_code=500,
            detail="Failed to send Telegram message"
        )

    return {
        "success": True,
        "message": "Usage report sent to Telegram",
        "sent_at": datetime.now(_IST).isoformat()
    }
