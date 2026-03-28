# Testing Standards

> Last verified against code: v1.1.0 (2026-03-28)

## Current State

- **247 tests**, 36% coverage (CI gate at 35%)
- **9 untested modules:** confluence, learning/*, backtester, alerts
- **Dev deps:** pytest, pytest-asyncio, pytest-cov, hypothesis, mutmut

## Test Structure

```
engine/tests/
├── conftest.py              # Shared fixtures
├── test_calendar.py         # Economic calendar
├── test_instruments.py      # InstrumentSpec position sizing
├── test_risk_manager.py     # Risk validation rules
├── test_startup.py          # Startup smoke tests (validates config, broker registry, imports)
├── test_strategies.py       # All 12 strategies
├── test_trade_grader.py     # Trade grading
├── unit/
│   ├── test_broker_registry.py
│   ├── test_coindcx_mt5_brokers.py
│   ├── test_delta_broker.py
│   ├── test_event_bus.py
│   ├── test_event_store.py
│   ├── test_events.py
│   ├── test_lab_engine.py
│   ├── test_models.py
│   ├── test_observability.py
│   ├── test_paper_broker.py
│   ├── test_pnl.py
│   ├── test_ports.py
│   ├── test_projections.py
│   ├── test_scheduler.py
│   ├── test_strategy_bridge.py
│   ├── test_v2_api.py
│   └── test_v2_instruments.py
├── integration/
│   ├── conftest.py
│   └── test_broker_contract.py
└── invariant/
    ├── test_accounting.py
    └── test_pnl_integrity.py
```

## Test Categories (pytest markers)

| Marker | Purpose | Speed |
|--------|---------|-------|
| `unit` | Fast isolated tests | < 1s each |
| `integration` | Broker integration (needs BROKER env) | Seconds |
| `invariant` | Critical accounting rules | < 1s each |
| `smoke` | Post-deploy health checks | Depends on network |

## CI Enforcement

### PR Check (`pr-check.yml`)
```bash
pytest tests/ --cov=notas_lave --cov-fail-under=35 -x -q --tb=short
```
- Coverage gate: 35% minimum
- Skip detection: > 3 skipped tests = failure
- `-x`: stop on first failure

### Deploy (`deploy.yml`)
Same tests run again before deploy (redundant safety).

## Testing Philosophy

From `docs/research/TESTING-AI-CODE.md`:
- **Human writes invariants/property tests** — critical rules that must always hold
- **Claude writes unit tests** — covering implementation details
- **Hypothesis** for property-based testing of trading math (position sizing, P&L)
- **mutmut** for mutation testing to verify test quality

## Fixtures (conftest.py)

```python
@pytest.fixture
def sample_candles():     # 250 realistic candles
@pytest.fixture
def config():             # TradingConfig with test defaults
@pytest.fixture
def paper_broker():       # PaperBroker(initial_balance=10000)
@pytest.fixture
def event_store():        # EventStore(":memory:")
```

## Rules

- **Coverage gate is a ratchet** — only goes up: 35% → 50% → 70%.
- **Never skip tests silently.** > 3 skips = CI failure.
- **Integration tests need `BROKER` env var** — don't run in CI by default.
- **Invariant tests are sacred** — if one fails, the system is fundamentally broken.
- **Use `asyncio_mode = "auto"`** — no need for `@pytest.mark.asyncio`.
- **Use `:memory:` for test databases** — never touch real DB files in tests.
- **Tests must be deterministic** — no network calls, no time-dependent assertions.
- **If you remove a broker/strategy/config field, add a startup test** that validates the system still starts. The v1.0.0 deploy failure happened because tests passed in CI but the VM's .env had a removed broker. `tests/test_startup.py` prevents this.
- **`pythonpath = ["src"]`** in `pyproject.toml` — tests import `from notas_lave.X`.
