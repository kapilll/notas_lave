"""
Learning Engine Analyzer — discovers what works and what doesn't.

Queries the trade journal and computes multi-dimensional breakdowns:
1. Strategy × Instrument: Which strategy works best on which instrument?
2. Strategy × Regime: Which strategy works in which market condition?
3. Time-of-Day: Which hours produce the best results?
4. Score Threshold: What's the optimal confluence score cutoff?
5. Exit Analysis: TP hits vs SL hits vs timeouts, MFE/MAE
6. Recent Trend: Is a strategy improving or degrading?

These analyses feed the recommendations module which suggests
weight adjustments, strategy filtering, and parameter tuning.
"""

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from sqlalchemy.orm import load_only
from ..journal.database import get_db, TradeLog


@dataclass
class StrategyStats:
    """Performance stats for one strategy slice."""
    trades: int = 0
    wins: int = 0
    losses: int = 0
    breakevens: int = 0
    total_pnl: float = 0.0
    avg_pnl: float = 0.0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    avg_duration_min: float = 0.0
    avg_mfe: float = 0.0      # Average max favorable excursion
    avg_mae: float = 0.0      # Average max adverse excursion
    tp_hits: int = 0
    sl_hits: int = 0
    timeouts: int = 0

    def to_dict(self) -> dict:
        return {
            "trades": self.trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": round(self.win_rate, 1),
            "total_pnl": round(self.total_pnl, 2),
            "avg_pnl": round(self.avg_pnl, 2),
            "avg_win": round(self.avg_win, 2),
            "avg_loss": round(self.avg_loss, 2),
            "profit_factor": round(self.profit_factor, 2),
            "avg_duration_min": round(self.avg_duration_min, 1),
            "avg_mfe": round(self.avg_mfe, 2),
            "avg_mae": round(self.avg_mae, 2),
            "tp_hits": self.tp_hits,
            "sl_hits": self.sl_hits,
            "timeouts": self.timeouts,
        }


def _compute_stats(trades: list[TradeLog]) -> StrategyStats:
    """Compute aggregate stats from a list of trade records.

    ML-13/TP-02 FIX: P&L contributions are weighted by exponential decay
    via get_trade_weight(). Win/loss COUNTS remain unweighted (a win is a
    win regardless of age), but dollar amounts favor recent data so the
    system adapts to current market conditions.
    """
    if not trades:
        return StrategyStats()

    stats = StrategyStats(trades=len(trades))
    win_pnls = []
    loss_pnls = []
    durations = []
    mfes = []
    maes = []

    for t in trades:
        weight = get_trade_weight(t)  # ML-13: exponential decay (0.0-1.0)
        raw_pnl = t.pnl or 0.0
        pnl = raw_pnl * weight  # Weighted P&L for aggregation

        stats.total_pnl += pnl

        # Win/loss classification uses RAW pnl (unweighted)
        if raw_pnl > 0:
            stats.wins += 1
            win_pnls.append(pnl)
        elif raw_pnl < 0:
            stats.losses += 1
            loss_pnls.append(pnl)
        else:
            stats.breakevens += 1

        if t.duration_seconds:
            durations.append(t.duration_seconds / 60.0)
        if t.max_favorable:
            mfes.append(t.max_favorable)
        if t.max_adverse:
            maes.append(t.max_adverse)

        if t.exit_reason == "tp_hit":
            stats.tp_hits += 1
        elif t.exit_reason == "sl_hit":
            stats.sl_hits += 1
        elif t.exit_reason in ("timeout", "time"):
            stats.timeouts += 1

    stats.win_rate = stats.wins / max(stats.trades, 1) * 100
    stats.avg_pnl = stats.total_pnl / max(stats.trades, 1)
    stats.avg_win = sum(win_pnls) / max(len(win_pnls), 1)
    stats.avg_loss = sum(loss_pnls) / max(len(loss_pnls), 1)

    gross_profit = sum(win_pnls)
    gross_loss = abs(sum(loss_pnls))
    stats.profit_factor = gross_profit / max(gross_loss, 0.01)

    stats.avg_duration_min = sum(durations) / max(len(durations), 1)
    stats.avg_mfe = sum(mfes) / max(len(mfes), 1)
    stats.avg_mae = sum(maes) / max(len(maes), 1)

    return stats


