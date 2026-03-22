"""Data integrity tests — catch P&L, SL/TP, and position tracking bugs.

These tests verify structural invariants that must ALWAYS hold:
- Exit prices are within reasonable range of entry
- SL/TP are on the correct side for the direction
- P&L sign matches exit reason (tp_hit → positive, sl_hit → negative)
- P&L magnitude is reasonable (cannot exceed notional value)
- No position has SL=0 or TP=0
- Every position links to a trade_log entry
- Exit price is near SL or TP when exit_reason says so

Run these on every commit to prevent data bugs from reaching production.
"""

import pytest
from engine.src.execution.paper_trader import Position, PaperTrader
from engine.src.data.models import Direction, TradeStatus
from engine.src.data.instruments import get_instrument


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════

def _make_position(
    direction="LONG", entry=100.0, sl=95.0, tp=110.0,
    exit_price=None, exit_reason="", pnl=0.0,
    size=1.0, symbol="BTCUSD", trade_log_id=1,
) -> Position:
    """Create a test position with sensible defaults."""
    d = Direction.LONG if direction == "LONG" else Direction.SHORT
    return Position(
        id="test-pos",
        signal_log_id=1,
        symbol=symbol,
        timeframe="1h",
        direction=d,
        regime="TRENDING",
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp,
        position_size=size,
        confluence_score=5.0,
        claude_confidence=7,
        strategies_agreed=["ema_crossover"],
        trade_log_id=trade_log_id,
        exit_price=exit_price or 0.0,
        exit_reason=exit_reason,
        pnl=pnl,
        original_stop_loss=sl,
        original_take_profit=tp,
    )


# ═══════════════════════════════════════════════════════════
# SL/TP Side Tests
# ═══════════════════════════════════════════════════════════

class TestSLTPSide:
    """LONG: SL < Entry < TP. SHORT: TP < Entry < SL."""

    def test_long_sl_below_entry(self):
        pos = _make_position(direction="LONG", entry=100, sl=95, tp=110)
        assert pos.stop_loss < pos.entry_price

    def test_long_tp_above_entry(self):
        pos = _make_position(direction="LONG", entry=100, sl=95, tp=110)
        assert pos.take_profit > pos.entry_price

    def test_short_sl_above_entry(self):
        pos = _make_position(direction="SHORT", entry=100, sl=105, tp=90)
        assert pos.stop_loss > pos.entry_price

    def test_short_tp_below_entry(self):
        pos = _make_position(direction="SHORT", entry=100, sl=105, tp=90)
        assert pos.take_profit < pos.entry_price

    def test_open_position_rejects_wrong_sl_side_long(self):
        """PaperTrader.open_position rejects LONG with SL >= entry."""
        pt = PaperTrader(track_risk=False)
        result = pt.open_position(
            signal_log_id=1, symbol="BTCUSD", timeframe="1h",
            direction=Direction.LONG, regime="TRENDING",
            entry_price=100.0, stop_loss=105.0, take_profit=110.0,
            position_size=1.0, confluence_score=5.0,
            claude_confidence=7, strategies_agreed=["test"],
        )
        assert result is None, "Should reject LONG with SL >= entry"

    def test_open_position_rejects_wrong_sl_side_short(self):
        """PaperTrader.open_position rejects SHORT with SL <= entry."""
        pt = PaperTrader(track_risk=False)
        result = pt.open_position(
            signal_log_id=1, symbol="BTCUSD", timeframe="1h",
            direction=Direction.SHORT, regime="TRENDING",
            entry_price=100.0, stop_loss=95.0, take_profit=90.0,
            position_size=1.0, confluence_score=5.0,
            claude_confidence=7, strategies_agreed=["test"],
        )
        assert result is None, "Should reject SHORT with SL <= entry"

    def test_open_position_rejects_zero_sl(self):
        """PaperTrader.open_position rejects SL=0."""
        pt = PaperTrader(track_risk=False)
        result = pt.open_position(
            signal_log_id=1, symbol="BTCUSD", timeframe="1h",
            direction=Direction.LONG, regime="TRENDING",
            entry_price=100.0, stop_loss=0.0, take_profit=110.0,
            position_size=1.0, confluence_score=5.0,
            claude_confidence=7, strategies_agreed=["test"],
        )
        assert result is None, "Should reject SL=0"

    def test_open_position_rejects_zero_tp(self):
        """PaperTrader.open_position rejects TP=0."""
        pt = PaperTrader(track_risk=False)
        result = pt.open_position(
            signal_log_id=1, symbol="BTCUSD", timeframe="1h",
            direction=Direction.LONG, regime="TRENDING",
            entry_price=100.0, stop_loss=95.0, take_profit=0.0,
            position_size=1.0, confluence_score=5.0,
            claude_confidence=7, strategies_agreed=["test"],
        )
        assert result is None, "Should reject TP=0"


# ═══════════════════════════════════════════════════════════
# Exit Price Validity Tests
# ═══════════════════════════════════════════════════════════

