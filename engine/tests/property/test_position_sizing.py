"""Property-based tests for position sizing.

LOCKED: These properties must always hold. If they fail, fix the implementation.
Never change an assumption or weaken an assertion to make a test pass.
"""

import pytest
from hypothesis import given, assume, settings
from hypothesis import strategies as st

from notas_lave.data.instruments import get_instrument


# Instruments with known positive contract sizes to test against
_INSTRUMENTS = ["XAUUSD", "BTCUSD", "ETHUSD"]


@given(
    symbol=st.sampled_from(_INSTRUMENTS),
    entry=st.floats(min_value=100.0, max_value=200_000.0, allow_nan=False, allow_infinity=False),
    sl_offset=st.floats(min_value=0.01, max_value=500.0, allow_nan=False, allow_infinity=False),
    balance=st.floats(min_value=100.0, max_value=10_000_000.0, allow_nan=False, allow_infinity=False),
    risk_pct=st.floats(min_value=0.001, max_value=0.10, allow_nan=False, allow_infinity=False),
)
def test_position_size_never_negative(symbol, entry, sl_offset, balance, risk_pct):
    """∀ entry, sl, balance, risk: position_size >= 0.

    Position sizing must never return a negative number regardless of inputs.
    A negative position size is nonsensical and would cause incorrect risk calculations.
    """
    sl = entry - sl_offset  # Always a valid LONG stop (below entry)
    spec = get_instrument(symbol)
    assume(spec is not None)
    size = spec.calculate_position_size(
        entry=entry, stop_loss=sl, account_balance=balance, risk_pct=risk_pct
    )
    assert size >= 0, (
        f"{symbol}: negative size {size} for entry={entry}, sl={sl}, "
        f"balance={balance}, risk_pct={risk_pct}"
    )


@given(
    symbol=st.sampled_from(_INSTRUMENTS),
    entry=st.floats(min_value=100.0, max_value=200_000.0, allow_nan=False, allow_infinity=False),
    sl_offset=st.floats(min_value=0.01, max_value=500.0, allow_nan=False, allow_infinity=False),
    balance=st.floats(min_value=100.0, max_value=10_000_000.0, allow_nan=False, allow_infinity=False),
    risk_pct=st.floats(min_value=0.001, max_value=0.10, allow_nan=False, allow_infinity=False),
)
def test_position_risk_never_exceeds_budget(symbol, entry, sl_offset, balance, risk_pct):
    """∀ LONG: actual_risk <= budget * 1.01 (1% tolerance for rounding).

    If the risk budget is $1000, we must never bet more than ~$1010 on a single trade.
    The 1% tolerance accounts for lot rounding (min_lot steps).
    """
    sl = entry - sl_offset
    spec = get_instrument(symbol)
    assume(spec is not None)

    size = spec.calculate_position_size(
        entry=entry, stop_loss=sl, account_balance=balance, risk_pct=risk_pct
    )
    assume(size > 0)  # Skip zero-size cases (min_lot rejection etc.)

    actual_risk = sl_offset * spec.contract_size * size
    budget = balance * risk_pct

    assert actual_risk <= budget * 1.01, (
        f"{symbol}: risk ${actual_risk:.2f} exceeds budget ${budget:.2f} * 1.01. "
        f"entry={entry}, sl={sl}, size={size}"
    )


@given(
    symbol=st.sampled_from(_INSTRUMENTS),
    entry=st.floats(min_value=100.0, max_value=200_000.0, allow_nan=False, allow_infinity=False),
    sl_offset1=st.floats(min_value=0.5, max_value=100.0, allow_nan=False, allow_infinity=False),
    sl_offset2=st.floats(min_value=200.0, max_value=500.0, allow_nan=False, allow_infinity=False),
    balance=st.floats(min_value=1000.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False),
)
def test_position_size_decreases_as_sl_widens(symbol, entry, sl_offset1, sl_offset2, balance):
    """Larger SL distance → smaller or equal position size (when both are tradeable).

    If your stop is further away, you must trade smaller to keep the same risk.
    A wider SL must NEVER allow a larger position — that would multiply risk.

    Note: QR-07 safety check may reject tiny positions where min_lot exceeds the
    risk budget. When this happens the tight SL may return 0 while the wider SL
    passes — this is correct (the tight SL required a position too small for
    the exchange). We only compare when both produce tradeable sizes.
    """
    spec = get_instrument(symbol)
    assume(spec is not None)
    assume(sl_offset1 < sl_offset2)  # sl1 is tighter

    sl1 = entry - sl_offset1  # Tighter stop
    sl2 = entry - sl_offset2  # Wider stop
    assume(sl1 > 0 and sl2 > 0)

    size_tight = spec.calculate_position_size(entry=entry, stop_loss=sl1, account_balance=balance)
    size_wide = spec.calculate_position_size(entry=entry, stop_loss=sl2, account_balance=balance)

    # Only meaningful to compare when both return tradeable (non-zero) sizes.
    # QR-07 rejection (size=0) means the position is too small for the exchange.
    assume(size_tight > 0 and size_wide > 0)

    assert size_tight >= size_wide, (
        f"{symbol}: tight SL ({sl_offset1:.2f}) gave smaller size ({size_tight}) "
        f"than wide SL ({sl_offset2:.2f}) size ({size_wide}). "
        f"entry={entry}, balance={balance}"
    )


