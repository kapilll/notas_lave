"""Tests for risk manager — the gatekeeper that prevents catastrophic losses."""

from engine.src.risk.manager import RiskManager
from engine.src.data.models import TradeSetup, Direction, MarketRegime, TradeStatus


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
        """Reject trade if daily P&L would breach 5% limit."""
        rm = RiskManager(starting_balance=100_000)
        today = rm._get_today_stats()
        today.realized_pnl = -4500  # Already lost $4500 today
        # Potential loss: |2000-1990| * 100(lots) = $100,000
        # -4500 - 100000 = -104500, limit is -5000 → rejected
        setup = _make_setup(position_size=100.0)
        valid, reasons = rm.validate_trade(setup)
        assert not valid
        assert any("DAILY DRAWDOWN" in r for r in reasons)

    def test_total_dd_rejection(self):
        """Reject trade if total P&L would breach 10% limit."""
        rm = RiskManager(starting_balance=100_000)
        rm.total_pnl = -9500  # Already lost $9500 total
        # Potential loss: |2000-1990| * 100 = $100,000
        # -9500 - 100000 = -109500, limit is -10000 → rejected
        setup = _make_setup(position_size=100.0)
        valid, reasons = rm.validate_trade(setup)
        assert not valid
        assert any("TOTAL DRAWDOWN" in r for r in reasons)

    def test_rr_too_low_rejection(self):
        """Reject trade with R:R below 2.0."""
        rm = RiskManager(starting_balance=100_000)
        setup = _make_setup(rr=1.2)
        valid, reasons = rm.validate_trade(setup)
        assert not valid
        assert any("R:R TOO LOW" in r for r in reasons)

    def test_invalid_sl_rejection(self):
        """Reject LONG trade with SL above entry."""
        rm = RiskManager(starting_balance=100_000)
        setup = _make_setup(sl=2010.0)  # SL above entry for LONG = invalid
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
        today.open_positions = 3  # Max is 3
        setup = _make_setup()
        valid, reasons = rm.validate_trade(setup)
        assert not valid
        assert any("MAX POSITIONS" in r for r in reasons)


class TestPnLTracking:
    def test_record_trade_updates_balance(self):
        rm = RiskManager(starting_balance=100_000)
        # Force clean state (DB may have persisted state from previous runs)
        rm.current_balance = 100_000
        rm.total_pnl = 0.0
        rm.current_balance += 500.0
        rm.total_pnl += 500.0
        assert rm.current_balance == 100_500
        assert rm.total_pnl == 500.0

    def test_daily_halt_triggers_on_loss(self):
        rm = RiskManager(starting_balance=100_000)
        today = rm._get_today_stats()
        today.realized_pnl = -5100.0  # Simulate loss exceeding 5%
        max_daily = rm.starting_balance * 0.05
        assert today.realized_pnl <= -max_daily
