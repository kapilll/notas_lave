"""
Base class for all trading strategies.

Every strategy inherits from this and implements `analyze()`.
The analyze method receives candles and returns a Signal.

This keeps all strategies consistent — same input, same output format.
"""

from abc import ABC, abstractmethod
from ..data.models import Candle, Signal, SignalStrength, Direction


class BaseStrategy(ABC):
    """
    All strategies inherit from this class.

    To create a new strategy:
    1. Create a file in strategies/ (e.g., my_strategy.py)
    2. Create a class that inherits BaseStrategy
    3. Implement the `analyze()` method
    4. Register it in the strategy registry

    The analyze method receives a list of Candles (oldest first)
    and returns a Signal with direction, strength, score, and levels.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name for this strategy (e.g., 'ema_crossover')."""
        ...

    @property
    @abstractmethod
    def category(self) -> str:
        """Category this strategy belongs to (e.g., 'scalping', 'ict', 'fibonacci')."""
        ...

    @abstractmethod
    def analyze(self, candles: list[Candle], symbol: str = "") -> Signal:
        """
        Analyze candles and produce a trading signal.

        Args:
            candles: List of Candle objects, oldest first. Minimum 200 candles recommended.
            symbol: The instrument being analyzed (for symbol-specific logic).

        Returns:
            Signal with direction, strength, score, and suggested levels.
        """
        ...

    def _no_signal(self, reason: str = "No setup detected") -> Signal:
        """Helper to return an empty signal when no setup is found."""
        return Signal(
            strategy_name=self.name,
            direction=None,
            strength=SignalStrength.NONE,
            score=0.0,
            reason=reason,
        )

    # --- Shared helpers for all strategies ---
    # These avoid duplicating ATR/volume logic across 12 strategy files.

    @staticmethod
    def compute_atr(candles: list[Candle], period: int = 14) -> float | None:
        """Average True Range — measures volatility adaptively."""
        if len(candles) < period + 1:
            return None
        true_ranges = []
        for i in range(1, len(candles)):
            tr = max(
                candles[i].high - candles[i].low,
                abs(candles[i].high - candles[i - 1].close),
                abs(candles[i].low - candles[i - 1].close),
            )
            true_ranges.append(tr)
        return sum(true_ranges[-period:]) / period

    @staticmethod
    def check_volume(candles: list[Candle], multiplier: float = 0.8, lookback: int = 20) -> bool:
        """Check if the LAST COMPLETED candle has reasonable volume.

        Compares candles[-2] (last completed) against the average of
        prior candles. The current candle (candles[-1]) is still forming
        and always has partial volume — comparing it would always fail.

        Volume confirms signal quality: high volume on a breakout confirms
        the move, low volume suggests a fake-out.
        """
        if len(candles) < lookback + 2:
            return True
        completed = candles[-2]
        volumes = [c.volume for c in candles[-lookback - 2:-2] if c.volume > 0]
        if not volumes:
            return True
        avg_vol = sum(volumes) / len(volumes)
        if avg_vol <= 0:
            return True
        return completed.volume >= avg_vol * multiplier

    @staticmethod
    def atr_stop_loss(entry: float, atr: float, direction: str, multiplier: float = 1.5) -> float:
        """Calculate ATR-based stop loss. Adapts to current volatility."""
        if direction == "LONG":
            return round(entry - atr * multiplier, 2)
        return round(entry + atr * multiplier, 2)

    @staticmethod
    def atr_take_profit(entry: float, atr: float, direction: str, rr_ratio: float = 2.0, sl_distance: float = 0) -> float:
        """Calculate ATR-based take profit. Default 2:1 R:R from SL distance."""
        if sl_distance <= 0:
            sl_distance = atr * 1.5
        if direction == "LONG":
            return round(entry + sl_distance * rr_ratio, 2)
        return round(entry - sl_distance * rr_ratio, 2)
