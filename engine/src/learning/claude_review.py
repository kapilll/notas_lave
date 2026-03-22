"""
Claude Weekly Review — AI analyzes the trade journal and sends insights.

HOW IT WORKS:
1. Pull analysis from the learning engine (strategy×instrument, regime, hours)
2. Send the analysis to Claude as structured data
3. Claude generates a human-readable report with:
   - What worked this week (top strategies, best instruments)
   - What failed (worst performers, losing patterns)
   - Specific recommendations (weight changes, blacklist, schedule)
   - Risk warnings (DD trend, overtrading, consistency rule)
4. Report is sent via Telegram so you can read it on your phone

WHY CLAUDE DOES THIS:
- Raw numbers are hard to interpret. "RSI Div: 68% WR, $2.3K P&L" is data.
  "RSI Divergence is your best strategy on Gold during London session.
   Consider increasing its weight in trending regimes." is insight.
- Claude spots patterns humans miss across multiple dimensions
- The report creates accountability — you review performance weekly

USAGE:
- Triggered manually: POST /api/learning/review
- Scheduled: Can be set up as a weekly cron job
- Telegram: Report is sent as a readable summary
"""

import json
import logging
from datetime import datetime, timezone
from ..config import config

logger = logging.getLogger(__name__)
from .analyzer import run_full_analysis
from .recommendations import generate_all_recommendations


REVIEW_SYSTEM_PROMPT = """You are the performance analyst for Notas Lave, an AI trading co-pilot.

You receive trading performance data from the learning engine. Your job is to produce a clear, actionable weekly review.

FORMAT YOUR RESPONSE AS A TELEGRAM MESSAGE using Markdown:
- Use *bold* for section headers
- Use `code` for numbers and strategy names
- Keep it concise — this will be read on a phone
- Maximum 2000 characters

SECTIONS TO INCLUDE:
1. *Performance Summary* — Total trades, win rate, P&L, max drawdown
2. *Top Performers* — Best 2-3 strategies by P&L, and on which instruments
3. *Underperformers* — Worst 1-2 strategies that should be reviewed
4. *Key Insight* — One actionable finding (e.g., "Your win rate drops 20% during volatile regimes")
5. *Recommendation* — One specific action to take this week

RULES:
- Be direct and specific, not generic
- Reference actual numbers from the data
- If there aren't enough trades for meaningful analysis, say so
- Don't sugarcoat — if performance is bad, explain why and what to change
- End with an encouraging but honest note
"""


def build_review_prompt(analysis: dict, recommendations: dict) -> str:
    """Build the prompt with all analysis data for Claude to interpret."""
    lines = ["TRADING PERFORMANCE DATA FOR REVIEW:", ""]

    # Overall stats
    overall = analysis.get("overall", {}).get("overall", {})
    lines.append("=== OVERALL ===")
    lines.append(f"Total trades: {overall.get('trades', 0)}")
    lines.append(f"Win rate: {overall.get('win_rate', 0)}%")
    lines.append(f"Net P&L: ${overall.get('total_pnl', 0):.2f}")
    lines.append(f"Profit factor: {overall.get('profit_factor', 0):.2f}")
    lines.append(f"Avg win: ${overall.get('avg_win', 0):.2f}")
    lines.append(f"Avg loss: ${overall.get('avg_loss', 0):.2f}")
    lines.append(f"Max drawdown: {overall.get('max_drawdown_pct', 0):.1f}%")
    lines.append("")

    # Strategy breakdown
    strat_breakdown = analysis.get("overall", {}).get("strategy_breakdown", {})
    if strat_breakdown:
        lines.append("=== STRATEGY BREAKDOWN ===")
        for name, stats in strat_breakdown.items():
            lines.append(
                f"  {name}: {stats['trades']} trades, "
                f"{stats['win_rate']}% WR, ${stats['total_pnl']:.2f} P&L, "
                f"PF {stats['profit_factor']:.2f}"
            )
        lines.append("")

    # By instrument
    by_instrument = analysis.get("by_instrument", {})
    if by_instrument:
        lines.append("=== BY INSTRUMENT ===")
        for symbol, strats in by_instrument.items():
            lines.append(f"  {symbol}:")
            for strat_name, stats in sorted(strats.items(), key=lambda x: x[1]['total_pnl'], reverse=True):
                lines.append(
                    f"    {strat_name}: {stats['trades']}t, "
                    f"{stats['win_rate']}% WR, ${stats['total_pnl']:.2f}"
                )
        lines.append("")

    # By regime
    by_regime = analysis.get("by_regime", {})
    if by_regime:
        lines.append("=== BY REGIME ===")
        for regime, strats in by_regime.items():
            total_pnl = sum(s['total_pnl'] for s in strats.values())
            total_trades = sum(s['trades'] for s in strats.values())
            lines.append(f"  {regime}: {total_trades} trades, ${total_pnl:.2f} P&L")
        lines.append("")

    # Exit reasons
    exits = analysis.get("exit_reasons", {})
    if exits:
        lines.append("=== EXIT REASONS ===")
        for reason, data in exits.items():
            lines.append(f"  {reason}: {data.get('count', 0)} ({data.get('pct', 0)}%)")
        lines.append("")

    # Recommendations
    if recommendations.get("status") == "ready":
        blacklist = recommendations.get("blacklist_suggestions", {})
        if blacklist:
            lines.append("=== BLACKLIST SUGGESTIONS ===")
            for sym, items in blacklist.items():
                for item in items:
                    lines.append(f"  {sym}: disable {item['strategy']} — {item['reason']}")
            lines.append("")

        score = recommendations.get("score_threshold", {})
        if score:
            lines.append(f"Recommended min score: {score.get('recommended_min_score', 'N/A')}")
            lines.append(f"Best score bucket: {score.get('best_bucket', 'N/A')} (PF {score.get('best_profit_factor', 0)})")
            lines.append("")

        hours = recommendations.get("trading_hours", {})
        best_hours = hours.get("best_hours", [])
        if best_hours:
            lines.append("Best trading hours (UTC): " +
                         ", ".join(f"{h['hour_utc']}:00" for h in best_hours[:3]))
        worst_hours = hours.get("worst_hours", [])
        if worst_hours:
            lines.append("Worst trading hours (UTC): " +
                         ", ".join(f"{h['hour_utc']}:00" for h in worst_hours[:3]))

    lines.append("")
    lines.append("Generate a weekly review based on this data.")
    return "\n".join(lines)


