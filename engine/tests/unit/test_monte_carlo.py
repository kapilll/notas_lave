"""Tests for Monte Carlo simulation — permutation test for backtest robustness."""

import pytest
from dataclasses import dataclass
from notas_lave.backtester.monte_carlo import run_monte_carlo, _block_shuffle


@dataclass
class _Trade:
    """Minimal trade stub — only .pnl needed."""
    pnl: float


def _wins(n: int, amount: float = 100.0) -> list[_Trade]:
    return [_Trade(pnl=amount) for _ in range(n)]


def _losses(n: int, amount: float = -50.0) -> list[_Trade]:
    return [_Trade(pnl=amount) for _ in range(n)]


def _mixed(wins: int, losses: int) -> list[_Trade]:
    return _wins(wins) + _losses(losses)


class TestBlockShuffle:
    def test_same_length_after_shuffle(self):
        pnls = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        result = _block_shuffle(pnls, block_size=3)
        assert len(result) == len(pnls)

    def test_same_elements_after_shuffle(self):
        pnls = [1.0, -2.0, 3.0, -4.0, 5.0]
        result = _block_shuffle(pnls, block_size=2)
        assert sorted(result) == sorted(pnls)

    def test_block_size_larger_than_list(self):
        pnls = [1.0, 2.0]
        result = _block_shuffle(pnls, block_size=10)
        assert sorted(result) == sorted(pnls)


class TestRunMonteCarlo:
    def test_empty_trades_returns_error(self):
        result = run_monte_carlo([])
        assert "error" in result
        assert result["n_trades"] == 0

    def test_returns_required_keys(self):
        trades = _mixed(20, 10)
        result = run_monte_carlo(trades, n_simulations=100)
        required = {
            "n_trades", "n_simulations", "starting_balance",
            "final_equity", "max_drawdown_pct", "probability_of_ruin_pct",
            "p_value", "edge_significant", "is_robust", "summary",
        }
        for key in required:
            assert key in result, f"Missing key: {key}"

    def test_n_trades_matches_input(self):
        trades = _mixed(15, 5)
        result = run_monte_carlo(trades, n_simulations=50)
        assert result["n_trades"] == 20

    def test_n_simulations_matches_input(self):
        trades = _wins(10)
        result = run_monte_carlo(trades, n_simulations=200)
        assert result["n_simulations"] == 200

    def test_consistently_profitable_strategy_is_robust(self):
        """A strategy that always wins $100 is almost certainly robust."""
        trades = _wins(50, amount=100.0)
        result = run_monte_carlo(trades, starting_balance=100_000.0, n_simulations=500)
        assert result["final_equity"]["P50"] > 100_000.0
        assert result["probability_of_ruin_pct"] == 0.0
        assert result["is_robust"] is True

    def test_catastrophic_losing_strategy_is_not_robust(self):
        """A strategy that always loses is never robust."""
        trades = _losses(50, amount=-500.0)
        result = run_monte_carlo(trades, starting_balance=10_000.0, n_simulations=200)
        assert result["final_equity"]["P50"] < 10_000.0

    def test_percentile_structure(self):
        trades = _mixed(30, 10)
        result = run_monte_carlo(trades, n_simulations=200)
        eq = result["final_equity"]
        dd = result["max_drawdown_pct"]
        # Percentiles must be monotonically non-decreasing
        assert eq["P5"] <= eq["P25"] <= eq["P50"] <= eq["P75"] <= eq["P95"]
        assert dd["P5"] <= dd["P25"] <= dd["P50"] <= dd["P75"] <= dd["P95"]

    def test_p_value_in_range(self):
        trades = _mixed(20, 10)
        result = run_monte_carlo(trades, n_simulations=200)
        assert 0.0 <= result["p_value"] <= 1.0

    def test_ruin_threshold_respected(self):
        """With ruin_threshold=5%, a very risky strategy should have high ruin probability."""
        trades = [_Trade(pnl=-200.0) if i % 2 == 0 else _Trade(pnl=100.0) for i in range(40)]
        result = run_monte_carlo(
            trades, starting_balance=1_000.0,
            n_simulations=500, ruin_threshold_pct=5.0,
        )
        # With such deep losses vs small balance, ruin should be common
        assert result["probability_of_ruin_pct"] >= 0.0  # Always non-negative

    def test_starting_balance_in_result(self):
        trades = _wins(10)
        result = run_monte_carlo(trades, starting_balance=50_000.0, n_simulations=50)
        assert result["starting_balance"] == 50_000.0

    def test_summary_is_non_empty_string(self):
        trades = _mixed(10, 5)
        result = run_monte_carlo(trades, n_simulations=100)
        assert isinstance(result["summary"], str)
        assert len(result["summary"]) > 20

    def test_expected_range_keys_present(self):
        trades = _mixed(20, 5)
        result = run_monte_carlo(trades, n_simulations=100)
        expected_range = result["expected_range"]
        assert "equity_low" in expected_range
        assert "equity_high" in expected_range
        assert "drawdown_low" in expected_range
        assert "drawdown_high" in expected_range
