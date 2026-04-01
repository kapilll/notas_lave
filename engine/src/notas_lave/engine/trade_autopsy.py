"""
Trade Autopsy — AI-powered post-trade analysis.

After every trade closes, an expert analysis is generated explaining:
- Market context and regime at entry/exit
- Why key levels held or failed
- What the strategy got right or wrong
- Actionable lessons for strategy improvement

Reports are saved to:
  1. TradeLog.lessons_learned (DB column, queryable)
  2. data/autopsies/{date}_trade{id}_{symbol}_{direction}.md (file, human-readable)
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..core.events import TradeClosed

logger = logging.getLogger(__name__)

AUTOPSIES_DIR = Path(__file__).parent.parent.parent.parent / "data" / "autopsies"

_AUTOPSY_PROMPT = """\
You are APEX — an expert crypto scalper and quant with 15 years of experience. \
Perform a ruthlessly honest post-trade autopsy. Be blunt. Numbers over adjectives.

COMPLETED TRADE #{trade_id}
  Symbol:    {symbol} {direction}
  Entry:     {entry_price} | Exit: {exit_price} | P&L: ${pnl:+.2f}
  SL:        {stop_loss} | TP: {take_profit} | R:R: {rr:.2f}
  Duration:  {duration_min:.0f} minutes | Exit: {exit_reason} | Grade: {grade}
  Strategy:  {strategy} (signal score: {score:.0f})
  Factors:   {factors}
  Regime:    {regime}
  Competing: {competing} other strategies also wanted this trade

RECENT 15M CANDLES — {symbol} (last 20, oldest first):
{candle_table}

PROVIDE (be specific, use exact price levels from the candle data):

## 1. Market Context at Entry
What was price doing? Trending, ranging, at a key level? Where was price relative to \
the VWAP, session highs/lows, or round numbers visible in the candles?

## 2. Entry Quality
Were the factors ({factors}) actually confirmed in the candle data? \
Was the entry well-timed or did it chase price into a move that was already done?

## 3. Why It {outcome}
Specific price-level explanation. What happened after entry? \
Where did momentum stall, reverse, or accelerate?

## 4. What {strategy} Missed
What context or signal was NOT captured by the strategy's factors \
that would have filtered this trade or improved the timing?

## 5. Lessons (2–3 max, actionable)
Concrete parameter or logic changes this trade suggests.

