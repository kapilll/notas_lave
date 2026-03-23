"""Domain exceptions — specific error types for the trading system.

Use these instead of generic ValueError/RuntimeError so callers
can catch specific failure modes.
"""


class TradingError(Exception):
    """Base exception for all trading system errors."""


class RiskRejected(TradingError):
    """Trade was rejected by the risk manager."""

    def __init__(self, reasons: list[str]):
        self.reasons = reasons
        super().__init__(f"Risk check failed: {', '.join(reasons)}")


class BrokerError(TradingError):
    """Broker operation failed."""

    def __init__(self, broker: str, operation: str, detail: str = ""):
        self.broker = broker
        self.operation = operation
        super().__init__(f"[{broker}] {operation} failed: {detail}")


class InstrumentNotFound(TradingError):
    """Unknown instrument symbol."""

    def __init__(self, symbol: str):
        self.symbol = symbol
        super().__init__(f"Unknown instrument: {symbol}")


class InsufficientBalance(TradingError):
    """Not enough balance to place the trade."""

    def __init__(self, required: float, available: float):
        self.required = required
        self.available = available
        super().__init__(
            f"Insufficient balance: need {required}, have {available}"
        )
