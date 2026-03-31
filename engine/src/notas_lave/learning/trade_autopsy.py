"""Trade Autopsy — automatic post-trade analysis + weekly edge analysis.

Phase 1: Per-trade reports (Claude Sonnet, ~$0.015/report)
Phase 2: Weekly edge analysis (Claude Sonnet, ~$0.030/week)

After every TradeClosed event:
1. Gather context from TradeLog + leaderboard (pure Python, zero API calls)
2. Optionally call Claude Sonnet for structured JSON analysis (~$0.015/report)
3. Save markdown report to data/trade_reports/YYYY-MM/
4. Send 2-line summary to Telegram

Skip conditions:
- Grade C (breakeven) — nothing to learn
- Duration < 60s — noise
- Duplicate symbol within 5 minutes — de-duplicate bursts

Fallback: if no Claude API key configured, saves rule-based report using
grade_and_learn() output instead of calling Claude.

Module design from: docs/research/COPILOT-DESIGN.md, Panel 7
"""

import json
import logging
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# Module-level imports — kept here so tests can patch them cleanly
from ..config import config
from ..journal.database import get_db, TradeLog
from ..engine.leaderboard import StrategyLeaderboard
from ..alerts.telegram import send_telegram

# Module-level duplicate tracker: {symbol: last_report_time}
_recent_reports: dict[str, datetime] = {}
_DUPLICATE_WINDOW_SECONDS = 300  # 5 minutes

# Haiku system prompt — reused every call (prompt caching kicks in after first call)
_HAIKU_SYSTEM_PROMPT = """You are a trading post-mortem analyst. Given a closed trade's pre-computed data, produce a structured JSON analysis. Be specific about what signal or condition caused success or failure. Identify one repeatable edge or anti-pattern.

Output ONLY valid JSON with these exact keys:
- verdict: one of CLEAN_WIN, TREND_CONTINUATION, COUNTER_TREND_FAILURE, NOISE_STOPPED, SL_TOO_TIGHT, REGIME_MISMATCH, GOOD_ENTRY_EARLY_EXIT, DIVERSITY_INFLATION, EDGE_TRADE, RANDOM_LOSS
- what_worked: 1 sentence, specific (name indicators/conditions)
- what_failed: 1 sentence, specific (name what went wrong)
- edge_signal: the condition pattern that led to this outcome
- improvement: 1 concrete actionable change
- confidence: 1-10 how certain you are about the verdict"""


def _data_dir() -> Path:
    """Returns engine/data/trade_reports/ directory."""
    # __file__ is at .../engine/src/notas_lave/learning/trade_autopsy.py
    # Go up 4 levels to reach engine/
    engine_dir = Path(__file__).resolve().parent.parent.parent.parent
    return engine_dir / "data" / "trade_reports"


