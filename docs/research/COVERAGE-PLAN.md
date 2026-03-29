# Test Coverage Plan

> **Last updated:** 2026-03-29
> **Current:** 536 tests, 50.4% coverage (gate: 50%)
> **Target:** 80% coverage by Q3 2026

---

## Milestones

| Gate | Target date | What gets us there |
|------|-------------|-------------------|
| 50% ✅ | Q1 2026 (done) | Leaderboard, indicators, risk manager, property tests |
| 60% | Q2 2026 | Learning engine + lab.py arena loop |
| 70% | Q2 2026 | Delta broker + API routes + backtester |
| 80% | Q3 2026 | Market data + alerts + remaining strategy branches |

To raise the CI gate: edit `engine/pyproject.toml` `fail_under` and `pr-check.yml` `--cov-fail-under` in the same PR.

---

## Current coverage by module

### 100% (done — protect these)
- `core/errors.py`, `core/events.py`, `core/ports.py`
- `engine/pnl.py`, `engine/event_bus.py` (95%)
- `execution/paper.py`, `execution/registry.py`
- `journal/event_store.py`
- `observability/logging.py`, `log_config.py`
- `backtester/monte_carlo.py`

### 80-99% (minor gaps — quick wins)
| Module | Coverage | Uncovered | How to fix |
|--------|----------|-----------|------------|
| `risk/manager.py` | 82% | 38 lines | Consistency rule (prop mode), hedging rejection in prop mode, DB loading path |
| `data/economic_calendar.py` | 84% | 21 lines | Already have `get_blackout_status` tests — run them |
| `confluence/scorer.py` | 86% | 19 lines | `_save_learned_state`, HTF counter-trend block path |
| `strategies/williams_system.py` | 79% | 27 lines | Signal-generating candle patterns |
| `strategies/indicators.py` | 96% | 3 lines | Edge cases in stochastic/VWAP |
| `engine/leaderboard.py` | 97% | 5 lines | Corrupt JSON load path, save exception handler |

### 50-79% (medium effort, no mocking needed)
| Module | Coverage | Lines | Approach |
|--------|----------|-------|----------|
| `strategies/order_flow_system.py` | 50% | 78 | Craft candles that trigger order flow signals |
| `strategies/breakout_system.py` | 54% | 53 | S/R compression + volume breakout candles |
| `api/system_routes.py` | 45% | 40 | TestClient for `/api/scan/all`, `/api/prices` |
| `api/lab_routes.py` | 27% | 110 | TestClient with lab_engine in Container |
| `journal/database.py` | 67% | 98 | In-memory SQLite, test log_signal/close_trade/etc |
| `execution/coindcx.py` | 47% | 63 | Stub broker — no network needed |
| `execution/mt5.py` | 38% | 55 | Stub broker — test "not implemented" paths |
| `backtester/engine.py` | 44% | 300 | Walk-forward with synthetic candles |

### 0-49% (complex, needs mocking or async)
| Module | Coverage | Lines | Why hard | Approach |
|--------|----------|-------|----------|----------|
| `engine/lab.py` | 36% | 290 | Async arena tick loop, multiple broker calls | Mock broker + EventStore, test `_run_tick()` |
| `execution/delta.py` | 37% | 152 | HMAC auth + live HTTP | Mock `httpx.AsyncClient` |
| `learning/analyzer.py` | 0% | 240 | SQL queries on TradeLog | In-memory SQLAlchemy |
| `learning/recommendations.py` | 0% | 241 | Depends on analyzer | Same DB setup |
| `learning/accuracy.py` | 0% | 161 | PredictionLog queries | In-memory SQLAlchemy |
| `learning/optimizer.py` | 0% | 135 | Walk-forward on candles | Synthetic candles + in-memory DB |
| `learning/progress.py` | 0% | 122 | Reads from multiple sources | Temp directory + minimal DB |
| `learning/ab_testing.py` | 0% | 98 | ABTest/ABTestResult SQL | In-memory SQLAlchemy |
| `learning/claude_review.py` | 0% | 134 | Calls Claude API | Mock `anthropic.AsyncAnthropic` |

### External API (mock required)
| Module | Coverage | Lines | Mock target |
|--------|----------|-------|-------------|
| `data/market_data.py` | 0% | 402 | Mock CCXT exchange + TwelveData HTTP |
| `data/historical_downloader.py` | 0% | 153 | Mock yfinance/CCXT |
| `claude_engine/decision.py` | 0% | 111 | Mock Anthropic client |
| `alerts/telegram.py` | 0% | 70 | Mock `httpx.post` to Telegram API |
| `alerts/scanner.py` | 0% | 81 | Mock candle fetching |
| `monitoring/token_tracker.py` | 0% | 72 | In-memory DB (no network) |

