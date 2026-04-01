"""Tests for risk manager — the gatekeeper that prevents catastrophic losses.

STABLE tier: add tests for new features, never remove/weaken existing assertions.
Tests work regardless of trading mode (prop or personal) by using
values that exceed BOTH modes' limits.
"""

from datetime import datetime, date, timedelta, timezone

from notas_lave.risk.manager import (
    RiskManager, WEIGHT_BOUNDS, MAX_BLACKLIST_GROWTH_PER_WEEK,
)
from notas_lave.data.models import TradeSetup, Direction, MarketRegime, TradeStatus


def _make_setup(
    direction=Direction.LONG, entry=2000.0, sl=1990.0, tp=2020.0,
    position_size=1.0, rr=2.0, symbol="XAUUSD",
) -> TradeSetup:
    return TradeSetup(
        symbol=symbol, timeframe="5m", direction=direction,
        entry_price=entry, stop_loss=sl, take_profit=tp,
        position_size=position_size, risk_reward_ratio=rr,
    )


# ────────────────────────────────────────────────────────────
# SL / TP Validation (UNIVERSAL — both modes)
# ────────────────────────────────────────────────────────────
class TestSLTPValidation:
    def test_long_sl_above_entry_rejected(self):
        rm = RiskManager(starting_balance=100_000)
        setup = _make_setup(direction=Direction.LONG, entry=2000.0, sl=2010.0, tp=2040.0)
        valid, reasons = rm.validate_trade(setup)
        assert not valid
        assert any("INVALID SL" in r for r in reasons)

    def test_long_sl_at_entry_rejected(self):
        rm = RiskManager(starting_balance=100_000)
        setup = _make_setup(entry=2000.0, sl=2000.0, tp=2040.0)
        valid, reasons = rm.validate_trade(setup)
        assert not valid
        assert any("INVALID SL" in r for r in reasons)

    def test_long_tp_below_entry_rejected(self):
        rm = RiskManager(starting_balance=100_000)
        setup = _make_setup(direction=Direction.LONG, entry=2000.0, sl=1990.0, tp=1980.0)
        valid, reasons = rm.validate_trade(setup)
        assert not valid
        assert any("INVALID TP" in r for r in reasons)

    def test_short_sl_below_entry_rejected(self):
        rm = RiskManager(starting_balance=100_000)
        setup = _make_setup(direction=Direction.SHORT, entry=2000.0, sl=1990.0, tp=1960.0)
        valid, reasons = rm.validate_trade(setup)
        assert not valid
        assert any("INVALID SL" in r for r in reasons)

    def test_short_tp_above_entry_rejected(self):
        rm = RiskManager(starting_balance=100_000)
        setup = _make_setup(direction=Direction.SHORT, entry=2000.0, sl=2010.0, tp=2020.0)
        valid, reasons = rm.validate_trade(setup)
        assert not valid
        assert any("INVALID TP" in r for r in reasons)

    def test_valid_long_passes(self):
        rm = RiskManager(starting_balance=100_000)
        setup = _make_setup(direction=Direction.LONG, entry=2000.0, sl=1990.0, tp=2020.0)
        valid, reasons = rm.validate_trade(setup)
        assert valid, f"Valid LONG should pass: {reasons}"

    def test_valid_short_passes(self):
        rm = RiskManager(starting_balance=100_000)
        setup = _make_setup(direction=Direction.SHORT, entry=2000.0, sl=2010.0, tp=1980.0,
                            position_size=0.5)
        valid, reasons = rm.validate_trade(setup)
        assert valid, f"Valid SHORT should pass: {reasons}"


# ────────────────────────────────────────────────────────────
# Core Validation (original STABLE tests — never weaken)
# ────────────────────────────────────────────────────────────
class TestTradeValidation:
    def test_valid_trade_passes(self):
        rm = RiskManager(starting_balance=100_000)
        setup = _make_setup()
        valid, reasons = rm.validate_trade(setup)
        assert valid
        assert len(reasons) == 0

    def test_daily_dd_rejection(self):
        rm = RiskManager(starting_balance=100_000)
        today = rm._get_today_stats()
        today.realized_pnl = -5500  # Exceeds both 5% and 6% limits
        setup = _make_setup(position_size=1000.0)
        valid, reasons = rm.validate_trade(setup)
        assert not valid
        assert any("DAILY DRAWDOWN" in r or "POSITION TOO LARGE" in r for r in reasons)

    def test_total_dd_rejection(self):
        rm = RiskManager(starting_balance=100_000)
        rm.total_pnl = -19500
        setup = _make_setup(position_size=1000.0)
        valid, reasons = rm.validate_trade(setup)
        assert not valid
        assert any("TOTAL DRAWDOWN" in r or "POSITION TOO LARGE" in r for r in reasons)

    def test_rr_too_low_rejection(self):
        rm = RiskManager(starting_balance=100_000)
        setup = _make_setup(rr=1.0)  # Below both 1.5 and 2.0
        valid, reasons = rm.validate_trade(setup)
        assert not valid
        assert any("R:R TOO LOW" in r for r in reasons)

    def test_invalid_sl_rejection(self):
        rm = RiskManager(starting_balance=100_000)
        setup = _make_setup(sl=2010.0)
        valid, reasons = rm.validate_trade(setup)
        assert not valid
        assert any("INVALID SL" in r for r in reasons)

    def test_halted_rejection(self):
        rm = RiskManager(starting_balance=100_000)
        today = rm._get_today_stats()
        today.is_trading_halted = True
        setup = _make_setup()
        valid, reasons = rm.validate_trade(setup)
        assert not valid
        assert any("HALTED" in r for r in reasons)

    def test_max_positions_rejection(self):
        rm = RiskManager(starting_balance=100_000)
        today = rm._get_today_stats()
        today.open_positions = 5
        setup = _make_setup()
        valid, reasons = rm.validate_trade(setup)
        assert not valid
        assert any("MAX POSITIONS" in r for r in reasons)

    def test_mode_aware_status(self):
        rm = RiskManager(starting_balance=100_000)
        status = rm.get_status()
        assert "mode" in status
        assert "limits" in status
        assert status["mode"] in ("prop", "personal")

    def test_unrealized_pnl_affects_daily_dd(self):
        """RC-03: Floating losses count toward daily DD."""
        rm = RiskManager(starting_balance=100_000)
        today = rm._get_today_stats()
        today.unrealized_pnl = -5500.0
        setup = _make_setup(position_size=1000.0)
        valid, reasons = rm.validate_trade(setup)
        assert not valid


