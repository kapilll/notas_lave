"""Tests for strategy signal output — ensure strategies don't crash and produce valid signals."""

from datetime import datetime, timezone
from engine.src.data.models import Candle, Signal, SignalStrength
from engine.src.strategies.registry import get_all_strategies


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
        assert len(strategies) == 14  # Verify count

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