## 6. Verdict
Grade A/B/C/D. One sentence: was this a valid setup or should it have been skipped?\
"""


async def run_autopsy(event: TradeClosed) -> None:
    """Entry point — called by EventBus after TradeClosed. Errors are swallowed."""
    from ..config import config

    if not config.autopsy_enabled:
        return
    if not config.anthropic_api_key:
        logger.debug("[AUTOPSY] ANTHROPIC_API_KEY not set — skipping")
        return

    try:
        await _do_autopsy(event, config)
    except Exception as e:
        logger.warning("[AUTOPSY] Trade #%s failed: %s", event.trade_id, e)


async def _do_autopsy(event: TradeClosed, config) -> None:
    from ..journal.database import get_db, TradeLog

    db = get_db()
    try:
        trade_id_int = int(event.trade_id)
    except (ValueError, TypeError):
        logger.warning("[AUTOPSY] Non-integer trade_id: %s", event.trade_id)
        return

    trade = db.query(TradeLog).filter(TradeLog.id == trade_id_int).first()
    if not trade:
        logger.warning("[AUTOPSY] Trade #%s not found in DB", event.trade_id)
        return

    # Skip if already has an autopsy (e.g. re-processed event)
    if trade.lessons_learned:
        return

    candle_table = await _get_candle_context(event.symbol)
    prompt = _build_prompt(trade, event, candle_table)

    report = await asyncio.to_thread(
        _call_claude,
        api_key=config.anthropic_api_key,
        model=config.autopsy_model,
        max_tokens=config.edge_analysis_max_tokens,
        prompt=prompt,
    )

    if not report:
        return

    trade.lessons_learned = report
    db.commit()

    _save_to_file(trade, report)

    logger.info(
        "[AUTOPSY] Trade #%d %s %s %s — report saved (%d chars)",
        trade.id, trade.symbol, trade.direction, event.reason, len(report),
    )


def _build_prompt(trade, event: TradeClosed, candle_table: str) -> str:
    sl = trade.stop_loss or 0
    tp = trade.take_profit or 0
    entry = trade.entry_price or 0
    rr = (abs(tp - entry) / abs(sl - entry)) if sl and entry and sl != entry else 0

    factors_raw = trade.strategy_factors or "[]"
    try:
        factors_list = json.loads(factors_raw)
        factors = ", ".join(factors_list) if factors_list else "none recorded"
    except (json.JSONDecodeError, TypeError):
        factors = str(factors_raw)

    outcome = "WORKED" if event.pnl > 0 else "FAILED"

    return _AUTOPSY_PROMPT.format(
        trade_id=trade.id,
        symbol=trade.symbol,
        direction=trade.direction,
        entry_price=entry,
        exit_price=trade.exit_price or 0,
        pnl=event.pnl,
        stop_loss=sl,
        take_profit=tp,
        rr=rr,
        duration_min=(trade.duration_seconds or 0) / 60,
        exit_reason=trade.exit_reason or event.reason,
        grade=trade.outcome_grade or "?",
        strategy=trade.proposing_strategy or "unknown",
        score=trade.strategy_score or 0,
        factors=factors,
        regime=trade.regime or "unknown",
        competing=trade.competing_proposals or 0,
        candle_table=candle_table,
        outcome=outcome,
    )


def _call_claude(api_key: str, model: str, max_tokens: int, prompt: str) -> Optional[str]:
    """Synchronous Claude API call — run via asyncio.to_thread."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text
    except Exception as e:
        logger.warning("[AUTOPSY] Claude call failed: %s", e)
        return None


async def _get_candle_context(symbol: str) -> str:
    """Fetch recent 15m candles and format as a readable table."""
    try:
        from ..data.market_data import market_data
        candles = await market_data.get_candles(symbol, "15m", limit=20)
        if not candles:
            return "No candle data available"

        lines = ["Time (UTC)       Open      High      Low       Close     Volume"]
        for c in candles:
            t = datetime.fromtimestamp(c["time"], tz=timezone.utc).strftime("%m-%d %H:%M")
            lines.append(
                f"{t}  {c['open']:<10.6g}{c['high']:<10.6g}"
                f"{c['low']:<10.6g}{c['close']:<10.6g}{c['volume']:.0f}"
            )
        return "\n".join(lines)
    except Exception as e:
        logger.debug("[AUTOPSY] Candle fetch failed: %s", e)
        return "Candle data unavailable"


def _save_to_file(trade, report: str) -> None:
    """Persist autopsy report as a markdown file."""
    try:
        AUTOPSIES_DIR.mkdir(parents=True, exist_ok=True)
        closed = trade.closed_at or datetime.now(timezone.utc)
        date_str = closed.strftime("%Y%m%d")
        filename = f"{date_str}_trade{trade.id:04d}_{trade.symbol}_{trade.direction}.md"
        path = AUTOPSIES_DIR / filename

        pnl_val = trade.pnl or 0
        header = (
            f"# Trade #{trade.id} Autopsy — {trade.symbol} {trade.direction}\n\n"
            f"**Strategy:** {trade.proposing_strategy or 'unknown'}  \n"
            f"**Entry:** {trade.entry_price} | **Exit:** {trade.exit_price} | "
            f"**P&L:** ${pnl_val:+.2f}  \n"
            f"**SL:** {trade.stop_loss} | **TP:** {trade.take_profit} | "
            f"**Exit reason:** {trade.exit_reason}  \n"
            f"**Opened:** {trade.opened_at} | **Closed:** {trade.closed_at}  \n"
            f"**Grade:** {trade.outcome_grade}\n\n---\n\n"
        )
        path.write_text(header + report)
    except Exception as e:
        logger.debug("[AUTOPSY] File save failed: %s", e)
