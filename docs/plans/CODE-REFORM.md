# Code Reform Plan — Making Notas Lave AI-Friendly

## The Problem

Every fix creates new bugs. This session alone: fixed P&L → broke positions →
fixed positions → broke P&L counter → fixed counter → hardcoded values appeared →
fixed those → ghost positions appeared → fixed ghosts → broker disconnected.

**Root cause: the codebase violates every principle that makes AI-assisted
development work.** The research is clear on what those principles are.

---

## What's Wrong (Specific Anti-Patterns)

### 1. God Files (2000+ lines each)
```
server.py:      2,343 lines — 60+ endpoints, business logic mixed in
lab_trader.py:  2,172 lines — scanning, trading, grading, learning, heartbeats
paper_trader.py:  873 lines — position tracking + close logic + P&L calc
```
**Impact:** Claude can't hold the full context. Changes in one function break
another function 800 lines away because they share implicit state.

### 2. Shared Mutable State Everywhere
- `_lab_trader` global in server.py — accessed by 20+ endpoints
- `paper_trader` singleton — shared between production and imports
- `use_db()` ContextVar — 38 call sites, each a potential wrong-DB bug
- `risk_manager` — mutated by paper_trader, lab_trader, and API endpoints
- `_broker` — reconnection state shared across all operations

**Impact:** Any function can silently modify state that another function
relies on. Impossible to reason about or test in isolation.

### 3. No Contracts Between Components
- `_check_closed_positions()` does: close exchange, wait, query balance,
  compute P&L, grade trade, update DB, update risk manager, check learning
  triggers — **7 concerns in one function**
- `open_position()` does: validate SL/TP, apply spread, compute margin,
  log to DB, update risk manager — **5 concerns**
- No interfaces, no type contracts, no dependency injection

**Impact:** Can't change one concern without touching all others. Can't
test one concern without mocking all others.

### 4. Multiple Sources of Truth
- Position P&L: Binance API, paper_trader formula, DB record, risk_manager counter
- Balance: Binance wallet, risk_manager.current_balance, lab_risk_state.json
- Open positions: Binance, paper_trader.positions dict, trade_logs WHERE exit IS NULL
- Starting balance: config, lab_config, risk_state JSON, hardcoded 4999.98

**Impact:** They ALWAYS drift. Every "fix" is choosing which source to trust
and patching the others. The next change re-introduces the drift.

### 5. No Test Isolation
- Tests wrote to production DB (fixed with conftest.py this session)
- No mocking of exchange connections
- Tests don't cover the integration paths that actually break
- 126 unit tests but 0 integration tests

---

## The Reform (Applying Research)

### Principle 1: Single Source of Truth — Eliminate Drift

**Rule: Every piece of data has ONE canonical source. Everything else reads from it.**

| Data | Source of Truth | Everything Else |
|------|----------------|-----------------|
| Balance | Binance API | Read-only cache in memory |
| Open Positions | Binance API | Local overlay for SL/TP/health only |
| P&L | `binance_balance - original_deposit` | No running counters |
| Closed Trade P&L | Balance-diff on close | Stored in DB, never recalculated |
| Trade History | Lab DB `trade_logs` | API reads from DB |
| Strategy Config | `lab_config.py` | No runtime overrides |

**Implementation:**
- Delete `risk_manager.total_pnl` running counter
- Delete `risk_manager.current_balance` — always read from Binance
- Remove `_save_risk_state` / `_load_risk_state` — no longer needed
- P&L endpoint = one line: `binance_balance - original_deposit`

### Principle 2: Small, Focused Modules — One File, One Job

**Rule: No file over 500 lines. Each module has a clear, single responsibility.**

```
BEFORE (2 god files):
  server.py (2343 lines) — everything
  lab_trader.py (2172 lines) — everything else

AFTER (focused modules):
  api/
    lab_routes.py        — Lab endpoints only
    trade_routes.py      — Trading endpoints only
    learning_routes.py   — Learning/review endpoints
    broker_routes.py     — Broker status endpoints

  lab/
    lab_engine.py        — Scan loop + trade execution (< 300 lines)
    lab_monitor.py       — Position monitoring + health checks
    lab_learning.py      — Grading, lessons, reviews, check-ins

  execution/
    position_manager.py  — Open/close/track positions (replaces paper_trader)
    exchange_client.py   — Binance API wrapper (read-only queries)
    order_executor.py    — Place/cancel orders (write operations)
```

### Principle 3: Contract-Driven Development — Define Before Code

