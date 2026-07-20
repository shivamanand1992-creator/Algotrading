"""
Claude API Usage Monitoring Service - LOCAL TRACKING

Since Anthropic API doesn't expose usage/billing endpoints via REST API,
this service tracks usage locally by intercepting Claude API calls.

Features:
- Local token usage tracking per request
- Cost calculation based on model pricing
- Daily/monthly aggregation
- Model-wise breakdown

Note: Billing balance must be checked manually on https://console.anthropic.com/
"""
import os
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from pathlib import Path
from loguru import logger


_IST = timezone(timedelta(hours=5, minutes=30))
_ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()

# Local usage tracking file
_USAGE_FILE = Path(__file__).parent.parent / "data" / "claude_usage.json"
_USAGE_FILE.parent.mkdir(exist_ok=True)

# Model pricing (USD per 1M tokens) - Updated 2026-07-20
_PRICING = {
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-sonnet-5": {"input": 2.00, "output": 10.00},  # Intro pricing
    "claude-opus-4-6": {"input": 5.00, "output": 25.00},
    "claude-opus-4-7": {"input": 5.00, "output": 25.00},
    "claude-opus-4-8": {"input": 5.00, "output": 25.00},
}


def is_configured() -> bool:
    """Check if Anthropic API key is available"""
    return bool(_ANTHROPIC_API_KEY)


def _load_usage_data() -> Dict:
    """Load usage data from local file"""
    if not _USAGE_FILE.exists():
        return {"records": []}

    try:
        with open(_USAGE_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"[ClaudeUsage] Failed to load usage data: {e}")
        return {"records": []}


def _save_usage_data(data: Dict):
    """Save usage data to local file"""
    try:
        with open(_USAGE_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"[ClaudeUsage] Failed to save usage data: {e}")


