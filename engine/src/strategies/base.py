"""
Base class for all trading strategies.

Every strategy inherits from this and implements `analyze()`.
The analyze method receives candles and returns a Signal.

This keeps all strategies consistent — same input, same output format.
"""

from abc import ABC, abstractmethod
from ..data.models import Candle, Signal, SignalStrength


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
