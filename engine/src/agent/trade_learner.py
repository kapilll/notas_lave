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

import asyncio
import json
import logging
from ..config import config

logger = logging.getLogger(__name__)
from ..execution.paper_trader import Position
from ..data.instruments import get_instrument
from ..journal.database import get_db, TradeLog

# CQ-23: Cache Anthropic client at module level instead of creating per-call
_claude_client = None


def _get_claude_client():
    """CQ-23: Cache Anthropic client instead of creating one per trade analysis."""
    global _claude_client
    if _claude_client is not None:
        return _claude_client

    import anthropic

    if config.claude_provider == "vertex" and config.google_cloud_project:
        _claude_client = anthropic.AnthropicVertex(
            project_id=config.google_cloud_project,
            region=config.google_cloud_region,
        )
    elif config.anthropic_api_key:
        _claude_client = anthropic.Anthropic(api_key=config.anthropic_api_key)
    return _claude_client


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

    # ML-21: Add cross-trade memory — fetch last 5 trades on the same symbol
    # so Claude can see patterns (e.g., "3 consecutive losses on ETH in VOLATILE")
    recent_context = ""
    try:
        db = get_db()
        recent = db.query(TradeLog).filter(
            TradeLog.symbol == position.symbol,
            TradeLog.exit_price.isnot(None),
            TradeLog.id != position.trade_log_id,
        ).order_by(TradeLog.id.desc()).limit(5).all()
        if recent:
            lines = []
            for r in recent:
                r_pnl = r.pnl or 0.0
                r_grade = r.outcome_grade or "?"
                r_reason = r.exit_reason or "?"
                lines.append(f"  {r.direction} {r.symbol}: P&L ${r_pnl:.2f} ({r_reason}), grade={r_grade}")
            recent_context = f"\n\nRECENT TRADES ON {position.symbol}:\n" + "\n".join(lines)
    except Exception:
        pass

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
    # ML-21: Append cross-trade context after the main trade data
    if recent_context:
        prompt += recent_context

    # Try Claude, fall back to rule-based analysis
    analysis = await _call_claude_analysis(prompt)
    if analysis and not _validate_claude_response(analysis):
        analysis = None  # Validation failed, fall back to rule-based
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
        # CQ-23: Use cached client instead of creating a new one per call
        client = _get_claude_client()
        if client is None:
            return None

        # CQ-12 FIX: Wrap synchronous Claude API call in asyncio.to_thread()
        # to avoid blocking the async event loop for 2-10s during API calls.
        response = await asyncio.to_thread(
            client.messages.create,
            model=config.claude_model,
            max_tokens=512,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )

        # Track token usage
        try:
            from ..monitoring.token_tracker import log_token_usage, extract_usage_from_response
            tokens_in, tokens_out = extract_usage_from_response(response)
            log_token_usage(
                purpose="trade_analysis",
                model=config.claude_model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )
        except Exception as e:
            logger.debug("Non-critical error tracking tokens: %s", e)

        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        return json.loads(text)

    except Exception as e:
        logger.error("Claude analysis error: %s", e)
        from ..alerts.telegram import send_error_alert
        await send_error_alert("Trade Learner", f"Claude API failed: {e}")
        return None


_validation_failure_count = 0


def _validate_claude_response(analysis: dict) -> bool:
    """E-02: Validate Claude's trade grading response before storing.

    Returns True if valid, False if validation fails.
    """
    global _validation_failure_count
    issues = []

    # grade must be exactly one of A, B, C, D, F
    grade = analysis.get("grade")
    if grade not in ("A", "B", "C", "D", "F"):
        issues.append(f"invalid grade '{grade}' (must be A/B/C/D/F)")

    # lesson must be a non-empty string, max 500 chars
    lesson = analysis.get("lesson")
    if not isinstance(lesson, str) or not lesson.strip():
        issues.append("lesson is missing or empty")
    elif len(lesson) > 500:
        issues.append(f"lesson too long ({len(lesson)} chars, max 500)")

    # strategy_note must be a non-empty string if present
    if "strategy_note" in analysis:
        note = analysis["strategy_note"]
        if not isinstance(note, str) or not note.strip():
            issues.append("strategy_note is present but empty")

    # regime_match must be a boolean if present
    if "regime_match" in analysis:
        rm = analysis["regime_match"]
        if not isinstance(rm, bool):
            issues.append(f"regime_match is '{rm}' (must be boolean)")

    if issues:
        _validation_failure_count += 1
        logger.warning(
            "Claude response failed validation (failure #%d): %s",
            _validation_failure_count, "; ".join(issues),
        )
        return False

    return True