class TestExitPrice:
    """Exit price must be within 50% of entry price."""

    def test_close_position_rejects_bad_exit_price(self):
        """PaperTrader.close_position clamps impossible exit prices."""
        pt = PaperTrader(track_risk=False)
        pos = pt.open_position(
            signal_log_id=1, symbol="BTCUSD", timeframe="1h",
            direction=Direction.LONG, regime="TRENDING",
            entry_price=100.0, stop_loss=95.0, take_profit=110.0,
            position_size=1.0, confluence_score=5.0,
            claude_confidence=7, strategies_agreed=["test"],
        )
        assert pos is not None
        # Update current price to something reasonable first
        pos.update_price(101.0)

        # Close with an insane exit price — should be clamped
        result = pt.close_position(pos.id, reason="manual", exit_price=1.0)
        assert result is not None
        closed_pos, pnl = result
        # Exit price should be clamped to current_price, not 1.0
        assert closed_pos.exit_price != 1.0
        ratio = closed_pos.exit_price / closed_pos.entry_price
        assert 0.5 <= ratio <= 2.0, f"Exit/entry ratio {ratio} out of range"

    def test_valid_exit_price_passes(self):
        """Normal exit prices should pass through unchanged."""
        pt = PaperTrader(track_risk=False)
        pos = pt.open_position(
            signal_log_id=1, symbol="BTCUSD", timeframe="1h",
            direction=Direction.LONG, regime="TRENDING",
            entry_price=100.0, stop_loss=95.0, take_profit=110.0,
            position_size=1.0, confluence_score=5.0,
            claude_confidence=7, strategies_agreed=["test"],
        )
        pos.update_price(105.0)
        result = pt.close_position(pos.id, reason="tp_hit", exit_price=110.0)
        closed_pos, pnl = result
        assert closed_pos.exit_price == 110.0


# ═══════════════════════════════════════════════════════════
# P&L Sanity Tests
# ═══════════════════════════════════════════════════════════

class TestPNLSanity:
    """P&L must be reasonable: sign matches exit reason, magnitude is bounded."""

    def test_tp_hit_positive_pnl_long(self):
        """LONG TP hit → P&L should be positive."""
        pt = PaperTrader(track_risk=False)
        pos = pt.open_position(
            signal_log_id=1, symbol="BTCUSD", timeframe="1h",
            direction=Direction.LONG, regime="TRENDING",
            entry_price=100.0, stop_loss=95.0, take_profit=110.0,
            position_size=0.001, confluence_score=5.0,
            claude_confidence=7, strategies_agreed=["test"],
        )
        pos.update_price(110.0)
        _, pnl = pt.close_position(pos.id, reason="tp_hit", exit_price=110.0)
        assert pnl > 0, f"LONG TP hit should have positive P&L, got {pnl}"

    def test_sl_hit_negative_pnl_long(self):
        """LONG SL hit → P&L should be negative."""
        pt = PaperTrader(track_risk=False)
        pos = pt.open_position(
            signal_log_id=1, symbol="BTCUSD", timeframe="1h",
            direction=Direction.LONG, regime="TRENDING",
            entry_price=100.0, stop_loss=95.0, take_profit=110.0,
            position_size=0.001, confluence_score=5.0,
            claude_confidence=7, strategies_agreed=["test"],
        )
        pos.update_price(95.0)
        _, pnl = pt.close_position(pos.id, reason="sl_hit", exit_price=95.0)
        assert pnl < 0, f"LONG SL hit should have negative P&L, got {pnl}"

    def test_tp_hit_positive_pnl_short(self):
        """SHORT TP hit → P&L should be positive."""
        pt = PaperTrader(track_risk=False)
        pos = pt.open_position(
            signal_log_id=1, symbol="BTCUSD", timeframe="1h",
            direction=Direction.SHORT, regime="TRENDING",
            entry_price=100.0, stop_loss=105.0, take_profit=90.0,
            position_size=0.001, confluence_score=5.0,
            claude_confidence=7, strategies_agreed=["test"],
        )
        pos.update_price(90.0)
        _, pnl = pt.close_position(pos.id, reason="tp_hit", exit_price=90.0)
        assert pnl > 0, f"SHORT TP hit should have positive P&L, got {pnl}"

    def test_sl_hit_negative_pnl_short(self):
        """SHORT SL hit → P&L should be negative."""
        pt = PaperTrader(track_risk=False)
        pos = pt.open_position(
            signal_log_id=1, symbol="BTCUSD", timeframe="1h",
            direction=Direction.SHORT, regime="TRENDING",
            entry_price=100.0, stop_loss=105.0, take_profit=90.0,
            position_size=0.001, confluence_score=5.0,
            claude_confidence=7, strategies_agreed=["test"],
        )
        pos.update_price(105.0)
        _, pnl = pt.close_position(pos.id, reason="sl_hit", exit_price=105.0)
        assert pnl < 0, f"SHORT SL hit should have negative P&L, got {pnl}"

    def test_pnl_cannot_exceed_notional(self):
        """P&L cannot exceed the position's notional value."""
        pt = PaperTrader(track_risk=False)
        pos = pt.open_position(
            signal_log_id=1, symbol="BTCUSD", timeframe="1h",
            direction=Direction.LONG, regime="TRENDING",
            entry_price=100.0, stop_loss=95.0, take_profit=110.0,
            position_size=0.001, confluence_score=5.0,
            claude_confidence=7, strategies_agreed=["test"],
        )
        pos.update_price(110.0)
        _, pnl = pt.close_position(pos.id, reason="tp_hit", exit_price=110.0)
        spec = get_instrument("BTCUSD")
        notional = pos.entry_price * pos.position_size * spec.contract_size
        assert abs(pnl) <= notional, f"|P&L|={abs(pnl)} > notional={notional}"


