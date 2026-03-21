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
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
    """Compute aggregate stats from a list of trade records."""
    if not trades:
        return StrategyStats()

    stats = StrategyStats(trades=len(trades))
    win_pnls = []
    loss_pnls = []
    durations = []
    mfes = []
    maes = []

    for t in trades:
        pnl = t.pnl or 0.0
        stats.total_pnl += pnl

        if pnl > 0:
            stats.wins += 1
            win_pnls.append(pnl)
        elif pnl < 0:
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


def _get_closed_trades(max_age_days: int = 60) -> list[TradeLog]:
    """
    Get closed trades from the journal, filtered by age.

    Only returns trades from the last max_age_days to ensure
    the analysis reflects CURRENT market behavior, not stale data.
    Set max_age_days=0 for all trades (no filter).

    Default is 60 days (not 90) because crypto regime shifts happen
    fast — 90 days mixes too many different market conditions and
    dilutes recent performance signals. 60 days balances having enough
    trades for statistical significance while staying regime-relevant.
    Future: add exponential decay weighting so older trades within the
    window contribute less, rather than using a hard cutoff (ML-13).
    """
    db = get_db()
    query = db.query(TradeLog).filter(TradeLog.exit_price.isnot(None))

    if max_age_days > 0:
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        query = query.filter(TradeLog.opened_at >= cutoff)

    return query.all()


def _get_strategies_for_trade(trade: TradeLog) -> list[str]:
    """Extract strategy names from a trade's strategies_agreed field."""
    if not trade.strategies_agreed:
        return []
    try:
        return json.loads(trade.strategies_agreed)
    except (json.JSONDecodeError, TypeError):
        return []


# ===== Analysis Functions =====


def analyze_strategy_by_instrument() -> dict[str, dict[str, dict]]:
    """
    Strategy × Instrument performance matrix.

    Returns: {instrument: {strategy: stats}}

    This tells you which strategies work on which instruments.
    Example: RSI Divergence might have 70% WR on Gold but 45% on BTC.
    """
    trades = _get_closed_trades()
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


def analyze_strategy_by_regime() -> dict[str, dict[str, dict]]:
    """
    Strategy × Regime performance matrix.

    Returns: {regime: {strategy: stats}}

    Tells you which strategies work in which market conditions.
    EMA Crossover should perform well in TRENDING but poorly in RANGING.
    """
    trades = _get_closed_trades()
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