def _get_closed_trades(max_age_days: int = 180, min_score: int = 0) -> list[TradeLog]:
    """
    Get closed trades from the journal, filtered by age and quality.

    ML-13: Default raised from 60 to 180 days. The hard cutoff is now a
    safety net; actual down-weighting of old trades is handled by
    get_trade_weight() exponential decay in _compute_stats(). This way
    trades from 90 days ago still contribute (at ~12.5% weight) instead
    of being silently discarded.

    DE-19: Uses load_only() to project only the columns needed for
    analysis, avoiding loading large text blobs (lessons_learned etc.).

    BF-01: min_score filters out low-quality trades (e.g., lab trades with
    score < 50) so production recommendations aren't biased by trades that
    production would never have taken. Default 0 = all trades.

    Set max_age_days=0 for all trades (no age filter).
    """
    db = get_db()
    query = db.query(TradeLog).options(
        load_only(
            TradeLog.id, TradeLog.symbol, TradeLog.timeframe, TradeLog.direction,
            TradeLog.regime, TradeLog.entry_price, TradeLog.exit_price,
            TradeLog.pnl, TradeLog.pnl_pct, TradeLog.duration_seconds,
            TradeLog.max_favorable, TradeLog.max_adverse, TradeLog.exit_reason,
            TradeLog.confluence_score, TradeLog.strategies_agreed,
            TradeLog.opened_at, TradeLog.outcome_grade,
        )
    ).filter(TradeLog.exit_price.isnot(None))

    if max_age_days > 0:
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        query = query.filter(TradeLog.opened_at >= cutoff)

    # BF-01: Filter out low-quality trades for production recommendations
    if min_score > 0:
        query = query.filter(TradeLog.confluence_score >= min_score)

    return query.all()


def get_trade_weight(
    trade: TradeLog,
    half_life_days: float = 30.0,
    current_regime: str | None = None,
) -> float:
    """
    ML-13 FIX: Exponential decay weighting for trades.

    Recent trades get weight ~1.0, older trades decay toward 0.
    Half-life of 30 days means a trade from 30 days ago has weight 0.5,
    60 days = 0.25, 90 days = 0.125.

    This replaces the hard 60-day cutoff with a smooth transition,
    ensuring recent regime data dominates without completely discarding
    older data that may still be relevant.

    ML-29 FIX: If current_regime is provided and matches the trade's
    regime, apply a 1.5x boost (capped at 1.0). This keeps regime-
    matching old trades relevant — a trending-regime trade from 90 days
    ago is more useful than a ranging trade from yesterday when we're
    currently in a trend.

    Formula: weight = exp(-0.693 * age_days / half_life)
    where 0.693 = ln(2)
    """
    if not trade.opened_at:
        return 1.0
    now = datetime.now(timezone.utc)
    trade_time = trade.opened_at
    if trade_time.tzinfo is None:
        trade_time = trade_time.replace(tzinfo=timezone.utc)
    age_days = (now - trade_time).total_seconds() / 86400
    weight = math.exp(-0.693 * age_days / half_life_days)

    # ML-29: Boost weight for trades whose regime matches the current regime.
    # A trending trade from 90 days ago (base weight 0.125) becomes 0.1875,
    # keeping it more influential than a non-matching trade at the same age.
    if current_regime and trade.regime and trade.regime == current_regime:
        weight = min(weight * 1.5, 1.0)

    return weight


def _get_strategies_for_trade(trade: TradeLog) -> list[str]:
    """Extract strategy names from a trade's strategies_agreed field."""
    if not trade.strategies_agreed:
        return []
    try:
        return json.loads(trade.strategies_agreed)
    except (json.JSONDecodeError, TypeError):
        return []


# ===== Analysis Functions =====


def analyze_strategy_by_instrument(min_score: int = 0) -> dict[str, dict[str, dict]]:
    """
    Strategy × Instrument performance matrix.

    Returns: {instrument: {strategy: stats}}

    This tells you which strategies work on which instruments.
    Example: RSI Divergence might have 70% WR on Gold but 45% on BTC.

    BF-01: min_score filters out low-quality trades (default 0 = all).
    """
    trades = _get_closed_trades(min_score=min_score)
    matrix: dict[str, dict[str, list[TradeLog]]] = {}

    for t in trades:
        symbol = t.symbol or "UNKNOWN"
        strategies = _get_strategies_for_trade(t)
        if not strategies:
            continue

        if symbol not in matrix:
            matrix[symbol] = {}

        for s in strategies:
            if s not in matrix[symbol]:
                matrix[symbol][s] = []
            matrix[symbol][s].append(t)

    result = {}
    for symbol, strats in matrix.items():
        result[symbol] = {}
        for strat_name, strat_trades in strats.items():
            result[symbol][strat_name] = _compute_stats(strat_trades).to_dict()

    return result


