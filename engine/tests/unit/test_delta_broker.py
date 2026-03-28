"""Tests for DeltaBroker — standalone implementation.

Tests verify the broker satisfies IBroker, uses InstrumentRegistry,
handles disconnected state, and signs requests correctly. No network calls.
"""

import pytest

from notas_lave.core.models import (
    BalanceInfo,
    Direction,
    ExchangePosition,
    OrderResult,
    TradeSetup,
)
from notas_lave.core.ports import IBroker


def test_delta_broker_satisfies_ibroker():
    from notas_lave.execution.delta import DeltaBroker

    broker = DeltaBroker(api_key="fake", api_secret="fake")
    assert isinstance(broker, IBroker)


def test_delta_broker_name():
    from notas_lave.execution.delta import DeltaBroker

    broker = DeltaBroker(api_key="fake", api_secret="fake")
    assert broker.name == "delta_testnet"


def test_delta_broker_not_connected_initially():
    from notas_lave.execution.delta import DeltaBroker

    broker = DeltaBroker(api_key="fake", api_secret="fake")
    assert broker.is_connected is False


def test_delta_broker_uses_instrument_registry():
    from notas_lave.execution.delta import DeltaBroker

    broker = DeltaBroker(api_key="fake", api_secret="fake")
    assert broker._exchange_symbol("BTCUSD") == "BTCUSD"
    assert broker._exchange_symbol("ETHUSD") == "ETHUSD"
    assert broker._exchange_symbol("SOLUSD") == "SOLUSD"
    # Pass-through for unmapped symbols
    assert broker._exchange_symbol("BTCUSDT") == "BTCUSDT"
    # XAU/XAG not on Delta — should pass through
    assert broker._exchange_symbol("XAUUSD") == "XAUUSD"


def test_delta_broker_registered():
    from notas_lave.execution.delta import DeltaBroker  # noqa: F401
    from notas_lave.execution.registry import _REGISTRY

    assert "delta_testnet" in _REGISTRY


def test_delta_broker_hmac_signature():
    from notas_lave.execution.delta import DeltaBroker

    broker = DeltaBroker(api_key="test_key", api_secret="test_secret")

    sig = broker._sign("GET", "1700000000", "/v2/products", "", "")
    assert isinstance(sig, str)
    assert len(sig) == 64  # SHA-256 hex digest is 64 chars

    # Same inputs produce same signature (deterministic)
    sig2 = broker._sign("GET", "1700000000", "/v2/products", "", "")
    assert sig == sig2

    # Different inputs produce different signatures
    sig3 = broker._sign("POST", "1700000000", "/v2/orders", "", '{"size":1}')
    assert sig3 != sig


def test_delta_broker_auth_headers():
    from notas_lave.execution.delta import DeltaBroker

    broker = DeltaBroker(api_key="test_key", api_secret="test_secret")
    headers = broker._auth_headers("GET", "/v2/products")

    assert headers["api-key"] == "test_key"
    assert "timestamp" in headers
    assert "signature" in headers
    assert headers["Content-Type"] == "application/json"


def test_delta_broker_product_id_without_products():
    from notas_lave.execution.delta import DeltaBroker

    broker = DeltaBroker(api_key="fake", api_secret="fake")
    # No products loaded yet
    assert broker._product_id("BTCUSD") is None


def test_delta_broker_product_id_with_cached_products():
    from notas_lave.execution.delta import DeltaBroker

    broker = DeltaBroker(api_key="fake", api_secret="fake")
    broker._product_ids = {"BTCUSD": 84, "ETHUSD": 1699}

    assert broker._product_id("BTCUSD") == 84
    assert broker._product_id("ETHUSD") == 1699
    assert broker._product_id("SOLUSD") is None  # Not in cache


def test_delta_broker_custom_base_url():
    from notas_lave.execution.delta import DeltaBroker

    broker = DeltaBroker(
        api_key="fake", api_secret="fake",
        base_url="https://api.india.delta.exchange",
    )
    assert broker._base_url == "https://api.india.delta.exchange"


@pytest.mark.asyncio
async def test_delta_disconnected_returns_empty_balance():
    from notas_lave.execution.delta import DeltaBroker

    broker = DeltaBroker(api_key="fake", api_secret="fake")
    balance = await broker.get_balance()
    assert isinstance(balance, BalanceInfo)
    assert balance.total == 0


@pytest.mark.asyncio
async def test_delta_disconnected_returns_empty_positions():
    from notas_lave.execution.delta import DeltaBroker

    broker = DeltaBroker(api_key="fake", api_secret="fake")
    positions = await broker.get_positions()
    assert positions == []


@pytest.mark.asyncio
async def test_delta_disconnected_rejects_order():
    from notas_lave.execution.delta import DeltaBroker

    broker = DeltaBroker(api_key="fake", api_secret="fake")
    setup = TradeSetup(
        symbol="BTCUSD", direction=Direction.LONG,
        entry_price=85000.0, stop_loss=84000.0,
        take_profit=87000.0, position_size=0.01,
    )
    result = await broker.place_order(setup)
    assert isinstance(result, OrderResult)
    assert result.success is False
    assert "Not connected" in result.error


@pytest.mark.asyncio
async def test_delta_disconnected_rejects_close():
    from notas_lave.execution.delta import DeltaBroker

    broker = DeltaBroker(api_key="fake", api_secret="fake")
    result = await broker.close_position("BTCUSD")
    assert isinstance(result, OrderResult)
    assert result.success is False


@pytest.mark.asyncio
async def test_delta_disconnected_cancel_returns_false():
    from notas_lave.execution.delta import DeltaBroker

    broker = DeltaBroker(api_key="fake", api_secret="fake")
    result = await broker.cancel_all_orders("BTCUSD")
    assert result is False


@pytest.mark.asyncio
async def test_delta_connect_fails_without_keys():
    from notas_lave.execution.delta import DeltaBroker

    broker = DeltaBroker(api_key="", api_secret="")
    connected = await broker.connect()
    assert connected is False
    assert broker.is_connected is False


@pytest.mark.asyncio
async def test_delta_disconnect():
    from notas_lave.execution.delta import DeltaBroker

    broker = DeltaBroker(api_key="fake", api_secret="fake")
    broker._connected = True
    await broker.disconnect()
    assert broker.is_connected is False


@pytest.mark.asyncio
async def test_delta_get_order_status_disconnected():
    from notas_lave.execution.delta import DeltaBroker

    broker = DeltaBroker(api_key="fake", api_secret="fake")
    result = await broker.get_order_status("12345")
    assert isinstance(result, OrderResult)
    assert result.success is False
    assert "Not connected" in result.error


def test_safe_float():
    from notas_lave.execution.delta import _safe_float

    assert _safe_float("123.45") == 123.45
    assert _safe_float(None) == 0.0
    assert _safe_float("invalid") == 0.0
    assert _safe_float(float("nan")) == 0.0
    assert _safe_float(float("inf")) == 0.0
    assert _safe_float("", 5.0) == 5.0