@given(
    symbol=st.sampled_from(_INSTRUMENTS),
    entry=st.floats(min_value=100.0, max_value=200_000.0, allow_nan=False, allow_infinity=False),
    sl_offset=st.floats(min_value=1.0, max_value=200.0, allow_nan=False, allow_infinity=False),
    balance1=st.floats(min_value=100.0, max_value=50_000.0, allow_nan=False, allow_infinity=False),
    balance2=st.floats(min_value=100_000.0, max_value=10_000_000.0, allow_nan=False, allow_infinity=False),
)
def test_position_size_scales_with_balance(symbol, entry, sl_offset, balance1, balance2):
    """Proportional to balance: larger account → larger (or equal) position at same risk%.

    If you double your account size, you should be able to take (at least) the same
    sized position. A larger balance must never result in a smaller position.
    """
    spec = get_instrument(symbol)
    assume(spec is not None)
    sl = entry - sl_offset
    assume(sl > 0)

    size_small = spec.calculate_position_size(entry=entry, stop_loss=sl, account_balance=balance1)
    size_large = spec.calculate_position_size(entry=entry, stop_loss=sl, account_balance=balance2)

    # QR-07: lot rounding can cause different-sized accounts to get rejected differently.
    # Only compare when both produce tradeable sizes.
    assume(size_small > 0 and size_large > 0)

    assert size_large >= size_small, (
        f"{symbol}: larger balance ({balance2}) produced smaller position ({size_large}) "
        f"than smaller balance ({balance1}) position ({size_small}). "
        f"entry={entry}, sl={sl}"
    )


@given(
    symbol=st.sampled_from(_INSTRUMENTS),
    entry=st.floats(min_value=100.0, max_value=200_000.0, allow_nan=False, allow_infinity=False),
    sl_offset=st.floats(min_value=0.01, max_value=500.0, allow_nan=False, allow_infinity=False),
    balance=st.floats(min_value=100.0, max_value=10_000_000.0, allow_nan=False, allow_infinity=False),
    risk_pct=st.floats(min_value=0.001, max_value=0.10, allow_nan=False, allow_infinity=False),
)
def test_qr07_min_lot_exceeding_risk_returns_zero(symbol, entry, sl_offset, balance, risk_pct):
    """QR-07: If clamping to min_lot would exceed the risk budget, return 0.

    This is a critical safety property. Without it, a $100 account with a $5 SL
    on Gold would get clamped from 0.0006 lots to 0.01 lots — turning 0.3% risk
    into 5% risk. The position sizer MUST reject when min_lot > risk budget.
    """
    sl = entry - sl_offset
    assume(sl > 0)
    spec = get_instrument(symbol)
    assume(spec is not None)

    size = spec.calculate_position_size(
        entry=entry, stop_loss=sl, account_balance=balance, risk_pct=risk_pct
    )

    if size > 0:
        # If we got a non-zero size, actual risk must not exceed budget by more than 1%
        actual_risk = size * sl_offset * spec.contract_size
        budget = balance * risk_pct
        assert actual_risk <= budget * 1.01, (
            f"QR-07 VIOLATION: {symbol} size={size} gives risk ${actual_risk:.2f} "
            f"but budget is ${budget:.2f}. min_lot check failed!"
        )


@given(
    symbol=st.sampled_from(_INSTRUMENTS),
    entry=st.floats(min_value=100.0, max_value=200_000.0, allow_nan=False, allow_infinity=False),
    balance=st.floats(min_value=100.0, max_value=10_000_000.0, allow_nan=False, allow_infinity=False),
)
def test_zero_sl_always_zero_position(symbol, entry, balance):
    """∀ entry: size(entry, sl=entry) == 0.

    SL at exactly the entry price means zero risk distance.
    A zero-risk trade has no meaningful size — must return 0.
    """
    spec = get_instrument(symbol)
    assume(spec is not None)
    size = spec.calculate_position_size(entry=entry, stop_loss=entry, account_balance=balance)
    assert size == 0.0, (
        f"{symbol}: SL==entry should give size=0, got {size} "
        f"(entry={entry}, balance={balance})"
    )