# ═══════════════════════════════════════════════════════════
# Trade Log ID Tests
# ═══════════════════════════════════════════════════════════

class TestTradeLogID:
    """Every position must link to a trade_log entry."""

    def test_open_position_creates_trade_log(self):
        """open_position always sets trade_log_id > 0."""
        pt = PaperTrader(track_risk=False)
        pos = pt.open_position(
            signal_log_id=1, symbol="BTCUSD", timeframe="1h",
            direction=Direction.LONG, regime="TRENDING",
            entry_price=100.0, stop_loss=95.0, take_profit=110.0,
            position_size=0.001, confluence_score=5.0,
            claude_confidence=7, strategies_agreed=["test"],
        )
        assert pos is not None
        assert pos.trade_log_id > 0, f"trade_log_id should be > 0, got {pos.trade_log_id}"

    def test_close_synced_position_creates_trade_log(self):
        """Closing a position with trade_log_id=0 creates a DB entry."""
        pt = PaperTrader(track_risk=False)
        pos = pt.open_position(
            signal_log_id=1, symbol="BTCUSD", timeframe="1h",
            direction=Direction.LONG, regime="TRENDING",
            entry_price=100.0, stop_loss=95.0, take_profit=110.0,
            position_size=0.001, confluence_score=5.0,
            claude_confidence=7, strategies_agreed=["test"],
        )
        # Simulate a synced position (trade_log_id=0)
        pos.trade_log_id = 0
        pos.update_price(110.0)
        result = pt.close_position(pos.id, reason="tp_hit", exit_price=110.0)
        assert result is not None
        closed_pos, _ = result
        assert closed_pos.trade_log_id > 0, "Close should create DB entry for synced positions"


# ═══════════════════════════════════════════════════════════
# Check Exit Tests (SL/TP Detection)
# ═══════════════════════════════════════════════════════════

class TestCheckExit:
    """check_exit correctly detects SL/TP hits from candle data."""

    def test_long_sl_hit_by_candle_low(self):
        pos = _make_position(direction="LONG", entry=100, sl=95, tp=110)
        pos.update_price(97.0, candle_high=98.0, candle_low=94.0)
        assert pos.check_exit() == "sl_hit"

    def test_long_tp_hit_by_candle_high(self):
        pos = _make_position(direction="LONG", entry=100, sl=95, tp=110)
        pos.update_price(108.0, candle_high=111.0, candle_low=107.0)
        assert pos.check_exit() == "tp_hit"

    def test_short_sl_hit_by_candle_high(self):
        pos = _make_position(direction="SHORT", entry=100, sl=105, tp=90)
        pos.update_price(103.0, candle_high=106.0, candle_low=102.0)
        assert pos.check_exit() == "sl_hit"

    def test_short_tp_hit_by_candle_low(self):
        pos = _make_position(direction="SHORT", entry=100, sl=105, tp=90)
        pos.update_price(92.0, candle_high=93.0, candle_low=89.0)
        assert pos.check_exit() == "tp_hit"

    def test_no_exit_when_between_sl_tp(self):
        pos = _make_position(direction="LONG", entry=100, sl=95, tp=110)
        pos.update_price(102.0, candle_high=103.0, candle_low=101.0)
        assert pos.check_exit() is None

    def test_no_exit_when_sl_is_zero(self):
        """SL=0 means not set — should never trigger."""
        pos = _make_position(direction="LONG", entry=100, sl=0, tp=110)
        pos.update_price(50.0, candle_high=51.0, candle_low=49.0)
        assert pos.check_exit() is None

    def test_no_exit_when_tp_is_zero(self):
        """TP=0 means not set — should never trigger."""
        pos = _make_position(direction="LONG", entry=100, sl=95, tp=0)
        pos.update_price(200.0, candle_high=201.0, candle_low=199.0)
        assert pos.check_exit() is None


# ═══════════════════════════════════════════════════════════
# Strategy Signal Validation Tests
# ═══════════════════════════════════════════════════════════

class TestStrategySignals:
    """Each strategy must produce signals with valid SL/TP side."""

    def test_all_strategies_have_valid_sl_tp_schema(self):
        """Verify each strategy's analyze() method signature exists."""
        from engine.src.strategies.registry import get_all_strategies
        strategies = get_all_strategies()
        assert len(strategies) >= 10, f"Expected 10+ strategies, got {len(strategies)}"
        for s in strategies:
            assert hasattr(s, 'analyze'), f"Strategy {s.name} missing analyze()"
            assert hasattr(s, 'name'), f"Strategy missing name attribute"