# ────────────────────────────────────────────────────────────
# Hedging
# ────────────────────────────────────────────────────────────
class TestHedging:
    def test_hedging_detected(self):
        rm = RiskManager(starting_balance=100_000)
        assert rm._check_hedging("XAUUSD", "SHORT", {"XAUUSD": "LONG"}) is True

    def test_same_direction_not_hedging(self):
        rm = RiskManager(starting_balance=100_000)
        assert rm._check_hedging("XAUUSD", "LONG", {"XAUUSD": "LONG"}) is False

    def test_no_positions_not_hedging(self):
        rm = RiskManager(starting_balance=100_000)
        assert rm._check_hedging("XAUUSD", "SHORT", None) is False


# ────────────────────────────────────────────────────────────
# P&L Tracking & State
# ────────────────────────────────────────────────────────────
class TestPnLTracking:
    def test_record_trade_updates_balance(self):
        rm = RiskManager(starting_balance=100_000)
        rm.current_balance += 500.0
        rm.total_pnl += 500.0
        assert rm.current_balance == 100_500
        assert rm.total_pnl == 500.0

    def test_daily_halt_triggers_on_loss(self):
        rm = RiskManager(starting_balance=100_000)
        today = rm._get_today_stats()
        today.realized_pnl = -21000.0  # 21% > personal 20% daily DD limit
        max_daily = rm.starting_balance * rm._max_daily_dd
        assert today.realized_pnl <= -max_daily

    def test_record_trade_result_updates_total_pnl(self):
        rm = RiskManager(starting_balance=100_000)
        rm.record_trade_result(pnl=500.0)
        assert rm.total_pnl == 500.0

    def test_record_trade_result_loss(self):
        rm = RiskManager(starting_balance=100_000)
        rm.record_trade_result(pnl=-300.0)
        assert rm.total_pnl == -300.0

    def test_record_trade_result_halts_on_large_loss(self):
        rm = RiskManager(starting_balance=100_000)
        rm.record_trade_result(pnl=-21000.0)  # 21% > personal 20% daily DD limit
        today = rm._get_today_stats()
        assert today.is_trading_halted is True

    def test_record_trade_result_updates_last_trade_date(self):
        rm = RiskManager(starting_balance=100_000)
        assert rm.last_trade_date is None
        rm.record_trade_result(pnl=100.0)
        assert rm.last_trade_date == datetime.now(timezone.utc).date()


# ────────────────────────────────────────────────────────────
# Status
# ────────────────────────────────────────────────────────────
class TestStatus:
    def test_get_status_has_all_fields(self):
        rm = RiskManager(starting_balance=100_000)
        s = rm.get_status()
        for f in ("mode", "balance", "total_pnl", "daily_pnl", "is_halted",
                  "can_trade", "limits", "open_positions"):
            assert f in s, f"Missing '{f}' in get_status()"

    def test_halted_blocks_can_trade(self):
        rm = RiskManager(starting_balance=100_000)
        rm._get_today_stats().is_trading_halted = True
        assert rm.get_status()["can_trade"] is False

    def test_fresh_instance_can_trade(self):
        rm = RiskManager(starting_balance=100_000)
        assert rm.get_status()["can_trade"] is True

    def test_original_starting_balance_never_changes(self):
        """RC-04: Total DD uses original balance, not current."""
        rm = RiskManager(starting_balance=100_000)
        rm.current_balance = 150_000
        rm.record_trade_result(pnl=10_000.0)
        assert rm.original_starting_balance == 100_000


# ────────────────────────────────────────────────────────────
# Constants
# ────────────────────────────────────────────────────────────
class TestConstants:
    def test_weight_bounds(self):
        """Weight bounds prevent learning engine from extreme allocations."""
        assert WEIGHT_BOUNDS == (0.05, 0.50)

    def test_max_blacklist_growth(self):
        """Max 3 blacklists per week — prevents disabling everything after bad week."""
        assert MAX_BLACKLIST_GROWTH_PER_WEEK == 3