def gather_trade_context(event) -> dict:
    """Read TradeLog + leaderboard and return compact context dict.

    Pure Python — no API calls. Falls back gracefully if DB or leaderboard
    are unavailable.
    """
    trade_id_str = str(event.trade_id)
    try:
        trade_id_int = int(trade_id_str)
    except ValueError:
        trade_id_int = 0

    ctx: dict = {
        "trade_id": trade_id_str,
        "symbol": event.symbol,
        "direction": event.direction,
        "entry_price": event.entry_price,
        "exit_price": event.exit_price,
        "pnl": event.pnl,
        "reason": event.reason,
        "timestamp": (
            event.timestamp.isoformat()
            if hasattr(event.timestamp, "isoformat")
            else str(event.timestamp)
        ),
        # Defaults — overwritten from TradeLog if available
        "stop_loss": 0.0,
        "take_profit": 0.0,
        "position_size": 0.0,
        "outcome_grade": "?",
        "duration_seconds": 0,
        "proposing_strategy": "unknown",
        "strategy_score": 0.0,
        "strategy_factors": "",
        "regime": "unknown",
        "timeframe": "?",
        "lessons_learned": "",
        # Leaderboard defaults
        "trust_score": 50.0,
        "win_rate": 0.0,
        "current_streak": 0,
        "total_trades": 0,
        # Computed
        "r_multiple": 0.0,
    }

    # Read from TradeLog
    if trade_id_int > 0:
        try:
            db = get_db()
            sql_trade = db.query(TradeLog).filter(TradeLog.id == trade_id_int).first()
            if sql_trade:
                ctx["stop_loss"] = sql_trade.stop_loss or 0.0
                ctx["take_profit"] = sql_trade.take_profit or 0.0
                ctx["position_size"] = sql_trade.position_size or 0.0
                ctx["outcome_grade"] = sql_trade.outcome_grade or "?"
                ctx["duration_seconds"] = sql_trade.duration_seconds or 0
                ctx["proposing_strategy"] = sql_trade.proposing_strategy or "unknown"
                ctx["strategy_score"] = sql_trade.strategy_score or 0.0
                ctx["strategy_factors"] = sql_trade.strategy_factors or ""
                ctx["regime"] = sql_trade.regime or "unknown"
                ctx["timeframe"] = sql_trade.timeframe or "?"
                ctx["lessons_learned"] = sql_trade.lessons_learned or ""
        except Exception as e:
            logger.warning("[Autopsy] Could not read TradeLog for #%s: %s", trade_id_str, e)

    # Compute R-multiple
    risk = abs(ctx["entry_price"] - ctx["stop_loss"]) if ctx["stop_loss"] > 0 else 0
    if risk > 0:
        ctx["r_multiple"] = round(ctx["pnl"] / risk, 2)

    # Read from leaderboard
    strategy_name = ctx["proposing_strategy"]
    if strategy_name and strategy_name != "unknown":
        try:
            leaderboard = StrategyLeaderboard()
            rec = leaderboard.get_strategy(strategy_name)
            if rec:
                ctx["trust_score"] = rec.get("trust_score", 50.0)
                ctx["win_rate"] = rec.get("win_rate", 0.0)
                ctx["current_streak"] = rec.get("current_streak", 0)
                ctx["total_trades"] = rec.get("total_trades", 0)
        except Exception as e:
            logger.warning("[Autopsy] Could not read leaderboard for %s: %s", strategy_name, e)

    return ctx


def should_generate_report(context: dict) -> bool:
    """Decide whether this trade warrants an autopsy report.

    Returns False (skip) when:
    - Grade is C (breakeven) — nothing to learn
    - Duration < 60s — noise trade
    - Same symbol already reported within 5 minutes — de-duplicate bursts
    """
    grade = context.get("outcome_grade", "?")
    if grade == "C":
        logger.debug("[Autopsy] Skipping #%s (grade C)", context.get("trade_id"))
        return False

    duration = context.get("duration_seconds", 0)
    if duration < 60:
        logger.debug(
            "[Autopsy] Skipping #%s (duration %ds < 60s)", context.get("trade_id"), duration
        )
        return False

    symbol = context.get("symbol", "")
    now = datetime.now(timezone.utc)
    last = _recent_reports.get(symbol)
    if last is not None:
        elapsed = (now - last).total_seconds()
        if elapsed < _DUPLICATE_WINDOW_SECONDS:
            logger.debug(
                "[Autopsy] Skipping #%s (duplicate %s within %ds)",
                context.get("trade_id"),
                symbol,
                int(elapsed),
            )
            return False

    return True


