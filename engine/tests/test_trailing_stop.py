"""Tests for trailing stop and dynamic TP extension.

Covers:
- Breakeven activation (existing behavior preserved)
- ATR-based step trailing (new)
- R-based fallback trailing (when no ATR)
- Dynamic TP extension (new)
- Safety: SL never moves backward, never exceeds TP
- Short direction trailing
- Exit reason differentiation (trailing_sl vs sl_hit, extended_tp vs tp_hit)
"""

from engine.src.execution.paper_trader import Position
from engine.src.data.models import Direction, TradeStatus


def _long_position(
    entry=100.0, sl=95.0, tp=110.0, atr=3.0, size=1.0,
) -> Position:
    """Create a test LONG position with ATR."""
    return Position(
        id="test-long",
        signal_log_id=1,
        symbol="BTCUSD",
        timeframe="15m",
        direction=Direction.LONG,
        regime="TRENDING",
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp,
        position_size=size,
        confluence_score=7.0,
        claude_confidence=7,
        strategies_agreed=["ema_crossover"],
        current_price=entry,
        original_stop_loss=sl,
        original_take_profit=tp,
        entry_atr=atr,
    )


def _short_position(
    entry=100.0, sl=105.0, tp=90.0, atr=3.0, size=1.0,
) -> Position:
    """Create a test SHORT position with ATR."""
    return Position(
        id="test-short",
        signal_log_id=1,
        symbol="BTCUSD",
        timeframe="15m",
        direction=Direction.SHORT,
        regime="TRENDING",
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp,
        position_size=size,
        confluence_score=7.0,
        claude_confidence=7,
        strategies_agreed=["ema_crossover"],
        current_price=entry,
        original_stop_loss=sl,
        original_take_profit=tp,
        entry_atr=atr,
    )


# ═══════════════════════════════════════════════════════════
# TRAILING STOP — LONG POSITIONS
# ═══════════════════════════════════════════════════════════

class TestTrailingStopLong:
    def test_no_trail_before_breakeven(self):
        """Trailing should NOT activate before breakeven is triggered."""
        pos = _long_position(entry=100, sl=95, tp=110, atr=3.0)
        pos.current_price = 103  # 3 points profit, not yet 1R (5 points)
        result = pos.trail_stop(trail_multiplier=1.5, min_step_r=0.5)
        assert result is False
        assert pos.stop_loss == 95.0  # Unchanged
        assert pos.trailing_active is False

    def test_trail_after_breakeven(self):
        """After breakeven, trail SL when price moves favorably."""
        pos = _long_position(entry=100, sl=95, tp=110, atr=3.0)
        # Simulate breakeven activation
        pos.breakeven_activated = True
        pos.stop_loss = 100.5  # Already at breakeven (entry + spread + fees)
        # Price moves up significantly
        pos.current_price = 112.0
        result = pos.trail_stop(trail_multiplier=1.5, min_step_r=0.5)
        assert result is True
        assert pos.trailing_active is True
        # Trail level = 112 - (3.0 * 1.5) = 107.5 — above breakeven SL of 100.5
        assert pos.stop_loss == 107.5
        assert pos.trail_step_count == 1

    def test_trail_ratchet_only_up(self):
        """SL should only move UP for longs, never backward."""
        pos = _long_position(entry=100, sl=95, tp=110, atr=3.0)
        pos.breakeven_activated = True
        pos.stop_loss = 107.5  # Already trailed
        pos.trailing_active = True
        pos.trail_step_count = 1
        # Price drops — trail should NOT move SL down
        pos.current_price = 108.0
        result = pos.trail_stop(trail_multiplier=1.5, min_step_r=0.5)
        assert result is False
        assert pos.stop_loss == 107.5  # Unchanged
        assert pos.trail_step_count == 1

    def test_trail_moves_further_up(self):
        """When price keeps rising, SL keeps trailing up."""
        pos = _long_position(entry=100, sl=95, tp=130, atr=3.0)  # Wide TP
        pos.breakeven_activated = True
        pos.stop_loss = 107.5
        pos.trailing_active = True
        pos.trail_step_count = 1
        # Price rises further — big enough step
        pos.current_price = 118.0
        result = pos.trail_stop(trail_multiplier=1.5, min_step_r=0.5)
        assert result is True
        # Trail level = 118 - 4.5 = 113.5 — above 107.5 + 2.5 (min_step), below TP (130)
        assert pos.stop_loss == 113.5
        assert pos.trail_step_count == 2

    def test_trail_min_step_prevents_noise(self):
        """Small price moves shouldn't trigger trailing (min step filter)."""
        pos = _long_position(entry=100, sl=95, tp=110, atr=3.0)
        pos.breakeven_activated = True
        pos.stop_loss = 107.5
        pos.trailing_active = True
        # Price moves up a tiny bit — not enough for min_step (0.5R = 2.5)
        pos.current_price = 112.5
        result = pos.trail_stop(trail_multiplier=1.5, min_step_r=0.5)
        # trail_level = 112.5 - 4.5 = 108.0 — only 0.5 above 107.5, less than min_step=2.5
        assert result is False
        assert pos.stop_loss == 107.5

    def test_trail_never_exceeds_tp(self):
        """SL must never trail past the take profit level."""
        pos = _long_position(entry=100, sl=95, tp=110, atr=1.0)
        pos.breakeven_activated = True
        pos.stop_loss = 108.0
        pos.trailing_active = True
        # Price rockets up — trail would put SL above TP
        pos.current_price = 112.0
        result = pos.trail_stop(trail_multiplier=1.5, min_step_r=0.5)
        # trail_level = 112 - 1.5 = 110.5 — this exceeds TP (110), so blocked
        assert result is False
        assert pos.stop_loss == 108.0


