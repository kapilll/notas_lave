"""Tests for domain exceptions — every exception class must be instantiable and catchable."""

import pytest
from notas_lave.core.errors import (
    TradingError, RiskRejected, BrokerError, InstrumentNotFound, InsufficientBalance,
)


class TestTradingError:
    def test_base_exception_is_exception(self):
        with pytest.raises(TradingError):
            raise TradingError("base error")

    def test_base_exception_message(self):
        e = TradingError("something went wrong")
        assert "something went wrong" in str(e)


class TestRiskRejected:
    def test_is_trading_error(self):
        e = RiskRejected(["DAILY DRAWDOWN: limit hit"])
        assert isinstance(e, TradingError)

    def test_stores_reasons(self):
        reasons = ["R:R TOO LOW: 1.0", "HALTED: daily limit"]
        e = RiskRejected(reasons)
        assert e.reasons == reasons

    def test_message_contains_reasons(self):
        e = RiskRejected(["DAILY DRAWDOWN"])
        assert "DAILY DRAWDOWN" in str(e)

    def test_multiple_reasons(self):
        e = RiskRejected(["reason one", "reason two"])
        assert "reason one" in str(e)
        assert "reason two" in str(e)

    def test_empty_reasons(self):
        e = RiskRejected([])
        assert e.reasons == []

    def test_catchable_as_trading_error(self):
        with pytest.raises(TradingError):
            raise RiskRejected(["test"])


class TestBrokerError:
    def test_is_trading_error(self):
        e = BrokerError("delta", "place_order", "timeout")
        assert isinstance(e, TradingError)

    def test_stores_broker_and_operation(self):
        e = BrokerError("delta_testnet", "get_balance", "connection refused")
        assert e.broker == "delta_testnet"
        assert e.operation == "get_balance"

    def test_message_format(self):
        e = BrokerError("paper", "place_order", "out of funds")
        assert "[paper]" in str(e)
        assert "place_order" in str(e)
        assert "out of funds" in str(e)

    def test_without_detail(self):
        e = BrokerError("paper", "connect")
        assert "connect" in str(e)

    def test_catchable_as_trading_error(self):
        with pytest.raises(TradingError):
            raise BrokerError("paper", "connect")


class TestInstrumentNotFound:
    def test_is_trading_error(self):
        e = InstrumentNotFound("DOGEUSDT")
        assert isinstance(e, TradingError)

    def test_stores_symbol(self):
        e = InstrumentNotFound("SHIB")
        assert e.symbol == "SHIB"

    def test_message_contains_symbol(self):
        e = InstrumentNotFound("UNKNOWN")
        assert "UNKNOWN" in str(e)

    def test_catchable(self):
        with pytest.raises(InstrumentNotFound):
            raise InstrumentNotFound("XYZ")


class TestInsufficientBalance:
    def test_is_trading_error(self):
        e = InsufficientBalance(required=1000.0, available=500.0)
        assert isinstance(e, TradingError)

    def test_stores_amounts(self):
        e = InsufficientBalance(required=250.0, available=100.0)
        assert e.required == 250.0
        assert e.available == 100.0

    def test_message_contains_amounts(self):
        e = InsufficientBalance(required=1000.0, available=50.0)
        assert "1000" in str(e)
        assert "50" in str(e)

    def test_catchable(self):
        with pytest.raises(InsufficientBalance):
            raise InsufficientBalance(100.0, 0.0)
