"""Property-based tests for risk manager invariants.

LOCKED: These properties must always hold. If they fail, fix the implementation.
Never change an assumption or weaken an assertion to make a test pass.
"""

from hypothesis import given, assume
from hypothesis import strategies as st

from notas_lave.risk.manager import RiskManager
from notas_lave.data.models import TradeSetup, Direction


def _make_valid_setup(
    direction: Direction = Direction.LONG,
    entry: float = 2000.0,
    sl: float = 1980.0,
    tp: float = 2040.0,
    position_size: float = 0.1,
    rr: float = 2.0,
) -> TradeSetup:
    return TradeSetup(
        symbol="XAUUSD",
        timeframe="5m",
        direction=direction,
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp,
        position_size=position_size,
        risk_reward_ratio=rr,
    )


@given(
    entry=st.floats(min_value=100.0, max_value=200_000.0, allow_nan=False, allow_infinity=False),
    sl_offset=st.floats(min_value=1.0, max_value=100.0, allow_nan=False, allow_infinity=False),
    tp_multiplier=st.floats(min_value=2.5, max_value=5.0, allow_nan=False, allow_infinity=False),
    balance=st.floats(min_value=10_000.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False),
)
def test_risk_always_rejects_when_halted(entry, sl_offset, tp_multiplier, balance):
    """∀ valid trade setup: if is_trading_halted == True → validate_trade() rejects.

    No trade must ever execute when trading is halted. This is the most important
    safety property — it prevents prop firm violations and catastrophic losses.
    """
    sl = entry - sl_offset
    tp = entry + sl_offset * tp_multiplier
    assume(sl > 0)

    rm = RiskManager(starting_balance=balance)
    today = rm._get_today_stats()
    today.is_trading_halted = True

    setup = _make_valid_setup(entry=entry, sl=sl, tp=tp, rr=tp_multiplier)
    valid, reasons = rm.validate_trade(setup)

    assert not valid, "validate_trade must reject when trading is halted"
    assert any("HALTED" in r for r in reasons), (
        f"Rejection reasons must mention HALTED. Got: {reasons}"
    )


@given(
    balance=st.floats(min_value=10_000.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False),
    daily_loss_multiplier=st.floats(min_value=1.1, max_value=2.0, allow_nan=False, allow_infinity=False),
)
def test_risk_always_rejects_on_daily_dd_breach(balance, daily_loss_multiplier):
    """∀ daily_loss > max_daily_dd * balance: validate_trade() rejects.

    Daily drawdown is the #1 prop firm rule. A breach must ALWAYS be caught.
    Using 22% loss (exceeds both prop 5% and personal 20% limits).
    """
    rm = RiskManager(starting_balance=balance)
    today = rm._get_today_stats()
    # 22% loss exceeds BOTH prop (5%) and personal (20%) daily DD limits
    today.realized_pnl = -balance * 0.22 * daily_loss_multiplier

    setup = _make_valid_setup(position_size=0.001)  # Tiny size to avoid position size rejection
    valid, reasons = rm.validate_trade(setup)

    assert not valid, (
        f"validate_trade must reject when daily DD is breached. "
        f"balance={balance}, daily_loss={today.realized_pnl:.2f}"
    )


@given(
    balance=st.floats(min_value=10_000.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False),
    total_loss_multiplier=st.floats(min_value=1.1, max_value=2.0, allow_nan=False, allow_infinity=False),
)
def test_risk_always_rejects_on_total_dd_breach(balance, total_loss_multiplier):
    """∀ total_pnl < -max_total_dd * balance: validate_trade() rejects.

    Total drawdown is static from original balance (prop firm rule).
    Using 12% total loss (exceeds both prop 10% and personal 20% limits... wait
    for personal 20%, 12% doesn't exceed. Use 22% instead).
    """
    rm = RiskManager(starting_balance=balance)
    # 22% total loss exceeds BOTH prop (10%) and personal (20%) total DD limits
    rm.total_pnl = -balance * 0.22 * total_loss_multiplier

    setup = _make_valid_setup(position_size=0.001)
    valid, reasons = rm.validate_trade(setup)

    assert not valid, (
        f"validate_trade must reject when total DD is breached. "
        f"balance={balance}, total_pnl={rm.total_pnl:.2f}"
    )


@given(
    entry=st.floats(min_value=100.0, max_value=200_000.0, allow_nan=False, allow_infinity=False),
    sl_above_offset=st.floats(min_value=0.01, max_value=100.0, allow_nan=False, allow_infinity=False),
    balance=st.floats(min_value=10_000.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False),
)
def test_risk_always_rejects_invalid_sl_for_long(entry, sl_above_offset, balance):
    """∀ LONG setup where sl >= entry: validate_trade() rejects.

    A LONG trade with SL at or above entry means the trade is already stopped out
    or has no meaningful stop. The risk manager must always catch this.
    """
    sl = entry + sl_above_offset  # SL above entry for LONG — always wrong
    tp = entry + sl_above_offset * 2.5

    rm = RiskManager(starting_balance=balance)
    setup = TradeSetup(
        symbol="XAUUSD",
        timeframe="5m",
        direction=Direction.LONG,
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp,
        position_size=0.1,
        risk_reward_ratio=2.0,
    )
    valid, reasons = rm.validate_trade(setup)

    assert not valid, (
        f"LONG with SL ({sl}) >= entry ({entry}) must always be rejected"
    )
    assert any("INVALID SL" in r for r in reasons), (
        f"Rejection must mention INVALID SL. Got: {reasons}"
    )