# ═══════════════════════════════════════════════════════════
# TRAILING STOP — SHORT POSITIONS
# ═══════════════════════════════════════════════════════════

class TestTrailingStopShort:
    def test_trail_short_after_breakeven(self):
        """For shorts, trail SL DOWN when price drops favorably."""
        pos = _short_position(entry=100, sl=105, tp=90, atr=3.0)
        pos.breakeven_activated = True
        pos.stop_loss = 99.5  # Already at breakeven
        # Price drops
        pos.current_price = 88.0
        result = pos.trail_stop(trail_multiplier=1.5, min_step_r=0.5)
        assert result is True
        assert pos.trailing_active is True
        # Trail level = 88 + 4.5 = 92.5 — below breakeven of 99.5
        assert pos.stop_loss == 92.5
        assert pos.trail_step_count == 1

    def test_trail_short_ratchet_only_down(self):
        """For shorts, SL should only move DOWN, never back up."""
        pos = _short_position(entry=100, sl=105, tp=90, atr=3.0)
        pos.breakeven_activated = True
        pos.stop_loss = 92.5
        pos.trailing_active = True
        pos.trail_step_count = 1
        # Price bounces up
        pos.current_price = 95.0
        result = pos.trail_stop(trail_multiplier=1.5, min_step_r=0.5)
        assert result is False
        assert pos.stop_loss == 92.5  # Unchanged

    def test_trail_short_never_below_tp(self):
        """For shorts, SL must never trail below TP."""
        pos = _short_position(entry=100, sl=105, tp=90, atr=1.0)
        pos.breakeven_activated = True
        pos.stop_loss = 92.0
        pos.trailing_active = True
        # Price drops near TP
        pos.current_price = 89.0
        result = pos.trail_stop(trail_multiplier=1.5, min_step_r=0.5)
        # trail_level = 89 + 1.5 = 90.5 — but must be > TP (90), just barely
        # 90.5 < 92.0 - 2.5 (min_step) → doesn't meet min_step requirement
        assert result is False


# ═══════════════════════════════════════════════════════════
# R-BASED FALLBACK (no ATR)
# ═══════════════════════════════════════════════════════════

class TestRBasedFallback:
    def test_trail_without_atr_uses_r(self):
        """When entry_atr=0, trail distance defaults to 1R."""
        pos = _long_position(entry=100, sl=95, tp=125, atr=0)  # No ATR, wide TP
        pos.breakeven_activated = True
        pos.stop_loss = 100.5
        # Price moves up a lot
        pos.current_price = 115.0
        result = pos.trail_stop(trail_multiplier=1.5, min_step_r=0.5)
        assert result is True
        # Without ATR, trail_distance = initial_risk (1R) = 5.0
        # trail_level = 115 - 5.0 = 110.0, well below TP (125)
        assert pos.stop_loss == 110.0

    def test_no_trail_with_zero_risk(self):
        """If original_stop_loss is 0 or equals entry, no trailing."""
        pos = _long_position(entry=100, sl=100, tp=110, atr=3.0)
        pos.original_stop_loss = 0  # Not set
        pos.breakeven_activated = True
        pos.current_price = 108.0
        result = pos.trail_stop()
        assert result is False


