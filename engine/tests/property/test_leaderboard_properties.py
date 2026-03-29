"""Property-based tests for Strategy Leaderboard.

LOCKED: These properties must always hold. If they fail, fix the implementation.
"""

import pytest
from hypothesis import given, assume, settings
from hypothesis import strategies as st

from notas_lave.engine.leaderboard import (
    StrategyLeaderboard, StrategyRecord,
    TRUST_MAX, TRUST_MIN, TRUST_WIN_BOOST, TRUST_LOSS_PENALTY,
)


def _fresh_leaderboard():
    """Create leaderboard that doesn't persist to disk."""
    lb = StrategyLeaderboard.__new__(StrategyLeaderboard)
    lb._records = {}
    lb._persist_path = "/dev/null"
    return lb


# --- Strategies for Hypothesis ---
win_loss_sequence = st.lists(
    st.tuples(
        st.booleans(),  # True = win, False = loss
        st.floats(min_value=0.01, max_value=10000.0, allow_nan=False, allow_infinity=False),
    ),
    min_size=1,
    max_size=100,
)


@given(sequence=win_loss_sequence)
def test_total_trades_equals_wins_plus_losses(sequence):
    """∀ sequence of wins/losses: total_trades == wins + losses.

    This is the most basic accounting invariant. If violated,
    the leaderboard is silently dropping or double-counting trades.
    """
    lb = _fresh_leaderboard()
    for is_win, amount in sequence:
        if is_win:
            lb.record_win("test_strategy", amount)
        else:
            lb.record_loss("test_strategy", -amount)

    rec = lb.get_or_create("test_strategy")
    assert rec.total_trades == rec.wins + rec.losses, (
        f"total_trades ({rec.total_trades}) != wins ({rec.wins}) + losses ({rec.losses})"
    )
    assert rec.total_trades == len(sequence)


@given(sequence=win_loss_sequence)
def test_trust_score_bounded_0_to_100(sequence):
    """∀ sequence: 0 ≤ trust_score ≤ 100.

    Trust score must never go below 0 or above 100, regardless of
    how many consecutive wins or losses occur.
    """
    lb = _fresh_leaderboard()
    for is_win, amount in sequence:
        if is_win:
            lb.record_win("test_strategy", amount)
        else:
            lb.record_loss("test_strategy", -amount)

    rec = lb.get_or_create("test_strategy")
    assert TRUST_MIN <= rec.trust_score <= TRUST_MAX, (
        f"Trust score {rec.trust_score} out of bounds [{TRUST_MIN}, {TRUST_MAX}]"
    )


@given(
    initial_trust=st.floats(min_value=TRUST_MIN + TRUST_WIN_BOOST,
                            max_value=TRUST_MAX - TRUST_WIN_BOOST,
                            allow_nan=False, allow_infinity=False),
    pnl=st.floats(min_value=0.01, max_value=10000.0, allow_nan=False, allow_infinity=False),
)
def test_trust_increases_on_win(initial_trust, pnl):
    """Win → trust increases (when not already at max)."""
    lb = _fresh_leaderboard()
    rec = lb.get_or_create("test_strategy")
    rec.trust_score = initial_trust
    before = rec.trust_score

    lb.record_win("test_strategy", pnl)

    assert rec.trust_score >= before, (
        f"Trust should increase on win: was {before}, now {rec.trust_score}"
    )


@given(
    initial_trust=st.floats(min_value=TRUST_MIN + TRUST_LOSS_PENALTY,
                            max_value=TRUST_MAX - TRUST_LOSS_PENALTY,
                            allow_nan=False, allow_infinity=False),
    pnl=st.floats(min_value=0.01, max_value=10000.0, allow_nan=False, allow_infinity=False),
)
def test_trust_decreases_on_loss(initial_trust, pnl):
    """Loss → trust decreases (when not already at min)."""
    lb = _fresh_leaderboard()
    rec = lb.get_or_create("test_strategy")
    rec.trust_score = initial_trust
    before = rec.trust_score

    lb.record_loss("test_strategy", -pnl)

    assert rec.trust_score <= before, (
        f"Trust should decrease on loss: was {before}, now {rec.trust_score}"
    )


@given(sequence=win_loss_sequence)
def test_gross_profit_and_loss_signs(sequence):
    """gross_profit >= 0, gross_loss <= 0, total_pnl == gross_profit + gross_loss."""
    lb = _fresh_leaderboard()
    for is_win, amount in sequence:
        if is_win:
            lb.record_win("test_strategy", amount)
        else:
            lb.record_loss("test_strategy", -amount)

    rec = lb.get_or_create("test_strategy")
    assert rec.gross_profit >= 0, f"gross_profit must be >= 0, got {rec.gross_profit}"
    assert rec.gross_loss <= 0, f"gross_loss must be <= 0, got {rec.gross_loss}"
    assert rec.total_pnl == pytest.approx(rec.gross_profit + rec.gross_loss, rel=1e-9), (
        f"total_pnl ({rec.total_pnl}) != profit ({rec.gross_profit}) + loss ({rec.gross_loss})"
    )


@given(n_wins=st.integers(min_value=0, max_value=50))
def test_max_consecutive_wins_never_exceeds_total_wins(n_wins):
    """consecutive_wins <= wins always."""
    lb = _fresh_leaderboard()
    for _ in range(n_wins):
        lb.record_win("test_strategy", 10.0)

    rec = lb.get_or_create("test_strategy")
    assert rec.consecutive_wins <= rec.wins


@given(n_losses=st.integers(min_value=0, max_value=50))
def test_max_consecutive_losses_never_exceeds_total_losses(n_losses):
    """consecutive_losses <= losses always."""
    lb = _fresh_leaderboard()
    for _ in range(n_losses):
        lb.record_loss("test_strategy", -10.0)

    rec = lb.get_or_create("test_strategy")
    assert rec.consecutive_losses <= rec.losses
