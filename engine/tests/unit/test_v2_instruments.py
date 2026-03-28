"""Tests for InstrumentSpec — centralized instrument registry.

After QR-03 merge, data/instruments.py is the single source of truth for:
- Instrument specs (pip, spread, contract size, position sizing)
- Exchange symbol mapping (delta, coindcx, mt5)
- core/instruments.py re-exports for backward compatibility
"""

import pytest


def test_instrument_spec_has_exchange_symbols():
    from notas_lave.data.instruments import get_instrument

    btc = get_instrument("BTCUSD")
    assert btc.exchange_symbol("delta") == "BTCUSD"
    assert btc.contract_size == 1.0
    assert btc.pip_size == 0.01


def test_instrument_is_frozen():
    from notas_lave.data.instruments import get_instrument

    inst = get_instrument("BTCUSD")
    with pytest.raises(AttributeError):
        inst.symbol = "CHANGED"


def test_exchange_symbol_lookup():
    from notas_lave.data.instruments import get_instrument

    btc = get_instrument("BTCUSD")
    assert btc.exchange_symbol("delta") == "BTCUSD"
    eth = get_instrument("ETHUSD")
    assert eth.exchange_symbol("delta") == "ETHUSD"


def test_exchange_symbol_unknown_broker_raises():
    from notas_lave.data.instruments import get_instrument

    xrp = get_instrument("XRPUSD")
    with pytest.raises(ValueError, match="not available on"):
        xrp.exchange_symbol("nonexistent_broker")


def test_core_instruments_backward_compat():
    """core/instruments.py re-exports from data/instruments.py."""
    from notas_lave.core.instruments import INSTRUMENTS, get_instrument, Instrument

    assert "BTCUSD" in INSTRUMENTS
    btc = get_instrument("BTCUSD")
    assert isinstance(btc, Instrument)


def test_registry_has_btcusd():
    from notas_lave.data.instruments import INSTRUMENTS

    assert "BTCUSD" in INSTRUMENTS
    btc = INSTRUMENTS["BTCUSD"]
    assert btc.contract_size == 1.0
    assert "delta" in btc.exchange_symbols


def test_registry_has_ethusd():
    from notas_lave.data.instruments import INSTRUMENTS

    assert "ETHUSD" in INSTRUMENTS


def test_registry_has_xauusd():
    from notas_lave.data.instruments import INSTRUMENTS

    assert "XAUUSD" in INSTRUMENTS
    xau = INSTRUMENTS["XAUUSD"]
    assert xau.contract_size == 100


def test_registry_has_lab_instruments():
    from notas_lave.data.instruments import INSTRUMENTS

    for sym in ("SOLUSD", "XRPUSD", "BNBUSD", "DOGEUSD"):
        assert sym in INSTRUMENTS, f"{sym} missing from registry"


def test_get_instrument_unknown_raises():
    from notas_lave.data.instruments import get_instrument

    with pytest.raises(KeyError, match="Unknown instrument"):
        get_instrument("NOSUCHSYMBOL")


def test_get_instrument_known():
    from notas_lave.data.instruments import get_instrument

    btc = get_instrument("BTCUSD")
    assert btc.symbol == "BTCUSD"


def test_delta_symbol_mapping():
    from notas_lave.data.instruments import INSTRUMENTS

    btc = INSTRUMENTS["BTCUSD"]
    assert btc.exchange_symbol("delta") == "BTCUSD"

    eth = INSTRUMENTS["ETHUSD"]
    assert eth.exchange_symbol("delta") == "ETHUSD"


def test_major_instruments_have_delta_mapping():
    from notas_lave.data.instruments import INSTRUMENTS

    for symbol in ("BTCUSD", "ETHUSD", "SOLUSD"):
        inst = INSTRUMENTS[symbol]
        assert "delta" in inst.exchange_symbols, (
            f"{symbol} has no Delta mapping"
        )