def track_usage(model: str, input_tokens: int, output_tokens: int):
    """
    Track a Claude API call

    Args:
        model: Model identifier (e.g. "claude-haiku-4-5")
        input_tokens: Input tokens consumed
        output_tokens: Output tokens consumed
    """
    pricing = _PRICING.get(model, {"input": 0, "output": 0})
    cost = (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000

    record = {
        "timestamp": datetime.now(_IST).isoformat(),
        "date": datetime.now(_IST).strftime("%Y-%m-%d"),
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "cost_usd": round(cost, 4)
    }

    data = _load_usage_data()
    data["records"].append(record)
    _save_usage_data(data)

    logger.debug(f"[ClaudeUsage] Tracked: {model} {input_tokens+output_tokens:,} tokens ${cost:.4f}")


def get_usage_summary(start_date: Optional[str] = None, end_date: Optional[str] = None) -> Optional[Dict]:
    """
    Get usage summary from local tracking data

    Args:
        start_date: ISO format date (YYYY-MM-DD), defaults to beginning of current month
        end_date: ISO format date (YYYY-MM-DD), defaults to today

    Returns:
        Dict with usage data compatible with analyze_usage()
    """
    now = datetime.now(_IST)
    if not start_date:
        start_date = now.replace(day=1).strftime("%Y-%m-%d")
    if not end_date:
        end_date = now.strftime("%Y-%m-%d")

    logger.info(f"[ClaudeUsage] Fetching local usage from {start_date} to {end_date}")

    data = _load_usage_data()
    filtered = [
        r for r in data.get("records", [])
        if start_date <= r.get("date", "") <= end_date
    ]

    return {"data": filtered}


def get_billing_info() -> Optional[Dict]:
    """
    Get billing placeholder - actual balance must be checked on console.anthropic.com

    Returns:
        Dict with placeholder message
    """
    logger.info("[ClaudeUsage] Billing info not available via API")
    return {
        "message": "Billing balance must be checked manually on https://console.anthropic.com/settings/billing",
        "note": "Anthropic API does not expose billing endpoints"
    }


def analyze_usage(usage_data: Dict) -> Dict:
    """
    Analyze usage data and calculate metrics

    Args:
        usage_data: Raw usage data from API

    Returns:
        Dict with analyzed metrics:
        - total_tokens: Total tokens consumed
        - total_cost: Total cost in USD
        - by_model: Breakdown by model
        - by_day: Daily usage trend
        - top_consumer: Model consuming most tokens
    """
    if not usage_data or "data" not in usage_data:
        return {
            "total_tokens": 0,
            "total_cost": 0.0,
            "by_model": {},
            "by_day": [],
            "top_consumer": None
        }

    # Aggregate by model
    by_model = {}
    by_day = {}
    total_tokens = 0
    total_cost = 0.0

    for entry in usage_data.get("data", []):
        model = entry.get("model", "unknown")
        date = entry.get("date", "unknown")

        input_tokens = entry.get("input_tokens", 0)
        output_tokens = entry.get("output_tokens", 0)
        total = input_tokens + output_tokens

        # Cost calculation (USD)
        cost = entry.get("cost_usd", 0.0)

        # By model
        if model not in by_model:
            by_model[model] = {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "cost_usd": 0.0,
                "requests": 0
            }

        by_model[model]["input_tokens"] += input_tokens
        by_model[model]["output_tokens"] += output_tokens
        by_model[model]["total_tokens"] += total
        by_model[model]["cost_usd"] += cost
        by_model[model]["requests"] += entry.get("requests", 0)

        # By day
        if date not in by_day:
            by_day[date] = {
                "total_tokens": 0,
                "cost_usd": 0.0
            }

        by_day[date]["total_tokens"] += total
        by_day[date]["cost_usd"] += cost

        total_tokens += total
        total_cost += cost

    # Find top consumer
    top_consumer = None
    if by_model:
        top_consumer = max(by_model.items(), key=lambda x: x[1]["total_tokens"])[0]

    # Convert by_day dict to sorted list
    daily_usage = [
        {"date": date, **metrics}
        for date, metrics in sorted(by_day.items())
    ]

    return {
        "total_tokens": total_tokens,
        "total_cost": round(total_cost, 2),
        "by_model": by_model,
        "by_day": daily_usage,
        "top_consumer": top_consumer
    }


def get_comprehensive_report() -> Dict:
    """
    Get comprehensive usage report including local usage analytics

    Returns:
        Dict with:
        - usage: Current month usage analytics
        - yesterday: Yesterday's usage
        - billing: Placeholder message (check console.anthropic.com manually)
        - generated_at: Report timestamp
    """
    logger.info("[ClaudeUsage] Generating comprehensive report from local data")

    try:
        # Get current month usage
        usage_data = get_usage_summary()
        usage_analytics = analyze_usage(usage_data) if usage_data else {
            "total_tokens": 0,
            "total_cost": 0.0,
            "by_model": {},
            "by_day": [],
            "top_consumer": None
        }

        # Get yesterday's usage for daily tracking
        yesterday = (datetime.now(_IST) - timedelta(days=1)).strftime("%Y-%m-%d")
        today = datetime.now(_IST).strftime("%Y-%m-%d")
        yesterday_data = get_usage_summary(start_date=yesterday, end_date=yesterday)
        yesterday_analytics = analyze_usage(yesterday_data) if yesterday_data else {
            "total_tokens": 0,
            "total_cost": 0.0,
            "by_model": {},
            "by_day": [],
            "top_consumer": None
        }

        # Get billing placeholder
        billing_data = get_billing_info()

        return {
            "usage": usage_analytics,
            "yesterday": yesterday_analytics,
            "billing": billing_data or {},
            "generated_at": datetime.now(_IST).isoformat(),
            "period": {
                "start": datetime.now(_IST).replace(day=1).strftime("%Y-%m-%d"),
                "end": today
            }
        }
    except Exception as e:
        logger.error(f"[ClaudeUsage] Failed to generate report: {e}")
        # Return safe default structure
        return {
            "usage": {
                "total_tokens": 0,
                "total_cost": 0.0,
                "by_model": {},
                "by_day": [],
                "top_consumer": None
            },
            "yesterday": {
                "total_tokens": 0,
                "total_cost": 0.0,
                "by_model": {},
                "by_day": [],
                "top_consumer": None
            },
            "billing": {},
            "generated_at": datetime.now(_IST).isoformat(),
            "period": {
                "start": datetime.now(_IST).replace(day=1).strftime("%Y-%m-%d"),
                "end": datetime.now(_IST).strftime("%Y-%m-%d")
            }
        }


def format_telegram_report(report: Dict) -> str:
    """
    Format usage report for Telegram

    Args:
        report: Comprehensive report from get_comprehensive_report()

    Returns:
        Formatted text for Telegram
    """
    usage = report.get("usage", {})
    billing = report.get("billing", {})
    yesterday = report.get("yesterday", {})

    lines = ["🤖 <b>Claude API Usage Report</b>\n"]

    # Billing info
    if billing:
        credits_remaining = billing.get("credits_remaining", 0)
        credits_limit = billing.get("credits_limit", 0)
        credits_used = credits_limit - credits_remaining if credits_limit else 0
        usage_pct = (credits_used / credits_limit * 100) if credits_limit else 0

        lines.append("<b>💳 Account Balance</b>")
        lines.append(f"Credits Used: ${credits_used:,.2f} / ${credits_limit:,.2f}")
        lines.append(f"Remaining: ${credits_remaining:,.2f} ({100-usage_pct:.1f}%)\n")

    # Current month usage
    lines.append(f"<b>📊 This Month ({report.get('period', {}).get('start', 'N/A')} to {report.get('period', {}).get('end', 'N/A')})</b>")
    lines.append(f"Total Tokens: {usage.get('total_tokens', 0):,}")
    lines.append(f"Total Cost: ${usage.get('total_cost', 0):,.2f}\n")

    # Yesterday's usage
    if yesterday.get("total_tokens", 0) > 0:
        lines.append("<b>📅 Yesterday</b>")
        lines.append(f"Tokens: {yesterday.get('total_tokens', 0):,}")
        lines.append(f"Cost: ${yesterday.get('total_cost', 0):,.2f}\n")

    # By model breakdown
    by_model = usage.get("by_model", {})
    if by_model:
        lines.append("<b>🔧 Usage by Model</b>")
        for model, stats in sorted(by_model.items(), key=lambda x: x[1]["total_tokens"], reverse=True):
            lines.append(
                f"• {model}: {stats['total_tokens']:,} tokens (${stats['cost_usd']:.2f})"
            )
        lines.append("")

    # Top consumer
    top = usage.get("top_consumer")
    if top:
        lines.append(f"🏆 <b>Top Consumer:</b> {top}\n")

    # Timestamp
    lines.append(f"<i>Generated at {datetime.now(_IST).strftime('%d %b %Y, %I:%M %p IST')}</i>")

    return "\n".join(lines)
