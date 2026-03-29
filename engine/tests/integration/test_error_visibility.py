"""Integration tests: every failure must surface visibly — no silent failures.

QA Architect rule: "Every silent failure in a trading system is a future loss."

These tests prove that:
1. Broker disconnection is visible in the API (not swallowed)
2. Trade rejections surface in exec_log (not just logged to file)
3. Market data failures change health status (not stuck at 'ok')
4. API endpoints correctly reflect actual connected/disconnected state

Tests use real implementations (PaperBroker, EventStore) — never mocks.
"""

import pytest
from fastapi.testclient import TestClient

from notas_lave.core.models import Direction, TradeSetup
from notas_lave.engine.event_bus import EventBus
from notas_lave.engine.pnl import PnLService
from notas_lave.execution.paper import PaperBroker
from notas_lave.journal.event_store import EventStore


def _make_app_with_lab():
    from notas_lave.api.app import Container, create_app
    from notas_lave.engine.lab import LabEngine

    broker = PaperBroker(initial_balance=10000.0)
    journal = EventStore(":memory:")
    bus = EventBus()
    pnl = PnLService(original_deposit=10000.0)
    lab = LabEngine(broker=broker, journal=journal, bus=bus, pnl=pnl)
    container = Container(broker=broker, journal=journal, bus=bus, pnl=pnl,
                          lab_engine=lab)
    return create_app(container), container


class TestBrokerDisconnectSurfacesInAPI:
    """Broker disconnect must be visible at the API level — not a silent failure."""

    def test_lab_status_shows_broker_disconnected(self):
        """When broker is not connected, /api/lab/status must say so.

        This is the failure mode the expert found: DeltaBroker returns cached
        balance when disconnected, making it look fine. The API must expose the
        actual is_connected state.
        """
        app, container = _make_app_with_lab()
        client = TestClient(app)

        # PaperBroker not connected (connect() never called)
        resp = client.get("/api/lab/status")
        assert resp.status_code == 200
        data = resp.json()

        assert data["broker_connected"] is False, (
            "Broker is disconnected but /api/lab/status shows broker_connected=True. "
            "Dashboard cannot show the 'Broker Offline' banner without this field."
        )

    @pytest.mark.asyncio
    async def test_lab_status_shows_broker_connected_after_connect(self):
        """After broker.connect(), lab status must reflect connected=True."""
        app, container = _make_app_with_lab()
        await container.broker.connect()
        client = TestClient(app)

        resp = client.get("/api/lab/status")
        assert resp.json()["broker_connected"] is True

    def test_system_health_shows_broker_disconnected(self):
        """System health must also reflect real broker connection status."""
        app, _ = _make_app_with_lab()
        client = TestClient(app)

        resp = client.get("/api/system/health")
        broker_component = resp.json()["components"]["broker"]
        assert broker_component["status"] == "disconnected"

    @pytest.mark.asyncio
    async def test_system_health_shows_broker_connected(self):
        app, container = _make_app_with_lab()
        await container.broker.connect()
        client = TestClient(app)

        resp = client.get("/api/system/health")
        broker_component = resp.json()["components"]["broker"]
        assert broker_component["status"] == "connected"


