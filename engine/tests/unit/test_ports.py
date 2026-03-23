"""Tests for v2 Protocol interfaces.

Verify that Protocol classes exist, are runtime_checkable,
and that conforming implementations are recognized.
"""

from datetime import datetime, timezone

import pytest


def test_ibroker_protocol_exists():
    from notas_lave.core.ports import IBroker
    assert hasattr(IBroker, 'name')
    assert hasattr(IBroker, 'is_connected')
    assert hasattr(IBroker, 'connect')
    assert hasattr(IBroker, 'get_balance')
    assert hasattr(IBroker, 'get_positions')
    assert hasattr(IBroker, 'place_order')
    assert hasattr(IBroker, 'close_position')


def test_ibroker_is_runtime_checkable():
    from notas_lave.core.ports import IBroker
    from notas_lave.core.models import BalanceInfo, ExchangePosition, OrderResult, TradeSetup

    class FakeBroker:
        @property
        def name(self) -> str:
            return "fake"

        @property
        def is_connected(self) -> bool:
            return True

        async def connect(self) -> bool:
            return True

        async def disconnect(self) -> None:
            pass

        async def get_balance(self) -> BalanceInfo:
            return BalanceInfo(total=1000.0, available=1000.0)

        async def get_positions(self) -> list[ExchangePosition]:
            return []

        async def get_order_status(self, order_id: str) -> OrderResult:
            return OrderResult()

        async def place_order(self, setup: TradeSetup) -> OrderResult:
            return OrderResult(success=True)

        async def close_position(self, symbol: str) -> OrderResult:
            return OrderResult(success=True)

        async def cancel_all_orders(self, symbol: str) -> bool:
            return True

    assert isinstance(FakeBroker(), IBroker)


def test_non_broker_fails_isinstance():
    from notas_lave.core.ports import IBroker

    class NotABroker:
        pass

    assert not isinstance(NotABroker(), IBroker)


def test_idata_provider_protocol():
    from notas_lave.core.ports import IDataProvider
    from notas_lave.core.models import Candle

    class FakeProvider:
        async def get_candles(self, symbol: str, timeframe: str, limit: int = 250) -> list[Candle]:
            return []

        async def get_current_price(self, symbol: str) -> float:
            return 85000.0

    assert isinstance(FakeProvider(), IDataProvider)


def test_irisk_manager_protocol():
    from notas_lave.core.ports import IRiskManager
    from notas_lave.core.models import TradeSetup

    class FakeRisk:
        def check_trade(self, setup: TradeSetup) -> tuple[bool, list[str]]:
            return True, []

    assert isinstance(FakeRisk(), IRiskManager)


def test_itrade_journal_protocol():
    from notas_lave.core.ports import ITradeJournal
    from notas_lave.core.models import Signal, TradeSetup

    class FakeJournal:
        def record_signal(self, signal: Signal) -> int:
            return 1

        def record_open(self, trade_id: int, setup: TradeSetup) -> None:
            pass

        def record_close(self, trade_id: int, exit_price: float, reason: str, pnl: float) -> None:
            pass

        def record_grade(self, trade_id: int, grade: str, lesson: str) -> None:
            pass

        def get_closed_trades(self, limit: int = 50) -> list[dict]:
            return []

        def get_open_trades(self) -> list[dict]:
            return []

    assert isinstance(FakeJournal(), ITradeJournal)


def test_istrategy_protocol():
    from notas_lave.core.ports import IStrategy
    from notas_lave.core.models import Candle, Signal

    class FakeStrategy:
        @property
        def name(self) -> str:
            return "fake"

        @property
        def category(self) -> str:
            return "test"

        def analyze(self, candles: list[Candle], symbol: str) -> Signal:
            return Signal(strategy_name="fake")

    assert isinstance(FakeStrategy(), IStrategy)


def test_ialerter_protocol():
    from notas_lave.core.ports import IAlerter

    class FakeAlerter:
        async def send(self, message: str) -> bool:
            return True

    assert isinstance(FakeAlerter(), IAlerter)
