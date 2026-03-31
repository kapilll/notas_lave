"""Tests for v2 API routes — DI, no globals, TestClient."""

import pytest
from fastapi.testclient import TestClient

from notas_lave.engine.event_bus import EventBus
from notas_lave.engine.pnl import PnLService
from notas_lave.execution.paper import PaperBroker
from notas_lave.journal.event_store import EventStore


def _make_app():
    from notas_lave.api.app import Container, create_app

    broker = PaperBroker(initial_balance=10000.0)
    journal = EventStore(":memory:")
    bus = EventBus()
    pnl = PnLService(original_deposit=10000.0)

    container = Container(broker=broker, journal=journal, bus=bus, pnl=pnl)
    return create_app(container), container


def test_health():
    app, _ = _make_app()
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_system_health():
    app, _ = _make_app()
    client = TestClient(app)
    resp = client.get("/api/system/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "components" in data
    assert "lab_engine" in data["components"]


def test_get_balance():
    app, _ = _make_app()
    client = TestClient(app)
    resp = client.get("/api/trade/balance")
    assert resp.status_code == 200
    assert resp.json()["total"] == 10000.0


def test_get_positions_empty():
    app, _ = _make_app()
    client = TestClient(app)
    resp = client.get("/api/trade/positions")
    assert resp.status_code == 200


def test_get_pnl():
    app, _ = _make_app()
    client = TestClient(app)
    resp = client.get("/api/trade/pnl")
    assert resp.status_code == 200
    data = resp.json()
    assert data["pnl"] == 0.0
    assert data["original_deposit"] == 10000.0


def test_lab_status_no_lab():
    app, _ = _make_app()
    client = TestClient(app)
    resp = client.get("/api/lab/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["lab_available"] is False


def test_lab_trades_empty():
    app, _ = _make_app()
    client = TestClient(app)
    resp = client.get("/api/lab/trades")
    assert resp.status_code == 200
    data = resp.json()
    assert data["trades"] == []
    assert data["summary"]["total_trades"] == 0


def test_risk_status():
    app, _ = _make_app()
    client = TestClient(app)
    resp = client.get("/api/risk/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["balance"] == 10000.0
    assert data["can_trade"] is True