class TestTradeRejectionSurfacesInAPI:
    """Trade rejections must appear in exec_log, not just engine logs."""

    def test_exec_log_empty_initially(self):
        app, _ = _make_app_with_lab()
        client = TestClient(app)
        resp = client.get("/api/lab/status")
        assert resp.json()["exec_log"] == []

    def test_exec_log_shows_rejection(self):
        """A simulated broker rejection must appear in /api/lab/status exec_log.

        Expert finding: broker rejections were only in Python logs, invisible
        to the dashboard. User saw a promising proposal disappear with no
        explanation.
        """
        app, container = _make_app_with_lab()
        # Simulate a rejection that would have been logged only (old behaviour)
        container.lab_engine._last_exec_log = [
            {"symbol": "BTCUSD", "result": "broker_rejected"},
            {"symbol": "ETHUSD", "result": "placed", "id": 1},
        ]
        client = TestClient(app)

        resp = client.get("/api/lab/status")
        exec_log = resp.json()["exec_log"]

        assert len(exec_log) == 2
        rejections = [e for e in exec_log if e["result"] == "broker_rejected"]
        assert len(rejections) == 1, (
            "Broker rejection not visible in exec_log. "
            "Dashboard cannot tell user why a trade wasn't placed."
        )

    def test_arena_status_exposes_exec_log(self):
        """Arena endpoint (polled every 10s) must also expose exec_log."""
        app, container = _make_app_with_lab()
        container.lab_engine._last_exec_log = [
            {"symbol": "SOLUSD", "result": "broker_rejected"}
        ]
        client = TestClient(app)

        resp = client.get("/api/lab/arena")
        data = resp.json()
        assert "exec_log" in data, (
            "/api/lab/arena is missing exec_log. "
            "Strategies tab will not show trade rejections."
        )
        assert len(data["exec_log"]) == 1


class TestMarketDataFailuresChangeHealthStatus:
    """Market data failures must change health status — not stay stuck at 'ok'."""

    def test_health_ok_when_no_market_failures(self):
        from notas_lave.data.market_data import market_data
        market_data._consecutive_failures.clear()

        app, _ = _make_app_with_lab()
        client = TestClient(app)
        resp = client.get("/api/system/health")
        assert resp.json()["components"]["market_data"]["status"] == "ok"

    def test_health_degraded_when_ccxt_fails(self):
        """CCXT failures must make market_data.status = 'degraded'.

        Old behaviour: status was always 'ok' even when CCXT had been failing
        for hours. Expert finding: user didn't know 3/6 symbols had no data.
        """
        from notas_lave.data.market_data import market_data
        market_data._consecutive_failures["ccxt"] = 5

        try:
            app, _ = _make_app_with_lab()
            client = TestClient(app)
            resp = client.get("/api/system/health")
            md = resp.json()["components"]["market_data"]

            assert md["status"] == "degraded", (
                f"5 CCXT failures but market_data.status='{md['status']}'. "
                "Must be 'degraded' when consecutive_failures > 0."
            )
            assert md["consecutive_failures"]["ccxt"] == 5
        finally:
            market_data._consecutive_failures.clear()

    def test_health_shows_failures_per_source(self):
        """Health must break down failures per data source (ccxt/twelvedata)."""
        from notas_lave.data.market_data import market_data
        market_data._consecutive_failures["ccxt"] = 2
        market_data._consecutive_failures["twelvedata"] = 1

        try:
            app, _ = _make_app_with_lab()
            client = TestClient(app)
            resp = client.get("/api/system/health")
            failures = resp.json()["components"]["market_data"]["consecutive_failures"]

            assert failures.get("ccxt") == 2
            assert failures.get("twelvedata") == 1
        finally:
            market_data._consecutive_failures.clear()


class TestConsecutiveErrorsVisible:
    """Consecutive tick errors must surface through the API, not just logs."""

    def test_errors_last_hour_zero_normally(self):
        app, _ = _make_app_with_lab()
        client = TestClient(app)
        resp = client.get("/api/system/health")
        assert resp.json()["errors_last_hour"] == 0

    def test_errors_last_hour_reflects_engine_errors(self):
        """errors_last_hour must read from lab_engine._consecutive_errors.

        Old behaviour: always returned 0. Expert finding: engine could be
        failing for 7.5 minutes (10 errors × 45s) with dashboard showing 0 errors.
        """
        app, container = _make_app_with_lab()
        container.lab_engine._consecutive_errors = 3

        client = TestClient(app)
        resp = client.get("/api/system/health")
        assert resp.json()["errors_last_hour"] == 3, (
            "errors_last_hour is 0 but engine has 3 consecutive errors. "
            "Health endpoint must read lab_engine._consecutive_errors."
        )

    def test_lab_status_consecutive_errors_field(self):
        app, container = _make_app_with_lab()
        container.lab_engine._consecutive_errors = 7

        client = TestClient(app)
        resp = client.get("/api/lab/status")
        assert resp.json()["consecutive_errors"] == 7