def analyze_strategy_by_regime(min_score: int = 0) -> dict[str, dict[str, dict]]:
    """
    Strategy × Regime performance matrix.

    Returns: {regime: {strategy: stats}}

    Tells you which strategies work in which market conditions.
    EMA Crossover should perform well in TRENDING but poorly in RANGING.

    BF-01: min_score filters out low-quality trades (default 0 = all).
    """
    trades = _get_closed_trades(min_score=min_score)
    matrix: dict[str, dict[str, list[TradeLog]]] = {}

    for t in trades:
        regime = t.regime or "UNKNOWN"
        strategies = _get_strategies_for_trade(t)

        if regime not in matrix:
            matrix[regime] = {}

        for s in strategies:
            if s not in matrix[regime]:
                matrix[regime][s] = []
            matrix[regime][s].append(t)

    result = {}
    for regime, strats in matrix.items():
        result[regime] = {}
        for strat_name, strat_trades in strats.items():
            result[regime][strat_name] = _compute_stats(strat_trades).to_dict()

    return result


def analyze_by_hour() -> dict[int, dict]:
    """
    Time-of-day analysis.

    Returns: {hour_utc: stats}

    Identifies which hours produce the best/worst results.
    Example: Hour 13 (NY open) might have highest win rate for Gold.
    """
    trades = _get_closed_trades()
    hourly: dict[int, list[TradeLog]] = {}

    for t in trades:
        if t.opened_at:
            hour = t.opened_at.hour
            if hour not in hourly:
                hourly[hour] = []
            hourly[hour].append(t)

    return {h: _compute_stats(trades).to_dict() for h, trades in sorted(hourly.items())}


def analyze_by_score_bucket() -> dict[str, dict]:
    """
    Score threshold analysis.

    Groups trades by confluence score ranges and computes stats per bucket.
    Answers: "What's the win rate at score 50-60 vs 70-80?"
    This tells you the optimal minimum score threshold.
    """
    trades = _get_closed_trades()
    buckets: dict[str, list[TradeLog]] = {
        "40-50": [], "50-60": [], "60-70": [], "70-80": [], "80+": [],
    }

    for t in trades:
        score = t.confluence_score or 0
        if score < 50:
            buckets["40-50"].append(t)
        elif score < 60:
            buckets["50-60"].append(t)
        elif score < 70:
            buckets["60-70"].append(t)
        elif score < 80:
            buckets["70-80"].append(t)
        else:
            buckets["80+"].append(t)

    return {bucket: _compute_stats(trades).to_dict() for bucket, trades in buckets.items()}


def analyze_exit_reasons() -> dict[str, dict]:
    """
    Exit reason breakdown.

    Returns: {exit_reason: {count, pct, avg_pnl}}

    If most exits are SL hits, strategies need wider stops or better entries.
    If many are timeouts, the TP targets might be too ambitious.
    """
    trades = _get_closed_trades()
    reasons: dict[str, list[TradeLog]] = {}

    for t in trades:
        reason = t.exit_reason or "unknown"
        if reason not in reasons:
            reasons[reason] = []
        reasons[reason].append(t)

    total = max(len(trades), 1)
    result = {}
    for reason, reason_trades in reasons.items():
        stats = _compute_stats(reason_trades)
        result[reason] = {
            "count": len(reason_trades),
            "pct": round(len(reason_trades) / total * 100, 1),
            "avg_pnl": stats.avg_pnl,
            "total_pnl": stats.total_pnl,
        }

    return result


def analyze_overall() -> dict:
    """
    Overall portfolio performance summary.

    High-level stats across all trades — the "report card".
    """
    trades = _get_closed_trades()
    stats = _compute_stats(trades)

    # Strategy-level breakdown
    strategy_totals: dict[str, list[TradeLog]] = {}
    for t in trades:
        for s in _get_strategies_for_trade(t):
            if s not in strategy_totals:
                strategy_totals[s] = []
            strategy_totals[s].append(t)

    strategy_breakdown = {
        name: _compute_stats(strat_trades).to_dict()
        for name, strat_trades in strategy_totals.items()
    }

    # Sort by P&L descending
    strategy_breakdown = dict(
        sorted(strategy_breakdown.items(), key=lambda x: x[1]["total_pnl"], reverse=True)
    )

    return {
        "overall": stats.to_dict(),
        "strategy_breakdown": strategy_breakdown,
        "total_strategies_used": len(strategy_breakdown),
    }