# ═══════════════════════════════════════════════════════════
# DYNAMIC TP EXTENSION
# ═══════════════════════════════════════════════════════════

class TestTPExtension:
    def test_extend_tp_at_75_pct(self):
        """TP extends when price covers 75% of distance to TP."""
        pos = _long_position(entry=100, sl=95, tp=110)
        # Price at 107.5 = 75% of 10-point TP distance
        pos.current_price = 107.5
        result = pos.extend_take_profit(max_extensions=3, threshold=0.75)
        assert result is True
        # TP extended by 1R (5 points): 110 + 5 = 115
        assert pos.take_profit == 115.0
        assert pos.tp_extensions == 1

    def test_no_extend_before_threshold(self):
        """TP should NOT extend before reaching threshold."""
        pos = _long_position(entry=100, sl=95, tp=110)
        pos.current_price = 106.0  # Only 60% of TP distance
        result = pos.extend_take_profit(max_extensions=3, threshold=0.75)
        assert result is False
        assert pos.take_profit == 110.0
        assert pos.tp_extensions == 0

    def test_max_extensions_cap(self):
        """TP extensions are capped at max_extensions."""
        pos = _long_position(entry=100, sl=95, tp=110)
        pos.tp_extensions = 3  # Already at max
        pos.current_price = 120.0
        result = pos.extend_take_profit(max_extensions=3)
        assert result is False
        assert pos.tp_extensions == 3

    def test_multiple_extensions(self):
        """Multiple TP extensions work correctly."""
        pos = _long_position(entry=100, sl=95, tp=110)
        # 1st extension at 75%
        pos.current_price = 107.5
        pos.extend_take_profit(max_extensions=3, threshold=0.75)
        assert pos.take_profit == 115.0
        assert pos.tp_extensions == 1

        # Price keeps rising — 75% of new TP distance
        # New TP distance = 115 - 100 = 15. 75% = 11.25 → price = 111.25
        pos.current_price = 111.25
        pos.extend_take_profit(max_extensions=3, threshold=0.75)
        assert pos.take_profit == 120.0
        assert pos.tp_extensions == 2

    def test_extend_tp_short(self):
        """TP extension works for SHORT positions."""
        pos = _short_position(entry=100, sl=105, tp=90)
        # Price at 92.5 = 75% of 10-point TP distance
        pos.current_price = 92.5
        result = pos.extend_take_profit(max_extensions=3, threshold=0.75)
        assert result is True
        # TP extended by 1R (5 points): 90 - 5 = 85
        assert pos.take_profit == 85.0
        assert pos.tp_extensions == 1

    def test_no_extend_without_original_sl(self):
        """No TP extension if original SL is missing (can't compute R)."""
        pos = _long_position(entry=100, sl=95, tp=110)
        pos.original_stop_loss = 0
        pos.current_price = 108.0
        result = pos.extend_take_profit()
        assert result is False


# ═══════════════════════════════════════════════════════════
# EXIT REASON DIFFERENTIATION
# ═══════════════════════════════════════════════════════════

class TestExitReasons:
    def test_sl_hit_without_trailing(self):
        """Normal SL hit returns 'sl_hit' when trailing not active."""
        pos = _long_position(entry=100, sl=95, tp=110)
        pos.update_price(94.0, candle_high=100.0, candle_low=94.0)
        exit_reason = pos.check_exit()
        assert exit_reason == "sl_hit"

    def test_trailing_sl_hit(self):
        """SL hit returns 'trailing_sl' when trailing was active."""
        pos = _long_position(entry=100, sl=95, tp=110)
        pos.trailing_active = True
        pos.stop_loss = 107.5  # Trailed SL
        pos.update_price(106.0, candle_high=108.0, candle_low=106.0)
        exit_reason = pos.check_exit()
        assert exit_reason == "trailing_sl"

    def test_tp_hit_without_extension(self):
        """Normal TP hit returns 'tp_hit'."""
        pos = _long_position(entry=100, sl=95, tp=110)
        pos.update_price(111.0, candle_high=111.0, candle_low=109.0)
        exit_reason = pos.check_exit()
        assert exit_reason == "tp_hit"

    def test_extended_tp_hit(self):
        """TP hit after extension returns 'extended_tp'."""
        pos = _long_position(entry=100, sl=95, tp=115)
        pos.tp_extensions = 1
        pos.update_price(116.0, candle_high=116.0, candle_low=114.0)
        exit_reason = pos.check_exit()
        assert exit_reason == "extended_tp"

    def test_trailing_sl_short(self):
        """Trailing SL hit on SHORT returns 'trailing_sl'."""
        pos = _short_position(entry=100, sl=105, tp=90)
        pos.trailing_active = True
        pos.stop_loss = 93.0  # Trailed down
        pos.update_price(94.0, candle_high=94.0, candle_low=89.0)
        exit_reason = pos.check_exit()
        assert exit_reason == "trailing_sl"