def build_prompt(context: dict) -> str:
    """Convert context dict to compact prompt string (~400 tokens)."""
    duration_min = context.get("duration_seconds", 0) // 60
    lines = [
        f"Trade #{context.get('trade_id')} — {context.get('symbol')} {context.get('direction')}",
        f"Grade: {context.get('outcome_grade')} | P&L: ${context.get('pnl', 0):.2f}"
        f" | R-Multiple: {context.get('r_multiple', 0):.2f}R",
        f"Duration: {duration_min}m | Exit: {context.get('reason')}",
        "",
        "PRICES",
        f"Entry: {context.get('entry_price', 0):.2f} | Exit: {context.get('exit_price', 0):.2f}"
        f" | SL: {context.get('stop_loss', 0):.2f} | TP: {context.get('take_profit', 0):.2f}",
        "",
        "STRATEGY",
        f"Strategy: {context.get('proposing_strategy')} | Signal Score: {context.get('strategy_score', 0):.1f}",
        f"Trust: {context.get('trust_score', 50):.0f}/100 | WR: {context.get('win_rate', 0):.1f}%"
        f" | Streak: {context.get('current_streak', 0):+d} | Trades: {context.get('total_trades', 0)}",
        "",
        "MARKET CONTEXT",
        f"Regime: {context.get('regime')}",
    ]

    factors = context.get("strategy_factors", "")
    if factors:
        try:
            factors_dict = json.loads(factors) if isinstance(factors, str) else factors
            if isinstance(factors_dict, dict) and factors_dict:
                factor_str = ", ".join(
                    f"{k}={v}" for k, v in list(factors_dict.items())[:5]
                )
                lines.append(f"Factors: {factor_str}")
        except Exception:
            pass

    lesson = context.get("lessons_learned", "")
    if lesson:
        lines += ["", f"RULE-BASED LESSON: {lesson}"]

    lines += ["", "Analyze this trade and respond with JSON only."]
    return "\n".join(lines)


def call_claude_haiku(system_prompt: str, user_prompt: str) -> dict:
    """Call Claude Haiku for trade analysis. Returns parsed dict.

    Returns empty dict if no API key configured or on any error.
    Token usage is logged to DB.
    """
    has_claude = config.anthropic_api_key or (
        config.claude_provider == "vertex" and config.google_cloud_project
    )
    if not has_claude:
        return {}

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
            model=config.autopsy_model,
            max_tokens=config.autopsy_max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        # Track token usage
        try:
            from ..monitoring.token_tracker import log_token_usage, extract_usage_from_response  # noqa: PLC0415
            tokens_in, tokens_out = extract_usage_from_response(response)
            log_token_usage(
                purpose="trade_autopsy",
                model=config.autopsy_model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                metadata={"symbol": ""},
            )
        except Exception as e:
            logger.warning("[Autopsy] Token tracking failed: %s", e)

        # Parse JSON response
        response_text = response.content[0].text.strip()
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
            response_text = response_text.strip()

        return json.loads(response_text)

    except json.JSONDecodeError as e:
        logger.warning("[Autopsy] Haiku returned invalid JSON: %s", e)
        return {}
    except Exception as e:
        logger.warning("[Autopsy] Haiku API error: %s", e)
        return {}