---

## Execution order (when you pick this up)

### Batch 1 — Quick wins (~30 min, +3% coverage)
Files at 80-99% with small gaps. No mocking. Just cover the missing branches.

1. `risk/manager.py` — prop mode consistency rule test (need to monkeypatch `config.is_personal_mode = False`)
2. `leaderboard.py` — corrupt JSON load test, save exception test
3. `confluence/scorer.py` — test `_save_learned_state` via `update_regime_weights` with temp path
4. `strategies/williams_system.py` — craft downtrend + oversold %R candles

**Effort:** 1 session
**Add to:** `tests/test_risk_manager.py`, `tests/unit/test_leaderboard.py`, `tests/unit/test_confluence_scorer.py`

---

### Batch 2 — Learning engine (~2 hours, +8% coverage)
All pure Python logic, no network. Needs in-memory SQLAlchemy DB setup.

Create `tests/unit/test_learning.py` with:
- `analyze_overall()` — empty DB, populated DB
- `analyze_strategy_by_instrument()` — win/loss rows per strategy
- `recommend_strategy_blacklist()` — threshold logic (30 trades, <35% WR)
- `get_test_results()` — A vs B comparison, confidence levels
- `get_cost_summary()` — no data, runtime data, build data

**Key fixture needed:**
```python
@pytest.fixture
def db_with_trades():
    """Populate in-memory DB with synthetic TradeLog rows."""
    from notas_lave.journal.database import _init_db, get_db, TradeLog
    _init_db(db_key="test", db_path="sqlite:///:memory:")
    use_db("test")
    db = get_db()
    # Insert synthetic trades...
    yield db
```

**Effort:** 1-2 sessions
**Coverage gain:** ~8% (1068 lines across 7 learning files)

---

### Batch 3 — API routes (~1 hour, +3% coverage)
FastAPI TestClient, no network. Already have the `_make_app()` pattern.

Add to `tests/unit/test_v2_api.py`:
- `/api/scan/all` — returns list of instruments
- `/api/scan/{symbol}` — single instrument scan
- `/api/lab/risk` — risk status from lab routes
- `/api/lab/strategies` — strategy leaderboard via lab routes
- `/api/costs/summary` — token cost summary

**Effort:** 30 min

---

### Batch 4 — Broker stubs (~1 hour, +2% coverage)
CoinDCX and MT5 are stubs. Test "not implemented" error paths, registration, and the few methods that do work.

Add to `tests/unit/test_coindcx_mt5_brokers.py`.

---

### Batch 5 — Lab engine arena loop (~3 hours, +5% coverage)
The most important untested code — the actual trading logic.

```python
# Pattern: mock broker, run one tick
async def test_arena_tick_places_best_proposal():
    broker = PaperBroker(initial_balance=5000.0)
    await broker.connect()
    engine = LabEngine(broker=broker, ...)
    candles = _make_trending_candles(300)
    # Inject candles via mock market_data
    with patch("notas_lave.data.market_data.get_candles", return_value=candles):
        await engine._run_one_tick()
    # Assert proposal was evaluated
```

**Effort:** 2-3 sessions
**Coverage gain:** ~5%

---

### Batch 6 — Delta broker with HTTP mocking (~2 hours, +3% coverage)
```python
import respx  # or httpx_mock

async def test_get_balance():
    with respx.mock:
        respx.get("https://cdn-ind.testnet.deltaex.org/v2/wallet/balances").mock(
            return_value=httpx.Response(200, json={"result": [{"asset_id": 5, "balance": "100"}]})
        )
        broker = DeltaBroker(...)
        balance = await broker.get_balance()
        assert balance.total == 100.0
```

**Effort:** 1-2 sessions

---

### Batch 7 — External API mocking (~3 hours, +5% coverage)
Market data, Telegram, historical downloader. Use `unittest.mock.patch` on the HTTP clients.

---

## Rules for new tests

1. **Never weaken existing assertions** — `== 7.5` stays `== 7.5`, not `> 0`
2. **Financial precision** — use `pytest.approx(..., abs=0.01)`, not `abs=1.0`
3. **No network** — all tests must work offline (mock or in-memory)
4. **Mode-agnostic risk tests** — use values that exceed BOTH prop (5% DD) and personal (20% DD)
5. **Property tests stay LOCKED** — never change an assumption to make it pass; fix the code

---

## Coverage ratchet

The CI gate only goes up. Before merging any PR that adds coverage:

```bash
# Check current gate
grep fail_under engine/pyproject.toml

# After adding tests, if coverage is now at 55%:
# Update both:
# engine/pyproject.toml: fail_under = 55
# .github/workflows/pr-check.yml: --cov-fail-under=55
```
