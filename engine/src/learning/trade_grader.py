"""Auto-grade closed trades and generate lessons — no Claude API needed.

Every closed trade gets:
- outcome_grade: A/B/C/D/F based on P&L vs risk, execution quality
- lessons_learned: Pattern-based insight about what worked/failed

This runs on every trade close, giving the Strategy Lab immediate
feedback without waiting for daily reviews.

GRADING SYSTEM:
  A = Excellent (TP hit + extended, or P&L > 2R)
  B = Good (TP hit, or P&L > 1R)
  C = Breakeven/small win (P&L between -0.5R and 1R)
  D = Loss (SL hit, P&L between -1R and -0.5R)
  F = Bad loss (P&L < -1R, or bad exit like SL=0)

LESSON CATEGORIES:
  - Entry timing (too early, too late, well-timed)
  - Exit quality (TP hit cleanly, SL hit fast, trailed well)
  - Strategy-regime fit (strategy X works in Y regime)
  - Risk management (position sized correctly, R:R was good/bad)
"""

import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def grade_trade(
    pnl: float,
    entry_price: float,
    exit_price: float,
    stop_loss: float,
    take_profit: float,
    direction: str,
    exit_reason: str,
    duration_seconds: int = 0,
    tp_extensions: int = 0,
    max_favorable: float = 0.0,
) -> str:
    """Grade a closed trade A-F based on P&L quality.

    Uses R-multiples (risk units) for grading so the grade is
    independent of position size. A $10 win on a $5 risk is
    the same grade as a $100 win on a $50 risk.
    """
    if entry_price <= 0 or stop_loss <= 0:
        return "F"  # Invalid data

    # Calculate risk in price units
    risk = abs(entry_price - stop_loss)
    if risk <= 0:
        return "F"

    # P&L in R-multiples (how many risks you made/lost)
    r_multiple = pnl / risk if risk > 0 else 0

    # Grade based on R-multiple and exit quality
    if exit_reason in ("tp_hit", "extended_tp") and pnl > 0:
        if tp_extensions > 0 or r_multiple >= 2.0:
            return "A"  # Extended TP or 2R+ profit
        return "B"  # Clean TP hit

    if exit_reason == "smart_exit" and pnl > 0:
        return "B"  # Good exit based on momentum

    if pnl > 0 and r_multiple >= 1.0:
        return "B"  # Profitable, at least 1R

    if pnl >= 0 or (pnl < 0 and abs(r_multiple) < 0.5):
        return "C"  # Breakeven or tiny loss

    if exit_reason in ("sl_hit", "trailing_sl") and r_multiple >= -1.1:
        return "D"  # Normal SL hit, contained loss

    return "F"  # Bad loss (> 1R or bad exit)