def _fallback_analysis(position: Position, pnl: float) -> dict:
    """
    Rule-based trade analysis when Claude is not available.

    ML-22/TP-04 FIX: Grade by PROCESS QUALITY (confluence score + R:R),
    not just outcome. The old approach gave A for TP hit and D for SL hit,
    which is outcome-biased — a high-quality setup that hits SL is bad luck
    (grade C), not a bad trade. A low-quality setup that hits TP is lucky
    (grade B), not a great trade. This prevents the learning engine from
    penalizing good process and rewarding lucky outcomes.
    """
    spec = get_instrument(position.symbol)
    strategy_name = position.strategies_agreed[0] if position.strategies_agreed else "unknown"

    # Process quality metrics
    score = position.confluence_score  # 0-10 scale
    risk = abs(position.entry_price - position.stop_loss) if position.stop_loss else 0
    reward = abs(position.take_profit - position.entry_price) if position.take_profit else 0
    rr_ratio = reward / risk if risk > 0 else 0
    high_quality = score >= 7 and rr_ratio >= 2.0
    low_quality = score < 5 or rr_ratio < 1.5

    # Grade by process + outcome combination
    if position.exit_reason == "tp_hit":
        if high_quality:
            grade = "A"  # Good process, good outcome
            lesson = f"TP hit on {position.symbol}. High-quality setup (score={score:.0f}, R:R={rr_ratio:.1f}) confirmed in {position.regime} regime."
        elif low_quality:
            grade = "B"  # Lucky win, weak setup
            lesson = f"TP hit on {position.symbol} but weak setup (score={score:.0f}, R:R={rr_ratio:.1f}). Don't mistake luck for edge."
        else:
            grade = "B"  # Decent setup, good outcome
            lesson = f"TP hit on {position.symbol}. Strategy {strategy_name} worked in {position.regime} regime."
    elif position.exit_reason == "sl_hit":
        if high_quality:
            grade = "C"  # Good process, bad luck
            lesson = f"SL hit on {position.symbol} despite strong setup (score={score:.0f}, R:R={rr_ratio:.1f}). Good process, bad luck — keep trading this setup."
        elif low_quality:
            grade = "D"  # Bad process, bad outcome
            lesson = f"SL hit on {position.symbol} with weak setup (score={score:.0f}, R:R={rr_ratio:.1f}) in {position.regime}. Should have been filtered."
        else:
            grade = "C"  # Average setup, loss is normal variance
            lesson = f"SL hit on {position.symbol} in {position.regime} regime. Normal variance for {strategy_name}."
    elif position.exit_reason == "breakeven":
        grade = "B"
        lesson = f"Breakeven on {position.symbol}. Trade moved in favor then reversed — consider wider trailing stop."
    elif position.exit_reason == "timeout":
        grade = "C"
        lesson = f"Timeout on {position.symbol}. Price didn't reach TP — target may be too ambitious for this regime."
    else:
        grade = "C"
        lesson = f"Trade closed ({position.exit_reason}) on {position.symbol}."

    # TP-01: Detect "lucky wins" — TP hit but MFE barely exceeded TP
    # This breaks the self-confirming learning loop: a trade that JUST
    # scraped its TP before reversing is lucky, not a validated setup.
    if position.exit_reason == "tp_hit" and position.max_favorable > 0 and risk > 0:
        tp_distance = abs(position.take_profit - position.entry_price)
        tp_pnl_equivalent = tp_distance * spec.contract_size * position.position_size
        mfe_beyond_tp = position.max_favorable - tp_pnl_equivalent
        if tp_pnl_equivalent > 0 and mfe_beyond_tp < tp_pnl_equivalent * 0.1:
            lesson += " LUCKY WIN: MFE barely exceeded TP — price reversed immediately after hitting target."
            if grade == "A":
                grade = "B"  # Downgrade lucky wins

    # Check if MFE was much larger than actual P&L (left money on table)
    if position.max_favorable > abs(pnl) * 2 and pnl <= 0:
        lesson += " MFE was much higher than final P&L — consider trailing stop instead of fixed TP."

    return {
        "grade": grade,
        "lesson": lesson,
        "strategy_note": "No change needed" if pnl > 0 else f"Monitor {strategy_name} on {position.symbol}",
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
            # Store the FULL analysis dict (grade, lesson, strategy_note,
            # regime_match) as JSON so no fields are lost. Previously only
            # the lesson text was saved, discarding strategy_note and
            # regime_match which are needed by the learning engine (ML-02).
            trade.lessons_learned = json.dumps(analysis)
            db.commit()
    except Exception as e:
        logger.exception("Journal update error: %s", e)