**Rule: Every module has a typed interface. Changes that break the contract fail tests.**

```python
# Example: PositionManager contract
class IPositionManager(Protocol):
    def open(self, setup: TradeSetup) -> Position: ...
    def close(self, position_id: str, reason: str) -> ClosedTrade: ...
    def get_open(self) -> list[Position]: ...
    def get_exchange_positions(self) -> list[ExchangePosition]: ...

# Example: P&L contract
class IPnLCalculator(Protocol):
    def get_total_pnl(self) -> float: ...  # Always: binance_balance - deposit
    def get_trade_pnl(self, trade_id: int) -> float: ...  # From DB
    def get_unrealized_pnl(self) -> float: ...  # From Binance positions
```

### Principle 4: TDD — Tests First, Code Second

**Rule: Write the test BEFORE the fix. If you can't write a test for it,
you don't understand the bug.**

**Workflow for every change:**
1. Write a failing test that demonstrates the bug
2. Run it — confirm it fails
3. Write the minimum code to make it pass
4. Run ALL tests — confirm nothing else broke
5. Commit

**Test categories needed:**
```
tests/
  unit/                    — Pure logic, no I/O
    test_pnl_calculator.py
    test_trade_grader.py
    test_position_validation.py
    test_strategy_signals.py

  integration/             — Components together, mocked exchange
    test_trade_lifecycle.py     — open → monitor → close → grade
    test_position_sync.py       — Binance ↔ local sync
    test_learning_pipeline.py   — trade → grade → lesson → review

  smoke/                   — Real API calls (run manually)
    test_binance_connection.py
    test_full_trade_cycle.py
```

### Principle 5: Dependency Injection — No Globals

**Rule: Components receive their dependencies, never import globals.**

```python
# BEFORE (tight coupling, untestable):
class LabTrader:
    def __init__(self):
        self.paper_trader = PaperTrader()  # Creates its own
        self._broker = None                # Manages its own connection

# AFTER (loose coupling, testable):
class LabEngine:
    def __init__(self,
                 exchange: IExchangeClient,
                 position_mgr: IPositionManager,
                 trade_log: ITradeLog,
                 config: LabConfig):
        self.exchange = exchange
        self.positions = position_mgr
        self.log = trade_log
        self.config = config
```

### Principle 6: CLAUDE.md as Living Contract

**Rule: CLAUDE.md answers: "What would break if I change this?"**

Structure:
1. **Architecture diagram** — which module talks to which
2. **Data flow** — where each piece of data comes from
3. **Invariants** — rules that must ALWAYS hold (e.g., "P&L = balance - deposit")
4. **Test commands** — how to verify changes
5. **Known traps** — things that look safe but aren't

---

## Migration Plan (Incremental, Not Big Bang)

### Phase 1: Test Foundation (Do First)
- [ ] Add integration tests for the trade lifecycle
- [ ] Add regression tests for every bug fixed this session
- [ ] Set up pre-commit hook: `pytest engine/tests/ -q`
- [ ] Every future change: test FIRST, code SECOND

### Phase 2: Extract P&L Module
- [ ] Create `engine/src/pnl/calculator.py` — single source of truth
- [ ] Delete all P&L calculation from paper_trader, lab_trader, server.py
- [ ] All endpoints call `pnl.get_total()`, `pnl.get_trade(id)`
- [ ] Test: P&L never drifts from Binance

### Phase 3: Extract Position Manager
- [ ] Create `engine/src/execution/position_manager.py`
- [ ] Single dict of positions, single DB table, single Binance query
- [ ] Delete `paper_trader.positions`, `_reload_open_positions`, sync endpoints
- [ ] Test: position count always matches Binance

### Phase 4: Split God Files
- [ ] Split server.py into route modules (lab, trading, learning, broker)
- [ ] Split lab_trader.py into engine, monitor, learning
- [ ] Each file < 500 lines
- [ ] Test: all endpoints still work

### Phase 5: Dependency Injection
- [ ] Add Protocol interfaces for exchange, positions, P&L
- [ ] Inject dependencies in constructors
- [ ] Delete all global singletons
- [ ] Test: components work with mock dependencies

---

## Success Criteria

After reform, this should be true:
1. `pytest` catches any bug BEFORE it reaches production
2. Changing one module NEVER breaks another
3. P&L always matches Binance (by construction, not by sync)
4. Claude can make a change in one file without reading 5 others
5. No more "fix X, break Y" cycles
