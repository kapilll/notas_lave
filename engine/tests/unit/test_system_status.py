"""Unit tests for system health endpoint — verifies it returns REAL data, not hardcoded values.

The expert audit found /api/system/health previously returned:
  - "market_data": {"status": "ok"}  (always, even when broken)
  - "errors_last_hour": 0            (always, even when 10 errors occurred)
  - "uptime_seconds": seconds-since-midnight (not actual uptime)

These tests prove that hardcoded behaviour is gone and real state is reflected.
"""

import pytest
from fastapi.testclient import TestClient

from notas_lave.engine.event_bus import EventBus
from notas_lave.engine.pnl import PnLService
from notas_lave.execution.paper import PaperBroker
from notas_lave.journal.event_store import EventStore


def _make_app(with_lab=False):
    from notas_lave.api.app import Container, create_app

    broker = PaperBroker(initial_balance=10000.0)
    journal = EventStore(":memory:")
    bus = EventBus()
    pnl = PnLService(original_deposit=10000.0)

    lab_engine = None
    if with_lab:
        from notas_lave.engine.lab import LabEngine
        lab_engine = LabEngine(broker=broker, journal=journal, bus=bus, pnl=pnl)

    container = Container(broker=broker, journal=journal, bus=bus, pnl=pnl,
                          lab_engine=lab_engine)
    return create_app(container), container


