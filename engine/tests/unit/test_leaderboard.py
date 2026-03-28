"""Tests for StrategyLeaderboard — arena trust scoring and suspension logic.

Critical safety properties:
- Losses hurt more than wins (asymmetric: -5 vs +3)
- Trust < 20 → strategy SUSPENDED, can_trade() always returns False
- Trust > 80 → proven, gets lower signal threshold (more opportunities)
"""

import os
import tempfile
import pytest

from notas_lave.engine.leaderboard import (
    StrategyLeaderboard, StrategyRecord,
    TRUST_WIN_BOOST, TRUST_LOSS_PENALTY,
    TRUST_MAX, TRUST_MIN, TRUST_SUSPEND_THRESHOLD,
    THRESHOLD_PROVEN, THRESHOLD_STANDARD, THRESHOLD_CAUTION,
)


def _make_leaderboard() -> StrategyLeaderboard:
    """Create a leaderboard with no-persist path for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "lb.json")
        lb = StrategyLeaderboard(persist_path=path)
    return lb


def _fresh() -> StrategyLeaderboard:
    """Leaderboard backed by temp file that persists during test."""
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "lb.json")
    return StrategyLeaderboard(persist_path=path)


# ─── Constants ───────────────────────────────────────────────────────────────

class TestConstants:
    def test_loss_penalty_greater_than_win_boost(self):
        """Losses must hurt more than wins — asymmetric risk."""
        assert TRUST_LOSS_PENALTY > TRUST_WIN_BOOST

    def test_suspend_threshold_reasonable(self):
        """Suspension kicks in at low trust, not at zero."""
        assert 0 < TRUST_SUSPEND_THRESHOLD < 50

    def test_threshold_proven_lower_than_standard(self):
        """Proven strategies get more trading opportunities (lower threshold)."""
        assert THRESHOLD_PROVEN < THRESHOLD_STANDARD

    def test_threshold_standard_lower_than_caution(self):
        assert THRESHOLD_STANDARD < THRESHOLD_CAUTION


# ─── StrategyRecord ───────────────────────────────────────────────────────────

class TestStrategyRecord:
    def test_default_trust_score(self):
        """New strategy starts at neutral trust (50)."""
        rec = StrategyRecord(name="test")
        assert rec.trust_score == 50.0
        assert rec.is_active is True

    def test_win_rate_zero_no_trades(self):
        rec = StrategyRecord(name="test")
        assert rec.win_rate == 0.0

    def test_win_rate_calculated(self):
        rec = StrategyRecord(name="test", total_trades=10, wins=7)
        assert rec.win_rate == 70.0

    def test_profit_factor_no_losses(self):
        rec = StrategyRecord(name="test", gross_profit=500.0, gross_loss=0.0)
        assert rec.profit_factor == 500.0

    def test_profit_factor_no_trades(self):
        rec = StrategyRecord(name="test")
        assert rec.profit_factor == 0.0

    def test_profit_factor_calculated(self):
        rec = StrategyRecord(name="test", gross_profit=300.0, gross_loss=-100.0)
        assert rec.profit_factor == pytest.approx(3.0)

    def test_expectancy_no_trades(self):
        rec = StrategyRecord(name="test")
        assert rec.expectancy == 0.0

    def test_expectancy_calculated(self):
        rec = StrategyRecord(name="test", total_trades=10, total_pnl=250.0)
        assert rec.expectancy == 25.0

    def test_min_signal_score_proven(self):
        """Trust ≥ 80 → lower threshold (proven)."""
        rec = StrategyRecord(name="test", trust_score=85.0)
        assert rec.min_signal_score == THRESHOLD_PROVEN

    def test_min_signal_score_standard(self):
        rec = StrategyRecord(name="test", trust_score=60.0)
        assert rec.min_signal_score == THRESHOLD_STANDARD

    def test_min_signal_score_caution(self):
        rec = StrategyRecord(name="test", trust_score=40.0)
        assert rec.min_signal_score == THRESHOLD_CAUTION

    def test_min_signal_score_suspended(self):
        """Trust < 30 → effectively suspended (score 100 = impossible)."""
        rec = StrategyRecord(name="test", trust_score=10.0)
        assert rec.min_signal_score == 100.0

    def test_status_proven(self):
        rec = StrategyRecord(name="test", trust_score=85.0)
        assert rec.status == "proven"

    def test_status_standard(self):
        rec = StrategyRecord(name="test", trust_score=60.0)
        assert rec.status == "standard"

    def test_status_caution(self):
        rec = StrategyRecord(name="test", trust_score=40.0)
        assert rec.status == "caution"

    def test_status_suspended_by_trust(self):
        rec = StrategyRecord(name="test", trust_score=15.0)
        assert rec.status == "suspended"

    def test_status_suspended_by_flag(self):
        rec = StrategyRecord(name="test", trust_score=60.0, is_active=False)
        assert rec.status == "suspended"

    def test_to_dict_has_all_fields(self):
        rec = StrategyRecord(name="trend_momentum")
        d = rec.to_dict()
        assert d["name"] == "trend_momentum"
        assert "win_rate" in d
        assert "profit_factor" in d
        assert "expectancy" in d
        assert "status" in d
        assert "trust_score" in d


# ─── StrategyLeaderboard ─────────────────────────────────────────────────────

class TestStrategyLeaderboard:
    def test_get_or_create_new_strategy(self):
        lb = _fresh()
        rec = lb.get_or_create("trend_momentum")
        assert rec.name == "trend_momentum"
        assert rec.trust_score == 50.0

    def test_get_or_create_idempotent(self):
        lb = _fresh()
        r1 = lb.get_or_create("mean_reversion")
        r2 = lb.get_or_create("mean_reversion")
        assert r1 is r2

    def test_record_win_increments_trades(self):
        lb = _fresh()
        lb.record_win("trend_momentum", pnl=100.0)
        rec = lb.get_or_create("trend_momentum")
        assert rec.total_trades == 1
        assert rec.wins == 1
        assert rec.total_pnl == 100.0

    def test_record_win_increases_trust(self):
        lb = _fresh()
        lb.record_win("trend_momentum", pnl=100.0)
        rec = lb.get_or_create("trend_momentum")
        assert rec.trust_score == 53.0  # 50 + 3

    def test_record_win_caps_at_max(self):
        lb = _fresh()
        # Win enough times to hit cap
        for _ in range(20):
            lb.record_win("strategy", pnl=10.0)
        rec = lb.get_or_create("strategy")
        assert rec.trust_score == TRUST_MAX

    def test_record_loss_decrements_trust(self):
        lb = _fresh()
        lb.record_loss("trend_momentum", pnl=-50.0)
        rec = lb.get_or_create("trend_momentum")
        assert rec.trust_score == 45.0  # 50 - 5

    def test_record_loss_suspends_at_threshold(self):
        """After enough losses, trust drops below threshold → suspended."""
        lb = _fresh()
        # Need (50 - 20) / 5 = 6 losses to hit suspension
        for _ in range(7):
            lb.record_loss("risky_strategy", pnl=-100.0)
        rec = lb.get_or_create("risky_strategy")
        assert rec.trust_score < TRUST_SUSPEND_THRESHOLD
        assert rec.is_active is False

    def test_record_loss_floors_at_zero(self):
        lb = _fresh()
        for _ in range(15):
            lb.record_loss("strategy", pnl=-100.0)
        rec = lb.get_or_create("strategy")
        assert rec.trust_score == TRUST_MIN

    def test_record_win_reactivates_suspended(self):
        """Winning after suspension (trust recovers above threshold) reactivates."""
        lb = _fresh()
        rec = lb.get_or_create("strategy")
        rec.trust_score = 19.0  # Below threshold
        rec.is_active = False
        lb.record_win("strategy", pnl=100.0)
        # Trust is now 22, above 20
        assert lb.get_or_create("strategy").is_active is True

    def test_streak_tracking_consecutive_wins(self):
        lb = _fresh()
        lb.record_win("s", pnl=10.0)
        lb.record_win("s", pnl=10.0)
        lb.record_win("s", pnl=10.0)
        rec = lb.get_or_create("s")
        assert rec.consecutive_wins >= 3

    def test_streak_resets_on_loss(self):
        lb = _fresh()
        lb.record_win("s", pnl=10.0)
        lb.record_win("s", pnl=10.0)
        lb.record_loss("s", pnl=-10.0)
        rec = lb.get_or_create("s")
        assert rec.current_streak < 0

    def test_can_trade_active_with_good_score(self):
        lb = _fresh()
        lb.get_or_create("strategy")  # trust=50, min_score=THRESHOLD_STANDARD=65
        assert lb.can_trade("strategy", signal_score=70.0) is True

    def test_can_trade_active_with_low_score(self):
        lb = _fresh()
        lb.get_or_create("strategy")
        assert lb.can_trade("strategy", signal_score=50.0) is False

    def test_can_trade_suspended_always_false(self):
        lb = _fresh()
        rec = lb.get_or_create("bad_strategy")
        rec.is_active = False
        assert lb.can_trade("bad_strategy", signal_score=100.0) is False

    def test_can_trade_proven_lower_threshold(self):
        """Proven strategy (trust>80) needs lower score to trade."""
        lb = _fresh()
        rec = lb.get_or_create("proven_strategy")
        rec.trust_score = 90.0  # Proven
        # THRESHOLD_PROVEN = 55 — score 60 should pass
        assert lb.can_trade("proven_strategy", signal_score=60.0) is True

    def test_get_leaderboard_returns_all(self):
        lb = _fresh()
        lb.record_win("a", pnl=100.0)
        lb.record_win("b", pnl=50.0)
        board = lb.get_leaderboard()
        assert len(board) == 2

    def test_get_leaderboard_sorted_by_trust(self):
        lb = _fresh()
        lb.record_win("low_trust", pnl=10.0)
        lb.record_win("high_trust", pnl=10.0)
        lb.record_win("high_trust", pnl=10.0)  # Two wins = higher trust
        board = lb.get_leaderboard(sort_by="trust_score")
        assert board[0]["trust_score"] >= board[1]["trust_score"]

    def test_get_leaderboard_sort_consecutive_losses(self):
        lb = _fresh()
        lb.record_loss("bad", pnl=-10.0)
        lb.record_loss("bad", pnl=-10.0)
        lb.record_win("good", pnl=10.0)
        board = lb.get_leaderboard(sort_by="consecutive_losses")
        # Lower losses first (ascending)
        assert board[0]["consecutive_losses"] <= board[-1]["consecutive_losses"]

    def test_get_strategy_returns_dict(self):
        lb = _fresh()
        lb.record_win("trend_momentum", pnl=200.0)
        d = lb.get_strategy("trend_momentum")
        assert d is not None
        assert d["name"] == "trend_momentum"

    def test_get_strategy_nonexistent_returns_none(self):
        lb = _fresh()
        assert lb.get_strategy("nonexistent_xyz") is None

    def test_get_active_strategies(self):
        lb = _fresh()
        lb.get_or_create("active_1")
        lb.get_or_create("active_2")
        rec = lb.get_or_create("suspended")
        rec.is_active = False
        active = lb.get_active_strategies()
        assert "active_1" in active
        assert "active_2" in active
        assert "suspended" not in active

    def test_reset_strategy(self):
        lb = _fresh()
        lb.record_win("s", pnl=500.0)
        lb.reset_strategy("s")
        rec = lb.get_or_create("s")
        assert rec.trust_score == 50.0
        assert rec.total_trades == 0

    def test_persist_and_load(self):
        """Save leaderboard, load it fresh → same data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "lb.json")
            lb1 = StrategyLeaderboard(persist_path=path)
            lb1.record_win("trend_momentum", pnl=150.0)
            lb1.record_loss("breakout_system", pnl=-50.0)

            lb2 = StrategyLeaderboard(persist_path=path)
            assert lb2.get_or_create("trend_momentum").wins == 1
            assert lb2.get_or_create("breakout_system").losses == 1

    def test_best_and_worst_trade_tracking(self):
        lb = _fresh()
        lb.record_win("s", pnl=500.0)
        lb.record_win("s", pnl=100.0)
        lb.record_loss("s", pnl=-200.0)
        rec = lb.get_or_create("s")
        assert rec.best_trade == 500.0
        assert rec.worst_trade == -200.0
