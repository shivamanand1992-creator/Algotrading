"""
Claude API Usage Monitoring Service

Fetches usage data from Claude API and provides analytics:
- Daily/monthly token consumption
- Cost breakdown by model
- API balance tracking
- Usage trends

API Reference: https://platform.claude.com/docs/en/manage-claude/usage-cost-api
"""
import os
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from loguru import logger
import urllib.request
import urllib.error


_IST = timezone(timedelta(hours=5, minutes=30))
_ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()


def is_configured() -> bool:
    """Check if Anthropic API key is available"""
    return bool(_ANTHROPIC_API_KEY)


def _make_api_request(endpoint: str) -> Optional[Dict]:
    """Make authenticated request to Claude API"""
    if not is_configured():
        logger.warning("[ClaudeUsage] ANTHROPIC_API_KEY not configured")
        return None

    try:
        headers = {
            "x-api-key": _ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }

        req = urllib.request.Request(
            f"https://api.anthropic.com/v1/{endpoint}",
            headers=headers
        )

        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode())
                return data
            else:
                logger.error(f"[ClaudeUsage] API returned status {resp.status}")
                return None

    except urllib.error.HTTPError as e:
        try:
            error_body = e.read().decode()
            logger.error(f"[ClaudeUsage] HTTP {e.code}: {error_body}")
        except:
            logger.error(f"[ClaudeUsage] HTTP {e.code}")
        return None
    except Exception as e:
        logger.error(f"[ClaudeUsage] Request failed: {e}")
        return None


def get_usage_summary(start_date: Optional[str] = None, end_date: Optional[str] = None) -> Optional[Dict]:
    """
    Get usage summary from Claude API

    Args:
        start_date: ISO format date (YYYY-MM-DD), defaults to beginning of current month
        end_date: ISO format date (YYYY-MM-DD), defaults to today

    Returns:
        Dict with usage data or None if failed
    """
    # Default to current month if not specified
    now = datetime.now(_IST)
    if not start_date:
        start_date = now.replace(day=1).strftime("%Y-%m-%d")
    if not end_date:
        end_date = now.strftime("%Y-%m-%d")

    endpoint = f"organization/usage?start_date={start_date}&end_date={end_date}"
    logger.info(f"[ClaudeUsage] Fetching usage from {start_date} to {end_date}")

    return _make_api_request(endpoint)


def get_billing_info() -> Optional[Dict]:
    """
    Get billing and balance information

    Returns:
        Dict with billing data including:
        - credits_remaining
        - credits_limit
        - next_billing_date
    """
    logger.info("[ClaudeUsage] Fetching billing info")
    return _make_api_request("organization/billing")


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
    Get comprehensive usage report including billing and analytics

    Returns:
        Dict with:
        - usage: Current month usage analytics
        - billing: Account balance and limits
        - generated_at: Report timestamp
    """
    logger.info("[ClaudeUsage] Generating comprehensive report")

    # Get current month usage
    usage_data = get_usage_summary()
    usage_analytics = analyze_usage(usage_data) if usage_data else {}

    # Get billing info
    billing_data = get_billing_info()

    # Get yesterday's usage for daily tracking
    yesterday = (datetime.now(_IST) - timedelta(days=1)).strftime("%Y-%m-%d")
    today = datetime.now(_IST).strftime("%Y-%m-%d")
    yesterday_data = get_usage_summary(start_date=yesterday, end_date=yesterday)
    yesterday_analytics = analyze_usage(yesterday_data) if yesterday_data else {}

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