def run_full_analysis() -> dict:
    """
    Run all analyses and return a comprehensive report.

    This is the main entry point for the learning engine.
    Called by the API endpoint and by the Claude weekly review.
    """
    return {
        "overall": analyze_overall(),
        "by_instrument": analyze_strategy_by_instrument(),
        "by_regime": analyze_strategy_by_regime(),
        "by_hour": analyze_by_hour(),
        "by_score": analyze_by_score_bucket(),
        "exit_reasons": analyze_exit_reasons(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ===== Strategy Combination Analysis =====


def analyze_strategy_combinations(min_trades: int = 10) -> dict:
    """
    Analyze which strategy COMBINATIONS perform best together.

    Groups closed trades by the set of agreeing strategies,
    computes WR and P&L for each combination, and identifies:
    - Best pairs (highest WR when these 2 agree)
    - Worst pairs (lowest WR when these 2 agree)
    - Solo vs combo performance (does adding a strategy help?)

    Returns a dict with keys: combinations, solo_performance,
    best_pairs, worst_pairs, insights.
    """
    trades = _get_closed_trades()

    # --- Group trades by frozenset of agreeing strategies ---
    combo_trades: dict[frozenset[str], list[TradeLog]] = {}
    for t in trades:
        strategies = _get_strategies_for_trade(t)
        if not strategies:
            continue
        key = frozenset(strategies)
        if key not in combo_trades:
            combo_trades[key] = []
        combo_trades[key].append(t)

    # --- Compute stats per combination ---
    combinations: list[dict] = []
    for combo, combo_trade_list in combo_trades.items():
        count = len(combo_trade_list)
        wins = sum(1 for t in combo_trade_list if (t.pnl or 0) > 0)
        total_pnl = sum(t.pnl or 0 for t in combo_trade_list)
        combinations.append({
            "strategies": sorted(combo),
            "trades": count,
            "wins": wins,
            "win_rate": round(wins / max(count, 1) * 100, 1),
            "total_pnl": round(total_pnl, 2),
            "avg_pnl": round(total_pnl / max(count, 1), 2),
        })

    # Sort by trade count descending (most data first)
    combinations.sort(key=lambda c: c["trades"], reverse=True)

    # --- Solo performance (combos with exactly 1 strategy) ---
    solo_performance: dict[str, dict] = {}
    for c in combinations:
        if len(c["strategies"]) == 1:
            solo_performance[c["strategies"][0]] = {
                "trades": c["trades"],
                "win_rate": c["win_rate"],
                "total_pnl": c["total_pnl"],
            }

    # --- Best/worst pairs (combos with exactly 2 strategies, enough trades) ---
    pairs = [c for c in combinations if len(c["strategies"]) == 2 and c["trades"] >= min_trades]
    pairs_by_wr = sorted(pairs, key=lambda c: c["win_rate"], reverse=True)
    best_pairs = pairs_by_wr[:5]
    worst_pairs = pairs_by_wr[-5:] if len(pairs_by_wr) >= 5 else pairs_by_wr[::-1][:5]

    # --- Generate human-readable insights ---
    insights: list[str] = []

    # Insight 1-3: Best pairs vs their solo performance
    for pair in best_pairs[:3]:
        s1, s2 = pair["strategies"]
        solo1_wr = solo_performance.get(s1, {}).get("win_rate", 0)
        solo2_wr = solo_performance.get(s2, {}).get("win_rate", 0)
        if solo1_wr > 0 or solo2_wr > 0:
            insights.append(
                f"{s1} + {s2} together: {pair['win_rate']}% WR over {pair['trades']} trades "
                f"(vs {solo1_wr}% {s1} solo, {solo2_wr}% {s2} solo)"
            )

    # Insight 4-5: Worst solo performers (strategies that need confirmation)
    weak_solos = sorted(
        [(name, stats) for name, stats in solo_performance.items() if stats["trades"] >= min_trades],
        key=lambda x: x[1]["win_rate"],
    )
    for name, stats in weak_solos[:2]:
        if stats["win_rate"] < 50:
            insights.append(
                f"{name} alone: {stats['win_rate']}% WR over {stats['trades']} trades "
                f"— avoid without confirmation from another strategy"
            )

    # Insight 6: Best solo performer
    strong_solos = sorted(
        [(name, stats) for name, stats in solo_performance.items() if stats["trades"] >= min_trades],
        key=lambda x: x[1]["win_rate"],
        reverse=True,
    )
    for name, stats in strong_solos[:1]:
        if stats["win_rate"] >= 55:
            insights.append(
                f"{name} solo: {stats['win_rate']}% WR over {stats['trades']} trades "
                f"— strong standalone performer"
            )

    # Insight 7: Largest combo (most strategies agreeing)
    large_combos = [c for c in combinations if len(c["strategies"]) >= 3 and c["trades"] >= min_trades]
    if large_combos:
        best_large = max(large_combos, key=lambda c: c["win_rate"])
        insights.append(
            f"{len(best_large['strategies'])}-strategy confluence "
            f"({', '.join(best_large['strategies'][:3])}{'...' if len(best_large['strategies']) > 3 else ''}): "
            f"{best_large['win_rate']}% WR over {best_large['trades']} trades"
        )

    # Cap insights at 7
    insights = insights[:7]

    return {
        "combinations": combinations,
        "solo_performance": solo_performance,
        "best_pairs": best_pairs,
        "worst_pairs": worst_pairs,
        "insights": insights,
    }


def get_combination_insights(min_trades: int = 10) -> list[str]:
    """Return just the insight strings for Telegram messages."""
    result = analyze_strategy_combinations(min_trades)
    return result.get("insights", [])
