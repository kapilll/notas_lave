"""Tests for strategy signal output — ensure strategies don't crash and produce valid signals."""

from datetime import datetime, timezone
from notas_lave.data.models import Candle, Signal, SignalStrength
from notas_lave.strategies.registry import get_all_strategies


def _make_candles(n: int = 250, base_price: float = 2000.0) -> list[Candle]:
    """Generate synthetic candles for testing."""
    import random
    random.seed(42)
    candles = []
    price = base_price
    for i in range(n):
        change = random.uniform(-5, 5)
        o = price
        c = price + change
        h = max(o, c) + random.uniform(0, 3)
        l = min(o, c) - random.uniform(0, 3)
        ts = datetime(2026, 3, 15, 8 + (i % 8), i % 60, tzinfo=timezone.utc)
        candles.append(Candle(
            timestamp=ts, open=o, high=h, low=l, close=c,
            volume=random.uniform(100, 1000),
        ))
        price = c
    return candles


class TestAllStrategies:
    """Every strategy must: not crash, return a Signal, have valid fields."""

    def test_all_strategies_return_signal(self):
        candles = _make_candles(250)
        strategies = get_all_strategies()
        assert len(strategies) == 12  # 14 - 2 removed (Order Blocks, Session Kill Zone)

        for strategy in strategies:
            signal = strategy.analyze(candles, "XAUUSD")
            assert isinstance(signal, Signal), f"{strategy.name} didn't return a Signal"
            assert isinstance(signal.strategy_name, str)
            assert signal.strategy_name == strategy.name

    def test_no_strategy_crashes_on_minimal_data(self):
        """Strategies should handle insufficient data gracefully."""
        candles = _make_candles(10)  # Very few candles
        for strategy in get_all_strategies():
            signal = strategy.analyze(candles, "XAUUSD")
            assert isinstance(signal, Signal)
            # With 10 candles, most strategies should return no signal
            assert signal.strength == SignalStrength.NONE or signal.score >= 0

    def test_signal_score_in_range(self):
        """Signal scores should be 0-100."""
        candles = _make_candles(250)
        for strategy in get_all_strategies():
            signal = strategy.analyze(candles, "XAUUSD")
            assert 0 <= signal.score <= 100, f"{strategy.name} score {signal.score} out of range"

    def test_sl_tp_on_correct_side(self):
        """If a signal fires, SL must be below entry for LONG, above for SHORT."""
        candles = _make_candles(500)
        for strategy in get_all_strategies():
            signal = strategy.analyze(candles, "XAUUSD")
            if signal.direction and signal.entry_price and signal.stop_loss and signal.take_profit:
                if signal.direction.value == "LONG":
                    assert signal.stop_loss < signal.entry_price, \
                        f"{strategy.name} LONG: SL {signal.stop_loss} >= entry {signal.entry_price}"
                    assert signal.take_profit > signal.entry_price, \
                        f"{strategy.name} LONG: TP {signal.take_profit} <= entry {signal.entry_price}"
                else:
                    assert signal.stop_loss > signal.entry_price, \
                        f"{strategy.name} SHORT: SL {signal.stop_loss} <= entry {signal.entry_price}"
                    assert signal.take_profit < signal.entry_price, \
                        f"{strategy.name} SHORT: TP {signal.take_profit} >= entry {signal.entry_price}"

    def test_strategy_names_unique(self):
        """No two strategies should have the same name."""
        names = [s.name for s in get_all_strategies()]
        assert len(names) == len(set(names)), f"Duplicate names: {names}"

    def test_strategy_categories_valid(self):
        """All strategies must have a recognized category."""
        valid_cats = {"scalping", "volume", "fibonacci", "ict", "breakout"}
        for s in get_all_strategies():
            assert s.category in valid_cats, f"{s.name} has invalid category: {s.category}"

    def test_volume_check_uses_completed_candle(self):
        """Volume check must compare the last COMPLETED candle, not the forming one."""
        from notas_lave.strategies.base import BaseStrategy

        # Create candles where last completed ([-2]) has good volume
        # but current forming ([-1]) has low volume (partial)
        candles = _make_candles(50)
        for c in candles:
            object.__setattr__(c, 'volume', 1000.0)
        object.__setattr__(candles[-2], 'volume', 900.0)
        object.__setattr__(candles[-1], 'volume', 50.0)  # Forming candle — ignored
        # Should PASS because [-2] has 900 >= 800 (80% of 1000)
        assert BaseStrategy.check_volume(candles) is True

        # Now set completed candle to very low volume
        object.__setattr__(candles[-2], 'volume', 100.0)
        assert BaseStrategy.check_volume(candles) is False

    def test_volume_check_returns_true_for_insufficient_data(self):
        """Volume check should pass (not block) when there's not enough candle data."""
        from notas_lave.strategies.base import BaseStrategy
        candles = _make_candles(5)  # Need lookback + 2 = 22
        assert BaseStrategy.check_volume(candles) is True

    def test_volume_check_handles_zero_volume(self):
        """Volume check should pass if all historical volumes are 0 (no data)."""
        from notas_lave.strategies.base import BaseStrategy
        candles = _make_candles(50)
        for c in candles:
            object.__setattr__(c, 'volume', 0.0)
        assert BaseStrategy.check_volume(candles) is True

    def test_atr_calculation(self):
        """ATR should return a positive value for valid candles."""
        from notas_lave.strategies.base import BaseStrategy
        candles = _make_candles(50)
        atr = BaseStrategy.compute_atr(candles, period=14)
        assert atr is not None
        assert atr > 0

    def test_atr_stop_loss_and_take_profit(self):
        """ATR-based SL/TP should be on correct sides of entry."""
        from notas_lave.strategies.base import BaseStrategy
        sl_long = BaseStrategy.atr_stop_loss(100.0, 2.0, "LONG", 1.5)
        assert sl_long < 100.0  # SL below entry for LONG
        sl_short = BaseStrategy.atr_stop_loss(100.0, 2.0, "SHORT", 1.5)
        assert sl_short > 100.0  # SL above entry for SHORT
        tp_long = BaseStrategy.atr_take_profit(100.0, 2.0, "LONG", 2.0)
        assert tp_long > 100.0  # TP above entry for LONG
        tp_short = BaseStrategy.atr_take_profit(100.0, 2.0, "SHORT", 2.0)
        assert tp_short < 100.0  # TP below entry for SHORT

    def test_no_zero_sl_tp_on_valid_signals(self):
        """If a strategy produces a signal, SL and TP must not be 0."""
        candles = _make_candles(500)
        for strategy in get_all_strategies():
            signal = strategy.analyze(candles, "BTCUSD")
            if signal.direction and signal.entry_price:
                if signal.stop_loss is not None:
                    assert signal.stop_loss != 0, \
                        f"{strategy.name} produced SL=0 with direction={signal.direction}"
                if signal.take_profit is not None:
                    assert signal.take_profit != 0, \
                        f"{strategy.name} produced TP=0 with direction={signal.direction}"

    def test_entry_price_positive(self):
        """Entry price must be positive if set."""
        candles = _make_candles(250)
        for strategy in get_all_strategies():
            signal = strategy.analyze(candles, "XAUUSD")
            if signal.entry_price is not None:
                assert signal.entry_price > 0, \
                    f"{strategy.name} produced negative entry: {signal.entry_price}"

    def test_risk_reward_ratio_reasonable(self):
        """If a signal has levels, R:R should be at least 0.5."""
        candles = _make_candles(500)
        for strategy in get_all_strategies():
            signal = strategy.analyze(candles, "XAUUSD")
            if signal.direction and signal.entry_price and signal.stop_loss and signal.take_profit:
                risk = abs(signal.entry_price - signal.stop_loss)
                reward = abs(signal.take_profit - signal.entry_price)
                if risk > 0:
                    rr = reward / risk
                    assert rr >= 0.5, \
                        f"{strategy.name} R:R={rr:.2f} too low (entry={signal.entry_price}, SL={signal.stop_loss}, TP={signal.take_profit})"
