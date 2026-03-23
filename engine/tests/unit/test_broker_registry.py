"""Tests for v2 broker registry — auto-discovery + factory.

The registry pattern means adding a new broker = creating a file
with @register_broker("name"). Zero changes to the factory.
"""

import pytest


def test_register_and_create_broker():
    from notas_lave.execution.registry import register_broker, create_broker, _REGISTRY

    @register_broker("test_broker")
    class TestBroker:
        @property
        def name(self) -> str:
            return "test_broker"

    assert "test_broker" in _REGISTRY
    broker = create_broker("test_broker")
    assert broker.name == "test_broker"

    # Cleanup
    del _REGISTRY["test_broker"]


def test_create_unknown_broker_raises():
    from notas_lave.execution.registry import create_broker

    with pytest.raises(KeyError, match="Unknown broker"):
        create_broker("nonexistent_broker")


def test_list_available_brokers():
    from notas_lave.execution.registry import list_brokers, register_broker, _REGISTRY

    @register_broker("list_test_a")
    class A:
        pass

    @register_broker("list_test_b")
    class B:
        pass

    brokers = list_brokers()
    assert "list_test_a" in brokers
    assert "list_test_b" in brokers

    # Cleanup
    del _REGISTRY["list_test_a"]
    del _REGISTRY["list_test_b"]


def test_register_duplicate_warns(caplog):
    import logging
    from notas_lave.execution.registry import register_broker, _REGISTRY

    @register_broker("dup_test")
    class First:
        pass

    with caplog.at_level(logging.WARNING):
        @register_broker("dup_test")
        class Second:
            pass

    assert "already registered" in caplog.text

    # Cleanup
    del _REGISTRY["dup_test"]