async def generate_review() -> dict:
    """
    Generate a Claude-powered weekly review.

    Returns: {review_text, sent_telegram, analysis_summary}
    """
    # Step 1: Get analysis and recommendations
    analysis = run_full_analysis()
    recommendations = generate_all_recommendations()

    overall = analysis.get("overall", {}).get("overall", {})
    total_trades = overall.get("trades", 0)

    if total_trades < 5:
        return {
            "status": "insufficient_data",
            "message": f"Need at least 5 trades for a review. Currently have {total_trades}.",
            "review_text": None,
            "sent_telegram": False,
        }

    # Step 2: Ask Claude to generate the review
    review_text = await _call_claude_for_review(analysis, recommendations)

    # Step 3: Send via Telegram
    sent = False
    if review_text:
        from ..alerts.telegram import send_telegram
        sent = await send_telegram(review_text)

    return {
        "status": "completed",
        "review_text": review_text,
        "sent_telegram": sent,
        "total_trades_analyzed": total_trades,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


async def _call_claude_for_review(analysis: dict, recommendations: dict) -> str:
    """Call Claude to generate the review text."""
    prompt = build_review_prompt(analysis, recommendations)

    has_claude = (
        config.anthropic_api_key
        or (config.claude_provider == "vertex" and config.google_cloud_project)
    )

    if not has_claude:
        # Fallback: generate a simple text report without Claude
        return _generate_fallback_report(analysis, recommendations)

    try:
        import anthropic

        if config.claude_provider == "vertex" and config.google_cloud_project:
            client = anthropic.AnthropicVertex(
                project_id=config.google_cloud_project,
                region=config.google_cloud_region,
            )
        else:
            client = anthropic.Anthropic(api_key=config.anthropic_api_key)

        response = client.messages.create(
            model=config.claude_model,
            max_tokens=1024,
            system=REVIEW_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        # Track token usage
        try:
            from ..monitoring.token_tracker import log_token_usage, extract_usage_from_response
            tokens_in, tokens_out = extract_usage_from_response(response)
            log_token_usage(
                purpose="weekly_review",
                model=config.claude_model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )
        except Exception:
            pass

        return response.content[0].text.strip()

    except Exception as e:
        logger.error("Claude API error: %s", e)
        from ..alerts.telegram import send_error_alert
        await send_error_alert("Claude Review", f"Review generation failed: {e}")
        return _generate_fallback_report(analysis, recommendations)


def _generate_fallback_report(analysis: dict, recommendations: dict) -> str:
    """Generate a text report when Claude API is not available."""
    overall = analysis.get("overall", {}).get("overall", {})
    strat_breakdown = analysis.get("overall", {}).get("strategy_breakdown", {})

    lines = [
        "*Notas Lave Weekly Review*",
        "",
        "*Performance Summary*",
        f"Trades: `{overall.get('trades', 0)}`",
        f"Win Rate: `{overall.get('win_rate', 0):.1f}%`",
        f"Net P&L: `${overall.get('total_pnl', 0):.2f}`",
        f"Profit Factor: `{overall.get('profit_factor', 0):.2f}`",
        "",
    ]

    # Top performers
    if strat_breakdown:
        sorted_strats = sorted(strat_breakdown.items(), key=lambda x: x[1]['total_pnl'], reverse=True)
        top = sorted_strats[:2]
        bottom = sorted_strats[-2:] if len(sorted_strats) > 2 else []

        lines.append("*Top Performers*")
        for name, stats in top:
            lines.append(f"  `{name}`: {stats['win_rate']}% WR, ${stats['total_pnl']:.2f}")
        lines.append("")

        if bottom and bottom[0][1]['total_pnl'] < 0:
            lines.append("*Underperformers*")
            for name, stats in bottom:
                if stats['total_pnl'] < 0:
                    lines.append(f"  `{name}`: {stats['win_rate']}% WR, ${stats['total_pnl']:.2f}")
            lines.append("")

    # Blacklist suggestions
    bl = recommendations.get("blacklist_suggestions", {}) if recommendations.get("status") == "ready" else {}
    if bl:
        lines.append("*Action Required*")
        for sym, items in bl.items():
            for item in items:
                lines.append(f"  Consider disabling `{item['strategy']}` on {sym}")
        lines.append("")

    lines.append("_Generated by Notas Lave Learning Engine_")
    return "\n".join(lines)
