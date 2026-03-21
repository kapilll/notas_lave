"""
Per-Trade Learning — Claude analyzes every closed trade immediately.

WHAT HAPPENS WHEN A TRADE CLOSES:
1. The trade data (entry, exit, duration, regime, strategies, P&L) is sent to Claude
2. Claude analyzes: WHY did this trade win or lose?
3. Claude produces:
   - Outcome grade (A/B/C/D/F)
   - Lesson learned (specific, actionable)
   - Whether the strategy should be adjusted for this instrument
4. The grade and lesson are stored in the journal
5. These lessons feed the weekly review and weight adjustments

THIS IS HOW THE SYSTEM LEARNS:
- Static systems make the same mistakes forever
- This system asks "why did I lose?" after every single loss
- Over hundreds of trades, patterns emerge:
  "RSI Divergence loses money on ETH during VOLATILE regime"
  "Camarilla works on Gold in RANGING but fails in TRENDING"
- These patterns automatically adjust blacklists and weights

GRADING:
A = Perfect execution (TP hit, good entry, right strategy for regime)
B = Profitable but could be better (late entry, suboptimal SL)
C = Breakeven or small loss (reasonable trade, just didn't work out)
D = Bad trade (wrong regime, ignored signals, poor R:R)
F = Terrible trade (all signals conflicted, should never have entered)
"""

import json
from ..config import config
from ..execution.paper_trader import Position
from ..data.instruments import get_instrument
from ..journal.database import get_db, TradeLog


TRADE_ANALYSIS_PROMPT = """You are analyzing a completed trade from the Notas Lave autonomous trading system.

TRADE DATA:
Symbol: {symbol}
Direction: {direction}
Regime: {regime}
Entry: {entry_price} | Exit: {exit_price}
SL: {stop_loss} | TP: {take_profit}
P&L: ${pnl:.2f} ({exit_reason})
Duration: {duration_min:.0f} minutes
Strategies: {strategies}
Confluence Score: {score}/10
Max Favorable (best unrealized): ${mfe:.2f}
Max Adverse (worst unrealized): ${mae:.2f}

RESPOND WITH EXACTLY THIS JSON:
{{
  "grade": "A/B/C/D/F",
  "lesson": "One specific sentence about what this trade teaches us",
  "strategy_note": "Should any strategy be adjusted for {symbol}? Yes/No and why",
  "regime_match": "Was {regime} the right regime for these strategies? true/false"
}}
"""


async def analyze_closed_trade(position: Position) -> str | None:
    """
    Send a closed trade to Claude for analysis.

    Returns the lesson learned (string) or None if analysis fails.
    Also updates the trade journal with the grade and lesson.
    """
    spec = get_instrument(position.symbol)
    pnl = spec.calculate_pnl(
        position.entry_price, position.exit_price,
        position.position_size, position.direction.value,
    )

    # Build the analysis prompt
    prompt = TRADE_ANALYSIS_PROMPT.format(
        symbol=position.symbol,
        direction=position.direction.value,
        regime=position.regime,
        entry_price=position.entry_price,
        exit_price=position.exit_price,
        stop_loss=position.stop_loss,
        take_profit=position.take_profit,
        pnl=pnl,
        exit_reason=position.exit_reason,
        duration_min=position.duration_seconds / 60,
        strategies=", ".join(position.strategies_agreed),
        score=position.confluence_score,
        mfe=position.max_favorable,
        mae=position.max_adverse,
    )

    # Try Claude, fall back to rule-based analysis
    analysis = await _call_claude_analysis(prompt)
    if not analysis:
        analysis = _fallback_analysis(position, pnl)

    # Store in journal
    _update_journal(position.trade_log_id, analysis)

    return analysis.get("lesson", None)


async def _call_claude_analysis(prompt: str) -> dict | None:
    """Call Claude to analyze a trade. Returns parsed JSON or None."""
    has_claude = (
        config.anthropic_api_key
        or (config.claude_provider == "vertex" and config.google_cloud_project)
    )

    if not has_claude:
        return None

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
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        return json.loads(text)

    except Exception as e:
        print(f"[Learner] Claude analysis error: {e}")
        return None


def _fallback_analysis(position: Position, pnl: float) -> dict:
    """
    Rule-based trade analysis when Claude is not available.

    Simple but still useful — grades by outcome and generates basic lessons.
    """
    spec = get_instrument(position.symbol)

    # Grade by outcome
    if position.exit_reason == "tp_hit":
        grade = "A" if pnl > 0 else "C"
        lesson = f"TP hit on {position.symbol}. Strategy {position.strategies_agreed[0] if position.strategies_agreed else 'unknown'} worked in {position.regime} regime."
    elif position.exit_reason == "sl_hit":
        grade = "D" if abs(pnl) > spec.spread_typical * 3 else "C"
        lesson = f"SL hit on {position.symbol} in {position.regime} regime. Entry may have been late or regime unfavorable for {position.strategies_agreed[0] if position.strategies_agreed else 'unknown'}."
    elif position.exit_reason == "breakeven":
        grade = "B"
        lesson = f"Breakeven on {position.symbol}. Trade moved in favor then reversed — consider wider trailing stop."
    elif position.exit_reason == "timeout":
        grade = "C"
        lesson = f"Timeout on {position.symbol}. Price didn't reach TP — target may be too ambitious for this regime."
    else:
        grade = "C"
        lesson = f"Trade closed ({position.exit_reason}) on {position.symbol}."

    # Check if MFE was much larger than actual P&L (left money on table)
    if position.max_favorable > abs(pnl) * 2 and pnl <= 0:
        lesson += " MFE was much higher than final P&L — consider trailing stop instead of fixed TP."

    return {
        "grade": grade,
        "lesson": lesson,
        "strategy_note": "No change needed" if pnl > 0 else f"Monitor {position.strategies_agreed[0] if position.strategies_agreed else 'unknown'} on {position.symbol}",
        "regime_match": pnl > 0,
    }


def _update_journal(trade_log_id: int, analysis: dict):
    """Store the analysis results in the trade journal."""
    if not trade_log_id:
        return

    try:
        db = get_db()
        trade = db.query(TradeLog).filter(TradeLog.id == trade_log_id).first()
        if trade:
            trade.outcome_grade = analysis.get("grade", "C")
            trade.lessons_learned = analysis.get("lesson", "")
            db.commit()
    except Exception as e:
        print(f"[Learner] Journal update error: {e}")