def save_report(trade_id: str, context: dict, analysis: dict, reports_dir: Path | None = None) -> Path:
    """Write trade autopsy markdown report to disk.

    File: data/trade_reports/YYYY-MM/trade_{id}_{symbol}_{direction}_{date}.md
    Returns the Path to the saved file.
    """
    base_dir = reports_dir if reports_dir is not None else _data_dir()
    now = datetime.now(timezone.utc)
    month_dir = base_dir / now.strftime("%Y-%m")
    month_dir.mkdir(parents=True, exist_ok=True)

    symbol = context.get("symbol", "UNKNOWN").replace("/", "")
    direction = context.get("direction", "UNK")
    date_str = now.strftime("%Y%m%d")
    filename = f"trade_{trade_id}_{symbol}_{direction}_{date_str}.md"
    filepath = month_dir / filename

    grade = context.get("outcome_grade", "?")
    pnl = context.get("pnl", 0)
    r_multiple = context.get("r_multiple", 0)
    duration_min = context.get("duration_seconds", 0) // 60
    strategy = context.get("proposing_strategy", "unknown")
    trust = context.get("trust_score", 50)
    score = context.get("strategy_score", 0)
    reason = context.get("reason", "")
    regime = context.get("regime", "unknown")
    entry = context.get("entry_price", 0)
    exit_p = context.get("exit_price", 0)
    sl = context.get("stop_loss", 0)
    tp = context.get("take_profit", 0)
    win_rate = context.get("win_rate", 0)
    streak = context.get("current_streak", 0)
    position_size = context.get("position_size", 0)
    timestamp_str = context.get("timestamp", now.isoformat())

    lines = [
        f"# Trade #{trade_id} — {symbol} {direction}",
        "",
        f"**Date:** {timestamp_str}",
        f"**Strategy:** {strategy} | **Trust:** {trust:.0f} | **Signal Score:** {score:.1f}",
        f"**Grade:** {grade} | **P&L:** ${pnl:.2f} | **R-Multiple:** {r_multiple:.2f}R",
        f"**Duration:** {duration_min} min | **Exit:** {reason}",
        "",
        "## Context at Entry",
        f"- Regime: {regime}",
        f"- Entry: {entry:.4f} | SL: {sl:.4f} | TP: {tp:.4f} | Exit: {exit_p:.4f}",
        f"- Strategy Win Rate: {win_rate:.1f}% | Streak: {streak:+d}",
    ]

    factors = context.get("strategy_factors", "")
    if factors:
        try:
            factors_dict = json.loads(factors) if isinstance(factors, str) else factors
            if isinstance(factors_dict, dict) and factors_dict:
                factor_str = ", ".join(
                    f"{k}={v}" for k, v in list(factors_dict.items())[:5]
                )
                lines.append(f"- Factors: {factor_str}")
        except Exception:
            pass

    if analysis:
        lines += [
            "",
            "## Claude Analysis",
            f"- **Verdict:** {analysis.get('verdict', 'UNKNOWN')}",
            f"- **What worked:** {analysis.get('what_worked', 'N/A')}",
            f"- **What failed:** {analysis.get('what_failed', 'N/A')}",
            f"- **Edge signal:** {analysis.get('edge_signal', 'N/A')}",
            f"- **Improvement:** {analysis.get('improvement', 'N/A')}",
            f"- **Confidence:** {analysis.get('confidence', 0)}/10",
        ]
    else:
        lesson = context.get("lessons_learned", "No analysis available.")
        lines += [
            "",
            "## Analysis",
            f"- **Lesson (rule-based):** {lesson}",
        ]

    lines += [
        "",
        "## Raw Data",
        f"- Entry: {entry:.4f} | Exit: {exit_p:.4f} | SL: {sl:.4f} | TP: {tp:.4f}",
        f"- Position size: {position_size} | Streak: {streak:+d} | Trust: {trust:.0f}",
    ]

    filepath.write_text("\n".join(lines), encoding="utf-8")
    logger.info("[Autopsy] Saved report: %s", filepath)
    return filepath


def format_telegram_summary(context: dict, analysis: dict) -> str:
    """Format 2-line Telegram summary. Each line < 200 chars.

    Line 1: grade emoji + trade id + symbol + direction + P&L + verdict
    Line 2: → improvement / lesson
    """
    grade = context.get("outcome_grade", "?")
    trade_id = context.get("trade_id", "?")
    symbol = context.get("symbol", "?")
    direction = context.get("direction", "?")
    pnl = context.get("pnl", 0)
    sign = "+" if pnl >= 0 else ""
    grade_emoji = {"A": "✅", "B": "✅", "C": "➖", "D": "❌", "F": "❌"}.get(grade, "❓")
    pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"

    if analysis:
        verdict = analysis.get("verdict", "UNKNOWN")
        improvement = analysis.get("improvement", "No improvement identified.")
        line1 = f"{grade_emoji} #{trade_id} {symbol} {direction} {pnl_str} ({grade}) — {verdict}"
        line2 = f"→ {improvement}"
    else:
        lesson = context.get("lessons_learned", "No analysis.")
        line1 = f"{grade_emoji} #{trade_id} {symbol} {direction} {pnl_str} ({grade})"
        line2 = f"→ {lesson}"

    return f"{line1[:200]}\n{line2[:200]}"


