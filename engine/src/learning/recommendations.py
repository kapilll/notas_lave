"""
Learning Engine Recommendations — turns analysis into action.

Takes the analysis from analyzer.py and produces:
1. Strategy weight adjustments per regime
2. Strategy enable/disable suggestions per instrument
3. Optimal score threshold recommendation
4. Best trading hours recommendation
5. Risk parameter suggestions

These recommendations can be:
- Displayed on the dashboard for the trader to review
- Auto-applied to the confluence scorer (with user approval)
- Sent as a Telegram summary (weekly review)
"""

import os
import json
from datetime import datetime, timezone, timedelta
from ..confluence.scorer import REGIME_WEIGHTS, DEFAULT_WEIGHTS
from .analyzer import (
    analyze_strategy_by_instrument,
    analyze_strategy_by_regime,
    analyze_by_hour,
    analyze_by_score_bucket,
    analyze_overall,
)


# QR-25: Minimum sample size for 95% confidence at detecting 10pp WR difference.
# Using rule of thumb: n >= (z^2 * p * (1-p)) / e^2 where z=1.96, p=0.5, e=0.10
# n >= (3.84 * 0.25) / 0.01 = 96, but with two-tailed binomial power analysis
# 50 trades gives ~80% power to detect a 15pp difference — an acceptable tradeoff
# between statistical rigor and practical data availability.
MIN_TRADES_FOR_RECOMMENDATION = 50

# ML-20/TP-07: Prevent daily weight/blacklist churn (algorithmic tilt).
# Adjustments are only applied if enough time AND trades have elapsed.
MIN_DAYS_BETWEEN_ADJUSTMENTS = 7    # At least 7 days between changes
MIN_TRADES_BETWEEN_ADJUSTMENTS = 10  # At least 10 new trades since last change

# File to track adjustment history
_ADJUSTMENT_STATE_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "adjustment_state.json"
)


