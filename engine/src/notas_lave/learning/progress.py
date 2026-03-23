"""
Learning Progress -- Single source of truth for what the system has learned.

This module aggregates all learning data into one queryable state.
Any new Claude session can call get_learning_state() to understand:
- What strategies work/don't work
- Current blacklists and weights
- Recent trade lessons
- Pending recommendations
- Overall system performance
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

# Base path for data files (engine/data/)
_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "data",
)


def get_learning_state(db_key: str = "lab") -> dict:
    """
    Aggregate all learning data into a single state dict.

    This is THE function a new Claude session calls first.
    Returns everything needed to understand system state.

    Each section is independently wrapped in try/except so a failure
    in one area doesn't prevent the rest from loading. Partial data
    is always better than no data.
    """
    from ..journal.database import use_db
    use_db(db_key)

    state: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "db_key": db_key,
    }

    # 1. Overview: total trades, win rate, profit factor, net P&L
    try:
        from .analyzer import analyze_overall
        overall = analyze_overall()
        overall_stats = overall.get("overall", {})
        state["overview"] = {
            "total_trades": overall_stats.get("trades", 0),
            "win_rate": overall_stats.get("win_rate", 0.0),
            "profit_factor": overall_stats.get("profit_factor", 0.0),
            "net_pnl": overall_stats.get("total_pnl", 0.0),
            "total_strategies_used": overall.get("total_strategies_used", 0),
        }
    except Exception as e:
        logger.error("Learning state: overview failed: %s", e)
        state["overview"] = {"error": str(e)}

    # 2. Active blacklists: which strategies are disabled per instrument
    try:
        from ..backtester.engine import INSTRUMENT_STRATEGY_BLACKLIST
        # Convert sets to sorted lists for JSON serialization
        blacklists = {
            symbol: sorted(strats)
            for symbol, strats in INSTRUMENT_STRATEGY_BLACKLIST.items()
            if strats
        }
        # Also check for learned (dynamic) blacklists on disk
        from ..journal.schemas import safe_load_json, LearnedBlacklists
        learned_path = os.path.join(_DATA_DIR, "learned_blacklists.json")
        learned_bl = safe_load_json(learned_path, LearnedBlacklists)
        learned_blacklists = learned_bl.data
        state["active_blacklists"] = {
            "static_and_dynamic": blacklists,
            "learned_from_file": learned_blacklists,
        }
    except Exception as e:
        logger.error("Learning state: blacklists failed: %s", e)
        state["active_blacklists"] = {"error": str(e)}

    # 3. Regime weights: current confluence weights per market regime
    try:
        from ..confluence.scorer import REGIME_WEIGHTS, DEFAULT_WEIGHTS
        state["regime_weights"] = {
            "per_regime": {
                regime.value: weights
                for regime, weights in REGIME_WEIGHTS.items()
            },
            "defaults": DEFAULT_WEIGHTS,
        }
    except Exception as e:
        logger.error("Learning state: regime_weights failed: %s", e)
        state["regime_weights"] = {"error": str(e)}

    # 4. Strategy performance: per-strategy stats (WR, P&L, trade count)
    try:
        from .analyzer import analyze_strategy_by_instrument
        state["strategy_performance"] = analyze_strategy_by_instrument()
    except Exception as e:
        logger.error("Learning state: strategy_performance failed: %s", e)
        state["strategy_performance"] = {"error": str(e)}

    # 5. Recent lessons: last 20 trade grades + lessons from Claude
    try:
        from ..journal.database import get_db, TradeLog
        db = get_db()
        graded_trades = (
            db.query(TradeLog)
            .filter(TradeLog.outcome_grade.isnot(None))
            .order_by(TradeLog.closed_at.desc())
            .limit(20)
            .all()
        )
        lessons = []
        for t in graded_trades:
            lesson_text = ""
            if t.lessons_learned:
                try:
                    parsed = json.loads(t.lessons_learned)
                    # lessons_learned is a JSON blob from Claude review
                    lesson_text = parsed.get("lesson", "") if isinstance(parsed, dict) else str(parsed)
                except (json.JSONDecodeError, TypeError):
                    lesson_text = t.lessons_learned
            lessons.append({
                "trade_id": t.id,
                "symbol": t.symbol,
                "strategy": t.strategies_agreed,
                "grade": t.outcome_grade,
                "lesson": lesson_text[:500] if lesson_text else "",
                "pnl": round(t.pnl or 0, 2),
                "closed_at": t.closed_at.isoformat() if t.closed_at else None,
            })
        state["recent_lessons"] = lessons
    except Exception as e:
        logger.error("Learning state: recent_lessons failed: %s", e)
        state["recent_lessons"] = {"error": str(e)}

    # 6. Optimizer findings: load from engine/data/optimizer_results.json
    try:
        from ..journal.schemas import OptimizerResults as _OptResults
        optimizer_path = os.path.join(_DATA_DIR, "optimizer_results.json")
        opt_validated = safe_load_json(optimizer_path, _OptResults)
        state["optimizer_findings"] = {
            sym: sym_data.model_dump()
            for sym, sym_data in opt_validated.data.items()
        }
    except Exception as e:
        logger.error("Learning state: optimizer_findings failed: %s", e)
        state["optimizer_findings"] = {"error": str(e)}

    # 7. Recommendations pending: from generate_all_recommendations()
    try:
        from .recommendations import generate_all_recommendations
        recs = generate_all_recommendations()
        if recs.get("status") == "ready":
            state["recommendations_pending"] = recs
        else:
            state["recommendations_pending"] = recs
    except Exception as e:
        logger.error("Learning state: recommendations failed: %s", e)
        state["recommendations_pending"] = {"error": str(e)}

    # 8. Daily summary: last 7 days of trading
    try:
        from ..journal.database import get_db, TradeLog
        db = get_db()
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        recent_trades = (
            db.query(TradeLog)
            .filter(
                TradeLog.exit_price.isnot(None),
                TradeLog.closed_at >= cutoff,
            )
            .all()
        )
        # Group by date
        daily: dict[str, dict] = {}
        for t in recent_trades:
            if not t.closed_at:
                continue
            day_str = t.closed_at.strftime("%Y-%m-%d")
            if day_str not in daily:
                daily[day_str] = {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0}
            daily[day_str]["trades"] += 1
            pnl = t.pnl or 0.0
            daily[day_str]["pnl"] += pnl
            if pnl > 0:
                daily[day_str]["wins"] += 1
            elif pnl < 0:
                daily[day_str]["losses"] += 1
        # Round P&L and sort by date
        for day_str in daily:
            daily[day_str]["pnl"] = round(daily[day_str]["pnl"], 2)
        state["daily_summary"] = dict(sorted(daily.items()))
    except Exception as e:
        logger.error("Learning state: daily_summary failed: %s", e)
        state["daily_summary"] = {"error": str(e)}

    # 9. Check-in trends: last 10 entries from lab_checkin_reports.json
    try:
        checkin_path = os.path.join(_DATA_DIR, "lab_checkin_reports.json")
        if os.path.exists(checkin_path):
            with open(checkin_path) as f:
                all_reports = json.load(f)
            state["check_in_trends"] = all_reports[-10:] if isinstance(all_reports, list) else []
        else:
            state["check_in_trends"] = []
    except Exception as e:
        logger.error("Learning state: check_in_trends failed: %s", e)
        state["check_in_trends"] = {"error": str(e)}

    return state


def save_learning_state(state: dict, path: str | None = None):
    """Save learning state to JSON file for cross-session persistence.

    Default path: engine/data/system_state.json
    Creates the directory if it doesn't exist.
    """
    if path is None:
        path = os.path.join(_DATA_DIR, "system_state.json")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(state, f, indent=2, default=str)
        logger.info("Saved learning state to %s", path)
    except Exception as e:
        logger.error("Failed to save learning state: %s", e)
