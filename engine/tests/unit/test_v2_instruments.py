"""Tests for v2 InstrumentRegistry — centralized symbol mapping.

The registry is the single source of truth for:
- Internal symbol → exchange symbol mapping
- Tick sizes, contract specs per broker
- Instrument discovery
"""

import pytest


def test_instrument_creation():
    from notas_lave.core.instruments import Instrument

    inst = Instrument(
        symbol="BTCUSD",
        name="Bitcoin/USD",
        contract_size=1.0,
        pip_size=0.01,
        exchange_symbols={"binance": "BTCUSDT", "coindcx": "BTCINR"},
    )
    assert inst.symbol == "BTCUSD"
    assert inst.contract_size == 1.0


def test_instrument_is_frozen():
    from notas_lave.core.instruments import Instrument

    inst = Instrument(symbol="BTCUSD", name="Bitcoin/USD", contract_size=1.0, pip_size=0.01)
    with pytest.raises(AttributeError):
        inst.symbol = "CHANGED"


def test_exchange_symbol_lookup():
    from notas_lave.core.instruments import Instrument

    inst = Instrument(
        symbol="BTCUSD",
        name="Bitcoin/USD",
        contract_size=1.0,
        pip_size=0.01,
        exchange_symbols={"binance": "BTCUSDT", "coindcx": "BTCINR"},
    )
    assert inst.exchange_symbol("binance") == "BTCUSDT"
    assert inst.exchange_symbol("coindcx") == "BTCINR"


def test_exchange_symbol_unknown_broker_raises():
    from notas_lave.core.instruments import Instrument

    inst = Instrument(
        symbol="BTCUSD",
        name="Bitcoin/USD",
        contract_size=1.0,
        pip_size=0.01,
        exchange_symbols={"binance": "BTCUSDT"},
    )
    with pytest.raises(ValueError, match="not available on mt5"):
        inst.exchange_symbol("mt5")


def test_registry_has_btcusd():
    from notas_lave.core.instruments import INSTRUMENTS

    assert "BTCUSD" in INSTRUMENTS
    btc = INSTRUMENTS["BTCUSD"]
    assert btc.contract_size == 1.0
    assert "binance" in btc.exchange_symbols


def test_registry_has_ethusd():
    from notas_lave.core.instruments import INSTRUMENTS

    assert "ETHUSD" in INSTRUMENTS


def test_registry_has_xauusd():
    from notas_lave.core.instruments import INSTRUMENTS

    assert "XAUUSD" in INSTRUMENTS
    gold = INSTRUMENTS["XAUUSD"]
    assert gold.contract_size == 100.0


def test_registry_has_lab_instruments():
    from notas_lave.core.instruments import INSTRUMENTS

    lab_symbols = ["SOLUSD", "XRPUSD", "BNBUSD", "DOGEUSD", "ADAUSD"]
    for sym in lab_symbols:
        assert sym in INSTRUMENTS, f"{sym} missing from registry"


def test_get_instrument_found():
    from notas_lave.core.instruments import get_instrument

    btc = get_instrument("BTCUSD")
    assert btc.symbol == "BTCUSD"


def test_get_instrument_not_found():
    from notas_lave.core.instruments import get_instrument

    with pytest.raises(KeyError, match="Unknown instrument"):
        get_instrument("FAKECOIN")


def test_binance_symbol_mapping():
    from notas_lave.core.instruments import INSTRUMENTS

    btc = INSTRUMENTS["BTCUSD"]
    assert btc.exchange_symbol("binance") == "BTCUSDT"

    eth = INSTRUMENTS["ETHUSD"]
    assert eth.exchange_symbol("binance") == "ETHUSDT"


def test_all_instruments_have_binance_mapping():
    from notas_lave.core.instruments import INSTRUMENTS

    for symbol, inst in INSTRUMENTS.items():
        assert "binance" in inst.exchange_symbols, (
            f"{symbol} has no Binance mapping"
        )
