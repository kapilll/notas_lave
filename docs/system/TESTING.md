# Testing Standards

> Last verified against code: v2.0.0 (2026-03-29)

## Current State

- **612 tests**, 49% coverage (CI gate at 49%, target 70% by Q3 2026)
- **Three-tier model:** Tier 1 (invariant/property) LOCKED, Tier 2 (integration) STABLE, Tier 3 (unit/) EVOLVING
- **Dev deps:** pytest, pytest-asyncio, pytest-cov, hypothesis, mutmut

## Test Structure

```
engine/tests/
├── conftest.py                          # DB redirect to :memory: (autouse)
├── test_calendar.py                     # Economic calendar
├── test_instruments.py                  # InstrumentSpec position sizing
├── test_risk_manager.py                 # Risk validation rules
├── test_startup.py                      # Startup smoke tests
├── test_strategies.py                   # All 6 composite strategies
├── test_trade_grader.py                 # Trade grading
├── unit/
│   ├── test_broker_registry.py
│   ├── test_delta_broker.py
│   ├── test_event_bus.py
│   ├── test_event_store.py
│   ├── test_events.py
│   ├── test_lab_engine.py
│   ├── test_models.py
│   ├── test_paper_broker.py
│   ├── test_pnl.py
│   ├── test_ports.py
│   ├── test_projections.py
│   ├── test_system_status.py            # Phase 1: error visibility tests
│   └── ...
├── integration/
│   ├── conftest.py                      # Broker fixture (BROKER env var)
│   ├── test_broker_contract.py          # IBroker protocol compliance
│   ├── test_error_visibility.py         # Phase 1: silent failures surface in API
│   ├── test_broker_reconciliation.py    # Phase 2: reconcile detects orphans, 2-tick safety
│   ├── test_trade_atomicity.py          # Phase 2: broker failure → clean journal
│   ├── test_websocket.py                # Phase 3: WS connect, subscribe, auth, broadcast
│   ├── test_ws_data_integrity.py        # Phase 3: WS data matches REST endpoints
│   └── test_end_to_end.py              # Phase 5: all layers agree simultaneously
├── invariant/
│   ├── test_pnl_integrity.py            # Profitable trades never recorded as $0
│   └── test_balance_reconciliation.py   # Leaderboard/journal/risk stay consistent
└── property/
    ├── conftest.py                      # Hypothesis CI profile (200 examples)
    ├── test_pnl_properties.py           # P&L math properties + contract_size
    ├── test_position_sizing.py          # Position size invariants
    ├── test_risk_properties.py          # Risk manager properties
    └── test_leaderboard_properties.py   # Trust score bounds, totals accounting
```

## Test Categories (pytest markers)

| Marker | Purpose | Speed |
|--------|---------|-------|
| `unit` | Fast isolated tests | < 1s each |
| `integration` | End-to-end flows (may need BROKER env) | Seconds |
| `invariant` | Critical accounting rules — LOCKED | < 1s each |
| `smoke` | Post-deploy health checks | Network-dependent |

## CI Enforcement

### PR Check (`pr-check.yml`)
```bash
pytest tests/ --cov=notas_lave --cov-fail-under=49 -x -q --tb=short
```
- Coverage gate: 49% minimum (ratchet: only goes up)
- `-x`: stop on first failure

### Deploy (`deploy.yml`)
Same tests run again before deploy (redundant safety).

## Testing Philosophy (Phase 2 rules)

1. **Never self-confirm**: Tests compare against BROKER truth (balance, positions, fills).
2. **No silent failures**: Every `try/except` that swallows an error must have a test proving the error surfaces.
3. **Property tests lock invariants**: Once a property passes, it's LOCKED. Future changes must satisfy it.
4. **Integration tests cross boundaries**: API response must match DB state. WS event must match REST response. Leaderboard must match TradeLog.
5. **Failure recovery tests**: Test broker failure, DB lock, network timeout — verify state is still consistent after.

## Fixtures (conftest.py)

```python
# Root conftest.py — autouse, redirects all DB to :memory:
@pytest.fixture(autouse=True)
def use_test_db():
    _init_db(db_key="default", db_path="sqlite:///:memory:")
    _init_db(db_key="lab", db_path="sqlite:///:memory:")
    yield
```

## Rules

- **Coverage gate is a ratchet** — only goes up: 49% → 60% → 70%.
- **Never skip tests silently.** > 3 skips = CI failure.
- **Invariant tests are sacred** — if one fails, the system is fundamentally broken.
- **Property tests use Hypothesis** — CI profile: 200 examples, 2s deadline.
- **Use `asyncio_mode = "auto"`** — no need for `@pytest.mark.asyncio`.
- **Use `:memory:` for test databases** — never touch real DB files in tests.
- **Isolate leaderboard in tests** — pass `persist_path=tmp_dir/test_leaderboard.json` to avoid shared disk state.
- **Tests must be deterministic** — no network calls, no time-dependent assertions.