# ═══════════════════════════════════════════════════════════
# INTEGRATION: FULL LIFECYCLE
# ═══════════════════════════════════════════════════════════

class TestFullLifecycle:
    def test_breakeven_then_trail_then_exit(self):
        """Full lifecycle: open → breakeven → trail → trailing SL hit.

        Uses ETHUSD (spread=$1.50) instead of BTCUSD ($15) so breakeven
        doesn't overshoot with tight test prices.
        """
        pos = Position(
            id="lifecycle", signal_log_id=1, symbol="ETHUSD", timeframe="15m",
            direction=Direction.LONG, regime="TRENDING",
            entry_price=100.0, stop_loss=90.0, take_profit=130.0,
            position_size=1.0, confluence_score=7.0, claude_confidence=7,
            strategies_agreed=["ema_crossover"], current_price=100.0,
            original_stop_loss=90.0, original_take_profit=130.0, entry_atr=5.0,
        )
        # Initial risk = 10 points (1R). ETHUSD spread = $1.50.

        # Phase 1: Price rises to 1R (110) → breakeven activates
        pos.update_price(111.0)
        pos.move_to_breakeven()
        assert pos.breakeven_activated is True
        # Breakeven = entry + spread + fee ≈ 101.5
        assert pos.stop_loss > 99

        # Phase 2: Price rises more → trailing starts
        pos.current_price = 120.0
        trailed = pos.trail_stop(trail_multiplier=1.5, min_step_r=0.5)
        assert trailed is True
        assert pos.trailing_active is True
        trail_sl = pos.stop_loss
        assert trail_sl > 100  # SL is above entry (in profit!)

        # Phase 3: Price rises even more → trail follows
        pos.current_price = 128.0
        trailed = pos.trail_stop(trail_multiplier=1.5, min_step_r=0.5)
        assert trailed is True
        assert pos.stop_loss > trail_sl  # SL moved higher
        profit_locked = pos.stop_loss - pos.entry_price
        assert profit_locked > 0  # Guaranteed profit regardless of exit

        # Phase 4: Price reverses → trailing SL hit
        pos.update_price(pos.stop_loss - 1, candle_high=128.0, candle_low=pos.stop_loss - 1)
        exit_reason = pos.check_exit()
        assert exit_reason == "trailing_sl"

    def test_trail_with_tp_extension(self):
        """Trail + TP extension: ride the trend for max profit."""
        pos = _long_position(entry=100, sl=95, tp=110, atr=3.0)
        pos.breakeven_activated = True
        pos.stop_loss = 100.5

        # TP extension at 75% of TP distance
        pos.current_price = 107.5
        extended = pos.extend_take_profit(max_extensions=3, threshold=0.75)
        assert extended is True
        assert pos.take_profit == 115.0  # Extended from 110 to 115

        # Trail follows the rise
        pos.current_price = 114.0
        pos.trail_stop(trail_multiplier=1.5, min_step_r=0.5)
        assert pos.stop_loss > 100.5  # Trail moved up
        assert pos.stop_loss < 115.0  # Still below TP

    def test_to_dict_includes_trailing_info(self):
        """API response includes trailing stop metadata."""
        pos = _long_position(entry=100, sl=95, tp=110)
        pos.trailing_active = True
        pos.trail_step_count = 3
        pos.tp_extensions = 1
        d = pos.to_dict()
        assert d["trailing_active"] is True
        assert d["trail_steps"] == 3
        assert d["tp_extensions"] == 1
        assert d["original_stop_loss"] == 95.0
        assert d["original_take_profit"] == 110.0


