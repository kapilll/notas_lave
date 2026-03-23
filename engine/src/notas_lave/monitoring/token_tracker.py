"""
Token & Cost Tracker — monitors Claude API usage and costs.

TWO CATEGORIES:
1. Runtime: API calls the trading engine makes for trade analysis, weekly reviews, evaluations
2. Build: Estimated cost of Claude Code sessions used to build this system (manual entry)

PRICING (approximate, Sonnet 4):
- Input:  $3.00 per million tokens
- Output: $15.00 per million tokens

WHY TRACK THIS:
- Know the ongoing cost of running the autonomous trader
- Measure if the system pays for itself (P&L vs API costs)
- Detect if Claude analysis is called too frequently (cost control)
- Track ROI: money spent building vs money earned trading
"""

import json
from datetime import datetime, timezone, timedelta, date
from ..journal.database import get_db, TokenUsage

# Pricing per million tokens (approximate)
PRICING = {
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-opus-4-6": {"input": 15.00, "output": 75.00},
}
DEFAULT_PRICING = {"input": 3.00, "output": 15.00}


def _estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    """Estimate USD cost from token counts."""
    prices = PRICING.get(model, DEFAULT_PRICING)
    cost_in = (tokens_in / 1_000_000) * prices["input"]
    cost_out = (tokens_out / 1_000_000) * prices["output"]
    return round(cost_in + cost_out, 6)


def log_token_usage(
    purpose: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
    category: str = "runtime",
    metadata: dict | None = None,
) -> int:
    """
    Log a Claude API call with token counts.

    Called after every Claude API call in the system.
    Returns the log ID.
    """
    cost = _estimate_cost(model, tokens_in, tokens_out)

    db = get_db()
    entry = TokenUsage(
        category=category,
        purpose=purpose,
        model=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        estimated_cost_usd=cost,
        metadata_json=json.dumps(metadata) if metadata else None,
    )
    db.add(entry)
    db.commit()
    return entry.id


def log_build_cost(
    tokens_in: int = 0,
    tokens_out: int = 0,
    estimated_cost: float = 0.0,
    description: str = "",
) -> int:
    """
    Manually log build cost (Claude Code session).

    Since we can't automatically detect Claude Code usage from within the engine,
    this allows manual entry of build session costs.
    """
    db = get_db()
    entry = TokenUsage(
        category="build",
        purpose="claude_code_session",
        model="claude-opus-4-6",
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        estimated_cost_usd=estimated_cost,
        metadata_json=json.dumps({"description": description}) if description else None,
    )
    db.add(entry)
    db.commit()
    return entry.id


def get_cost_summary(max_age_days: int = 30) -> dict:
    """
    Get a summary of all costs broken down by category and purpose.
    """
    db = get_db()

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    entries = db.query(TokenUsage).filter(
        TokenUsage.timestamp >= cutoff,
    ).all()

    if not entries:
        return {
            "status": "no_data",
            "message": "No API usage tracked yet.",
            "period_days": max_age_days,
            "runtime": {"total_cost": 0, "total_tokens_in": 0, "total_tokens_out": 0, "calls": 0},
            "build": {"total_cost": 0, "calls": 0},
        }

    # Split by category
    runtime = [e for e in entries if e.category == "runtime"]
    build = [e for e in entries if e.category == "build"]

    # Runtime breakdown by purpose
    purpose_breakdown: dict[str, dict] = {}
    for e in runtime:
        p = e.purpose or "other"
        if p not in purpose_breakdown:
            purpose_breakdown[p] = {"calls": 0, "tokens_in": 0, "tokens_out": 0, "cost": 0.0}
        purpose_breakdown[p]["calls"] += 1
        purpose_breakdown[p]["tokens_in"] += e.tokens_in or 0
        purpose_breakdown[p]["tokens_out"] += e.tokens_out or 0
        purpose_breakdown[p]["cost"] += e.estimated_cost_usd or 0.0

    for p in purpose_breakdown:
        purpose_breakdown[p]["cost"] = round(purpose_breakdown[p]["cost"], 4)

    runtime_total_cost = sum(e.estimated_cost_usd or 0 for e in runtime)
    build_total_cost = sum(e.estimated_cost_usd or 0 for e in build)

    return {
        "status": "ready",
        "period_days": max_age_days,
        "runtime": {
            "total_cost": round(runtime_total_cost, 4),
            "total_tokens_in": sum(e.tokens_in or 0 for e in runtime),
            "total_tokens_out": sum(e.tokens_out or 0 for e in runtime),
            "calls": len(runtime),
            "by_purpose": purpose_breakdown,
        },
        "build": {
            "total_cost": round(build_total_cost, 4),
            "calls": len(build),
        },
        "total_cost": round(runtime_total_cost + build_total_cost, 4),
    }


def get_cost_history(max_age_days: int = 30) -> dict:
    """
    Get daily cost history for graphing.
    Returns cost per day for both runtime and build.
    """
    db = get_db()

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    entries = db.query(TokenUsage).filter(
        TokenUsage.timestamp >= cutoff,
    ).order_by(TokenUsage.timestamp.asc()).all()

    daily: dict[str, dict] = {}
    for e in entries:
        day = e.timestamp.strftime("%Y-%m-%d") if e.timestamp else "unknown"
        if day not in daily:
            daily[day] = {"runtime_cost": 0.0, "build_cost": 0.0, "runtime_calls": 0, "build_calls": 0, "tokens_in": 0, "tokens_out": 0}
        if e.category == "runtime":
            daily[day]["runtime_cost"] += e.estimated_cost_usd or 0
            daily[day]["runtime_calls"] += 1
        else:
            daily[day]["build_cost"] += e.estimated_cost_usd or 0
            daily[day]["build_calls"] += 1
        daily[day]["tokens_in"] += e.tokens_in or 0
        daily[day]["tokens_out"] += e.tokens_out or 0

    points = []
    for day in sorted(daily.keys()):
        d = daily[day]
        points.append({
            "date": day,
            "runtime_cost": round(d["runtime_cost"], 4),
            "build_cost": round(d["build_cost"], 4),
            "total_cost": round(d["runtime_cost"] + d["build_cost"], 4),
            "runtime_calls": d["runtime_calls"],
            "tokens_in": d["tokens_in"],
            "tokens_out": d["tokens_out"],
        })

    return {
        "status": "ready",
        "period_days": max_age_days,
        "points": points,
    }


def extract_usage_from_response(response) -> tuple[int, int]:
    """
    Extract token counts from an Anthropic API response.

    Works with both direct Anthropic and Vertex AI responses.
    The response.usage object has input_tokens and output_tokens.
    """
    try:
        usage = response.usage
        return usage.input_tokens, usage.output_tokens
    except (AttributeError, TypeError):
        return 0, 0
