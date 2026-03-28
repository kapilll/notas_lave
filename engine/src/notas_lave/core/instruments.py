"""DEPRECATED: Use data.instruments instead.

QR-03 FIX: Instrument registry merged into data/instruments.py.
This file re-exports for backward compatibility.
"""

from ..data.instruments import (
    InstrumentSpec as Instrument,  # Alias for backward compat
    INSTRUMENTS,
    get_instrument,
)

__all__ = ["Instrument", "INSTRUMENTS", "get_instrument"]