async def handle_trade_closed(event) -> None:
    """Event bus orchestrator: gather → check → build → analyze → save → telegram.

    Subscribed to TradeClosed via run.py. Runs after every trade closes.
    All errors are caught and logged — never crashes the engine.
    """
    if not config.autopsy_enabled:
        return

    try:
        # Step 1: Gather context from DB + leaderboard
        context = gather_trade_context(event)

        # Step 2: Should we generate a report?
        if not should_generate_report(context):
            return

        # Mark this symbol as recently reported (before API call to block duplicates)
        _recent_reports[context["symbol"]] = datetime.now(timezone.utc)

        # Step 3: Build compact prompt
        user_prompt = build_prompt(context)

        # Step 4: Call Claude Haiku (returns {} if no API key or on error)
        analysis = call_claude_haiku(_HAIKU_SYSTEM_PROMPT, user_prompt)

        # Step 5: Save report to disk
        save_report(context["trade_id"], context, analysis)

        # Step 6: Send Telegram summary
        try:
            summary = format_telegram_summary(context, analysis)
            await send_telegram(summary)
        except Exception as e:
            logger.warning("[Autopsy] Telegram send failed: %s", e)

    except Exception as e:
        logger.error(
            "[Autopsy] handle_trade_closed failed for #%s: %s",
            getattr(event, "trade_id", "?"),
            e,
        )


# ─── Phase 2: Weekly Edge Analysis ───────────────────────────────────────────

_SONNET_EDGE_SYSTEM_PROMPT = """You are a quantitative trading researcher. Given a week's pre-computed trade summary (NOT raw trades — already aggregated), identify:

1. Repeatable edges: conditions that consistently lead to profitable trades. Rank by sample size and win rate. Name exact indicators, regimes, strategies.
2. Anti-patterns: conditions that consistently lose. Same specificity.
3. Recurring failures: common themes in what_failed across trades.
4. Actionable recommendations: specific config or code changes.

Format as markdown. Be concise. Focus on statistical significance — patterns with 5+ trades are interesting, 10+ are actionable."""


def _week_dates(week: str) -> tuple[datetime, datetime]:
    """Return (monday, sunday) for ISO week string like '2026-W13'."""
    monday = datetime.strptime(f"{week}-1", "%G-W%V-%u").replace(tzinfo=timezone.utc)
    sunday = monday + timedelta(days=6)
    return monday, sunday


def _parse_report(filepath: Path) -> dict:
    """Parse a trade report markdown file into a structured dict.

    Returns dict with keys: trade_id, symbol, direction, grade, pnl,
    strategy, regime, duration_min, timestamp, verdict, what_failed, edge_signal.
    Returns empty dict if parsing fails.
    """
    try:
        text = filepath.read_text(encoding="utf-8")
    except OSError:
        return {}

    result: dict = {
        "trade_id": "", "symbol": "", "direction": "", "grade": "",
        "pnl": 0.0, "strategy": "", "regime": "", "duration_min": 0,
        "timestamp": "", "verdict": "", "what_failed": "", "edge_signal": "",
        "improvement": "",
    }

    # Title: "# Trade #42 — BTCUSD LONG"
    m = re.search(r"^# Trade #(\S+) — (\S+) (\S+)", text, re.MULTILINE)
    if m:
        result["trade_id"] = m.group(1)
        result["symbol"] = m.group(2)
        result["direction"] = m.group(3)

    # **Date:** 2026-03-31T...
    m = re.search(r"\*\*Date:\*\* (.+)", text)
    if m:
        result["timestamp"] = m.group(1).strip()

    # **Strategy:** trend_momentum | ...
    m = re.search(r"\*\*Strategy:\*\* (\S+)", text)
    if m:
        result["strategy"] = m.group(1).strip(" |")

    # **Grade:** B | **P&L:** $5.00 | ...
    m = re.search(r"\*\*Grade:\*\* (\S) \| \*\*P&L:\*\* \$?([\-\d\.]+)", text)
    if m:
        result["grade"] = m.group(1)
        try:
            result["pnl"] = float(m.group(2))
        except ValueError:
            pass

    # **Duration:** 60 min | ...
    m = re.search(r"\*\*Duration:\*\* (\d+) min", text)
    if m:
        result["duration_min"] = int(m.group(1))

    # - Regime: TRENDING
    m = re.search(r"- Regime: (\S+)", text)
    if m:
        result["regime"] = m.group(1)

    # Claude Analysis section
    m = re.search(r"- \*\*Verdict:\*\* (.+)", text)
    if m:
        result["verdict"] = m.group(1).strip()

    m = re.search(r"- \*\*What failed:\*\* (.+)", text)
    if m:
        result["what_failed"] = m.group(1).strip()

    m = re.search(r"- \*\*Edge signal:\*\* (.+)", text)
    if m:
        result["edge_signal"] = m.group(1).strip()

    m = re.search(r"- \*\*Improvement:\*\* (.+)", text)
    if m:
        result["improvement"] = m.group(1).strip()

    return result