def generate_lesson(
    symbol: str,
    direction: str,
    entry_price: float,
    exit_price: float,
    stop_loss: float,
    take_profit: float,
    exit_reason: str,
    pnl: float,
    duration_seconds: int,
    strategies: list[str],
    regime: str,
    timeframe: str,
    grade: str,
    max_favorable: float = 0.0,
    max_adverse: float = 0.0,
    tp_extensions: int = 0,
    trailing_active: bool = False,
) -> str:
    """Generate a concise, pattern-based lesson for a closed trade.

    Not Claude-powered — uses rules to identify common patterns.
    Returns a 1-2 sentence insight.
    """
    parts = []
    strategy_name = strategies[0] if strategies else "unknown"
    risk = abs(entry_price - stop_loss) if stop_loss > 0 else 0
    duration_min = duration_seconds // 60 if duration_seconds else 0

    # 1. Exit quality
    if exit_reason == "tp_hit" and tp_extensions > 0:
        parts.append(f"TP extended {tp_extensions}x — trend was strong")
    elif exit_reason == "tp_hit":
        parts.append("Clean TP hit")
    elif exit_reason == "extended_tp":
        parts.append(f"Extended TP hit after {tp_extensions} extensions — runner worked")
    elif exit_reason == "trailing_sl" and pnl > 0:
        parts.append("Trailing SL locked profit after reversal — good defense")
    elif exit_reason == "trailing_sl" and pnl <= 0:
        parts.append("Trailed to breakeven then reversed — flat/small loss")
    elif exit_reason == "smart_exit":
        parts.append("Exited on momentum reversal signal")
    elif exit_reason == "sl_hit" and duration_min < 5:
        parts.append(f"SL hit in {duration_min}m — entry timing was too early")
    elif exit_reason == "sl_hit" and duration_min < 30:
        parts.append("SL hit quickly — check if entry was in range zone")
    elif exit_reason == "sl_hit":
        parts.append("SL hit — directional call was wrong")

    # 2. MFE/MAE insight (did we leave money on the table?)
    if max_favorable > 0 and pnl < 0 and risk > 0:
        mfe_r = max_favorable / risk
        if mfe_r > 1.0:
            parts.append(f"Was up {mfe_r:.1f}R before reversing — consider tighter trail")

    if max_adverse < 0 and pnl > 0 and risk > 0:
        mae_r = abs(max_adverse) / risk
        if mae_r > 0.8:
            parts.append(f"Drawdown reached {mae_r:.1f}R — survived but entry was shaky")

    # 3. Strategy-regime insight
    if regime and regime != "unknown":
        if grade in ("A", "B"):
            parts.append(f"{strategy_name} works in {regime} on {timeframe}")
        elif grade == "F":
            parts.append(f"{strategy_name} struggles in {regime} — consider skipping")

    # 4. Duration insight
    if grade in ("A", "B") and duration_min > 240:
        parts.append("Patience paid off — held for 4h+")
    elif grade in ("D", "F") and duration_min < 2:
        parts.append("Closed in under 2 min — possible noise trade")

    if not parts:
        if pnl > 0:
            parts.append(f"{strategy_name} on {symbol} {timeframe}: profitable trade")
        else:
            parts.append(f"{strategy_name} on {symbol} {timeframe}: loss taken")

    return ". ".join(parts[:3]) + "."


def grade_and_learn(trade_data: dict) -> tuple[str, str]:
    """Grade a trade and generate its lesson. Returns (grade, lesson).

    Args:
        trade_data: dict with keys matching TradeLog columns
    """
    # Parse strategies from JSON if needed
    strategies = trade_data.get("strategies_agreed", [])
    if isinstance(strategies, str):
        try:
            strategies = json.loads(strategies)
        except Exception:
            strategies = []

    grade = grade_trade(
        pnl=trade_data.get("pnl", 0) or 0,
        entry_price=trade_data.get("entry_price", 0) or 0,
        exit_price=trade_data.get("exit_price", 0) or 0,
        stop_loss=trade_data.get("stop_loss", 0) or 0,
        take_profit=trade_data.get("take_profit", 0) or 0,
        direction=trade_data.get("direction", "LONG"),
        exit_reason=trade_data.get("exit_reason", ""),
        duration_seconds=trade_data.get("duration_seconds", 0) or 0,
        tp_extensions=trade_data.get("tp_extensions", 0) or 0,
        max_favorable=trade_data.get("max_favorable", 0) or 0,
    )

    lesson = generate_lesson(
        symbol=trade_data.get("symbol", "?"),
        direction=trade_data.get("direction", "LONG"),
        entry_price=trade_data.get("entry_price", 0) or 0,
        exit_price=trade_data.get("exit_price", 0) or 0,
        stop_loss=trade_data.get("stop_loss", 0) or 0,
        take_profit=trade_data.get("take_profit", 0) or 0,
        exit_reason=trade_data.get("exit_reason", ""),
        pnl=trade_data.get("pnl", 0) or 0,
        duration_seconds=trade_data.get("duration_seconds", 0) or 0,
        strategies=strategies,
        regime=trade_data.get("regime", "unknown") or "unknown",
        timeframe=trade_data.get("timeframe", "?") or "?",
        grade=grade,
        max_favorable=trade_data.get("max_favorable", 0) or 0,
        max_adverse=trade_data.get("max_adverse", 0) or 0,
        tp_extensions=trade_data.get("tp_extensions", 0) or 0,
    )

    return grade, lesson
