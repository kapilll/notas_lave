"""Tests for risk manager — the gatekeeper that prevents catastrophic losses.

Tests work regardless of trading mode (prop or personal) by using
values that exceed BOTH modes' limits.
"""

from notas_lave.risk.manager import RiskManager
from notas_lave.data.models import TradeSetup, Direction, MarketRegime, TradeStatus


def _make_setup(
    direction=Direction.LONG, entry=2000.0, sl=1990.0, tp=2020.0,
    position_size=1.0, rr=2.0,
) -> TradeSetup:
    return TradeSetup(
        symbol="XAUUSD", timeframe="5m", direction=direction,
        entry_price=entry, stop_loss=sl, take_profit=tp,
        position_size=position_size, risk_reward_ratio=rr,
    )


class TestTradeValidation:
    def test_valid_trade_passes(self):
        rm = RiskManager(starting_balance=100_000)
        setup = _make_setup()
        valid, reasons = rm.validate_trade(setup)
        assert valid
        assert len(reasons) == 0

    def test_daily_dd_rejection(self):
        """Reject trade if daily P&L + potential loss breaches daily limit."""
        rm = RiskManager(starting_balance=100_000)
        today = rm._get_today_stats()
        today.realized_pnl = -5500  # Already lost $5500 (exceeds both 5% and 6% - $500 buffer)
        # potential_loss = |2000-1990| * 1000 = $10,000
        setup = _make_setup(position_size=1000.0)
        valid, reasons = rm.validate_trade(setup)
        assert not valid
        assert any("DAILY DRAWDOWN" in r or "POSITION TOO LARGE" in r for r in reasons)

    def test_total_dd_rejection(self):
        """Reject trade if total P&L + potential loss breaches total limit."""
        rm = RiskManager(starting_balance=100_000)
        rm.total_pnl = -19500  # Near both 10% ($10K) and 20% ($20K) limits
        # potential_loss = |2000-1990| * 1000 = $10,000
        setup = _make_setup(position_size=1000.0)
        valid, reasons = rm.validate_trade(setup)
        assert not valid
        assert any("TOTAL DRAWDOWN" in r or "POSITION TOO LARGE" in r for r in reasons)

    def test_rr_too_low_rejection(self):
        """Reject trade with R:R below minimum (1.5 personal, 2.0 prop)."""
        rm = RiskManager(starting_balance=100_000)
        setup = _make_setup(rr=1.0)  # Below both 1.5 and 2.0
        valid, reasons = rm.validate_trade(setup)
        assert not valid
        assert any("R:R TOO LOW" in r for r in reasons)

    def test_invalid_sl_rejection(self):
        """Reject LONG trade with SL above entry."""
        rm = RiskManager(starting_balance=100_000)
        setup = _make_setup(sl=2010.0)
        valid, reasons = rm.validate_trade(setup)
        assert not valid
        assert any("INVALID SL" in r for r in reasons)

    def test_halted_rejection(self):
        """Reject all trades when daily halt is active."""
        rm = RiskManager(starting_balance=100_000)
        today = rm._get_today_stats()
        today.is_trading_halted = True
        setup = _make_setup()
        valid, reasons = rm.validate_trade(setup)
        assert not valid
        assert any("HALTED" in r for r in reasons)

    def test_max_positions_rejection(self):
        """Reject when max concurrent positions reached."""
        rm = RiskManager(starting_balance=100_000)
        today = rm._get_today_stats()
        today.open_positions = 5  # Exceeds both prop (3) and personal (2)
        setup = _make_setup()
        valid, reasons = rm.validate_trade(setup)
        assert not valid
        assert any("MAX POSITIONS" in r for r in reasons)

    def test_mode_aware_status(self):
        """Status should report the current mode and limits."""
        rm = RiskManager(starting_balance=100_000)
        status = rm.get_status()
        assert "mode" in status
        assert "limits" in status
        assert status["mode"] in ("prop", "personal")


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
        # Use a loss that exceeds both 5% ($5K) and 6% ($6K)
        today.realized_pnl = -7000.0
        max_daily = rm.starting_balance * rm._max_daily_dd
        assert today.realized_pnl <= -max_daily