def _find_week_reports(reports_dir: Path, week: str) -> list[Path]:
    """Find all report files that fall within the given ISO week."""
    monday, sunday = _week_dates(week)
    # Build set of YYYYMMDD date strings for the week
    week_dates = set()
    d = monday
    while d <= sunday:
        week_dates.add(d.strftime("%Y%m%d"))
        d += timedelta(days=1)

    found = []
    for month_dir in sorted(reports_dir.glob("????-??")):
        if not month_dir.is_dir():
            continue
        for f in month_dir.glob("trade_*.md"):
            # Filename: trade_{id}_{symbol}_{direction}_{YYYYMMDD}.md
            parts = f.stem.split("_")
            if len(parts) >= 5:
                date_part = parts[-1]
                if date_part in week_dates:
                    found.append(f)
    return sorted(found)


def compile_weekly_summary(reports_dir: Path | None = None, week: str | None = None) -> str:
    """Read all reports for a week and compress to ~2,000 token summary.

    Pure Python — no API calls. Aggregates by strategy, regime, verdict, hour.

    Args:
        reports_dir: base directory (defaults to _data_dir())
        week: ISO week like "2026-W13" (defaults to current week)

    Returns compact summary string ready to send to Sonnet.
    """
    base_dir = reports_dir if reports_dir is not None else _data_dir()

    if week is None:
        now = datetime.now(timezone.utc)
        year, weeknum, _ = now.isocalendar()
        week = f"{year}-W{weeknum:02d}"

    files = _find_week_reports(base_dir, week)
    if not files:
        return f"WEEK SUMMARY ({week}): No reports found."

    reports = [_parse_report(f) for f in files]
    reports = [r for r in reports if r.get("trade_id")]  # filter parse failures

    total = len(reports)
    wins = sum(1 for r in reports if r["pnl"] > 0)
    losses = total - wins
    total_pnl = sum(r["pnl"] for r in reports)

    # By strategy
    by_strategy: dict[str, dict] = {}
    for r in reports:
        s = r["strategy"] or "unknown"
        if s not in by_strategy:
            by_strategy[s] = {"wins": 0, "losses": 0, "pnl": 0.0}
        if r["pnl"] > 0:
            by_strategy[s]["wins"] += 1
        else:
            by_strategy[s]["losses"] += 1
        by_strategy[s]["pnl"] += r["pnl"]

    # By regime
    by_regime: dict[str, dict] = {}
    for r in reports:
        reg = r["regime"] or "unknown"
        if reg not in by_regime:
            by_regime[reg] = {"wins": 0, "losses": 0}
        if r["pnl"] > 0:
            by_regime[reg]["wins"] += 1
        else:
            by_regime[reg]["losses"] += 1

    # By verdict
    verdict_counts: dict[str, int] = {}
    for r in reports:
        v = r["verdict"] or "no_analysis"
        verdict_counts[v] = verdict_counts.get(v, 0) + 1

    # By hour (from timestamp)
    by_hour: dict[int, dict] = {}
    for r in reports:
        ts = r.get("timestamp", "")
        try:
            # Handle both ISO format and plain strings
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            hour = dt.hour
        except (ValueError, AttributeError):
            continue
        if hour not in by_hour:
            by_hour[hour] = {"wins": 0, "losses": 0}
        if r["pnl"] > 0:
            by_hour[hour]["wins"] += 1
        else:
            by_hour[hour]["losses"] += 1

    # Common failures and edges (top 5)
    failures = [r["what_failed"] for r in reports if r.get("what_failed") and r["what_failed"] != "N/A"][:8]
    edges = [r["edge_signal"] for r in reports if r.get("edge_signal") and r["edge_signal"] != "N/A"][:8]
    improvements = [r["improvement"] for r in reports if r.get("improvement") and r["improvement"] != "N/A"][:5]

    # Format strategy summary
    strat_lines = []
    for name, stats in sorted(by_strategy.items(), key=lambda x: x[1]["pnl"], reverse=True):
        t = stats["wins"] + stats["losses"]
        wr = int(stats["wins"] / t * 100) if t else 0
        strat_lines.append(f"  {name}: {stats['wins']}W/{stats['losses']}L ${stats['pnl']:.2f} ({wr}% WR)")

    # Format regime summary
    regime_lines = []
    for reg, stats in sorted(by_regime.items()):
        t = stats["wins"] + stats["losses"]
        wr = int(stats["wins"] / t * 100) if t else 0
        regime_lines.append(f"  {reg}: {stats['wins']}W/{stats['losses']}L ({wr}% WR)")

    # Format verdict summary
    verdict_lines = [f"  {v}: {c}" for v, c in sorted(verdict_counts.items(), key=lambda x: -x[1])]

    # Format hour summary (only hours with trades)
    hour_lines = []
    for hour in sorted(by_hour.keys()):
        stats = by_hour[hour]
        t = stats["wins"] + stats["losses"]
        wr = int(stats["wins"] / t * 100) if t else 0
        hour_lines.append(f"  {hour:02d}:00 UTC: {stats['wins']}W/{stats['losses']}L ({wr}% WR)")

    lines = [
        f"WEEK SUMMARY ({week}): {total} trades | {wins}W/{losses}L | Net P&L: ${total_pnl:.2f}",
        "",
        "BY STRATEGY:",
        *strat_lines,
        "",
        "BY REGIME:",
        *regime_lines,
        "",
        "BY VERDICT:",
        *verdict_lines,
        "",
        "BY HOUR (UTC):",
        *(hour_lines or ["  No timestamp data"]),
        "",
        "COMMON FAILURES:",
        *([f"  - {f}" for f in failures] if failures else ["  None"]),
        "",
        "EDGE SIGNALS:",
        *([f"  - {e}" for e in edges] if edges else ["  None"]),
        "",
        "TOP IMPROVEMENTS:",
        *([f"  - {i}" for i in improvements] if improvements else ["  None"]),
    ]

    return "\n".join(lines)