# ═══════════════════════════════════════════════════════════
# SMART POSITION HEALTH
# ═══════════════════════════════════════════════════════════

def _make_candles(prices, volumes=None):
    """Helper: create candle list from close prices for testing."""
    from engine.src.data.models import Candle
    from datetime import datetime, timezone, timedelta
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles = []
    for i, price in enumerate(prices):
        vol = volumes[i] if volumes else 100.0
        candles.append(Candle(
            timestamp=base + timedelta(minutes=i),
            open=price - 0.5, high=price + 1, low=price - 1,
            close=price, volume=vol,
        ))
    return candles


class TestPositionHealth:
    def test_rsi_computation(self):
        """RSI should be calculable from candle data."""
        # Steadily rising prices → RSI should be high
        prices = [100 + i * 0.5 for i in range(20)]
        candles = _make_candles(prices)
        rsi = Position._compute_rsi(candles, 14)
        assert rsi > 70  # Strong uptrend → high RSI

    def test_rsi_downtrend(self):
        """Falling prices → low RSI."""
        prices = [120 - i * 0.5 for i in range(20)]
        candles = _make_candles(prices)
        rsi = Position._compute_rsi(candles, 14)
        assert rsi < 30

    def test_rsi_insufficient_data(self):
        """Not enough candles → returns neutral 50."""
        candles = _make_candles([100, 101, 102])
        rsi = Position._compute_rsi(candles, 14)
        assert rsi == 50.0

    def test_volume_ratio_above_average(self):
        """Recent volume spike → ratio > 1."""
        volumes = [100] * 14 + [200, 200, 200]  # Spike at end
        candles = _make_candles([100] * 17, volumes)
        ratio = Position._volume_ratio(candles, recent=3, lookback=14)
        assert ratio > 1.5

    def test_volume_ratio_below_average(self):
        """Recent volume drop → ratio < 1."""
        volumes = [200] * 14 + [50, 50, 50]  # Drop at end
        candles = _make_candles([100] * 17, volumes)
        ratio = Position._volume_ratio(candles, recent=3, lookback=14)
        assert ratio < 0.5

    def test_candle_alignment_bullish(self):
        """All candles rising → 1.0 alignment for LONG."""
        prices = [100 + i for i in range(10)]
        candles = _make_candles(prices)
        # Fix candles so open < close (bullish)
        for c in candles:
            c.open = c.close - 1
        alignment = Position._candle_alignment(candles, Direction.LONG, 5)
        assert alignment == 1.0

    def test_health_strong_momentum_long(self):
        """Moderate uptrend + good volume → STRONG health for LONG."""
        # Mix of up and small down candles → RSI in 55-70 range
        prices = [100, 100.3, 100.1, 100.5, 100.4, 100.7, 100.6, 101.0,
                  100.9, 101.2, 101.0, 101.4, 101.3, 101.6, 101.5, 101.8,
                  101.7, 102.0, 101.9, 102.2]
        volumes = [120] * 20
        candles = _make_candles(prices, volumes)
        # Make last 5 candles bullish (alignment >= 0.6)
        for c in candles[-5:]:
            c.open = c.close - 0.5

        pos = _long_position(entry=100, sl=95, tp=115)
        pos.compute_health(candles)
        assert pos.health_momentum == "STRONG"
        assert pos.health_trail_adjustment > 1.0  # Trail wider
        assert pos.health_can_extend_tp is True

    def test_health_fading_momentum_long(self):
        """RSI > 75 → FADING health, trail tighter."""
        # Very steep rise → RSI > 75
        prices = [100 + i * 2 for i in range(20)]
        candles = _make_candles(prices)
        pos = _long_position(entry=100, sl=95, tp=150)
        pos.compute_health(candles)
        assert pos.health_momentum == "FADING"
        assert pos.health_trail_adjustment < 1.0  # Trail tighter
        assert pos.health_can_extend_tp is False  # Don't extend

    def test_health_reversing_momentum_long(self):
        """RSI drops below 40 for long → REVERSING."""
        # Rise then sharp drop
        prices = [100 + i for i in range(10)] + [110 - i * 2 for i in range(10)]
        candles = _make_candles(prices)
        pos = _long_position(entry=100, sl=95, tp=115)
        pos.compute_health(candles)
        assert pos.health_momentum == "REVERSING"
        assert pos.health_trail_adjustment <= 0.5

    def test_smart_exit_requires_breakeven(self):
        """Smart exit should NOT trigger if not yet at breakeven (Guardian rule)."""
        prices = [100 + i for i in range(10)] + [110 - i * 2 for i in range(10)]
        volumes = [150] * 20
        candles = _make_candles(prices, volumes)
        # Make last candles bearish
        for c in candles[-5:]:
            c.open = c.close + 1

        pos = _long_position(entry=100, sl=95, tp=115)
        pos.breakeven_activated = False  # NOT at breakeven
        pos.compute_health(candles)
        # Even though momentum is reversing, should NOT exit (not in profit)
        assert pos.health_should_exit is False

    def test_smart_exit_triggers_after_breakeven(self):
        """Smart exit SHOULD trigger if at breakeven + momentum reversed."""
        prices = [100 + i for i in range(10)] + [110 - i * 2 for i in range(10)]
        volumes = [150] * 20
        candles = _make_candles(prices, volumes)
        # Make last candles bearish (alignment < 0.3)
        for c in candles[-5:]:
            c.open = c.close + 2

        pos = _long_position(entry=100, sl=95, tp=115)
        pos.breakeven_activated = True
        pos.unrealized_pnl = 5.0  # BF-A03: Smart exit now checks unrealized_pnl > 0
        pos.compute_health(candles)
        assert pos.health_momentum == "REVERSING"
        assert pos.health_should_exit is True
        assert "Momentum reversed" in pos.health_reason

    def test_health_short_strong(self):
        """Moderate downtrend + RSI < 45 → STRONG for SHORT."""
        # Mix of down and small up candles → RSI in 30-45 range
        prices = [120, 119.7, 119.9, 119.5, 119.6, 119.3, 119.4, 119.0,
                  119.1, 118.8, 119.0, 118.6, 118.7, 118.4, 118.5, 118.2,
                  118.3, 118.0, 118.1, 117.8]
        volumes = [120] * 20
        candles = _make_candles(prices, volumes)
        # Make last 5 candles bearish (alignment >= 0.6)
        for c in candles[-5:]:
            c.open = c.close + 0.5

        pos = _short_position(entry=120, sl=125, tp=110)
        pos.compute_health(candles)
        assert pos.health_momentum == "STRONG"
        assert pos.health_trail_adjustment > 1.0

    def test_health_to_dict(self):
        """Dashboard should see health info."""
        pos = _long_position(entry=100, sl=95, tp=110)
        pos.health_momentum = "STRONG"
        pos.health_reason = "RSI=62, vol=1.3x"
        d = pos.to_dict()
        assert d["health_momentum"] == "STRONG"
        assert d["health_reason"] == "RSI=62, vol=1.3x"

    def test_adaptive_trail_with_health(self):
        """Trail multiplier should be adjusted by health."""
        pos = _long_position(entry=100, sl=95, tp=130, atr=3.0)
        pos.breakeven_activated = True
        pos.stop_loss = 100.5

        # STRONG health → wider trail (1.3x adjustment)
        pos.health_trail_adjustment = 1.3
        pos.current_price = 112.0
        # Effective multiplier = 1.5 * 1.3 = 1.95
        # Trail distance = 3.0 * 1.95 = 5.85
        # Trail level = 112 - 5.85 = 106.15
        trailed = pos.trail_stop(trail_multiplier=1.5 * 1.3, min_step_r=0.5)
        assert trailed is True
        strong_sl = pos.stop_loss

        # Reset for FADING test
        pos2 = _long_position(entry=100, sl=95, tp=130, atr=3.0)
        pos2.breakeven_activated = True
        pos2.stop_loss = 100.5
        pos2.health_trail_adjustment = 0.7
        pos2.current_price = 112.0
        # Effective multiplier = 1.5 * 0.7 = 1.05
        # Trail distance = 3.0 * 1.05 = 3.15
        # Trail level = 112 - 3.15 = 108.85
        trailed2 = pos2.trail_stop(trail_multiplier=1.5 * 0.7, min_step_r=0.5)
        assert trailed2 is True
        fading_sl = pos2.stop_loss

        # FADING trail should be TIGHTER (higher SL = more profit locked)
        assert fading_sl > strong_sl