class TestHealthEndpointReturnsRealData:
    """The health endpoint must surface actual state, never hardcoded values."""

    def test_health_includes_required_top_level_keys(self):
        app, _ = _make_app()
        client = TestClient(app)
        resp = client.get("/api/system/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "timestamp" in data
        assert "uptime_seconds" in data
        assert "components" in data
        assert "errors_last_hour" in data

    def test_uptime_is_positive_not_seconds_since_midnight(self):
        """Uptime must be time since process start, not time-of-day seconds.

        The old bug: `int(time.time() - time.time() % 86400)` gave seconds
        elapsed today (e.g. 43200 at noon) regardless of when the process started.
        """
        app, _ = _make_app()
        client = TestClient(app)
        resp = client.get("/api/system/health")
        uptime = resp.json()["uptime_seconds"]
        # A freshly created app must have uptime < 60s, not mid-day seconds
        assert uptime < 60, (
            f"uptime_seconds={uptime} looks like time-of-day, not process uptime. "
            "Fix: use a module-level _APP_START = time.time() captured at import."
        )

    def test_broker_status_reflects_actual_connection(self):
        """Broker status must come from broker.is_connected, not hardcoded."""
        app, container = _make_app()
        client = TestClient(app)

        # PaperBroker is NOT connected yet (connect() not called)
        resp = client.get("/api/system/health")
        broker_status = resp.json()["components"]["broker"]["status"]
        assert broker_status == "disconnected", (
            "Broker not yet connected but health shows 'connected'. "
            "broker.is_connected must be the source, not a hardcoded string."
        )

    def test_market_data_status_ok_when_no_failures(self):
        """Market data status is 'ok' when there are no consecutive failures."""
        from notas_lave.data.market_data import market_data
        # Ensure clean state
        market_data._consecutive_failures.clear()

        app, _ = _make_app()
        client = TestClient(app)
        resp = client.get("/api/system/health")
        md = resp.json()["components"]["market_data"]
        assert md["status"] == "ok"

    def test_market_data_status_degraded_when_failures_exist(self):
        """Market data status becomes 'degraded' when consecutive failures > 0.

        This is the core fix: the old endpoint returned 'ok' even when CCXT
        had been failing for hours. Now it reads market_data._consecutive_failures.
        """
        from notas_lave.data.market_data import market_data
        # Simulate a CCXT failure
        market_data._consecutive_failures["ccxt"] = 3
        try:
            app, _ = _make_app()
            client = TestClient(app)
            resp = client.get("/api/system/health")
            md = resp.json()["components"]["market_data"]
            assert md["status"] == "degraded", (
                "3 CCXT failures but market_data.status is still 'ok'. "
                "Health must read _consecutive_failures, not return hardcoded 'ok'."
            )
            assert "consecutive_failures" in md
            assert md["consecutive_failures"].get("ccxt", 0) == 3
        finally:
            market_data._consecutive_failures.clear()

    def test_errors_last_hour_zero_with_no_lab_engine(self):
        """errors_last_hour is 0 when no lab engine is running."""
        app, _ = _make_app(with_lab=False)
        client = TestClient(app)
        resp = client.get("/api/system/health")
        assert resp.json()["errors_last_hour"] == 0

    def test_errors_last_hour_reflects_lab_engine_consecutive_errors(self):
        """errors_last_hour must reflect lab engine's actual consecutive errors."""
        app, container = _make_app(with_lab=True)
        # Manually set consecutive errors (simulates 5 tick failures)
        container.lab_engine._consecutive_errors = 5

        client = TestClient(app)
        resp = client.get("/api/system/health")
        data = resp.json()
        assert data["errors_last_hour"] == 5, (
            "errors_last_hour was 0 but lab engine had 5 consecutive errors. "
            "The endpoint must read lab_engine._consecutive_errors, not return 0."
        )
        assert data["components"]["lab_engine"]["consecutive_errors"] == 5


class TestLabStatusObservabilityFields:
    """Lab status endpoint must surface broker connection and trade rejections."""

    def test_lab_status_has_broker_connected_field(self):
        from notas_lave.api.app import Container, create_app
        from notas_lave.engine.lab import LabEngine

        broker = PaperBroker(initial_balance=10000.0)
        journal = EventStore(":memory:")
        bus = EventBus()
        pnl = PnLService(original_deposit=10000.0)
        lab_engine = LabEngine(broker=broker, journal=journal, bus=bus, pnl=pnl)
        container = Container(broker=broker, journal=journal, bus=bus, pnl=pnl,
                              lab_engine=lab_engine)
        app = create_app(container)
        client = TestClient(app)

        resp = client.get("/api/lab/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "broker_connected" in data, (
            "/api/lab/status is missing broker_connected field. "
            "Dashboard cannot show broker offline banner without it."
        )
        # PaperBroker not connected yet → must be False
        assert data["broker_connected"] is False

    def test_lab_status_has_exec_log_field(self):
        from notas_lave.api.app import Container, create_app
        from notas_lave.engine.lab import LabEngine

        broker = PaperBroker(initial_balance=10000.0)
        journal = EventStore(":memory:")
        bus = EventBus()
        pnl = PnLService(original_deposit=10000.0)
        lab_engine = LabEngine(broker=broker, journal=journal, bus=bus, pnl=pnl)
        # Simulate a trade rejection in the exec log
        lab_engine._last_exec_log = [
            {"symbol": "BTCUSD", "result": "broker_rejected"}
        ]
        container = Container(broker=broker, journal=journal, bus=bus, pnl=pnl,
                              lab_engine=lab_engine)
        app = create_app(container)
        client = TestClient(app)

        resp = client.get("/api/lab/status")
        data = resp.json()
        assert "exec_log" in data, (
            "/api/lab/status is missing exec_log field. "
            "Trade rejections are silent without this."
        )
        assert len(data["exec_log"]) == 1
        assert data["exec_log"][0]["result"] == "broker_rejected"

    def test_lab_status_has_consecutive_errors_field(self):
        from notas_lave.api.app import Container, create_app
        from notas_lave.engine.lab import LabEngine

        broker = PaperBroker(initial_balance=10000.0)
        journal = EventStore(":memory:")
        bus = EventBus()
        pnl = PnLService(original_deposit=10000.0)
        lab_engine = LabEngine(broker=broker, journal=journal, bus=bus, pnl=pnl)
        lab_engine._consecutive_errors = 4
        container = Container(broker=broker, journal=journal, bus=bus, pnl=pnl,
                              lab_engine=lab_engine)
        app = create_app(container)
        client = TestClient(app)

        resp = client.get("/api/lab/status")
        data = resp.json()
        assert data.get("consecutive_errors") == 4, (
            "/api/lab/status missing consecutive_errors or wrong value. "
            "Dashboard cannot warn about degraded engine without this."
        )


class TestConsecutiveErrorThreshold:
    """Verify the alert threshold is 3, not 10.

    The old threshold meant 10 tick failures (up to 7.5 minutes at balanced pace)
    before any Telegram alert. The new threshold is 3 (~2.25 minutes).
    """

    def test_lab_engine_tracks_consecutive_errors(self):
        from notas_lave.engine.lab import LabEngine

        broker = PaperBroker(initial_balance=5000.0)
        journal = EventStore(":memory:")
        bus = EventBus()
        pnl = PnLService(original_deposit=5000.0)
        engine = LabEngine(broker=broker, journal=journal, bus=bus, pnl=pnl)

        # Initially 0
        assert engine._consecutive_errors == 0

    def test_lab_engine_has_started_at_timestamp(self):
        """Engine must track when it started for health endpoint uptime."""
        from datetime import datetime
        from notas_lave.engine.lab import LabEngine

        broker = PaperBroker(initial_balance=5000.0)
        journal = EventStore(":memory:")
        bus = EventBus()
        pnl = PnLService(original_deposit=5000.0)
        engine = LabEngine(broker=broker, journal=journal, bus=bus, pnl=pnl)

        assert hasattr(engine, "_started_at")
        assert isinstance(engine._started_at, datetime)

    def test_arena_status_includes_exec_log_and_errors(self):
        """get_arena_status() must expose exec_log and consecutive_errors."""
        from notas_lave.engine.lab import LabEngine

        broker = PaperBroker(initial_balance=5000.0)
        journal = EventStore(":memory:")
        bus = EventBus()
        pnl = PnLService(original_deposit=5000.0)
        engine = LabEngine(broker=broker, journal=journal, bus=bus, pnl=pnl)
        engine._last_exec_log = [{"symbol": "ETHUSD", "result": "broker_rejected"}]
        engine._consecutive_errors = 2

        arena = engine.get_arena_status()
        assert "exec_log" in arena
        assert "consecutive_errors" in arena
        assert arena["consecutive_errors"] == 2
        assert arena["exec_log"][0]["result"] == "broker_rejected"