def analyze_edges(summary: str, week: str | None = None, reports_dir: Path | None = None) -> str:
    """Call Sonnet on the weekly summary to find edges and anti-patterns.

    Saves result to data/trade_reports/summaries/week_{week}.md.
    Returns the analysis markdown string (empty string on failure or no API key).
    """
    has_claude = config.anthropic_api_key or (
        config.claude_provider == "vertex" and config.google_cloud_project
    )
    if not has_claude:
        logger.warning("[Autopsy] No Claude API key — skipping edge analysis")
        return ""

    if week is None:
        now = datetime.now(timezone.utc)
        year, weeknum, _ = now.isocalendar()
        week = f"{year}-W{weeknum:02d}"

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
            model=config.edge_analysis_model,
            max_tokens=config.edge_analysis_max_tokens,
            system=_SONNET_EDGE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": summary}],
        )

        # Track tokens
        try:
            from ..monitoring.token_tracker import log_token_usage, extract_usage_from_response  # noqa: PLC0415
            tokens_in, tokens_out = extract_usage_from_response(response)
            log_token_usage(
                purpose="edge_analysis",
                model=config.edge_analysis_model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                metadata={"week": week},
            )
        except Exception as e:
            logger.warning("[Autopsy] Token tracking failed for edge analysis: %s", e)

        analysis = response.content[0].text.strip()

    except Exception as e:
        logger.error("[Autopsy] Edge analysis API error: %s", e)
        return ""

    # Save to summaries directory
    base_dir = reports_dir if reports_dir is not None else _data_dir()
    summaries_dir = base_dir / "summaries"
    summaries_dir.mkdir(parents=True, exist_ok=True)
    out_path = summaries_dir / f"week_{week}.md"

    header = (
        f"# Edge Analysis — {week}\n\n"
        f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
        f"**Model:** {config.edge_analysis_model}\n\n"
        f"## Input Summary\n\n```\n{summary}\n```\n\n"
        f"## Analysis\n\n"
    )
    out_path.write_text(header + analysis, encoding="utf-8")
    logger.info("[Autopsy] Saved edge analysis: %s", out_path)

    return analysis


