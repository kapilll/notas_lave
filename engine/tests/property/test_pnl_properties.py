"""Property-based tests for P&L calculation.

LOCKED: These properties must always hold. If they fail, fix the implementation.
Never change an assumption or weaken an assertion to make a test pass.
"""

import pytest
from hypothesis import given, assume
from hypothesis import strategies as st

from notas_lave.data.instruments import get_instrument


_INSTRUMENTS = ["XAUUSD", "BTCUSD", "ETHUSD"]


@given(
    symbol=st.sampled_from(_INSTRUMENTS),
    entry=st.floats(min_value=1.0, max_value=200_000.0, allow_nan=False, allow_infinity=False),
    exit_offset=st.floats(min_value=0.01, max_value=10_000.0, allow_nan=False, allow_infinity=False),
    lots=st.floats(min_value=0.001, max_value=100.0, allow_nan=False, allow_infinity=False),
)
def test_long_pnl_positive_when_price_rises(symbol, entry, exit_offset, lots):
    """∀ entry > 0, exit > entry, lots > 0: LONG P&L > 0.

    A long position makes money when price goes up. This is the most fundamental
    property of a directional trade. If violated, the P&L engine is broken.
    """
    exit_price = entry + exit_offset
    spec = get_instrument(symbol)
    assume(spec is not None)

    pnl = spec.calculate_pnl(entry=entry, exit=exit_price, lots=lots, direction="LONG")
    assert pnl > 0, (
        f"{symbol}: LONG P&L should be positive when exit ({exit_price}) > entry ({entry}). "
        f"Got {pnl} for {lots} lots"
    )


@given(
    symbol=st.sampled_from(_INSTRUMENTS),
    entry=st.floats(min_value=1.0, max_value=200_000.0, allow_nan=False, allow_infinity=False),
    exit_offset=st.floats(min_value=0.01, max_value=10_000.0, allow_nan=False, allow_infinity=False),
    lots=st.floats(min_value=0.001, max_value=100.0, allow_nan=False, allow_infinity=False),
)
def test_short_pnl_positive_when_price_falls(symbol, entry, exit_offset, lots):
    """∀ entry > 0, exit < entry, lots > 0: SHORT P&L > 0.

    A short position makes money when price goes down.
    """
    exit_price = entry - exit_offset
    assume(exit_price > 0)
    spec = get_instrument(symbol)
    assume(spec is not None)

    pnl = spec.calculate_pnl(entry=entry, exit=exit_price, lots=lots, direction="SHORT")
    assert pnl > 0, (
        f"{symbol}: SHORT P&L should be positive when exit ({exit_price}) < entry ({entry}). "
        f"Got {pnl} for {lots} lots"
    )


@given(
    symbol=st.sampled_from(_INSTRUMENTS),
    entry=st.floats(min_value=1.0, max_value=200_000.0, allow_nan=False, allow_infinity=False),
    lots=st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False),
    direction=st.sampled_from(["LONG", "SHORT"]),
)
def test_pnl_zero_at_entry(symbol, entry, lots, direction):
    """∀ entry > 0, lots >= 0: P&L is exactly 0 when exit == entry.

    If you close a trade at exactly the entry price, P&L must be zero.
    Any non-zero result implies a pricing or math bug.
    """
    spec = get_instrument(symbol)
    assume(spec is not None)

    pnl = spec.calculate_pnl(entry=entry, exit=entry, lots=lots, direction=direction)
    assert pnl == pytest.approx(0.0, abs=1e-9), (
        f"{symbol}: P&L should be 0.0 when exit==entry. Got {pnl}"
    )


@given(
    symbol=st.sampled_from(_INSTRUMENTS),
    entry=st.floats(min_value=1.0, max_value=200_000.0, allow_nan=False, allow_infinity=False),
    exit_offset=st.floats(min_value=0.01, max_value=10_000.0, allow_nan=False, allow_infinity=False),
    lots=st.floats(min_value=0.001, max_value=100.0, allow_nan=False, allow_infinity=False),
)
def test_pnl_is_antisymmetric(symbol, entry, exit_offset, lots):
    """flip direction, flip sign: LONG P&L == -(SHORT P&L) at the same prices.

    If going LONG from A to B makes $X, going SHORT from A to B must lose exactly $X.
    This antisymmetry is fundamental to zero-sum market mechanics.
    """
    exit_price = entry + exit_offset
    spec = get_instrument(symbol)
    assume(spec is not None)

    pnl_long = spec.calculate_pnl(entry=entry, exit=exit_price, lots=lots, direction="LONG")
    pnl_short = spec.calculate_pnl(entry=entry, exit=exit_price, lots=lots, direction="SHORT")

    assert pnl_long == pytest.approx(-pnl_short, rel=1e-9), (
        f"{symbol}: LONG P&L ({pnl_long}) should equal -SHORT P&L ({pnl_short}). "
        f"entry={entry}, exit={exit_price}, lots={lots}"
    )


@given(
    symbol=st.sampled_from(_INSTRUMENTS),
    entry=st.floats(min_value=1.0, max_value=200_000.0, allow_nan=False, allow_infinity=False),
    exit_offset=st.floats(min_value=0.01, max_value=10_000.0, allow_nan=False, allow_infinity=False),
    lots=st.floats(min_value=0.001, max_value=100.0, allow_nan=False, allow_infinity=False),
    direction=st.sampled_from(["LONG", "SHORT"]),
)
def test_pnl_includes_contract_size(symbol, entry, exit_offset, lots, direction):
    """∀ instrument: pnl = price_diff * lots * contract_size.

    Contract size is critical — Gold has contract_size=100 (100 oz/lot),
    crypto has contract_size=1. Without it, Gold P&L is 100x wrong.
    """
    exit_price = entry + exit_offset if direction == "LONG" else entry - exit_offset
    assume(exit_price > 0)
    spec = get_instrument(symbol)
    assume(spec is not None)

    pnl = spec.calculate_pnl(entry=entry, exit=exit_price, lots=lots, direction=direction)

    # Manually compute expected P&L
    price_diff = (exit_price - entry) if direction == "LONG" else (entry - exit_price)
    expected = price_diff * spec.contract_size * lots

    assert pnl == pytest.approx(expected, rel=1e-9), (
        f"{symbol}: P&L={pnl} but expected price_diff*contract_size*lots = {expected}. "
        f"contract_size={spec.contract_size}"
    )


@given(
    deposit=st.floats(min_value=100.0, max_value=10_000_000.0, allow_nan=False, allow_infinity=False),
    pnl_offset=st.floats(min_value=-50_000.0, max_value=50_000.0, allow_nan=False, allow_infinity=False),
)
def test_pnl_service_identity(deposit, pnl_offset):
    """∀ deposit > 0, balance: pnl_service.calculate(balance).pnl == balance - deposit.

    The P&L service computes net profit/loss since account inception.
    This must exactly equal current_balance - original_deposit.
    """
    from notas_lave.engine.pnl import PnLService

    current_balance = deposit + pnl_offset
    assume(current_balance > 0)

    svc = PnLService(original_deposit=deposit)
    result = svc.calculate(current_balance)

    expected_pnl = current_balance - deposit
    assert result.pnl == pytest.approx(expected_pnl, abs=0.01), (
        f"P&L service: got {result.pnl}, expected {expected_pnl} "
        f"(deposit={deposit}, balance={current_balance})"
    )
