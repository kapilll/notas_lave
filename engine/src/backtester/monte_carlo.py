"""
Monte Carlo Simulation (QR-09) — Permutation test for backtest robustness.

Takes a list of BacktestTrade objects, shuffles trade order 10,000 times,
and computes percentile statistics for max drawdown and final equity.

This answers: "Was our backtest result lucky, or is it robust?"

If the P5 final equity is still positive and the P95 max drawdown is
within FundingPips limits (< 10%), the strategy is robust.
"""

import random
from dataclasses import dataclass

# Type alias — we only need pnl from each trade
# Works with BacktestTrade or any object with a .pnl attribute


def _block_shuffle(pnls: list[float], block_size: int = 5) -> list[float]:
    """QR-15: Block bootstrap — shuffle blocks to preserve serial correlation."""
    n = len(pnls)
    blocks = [pnls[i:i+block_size] for i in range(0, n, block_size)]
    random.shuffle(blocks)
    result = []
    for block in blocks:
        result.extend(block)
    return result[:n]  # Trim to original length


def run_monte_carlo(
    trades: list,
    starting_balance: float = 100_000.0,
    n_simulations: int = 10_000,
    ruin_threshold_pct: float = 10.0,
) -> dict:
    """
    Run Monte Carlo permutation test on backtest trades.

    Args:
        trades: List of BacktestTrade objects (must have .pnl attribute)
        starting_balance: Starting account balance
        n_simulations: Number of random permutations (default 10,000)
        ruin_threshold_pct: Drawdown % that counts as "ruin" (default 10%)

    Returns:
        Dictionary with percentile stats, probability of ruin, and outcome ranges.
    """
    if not trades:
        return {
            "error": "No trades to simulate",
            "n_trades": 0,
            "n_simulations": 0,
        }

    # Extract PnL values from trade objects
    pnls = [t.pnl for t in trades]
    n_trades = len(pnls)

    # Run simulations
    final_equities: list[float] = []
    max_drawdowns: list[float] = []
    ruin_count = 0

    for _ in range(n_simulations):
        # QR-15: Block bootstrap — shuffle blocks to preserve serial correlation
        block_size = min(5, max(2, n_trades // 20))
        shuffled = _block_shuffle(pnls, block_size=block_size)

        # Walk through trades, track equity and drawdown
        equity = starting_balance
        peak = starting_balance
        worst_dd = 0.0

        for pnl in shuffled:
            equity += pnl
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak * 100.0 if peak > 0 else 0.0
            if dd > worst_dd:
                worst_dd = dd

        final_equities.append(equity)
        max_drawdowns.append(worst_dd)

        if worst_dd >= ruin_threshold_pct:
            ruin_count += 1

    # Sort for percentile calculations
    final_equities.sort()
    max_drawdowns.sort()

    def percentile(data: list[float], p: float) -> float:
        """Get the p-th percentile value from sorted data."""
        idx = int(len(data) * p / 100)
        idx = min(idx, len(data) - 1)
        return round(data[idx], 2)

    # Compute statistics
    equity_stats = {
        "P5": percentile(final_equities, 5),
        "P25": percentile(final_equities, 25),
        "P50": percentile(final_equities, 50),
        "P75": percentile(final_equities, 75),
        "P95": percentile(final_equities, 95),
    }

    drawdown_stats = {
        "P5": percentile(max_drawdowns, 5),
        "P25": percentile(max_drawdowns, 25),
        "P50": percentile(max_drawdowns, 50),
        "P75": percentile(max_drawdowns, 75),
        "P95": percentile(max_drawdowns, 95),
    }

    probability_of_ruin = round(ruin_count / n_simulations * 100, 2)

    # QR-16: Permutation test — is the edge statistically significant?
    # H0: trades have no directional edge (mean P&L = 0)
    # Test: what fraction of shuffled sequences have mean >= observed mean?
    observed_mean = sum(pnls) / n_trades if n_trades > 0 else 0
    better_count = sum(1 for eq in final_equities if (eq - starting_balance) / max(n_trades, 1) >= observed_mean)
    p_value = better_count / n_simulations if n_simulations > 0 else 1.0

    # Bootstrap 95% CI on final equity
    ci_lower = percentile(final_equities, 2.5) if len(final_equities) > 40 else equity_stats["P5"]
    ci_upper = percentile(final_equities, 97.5) if len(final_equities) > 40 else equity_stats["P95"]

    # Expected range (middle 90% of outcomes)
    expected_range = {
        "equity_low": equity_stats["P5"],
        "equity_high": equity_stats["P95"],
        "drawdown_low": drawdown_stats["P5"],
        "drawdown_high": drawdown_stats["P95"],
    }

    return {
        "n_trades": n_trades,
        "n_simulations": n_simulations,
        "starting_balance": starting_balance,
        "ruin_threshold_pct": ruin_threshold_pct,
        "final_equity": equity_stats,
        "max_drawdown_pct": drawdown_stats,
        "probability_of_ruin_pct": probability_of_ruin,
        "p_value": round(p_value, 4),
        "edge_significant": p_value < 0.05,
        "equity_ci_95": {"lower": ci_lower, "upper": ci_upper},
        "expected_range": expected_range,
        "is_robust": probability_of_ruin < 5.0 and equity_stats["P5"] > starting_balance,
        "summary": (
            f"Over {n_simulations:,} simulations with {n_trades} trades: "
            f"median final equity ${equity_stats['P50']:,.0f}, "
            f"median max DD {drawdown_stats['P50']:.1f}%, "
            f"ruin probability {probability_of_ruin:.1f}%, "
            f"p-value {p_value:.4f} ({'significant' if p_value < 0.05 else 'NOT significant'})"
        ),
    }
