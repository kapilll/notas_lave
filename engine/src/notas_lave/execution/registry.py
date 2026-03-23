"""Broker registry — auto-discovery via @register_broker decorator.

Usage:
    @register_broker("binance")
    class BinanceBroker:
        ...

    broker = create_broker("binance")

Adding a new broker = creating a file with @register_broker.
Zero changes to this file or any factory.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Module-level registry: broker_name -> broker_class
_REGISTRY: dict[str, type] = {}


def register_broker(name: str):
    """Decorator to register a broker class by name."""

    def decorator(cls: type) -> type:
        if name in _REGISTRY:
            logger.warning(
                "Broker '%s' already registered (%s), overwriting with %s",
                name, _REGISTRY[name].__name__, cls.__name__,
            )
        _REGISTRY[name] = cls
        return cls

    return decorator


def create_broker(name: str, **kwargs: Any):
    """Create a broker instance by name. Raises KeyError if unknown."""
    if name not in _REGISTRY:
        raise KeyError(
            f"Unknown broker: '{name}'. "
            f"Available: {list(_REGISTRY.keys())}"
        )
    return _REGISTRY[name](**kwargs)


def list_brokers() -> list[str]:
    """Return names of all registered brokers."""
    return list(_REGISTRY.keys())