def list_reports(limit: int = 20, reports_dir: Path | None = None) -> list[dict]:
    """List recent trade autopsy reports (metadata only, no full content).

    Returns list of dicts with: filename, trade_id, symbol, direction,
    grade, pnl, strategy, week, path.
    """
    base_dir = reports_dir if reports_dir is not None else _data_dir()
    all_files: list[Path] = []
    for month_dir in base_dir.glob("????-??"):
        if month_dir.is_dir():
            all_files.extend(month_dir.glob("trade_*.md"))

    # Sort newest first by modification time
    all_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    all_files = all_files[:limit]

    results = []
    for f in all_files:
        parsed = _parse_report(f)
        # Derive ISO week from filename date
        week = ""
        parts = f.stem.split("_")
        if len(parts) >= 5:
            date_str = parts[-1]
            try:
                dt = datetime.strptime(date_str, "%Y%m%d")
                year, weeknum, _ = dt.isocalendar()
                week = f"{year}-W{weeknum:02d}"
            except ValueError:
                pass
        results.append({
            "filename": f.name,
            "trade_id": parsed.get("trade_id", ""),
            "symbol": parsed.get("symbol", ""),
            "direction": parsed.get("direction", ""),
            "grade": parsed.get("grade", ""),
            "pnl": parsed.get("pnl", 0.0),
            "strategy": parsed.get("strategy", ""),
            "verdict": parsed.get("verdict", ""),
            "week": week,
            "path": str(f),
        })
    return results


def get_report_content(trade_id: str, reports_dir: Path | None = None) -> str | None:
    """Read full content of a trade report by trade_id. Returns None if not found."""
    base_dir = reports_dir if reports_dir is not None else _data_dir()
    for month_dir in base_dir.glob("????-??"):
        if not month_dir.is_dir():
            continue
        for f in month_dir.glob(f"trade_{trade_id}_*.md"):
            try:
                return f.read_text(encoding="utf-8")
            except OSError:
                return None
    return None


def get_edge_analysis(week: str | None = None, reports_dir: Path | None = None) -> str | None:
    """Read weekly edge analysis from disk. Returns None if not found."""
    if week is None:
        now = datetime.now(timezone.utc)
        year, weeknum, _ = now.isocalendar()
        week = f"{year}-W{weeknum:02d}"

    base_dir = reports_dir if reports_dir is not None else _data_dir()
    path = base_dir / "summaries" / f"week_{week}.md"
    if path.exists():
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return None
    return None