def _load_adjustment_state() -> dict:
    """Load the last adjustment timestamp and trade count."""
    try:
        if os.path.exists(_ADJUSTMENT_STATE_FILE):
            with open(_ADJUSTMENT_STATE_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {"last_adjustment_date": None, "trades_at_last_adjustment": 0}


def _save_adjustment_state(total_trades: int):
    """Record that an adjustment was applied now."""
    try:
        os.makedirs(os.path.dirname(_ADJUSTMENT_STATE_FILE), exist_ok=True)
        state = {
            "last_adjustment_date": datetime.now(timezone.utc).isoformat(),
            "trades_at_last_adjustment": total_trades,
        }
        with open(_ADJUSTMENT_STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass


def is_adjustment_allowed(total_trades: int) -> tuple[bool, str]:
    """
    ML-20/TP-07: Check if enough time and trades have passed to allow
    weight/blacklist adjustments. Prevents daily churn that causes
    algorithmic tilt (overfitting to recent noise).

    Returns (allowed: bool, reason: str).
    """
    state = _load_adjustment_state()

    last_date_str = state.get("last_adjustment_date")
    if last_date_str:
        last_date = datetime.fromisoformat(last_date_str)
        days_since = (datetime.now(timezone.utc) - last_date).days
        if days_since < MIN_DAYS_BETWEEN_ADJUSTMENTS:
            return False, f"Only {days_since} days since last adjustment (need {MIN_DAYS_BETWEEN_ADJUSTMENTS})"

    trades_at_last = state.get("trades_at_last_adjustment", 0)
    new_trades = total_trades - trades_at_last
    if new_trades < MIN_TRADES_BETWEEN_ADJUSTMENTS:
        return False, f"Only {new_trades} new trades since last adjustment (need {MIN_TRADES_BETWEEN_ADJUSTMENTS})"

    return True, "OK"


def _get_strategy_categories() -> dict[str, str]:
    """ML-25: Build strategy-to-category mapping from the registry.

    Replaces the hardcoded STRATEGY_CATEGORIES dict so new strategies
    registered in registry.py are automatically picked up here.
    """
    try:
        from ..strategies.registry import get_all_strategies
        return {s.name: s.category for s in get_all_strategies()}
    except Exception:
        # Fallback if registry import fails (e.g., during tests)
        return {}


def recommend_strategy_rehabilitation() -> dict[str, list[str]]:
    """TP-06: Identify blacklisted strategies that may deserve re-testing.

    If a strategy was blacklisted, it stays blacklisted forever — this
    creates asymmetric learning where the system can only REMOVE strategies,
    never rehabilitate ones that might work in a changed market regime.

    This function surfaces the current blacklist for visibility. Full
    rehabilitation requires shadow-mode execution (future ML-17 integration)
    where blacklisted strategies run in paper mode to prove they've improved.
    """
    try:
        from ..backtester.engine import INSTRUMENT_STRATEGY_BLACKLIST
    except ImportError:
        return {}

    return {
        symbol: sorted(strats)
        for symbol, strats in INSTRUMENT_STRATEGY_BLACKLIST.items()
        if strats
    }


def get_regime_warnings() -> list[dict]:
    """TP-13: Identify strategies that fail in specific market regimes.

    Unlike the instrument-level blacklist which is absolute, regime warnings
    flag strategies that underperform only in certain conditions. This
    allows the confluence scorer to reduce weight in those regimes instead
    of permanently disabling the strategy.
    """
    by_regime = analyze_strategy_by_regime()
    warnings = []

    for regime, strategies in by_regime.items():
        for strat_name, stats in strategies.items():
            trades = stats["trades"]
            wr = stats["win_rate"]
            pnl = stats["total_pnl"]
            if trades >= 20 and wr < 30 and pnl < 0:
                warnings.append({
                    "strategy": strat_name,
                    "regime": regime,
                    "trades": trades,
                    "win_rate": round(wr, 1),
                    "total_pnl": round(pnl, 2),
                    "reason": f"Only {wr:.0f}% WR in {regime} regime ({trades} trades, ${pnl:.0f})",
                })

    return warnings


def recommend_strategy_blacklist() -> dict[str, list[dict]]:
    """
    Recommend which strategies to disable per instrument.

    A strategy should be blacklisted on an instrument if:
    - It has 30+ trades with < 35% win rate, OR
    - It has negative total P&L with 50+ trades (enough sample size)

    Returns: {instrument: [{strategy, reason, trades, win_rate, pnl}]}
    """
    by_instrument = analyze_strategy_by_instrument()
    recommendations: dict[str, list[dict]] = {}

    for instrument, strategies in by_instrument.items():
        recs = []
        for strat_name, stats in strategies.items():
            trades = stats["trades"]
            wr = stats["win_rate"]
            pnl = stats["total_pnl"]

            if trades < MIN_TRADES_FOR_RECOMMENDATION:
                continue

            reasons = []
            # QR-25: 35% WR with 50+ trades: binomial test p-value < 0.001
            # against H0: true WR=50%. This is a strong signal of
            # underperformance, not a random fluctuation.
            if wr < 35:
                reasons.append(f"Low win rate ({wr:.1f}% on {trades} trades)")
            if pnl < 0 and trades >= 50:
                reasons.append(f"Net negative P&L (${pnl:.2f} on {trades} trades)")

            if reasons:
                recs.append({
                    "strategy": strat_name,
                    "reason": "; ".join(reasons),
                    "trades": trades,
                    "win_rate": round(wr, 1),
                    "pnl": round(pnl, 2),
                    "action": "BLACKLIST",
                })

        if recs:
            recommendations[instrument] = sorted(recs, key=lambda x: x["pnl"])

    return recommendations


def get_dynamic_blacklist() -> dict[str, set[str]]:
    """
    Generate a dynamic blacklist from journal data.

    Instead of hardcoding which strategies to disable,
    this analyzes actual trade performance and returns
    strategies that should be disabled per instrument.

    Used by the backtester and scanner to filter strategies
    based on REAL performance, not assumptions.
    """
    suggestions = recommend_strategy_blacklist()
    blacklist: dict[str, set[str]] = {}

    for instrument, recs in suggestions.items():
        blacklist[instrument] = {r["strategy"] for r in recs}

    return blacklist


def recommend_weight_adjustments() -> dict[str, dict[str, float]]:
    """
    Recommend new confluence weights per regime based on category performance.

    Strategy categories that perform well in a regime should get higher weight.
    Categories that underperform should get lower weight.

    Uses relative P&L per category within each regime to compute new weights.
    Weights always sum to 1.0.

    Returns: {regime: {category: suggested_weight}}
    """
    by_regime = analyze_strategy_by_regime()

    # ML-25: Build strategy-to-category mapping dynamically from the registry
    # instead of maintaining a duplicate hardcoded dict that drifts out of sync.
    STRATEGY_CATEGORIES = _get_strategy_categories()

    all_categories = set(STRATEGY_CATEGORIES.values()) or {"scalping", "ict", "fibonacci", "volume", "breakout"}
    suggested_weights: dict[str, dict[str, float]] = {}

    for regime, strategies in by_regime.items():
        # Compute total P&L per category in this regime
        cat_pnl: dict[str, float] = {c: 0.0 for c in all_categories}
        cat_trades: dict[str, int] = {c: 0 for c in all_categories}

        for strat_name, stats in strategies.items():
            cat = STRATEGY_CATEGORIES.get(strat_name)
            if cat:
                cat_pnl[cat] += stats["total_pnl"]
                cat_trades[cat] += stats["trades"]

        # ML-19 FIX: Use avg_pnl (total_pnl / trades) instead of raw total_pnl.
        # Raw P&L biases toward categories with more trades (scalping has 6
        # strategies vs fibonacci's 1), making the weights reflect trade COUNT
        # not trade QUALITY. Also require min 20 trades per category.
        cat_avg_pnl: dict[str, float] = {}
        for c in all_categories:
            if cat_trades[c] >= 20:
                cat_avg_pnl[c] = cat_pnl[c] / cat_trades[c]
            else:
                cat_avg_pnl[c] = 0.0  # Not enough data — neutral weight

        # Convert to weights: categories with positive avg P&L get more weight
        # Use softmax-like approach: shift all values positive, then normalize
        min_pnl = min(cat_avg_pnl.values()) if cat_avg_pnl else 0
        shifted = {c: pnl - min_pnl + 1.0 for c, pnl in cat_avg_pnl.items()}
        total = sum(shifted.values())

        if total > 0:
            weights = {c: round(v / total, 3) for c, v in shifted.items()}
            # Clamp: no category below 0.05 or above 0.50
            for c in weights:
                weights[c] = max(0.05, min(0.50, weights[c]))
            # Re-normalize to sum to 1.0
            w_total = sum(weights.values())
            weights = {c: round(v / w_total, 3) for c, v in weights.items()}
            suggested_weights[regime] = weights

    return suggested_weights


def recommend_score_threshold() -> dict:
    """
    Recommend the optimal minimum confluence score.

    Analyzes win rate and profit factor at each score bucket.
    The optimal threshold is where profit factor is maximized
    without sacrificing too many trades.

    Returns: {recommended_min_score, analysis_by_bucket}
    """
    by_score = analyze_by_score_bucket()

    best_bucket = None
    best_pf = 0.0

    for bucket, stats in by_score.items():
        if stats["trades"] >= 5 and stats["profit_factor"] > best_pf:
            best_pf = stats["profit_factor"]
            best_bucket = bucket

    # Parse bucket to get lower bound as recommended threshold
    recommended = 60  # Default
    if best_bucket:
        try:
            lower = best_bucket.replace("+", "").split("-")[0]
            recommended = int(lower)
        except (ValueError, IndexError):
            pass

    return {
        "recommended_min_score": recommended,
        "best_bucket": best_bucket,
        "best_profit_factor": round(best_pf, 2),
        "analysis": by_score,
    }


def recommend_trading_hours() -> dict:
    """
    Recommend the best and worst trading hours.

    Identifies hours with highest win rate and profit factor,
    and hours that should be avoided.

    Returns: {best_hours, worst_hours, by_hour}
    """
    by_hour = analyze_by_hour()

    best_hours = []
    worst_hours = []

    for hour, stats in by_hour.items():
        if stats["trades"] < 5:
            continue
        if stats["win_rate"] >= 55 and stats["profit_factor"] >= 1.2:
            best_hours.append({"hour_utc": hour, **stats})
        elif stats["win_rate"] < 40 or stats["profit_factor"] < 0.8:
            worst_hours.append({"hour_utc": hour, **stats})

    best_hours.sort(key=lambda x: x["profit_factor"], reverse=True)
    worst_hours.sort(key=lambda x: x["profit_factor"])

    return {
        "best_hours": best_hours[:5],
        "worst_hours": worst_hours[:5],
        "all_hours": by_hour,
    }


def generate_all_recommendations() -> dict:
    """
    Generate all recommendations in one call.

    This is the main entry point for the learning engine's
    recommendation system. Returns everything the dashboard
    and the trader need to make informed adjustments.
    """
    overall = analyze_overall()

    # Only generate recommendations if we have enough data
    total_trades = overall["overall"]["trades"]

    if total_trades < MIN_TRADES_FOR_RECOMMENDATION:
        return {
            "status": "insufficient_data",
            "message": f"Need at least {MIN_TRADES_FOR_RECOMMENDATION} trades for recommendations. "
                       f"Currently have {total_trades}.",
            "total_trades": total_trades,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # ML-20/TP-07: Check if adjustment cooldown has elapsed
    allowed, cooldown_reason = is_adjustment_allowed(total_trades)

    result = {
        "status": "ready",
        "total_trades_analyzed": total_trades,
        "overall_performance": overall,
        "blacklist_suggestions": recommend_strategy_blacklist(),
        "weight_adjustments": recommend_weight_adjustments(),
        "score_threshold": recommend_score_threshold(),
        "trading_hours": recommend_trading_hours(),
        # TP-06: Surface blacklisted strategies that may deserve re-testing
        "rehabilitation_candidates": recommend_strategy_rehabilitation(),
        # TP-13: Regime-specific underperformance warnings
        "regime_warnings": get_regime_warnings(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        # ML-20: Include adjustment gate info so callers know whether
        # to auto-apply or just display recommendations.
        "adjustment_allowed": allowed,
        "adjustment_cooldown_reason": cooldown_reason if not allowed else None,
    }

    return result
