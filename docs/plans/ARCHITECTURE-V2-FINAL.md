# Notas Lave v2 — Final Architecture (Expert Panel Review)

## Expert Panel Review

Six engineering experts reviewed the CODE-REFORM.md and ARCHITECTURE-V2.md
plans. Their critiques are below, followed by the unified final architecture.

---

### Panel 1: Trading Systems Architect (15yr quant, built systems at prop firms)

**What's good:**
- Broker abstraction with Protocol is exactly right. We use this at every firm.
- Event bus for decoupling is the standard pattern. NautilusTrader, aat, zipline all do this.

**What's missing:**

> "You have no concept of an ORDER LIFECYCLE. A trade isn't just open/close.
> It's: signal → order_pending → order_sent → order_acked → partially_filled →
> filled → position_open → sl_monitoring → close_sent → close_filled → settled.
> Each state transition is an event. Your current system jumps from signal to
> position with no intermediate states — that's why fills get lost."

> "Your IBroker.place_order returns OrderResult synchronously. Real exchanges
> are ASYNC — you send an order, get an ack, then get a fill later (maybe
> partial). You need an order state machine, not a request-response pattern."

> "Symbol mapping (BTCUSD → BTCUSDT) should be in the Instrument model, not
> scattered across broker code. Each instrument knows its exchange symbol."

**Additions needed:**
- `OrderStateMachine` — tracks order lifecycle with state transitions
- `InstrumentRegistry` — symbol mapping, tick sizes, contract specs per broker
- Separate `read` (get_positions, get_balance) from `write` (place_order) on IBroker
- Add `IBroker.get_order_status(order_id)` for async fill detection

---

### Panel 2: Python Software Engineer (SOLID, Clean Architecture, DI expert)

**What's good:**
- Protocol-based interfaces, dependency injection, no globals — textbook clean.
- The 500-line limit and file structure are practical.

**What's missing:**

> "The broker_factory uses match/case — that's still a modification point.
> Use a registry pattern: brokers register themselves, factory looks them up.
> Adding a new broker = creating a file, zero factory changes."

> "The event bus swallows exceptions silently. In trading, a failed event
> handler (e.g., failed to log trade to DB) is CRITICAL. You need event
> handler failure policies: retry, dead-letter, halt."

> "You're mixing Pydantic models (for validation) with dataclass events.
> Pick one. Use Pydantic for external boundaries (API, config, DB), use
> plain dataclasses or NamedTuples for internal events (faster, simpler)."

**Additions needed:**
- Registry pattern for brokers: `@register_broker("binance")`
- Event handler failure policy (retry with backoff, dead-letter queue)
- Clear separation: Pydantic = boundaries, dataclass = internal

---

### Panel 3: Data Engineer (pipelines, schema design, event sourcing)

**What's good:**
- Schema-first with Pydantic is correct.
- Single source of truth table is the most important thing in the doc.

**What's missing:**

> "You have no DATA VERSIONING. When you change a trade_log schema (add a
> column), what happens to existing data? You need migration support.
> Alembic for SQLAlchemy, or manual version tracking."

> "Your journal should be APPEND-ONLY. Never update a trade_log row. Instead:
> insert a new event row (TradeOpened, TradeClosed, TradeGraded). Reconstruct
> current state by replaying events. This gives you a complete audit trail
> and eliminates update bugs."

> "Balance-diff P&L is great but has a race condition: if two positions close
> within the 3-second wait window, their balance diffs overlap. Use the
> Binance income API as primary, balance-diff as verification."

**Additions needed:**
- Alembic for DB migrations
- Event-sourced trade journal (append-only events, not mutable rows)
- Document the race condition in balance-diff and the mitigation strategy
- Add `data_version` field to all stored records

---

### Panel 4: ML Engineer (feature stores, experiment tracking, model lifecycle)

**What's good:**
- Feature extraction exists. Trade grading is a good signal for learning.

**What's missing:**

> "You have no EXPERIMENT TRACKING. When you change a strategy parameter,
> how do you know if it improved performance? You need before/after comparison
> with statistical significance. Even a simple A/B log is better than nothing."

> "The learning engine should capture FEATURES at trade time, not reconstruct
> them later. Store the exact RSI, volume ratio, ATR, regime at the moment
> of the signal. These are your training features for XGBoost later."

> "Strategy weights should adapt based on a multi-armed bandit, not manual
> adjustment. Thompson Sampling or UCB1 for exploring which strategy works
> best on which instrument/regime combination."

**Additions needed:**
- Feature snapshot at signal time (stored with the trade)
- MLflow or simple experiment log for parameter changes
- Multi-armed bandit for strategy weight allocation
- Separate feature store table (trade_id → feature_vector)

---

### Panel 5: DevOps/SRE (reliability, deployment, observability)

**What's good:**
- Health endpoints exist. Telegram alerts work.

**What's missing:**

> "You have NO structured logging. Grep through 'notas_lave.log' is not
> observability. Use structlog with JSON output. Every log line should have:
> timestamp, level, component, trade_id (if applicable), and structured data."

> "Pre-commit hook running ALL tests is too slow. Run only UNIT tests on
> pre-commit (< 5 seconds). Run integration tests on CI or pre-push."

> "You need a GRACEFUL SHUTDOWN that actually works. Close all exchange
> positions, cancel pending orders, checkpoint state, THEN exit. Your current
> shutdown is a best-effort that fails silently."

> "Circuit breaker pattern for broker connections. After N failures, stop
> trying for M seconds. Your current code just retries forever."

**Additions needed:**
- structlog with JSON output
- Split pre-commit (unit only, < 5s) from CI (full suite)
- Graceful shutdown checklist (positions, orders, state, notifications)
- Circuit breaker with configurable thresholds

---

### Panel 6: AI-Assisted Development Expert (builds with Claude daily)

**What's good:**
- The "Design Rules for Claude" section is gold. Keep it in CLAUDE.md.
- TDD workflow is correct — this is the #1 practice for AI coding.

**What's missing:**

> "You need INVARIANT TESTS — tests that assert global properties, not just
> unit behavior. Example: 'the sum of all open position P&L plus closed
> trade P&L plus current balance must equal original_deposit + total_deposits'.
> Run these after EVERY change."

> "CLAUDE.md should have a DECISION LOG. When Claude makes an architectural
> choice (e.g., 'use balance-diff for P&L'), document WHY and what alternatives
> were rejected. Next session Claude won't re-explore rejected paths."

> "Each module needs a MODULE.md with: purpose (1 line), inputs, outputs,
> invariants, and 'things that will break if you change this'. This is
> Claude's map. Without it, Claude reads 500 lines to understand context."

> "The migration plan should be TESTABLE at each wave. After Wave 1, run
> invariant tests. After Wave 2, run broker integration tests. If a wave
> breaks invariants, STOP and fix before continuing."

**Additions needed:**
- Invariant tests (global property assertions)
- Decision log in CLAUDE.md
- MODULE.md per directory (purpose, inputs, outputs, invariants)
- Migration gates: each wave has acceptance tests that must pass

---

## Final Unified Architecture

Merging both documents plus all panel feedback.

---

## Core Principles (Non-Negotiable)

1. **Single Source of Truth.** Balance = broker. P&L = balance - deposit.
   Positions = broker + local health overlay. No running counters.

2. **Ports & Adapters.** Business logic depends on interfaces (ports.py).
   Brokers, data feeds, alerts are swappable adapters. Adding a new broker
   = one new file implementing IBroker. Zero changes elsewhere.

3. **Event-Driven Side Effects.** Engine publishes events (TradeOpened,
   TradeClosed). Subscribers react independently (Telegram, grading, DB
   logging). Adding a notification channel = subscribing to events.

4. **TDD Mandatory.** Every change starts with a failing test. Pre-commit
   runs unit tests (< 5s). Pre-push runs full suite. No exceptions.

5. **< 400 lines per file.** If longer, split. Claude needs full context.

6. **Pydantic at boundaries, dataclass internally.** API, config, DB =
   Pydantic (validated). Events, internal state = dataclass (fast).

7. **Append-only journal.** Never UPDATE a trade record. INSERT events
   (TradeOpened, TradeClosed, TradeGraded). Replay to reconstruct state.

---

## File Structure

```
engine/
├── pyproject.toml                 # deps, mypy, pytest, ruff config
│
├── src/notas_lave/
│   ├── core/                      # DOMAIN — pure logic, zero I/O
│   │   ├── models.py              #   Candle, Signal, TradeSetup, Position (Pydantic)
│   │   ├── events.py              #   Domain events (frozen dataclasses)
│   │   ├── ports.py               #   ALL Protocol interfaces
│   │   ├── errors.py              #   Domain exceptions
│   │   └── instruments.py         #   InstrumentRegistry: symbol mapping + specs
│   │
│   ├── strategy/                  # STRATEGIES — stateless, pluggable
│   │   ├── base.py                #   IStrategy protocol + helpers
│   │   ├── registry.py            #   Auto-discover + @register_strategy
│   │   ├── confluence.py          #   Multi-strategy scoring
│   │   ├── ema_crossover.py       #   < 150 lines each
│   │   ├── bollinger_bands.py
│   │   └── ... (12 strategies)
│   │
│   ├── execution/                 # BROKER ADAPTERS
│   │   ├── registry.py            #   @register_broker + create_broker()
│   │   ├── binance.py             #   BinanceBroker(IBroker)
│   │   ├── paper.py               #   PaperBroker(IBroker)
│   │   ├── coindcx.py             #   CoinDCXBroker(IBroker) — stub
│   │   ├── mt5.py                 #   MT5Broker(IBroker) — stub
│   │   └── tradingview.py         #   TVWebhookBroker(IBroker) — stub
│   │
│   ├── data/                      # MARKET DATA ADAPTERS
│   │   ├── registry.py            #   @register_provider + create_provider()
│   │   ├── binance_data.py        #   BinanceData(IDataProvider)
│   │   ├── twelve_data.py         #   TwelveData(IDataProvider)
│   │   └── csv_data.py            #   CSVData(IDataProvider)
│   │
│   ├── risk/                      # RISK — composable rules
│   │   ├── manager.py             #   RiskManager(IRiskManager)
│   │   ├── rules.py               #   Individual rule functions
│   │   └── lab_risk.py            #   LabRisk(IRiskManager) — permissive
│   │
│   ├── journal/                   # PERSISTENCE — event-sourced
│   │   ├── event_store.py         #   Append-only trade events
│   │   ├── projections.py         #   Rebuild state from events
│   │   ├── schemas.py             #   Pydantic models for DB tables
│   │   └── migrations.py          #   Schema versioning (Alembic lite)
│   │
│   ├── learning/                  # ML & LEARNING
│   │   ├── grader.py              #   Auto-grade A-F
│   │   ├── features.py            #   Feature extraction + snapshot
│   │   ├── analyzer.py            #   Performance analytics
│   │   ├── optimizer.py           #   Walk-forward optimization
│   │   ├── bandit.py              #   Multi-armed bandit for strategy weights
│   │   └── review.py              #   Claude-powered review
│   │
│   ├── engine/                    # ORCHESTRATION
│   │   ├── lab.py                 #   Lab engine (< 300 lines)
│   │   ├── production.py          #   Production engine (< 300 lines)
│   │   ├── event_bus.py           #   Pub/Sub with failure policies
│   │   ├── scheduler.py           #   Periodic tasks
│   │   └── pnl.py                 #   PnLService (balance - deposit)
│   │
│   ├── api/                       # HTTP — thin routes, no logic
│   │   ├── app.py                 #   FastAPI + lifespan + DI wiring
│   │   ├── lab_routes.py
│   │   ├── trade_routes.py
│   │   ├── learning_routes.py
│   │   └── system_routes.py
│   │
│   ├── alerts/                    # NOTIFICATIONS
│   │   ├── telegram.py            #   IAlerter implementation
│   │   └── webhook.py             #   Generic webhook
│   │
│   ├── observability/             # LOGGING & METRICS
│   │   ├── logging.py             #   structlog JSON setup
│   │   └── metrics.py             #   Key trading metrics
│   │
│   └── config.py                  # Pydantic Settings
│
├── tests/
│   ├── conftest.py                # In-memory DB, mock broker, fixtures
│   ├── unit/                      # < 5s total, pre-commit
│   │   ├── test_models.py
│   │   ├── test_grader.py
│   │   ├── test_strategies.py
│   │   ├── test_risk_rules.py
│   │   ├── test_confluence.py
│   │   ├── test_pnl.py
│   │   └── test_instruments.py
│   ├── integration/               # Full suite, pre-push
│   │   ├── test_trade_lifecycle.py
│   │   ├── test_event_bus.py
│   │   └── test_broker_adapters.py
│   ├── invariant/                 # Global property tests, every commit
│   │   ├── test_data_integrity.py
│   │   └── test_accounting.py     # balance + pnl + positions = deposit
│   └── smoke/                     # Manual, real exchange
│       └── test_binance_live.py
│
├── docs/
│   ├── decisions/                 # Decision log (WHY we chose X over Y)
│   │   ├── 001-balance-diff-pnl.md
│   │   ├── 002-event-bus-over-direct-calls.md
│   │   └── 003-protocol-over-abc.md
│   └── plans/
│       └── ARCHITECTURE-V2-FINAL.md  # This file
│
└── dashboard/                     # Next.js frontend
```

---

## Core Interfaces (ports.py)

```python
"""Ports — contracts that ALL adapters must implement.

Rules:
- Business logic imports ONLY from core/ (never from execution/, data/, etc.)
- Adding a new broker = implementing IBroker in a new file
- Adding a new data source = implementing IDataProvider in a new file
- ZERO changes to any existing file
"""

from typing import Protocol, runtime_checkable
from .models import (
    Candle, Signal, TradeSetup, OrderResult,
    BalanceInfo, ExchangePosition, Instrument,
)


@runtime_checkable
class IBroker(Protocol):
    """Exchange operations — read and write separated."""
    @property
    def name(self) -> str: ...
    @property
    def is_connected(self) -> bool: ...

    # Lifecycle
    async def connect(self) -> bool: ...
    async def disconnect(self) -> None: ...

    # Read (safe, no side effects)
    async def get_balance(self) -> BalanceInfo: ...
    async def get_positions(self) -> list[ExchangePosition]: ...
    async def get_order_status(self, order_id: str) -> OrderResult: ...

    # Write (side effects, requires caution)
    async def place_order(self, setup: TradeSetup) -> OrderResult: ...
    async def close_position(self, symbol: str) -> OrderResult: ...
    async def cancel_all_orders(self, symbol: str) -> bool: ...


@runtime_checkable
class IDataProvider(Protocol):
    """Market data — candles and prices."""
    async def get_candles(
        self, symbol: str, timeframe: str, limit: int = 250,
    ) -> list[Candle]: ...
    async def get_current_price(self, symbol: str) -> float: ...


@runtime_checkable
class IRiskManager(Protocol):
    """Pre-trade validation — decoupled from execution."""
    def check_trade(self, setup: TradeSetup) -> tuple[bool, list[str]]: ...


@runtime_checkable
class ITradeJournal(Protocol):
    """Append-only trade journal. Never updates — only inserts events."""
    def record_signal(self, signal: Signal) -> int: ...
    def record_open(self, trade_id: int, setup: TradeSetup) -> None: ...
    def record_close(self, trade_id: int, exit_price: float,
                     reason: str, pnl: float) -> None: ...
    def record_grade(self, trade_id: int, grade: str, lesson: str) -> None: ...
    def get_closed_trades(self, limit: int = 50) -> list[dict]: ...
    def get_open_trades(self) -> list[dict]: ...


@runtime_checkable
class IStrategy(Protocol):
    """Trading strategy — stateless, testable."""
    @property
    def name(self) -> str: ...
    @property
    def category(self) -> str: ...
    def analyze(self, candles: list[Candle], symbol: str) -> Signal: ...


@runtime_checkable
class IAlerter(Protocol):
    """Notification channel."""
    async def send(self, message: str) -> bool: ...
```

---

## Instrument Registry (instruments.py)

```python
"""Symbol mapping lives HERE, not scattered across broker code.

Each instrument knows its exchange symbols, tick sizes, contract specs.
Brokers ask the instrument for their symbol, not the other way around.
"""

@dataclass(frozen=True)
class Instrument:
    symbol: str           # Internal: "BTCUSD"
    name: str             # "Bitcoin / USD"
    contract_size: float  # 1.0 for crypto, 100.0 for gold
    pip_size: float
    spread_typical: float

    # Per-broker symbol mapping
    exchange_symbols: dict[str, str] = field(default_factory=dict)
    # e.g., {"binance": "BTCUSDT", "coindcx": "BTCINR", "mt5": "BTCUSD.raw"}

    tick_sizes: dict[str, float] = field(default_factory=dict)
    # e.g., {"binance": 0.10, "coindcx": 1.0}

    def exchange_symbol(self, broker: str) -> str:
        """Get the symbol this broker uses. Raises if not mapped."""
        sym = self.exchange_symbols.get(broker)
        if not sym:
            raise ValueError(f"{self.symbol} not available on {broker}")
        return sym


# Registry
INSTRUMENTS: dict[str, Instrument] = {
    "BTCUSD": Instrument(
        symbol="BTCUSD", name="Bitcoin/USD",
        contract_size=1.0, pip_size=0.01, spread_typical=0.5,
        exchange_symbols={"binance": "BTCUSDT", "coindcx": "BTCINR", "mt5": "BTCUSD"},
        tick_sizes={"binance": 0.10, "coindcx": 1.0},
    ),
    # ... more instruments
}
```

---

## Event Bus with Failure Policies

```python
"""Event bus with configurable failure handling.

CRITICAL events (DB logging) → retry 3x, then halt
OPTIONAL events (Telegram) → log error, continue
"""

class FailurePolicy(Enum):
    LOG_AND_CONTINUE = "log"       # For notifications
    RETRY_3X = "retry"             # For persistence
    HALT = "halt"                  # For critical invariants

class EventBus:
    def __init__(self):
        self._handlers: dict[type, list[tuple[Callable, FailurePolicy]]] = defaultdict(list)

    def subscribe(self, event_type: type, handler: Callable,
                  policy: FailurePolicy = FailurePolicy.LOG_AND_CONTINUE):
        self._handlers[event_type].append((handler, policy))

    async def publish(self, event: Any) -> None:
        for handler, policy in self._handlers.get(type(event), []):
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                if policy == FailurePolicy.HALT:
                    raise  # Bubble up — caller must handle
                elif policy == FailurePolicy.RETRY_3X:
                    await self._retry(handler, event, max_retries=3)
                else:
                    logger.error("Event handler %s failed: %s", handler.__name__, e)
```

---

## Invariant Tests (test_accounting.py)

```python
"""Global invariants that must ALWAYS hold. Run after every change.

If any of these fail, the system has a data integrity bug.
"""

def test_accounting_identity(broker, journal, config):
    """The fundamental accounting equation must hold:
    current_balance = original_deposit + sum(all_closed_pnl) + sum(unrealized_pnl)
    """
    balance = broker.get_balance().total
    deposit = config.original_deposit
    closed_pnl = sum(t.pnl for t in journal.get_closed_trades(limit=10000))
    unrealized = sum(p.unrealized_pnl for p in broker.get_positions())

    expected = deposit + closed_pnl + unrealized
    assert abs(balance - expected) < 1.0, (
        f"Accounting mismatch: balance={balance}, "
        f"expected={expected} (deposit={deposit} + closed={closed_pnl} + unrealized={unrealized})"
    )

def test_no_orphaned_positions(broker, journal):
    """Every broker position must have a journal entry. No ghosts."""
    exchange_symbols = {p.symbol for p in broker.get_positions()}
    journal_symbols = {t.symbol for t in journal.get_open_trades()}
    orphans = exchange_symbols - journal_symbols
    assert not orphans, f"Positions on exchange with no journal entry: {orphans}"

def test_no_ghost_journal_entries(broker, journal):
    """Every open journal entry must have a broker position. No ghosts."""
    exchange_symbols = {p.symbol for p in broker.get_positions()}
    journal_symbols = {t.symbol for t in journal.get_open_trades()}
    ghosts = journal_symbols - exchange_symbols
    assert not ghosts, f"Journal entries with no exchange position: {ghosts}"
```

---

## Migration Waves (with Gates)

Each wave has acceptance tests. If tests fail, STOP. Fix before continuing.

### Wave 1: Foundation + Tests (1 session)
Build the skeleton that everything plugs into.

- [ ] Create `core/models.py` — Pydantic models for all domain objects
- [ ] Create `core/ports.py` — all Protocol interfaces
- [ ] Create `core/events.py` — domain events
- [ ] Create `core/instruments.py` — InstrumentRegistry
- [ ] Create `engine/event_bus.py` — pub/sub with failure policies
- [ ] Create `engine/pnl.py` — PnLService (balance - deposit)
- [ ] Create `tests/invariant/test_accounting.py`
- [ ] Set up pre-commit: unit tests only (< 5s)
- [ ] Set up mypy strict on `core/` module

**Gate:** `core/` has 100% type coverage. Invariant tests defined.

### Wave 2: Broker Abstraction (1 session)
Make brokers swappable.

- [ ] Extract BinanceBroker from binance_testnet.py (implements IBroker)
- [ ] Extract PaperBroker from paper_trader.py (implements IBroker)
- [ ] Create broker registry + factory
- [ ] Move symbol mapping to InstrumentRegistry
- [ ] Lab engine uses IBroker — no direct Binance imports

**Gate:** `BROKER=paper pytest tests/integration/ -q` passes.
`BROKER=binance_testnet pytest tests/integration/ -q` passes.
Same tests, different broker, zero code changes.

### Wave 3: Event-Sourced Journal (1 session)
Eliminate mutable trade records.

- [ ] Create append-only event store (TradeOpened, TradeClosed, TradeGraded)
- [ ] Projections rebuild current state from events
- [ ] Migrate existing trade_logs to event format
- [ ] Feature snapshots stored with signals

**Gate:** Invariant tests pass. Replaying events produces same state.

### Wave 4: Split God Files (1 session)
Break server.py and lab_trader.py into focused modules.

- [ ] Split server.py → api/app.py + 4 route modules
- [ ] Split lab_trader.py → engine/lab.py + scheduler.py
- [ ] Each file < 400 lines
- [ ] All 38 use_db() calls replaced with DI

**Gate:** All existing endpoints return same responses. 0 regressions.

### Wave 5: Multi-Broker + Observability (1 session)
The payoff — add new brokers with zero business logic changes.

- [ ] Add CoinDCX adapter (implements IBroker)
- [ ] Add MT5 adapter stub (implements IBroker)
- [ ] Add TradingView webhook adapter
- [ ] Add structlog JSON logging
- [ ] Add structured metrics (trade latency, fill rate, P&L per strategy)

**Gate:** `BROKER=coindcx` works end-to-end (or fails clearly at the
broker level, never in business logic).

---

## Decision Log (Why We Chose X)

### D001: Balance-diff for P&L (over formula-based)
- **Chosen:** `pnl = binance_balance - original_deposit`
- **Rejected:** `(exit - entry) * size * contract - fees`
- **Why:** Formula misses funding fees, slippage, partial fills.
  Balance-diff captures everything.
- **Caveat:** Race condition with concurrent closes. Mitigate by
  serializing close operations or using income API as verification.

### D002: Event bus over direct function calls
- **Chosen:** `bus.publish(TradeClosed(...))` → subscribers react
- **Rejected:** `close_position(); grade_trade(); send_telegram(); update_db()`
- **Why:** Direct calls create coupling. Changing Telegram logic required
  editing execution code. With events, add/remove subscribers freely.

### D003: Protocol over ABC for interfaces
- **Chosen:** `class IBroker(Protocol):`
- **Rejected:** `class IBroker(ABC):`
- **Why:** Protocols support structural typing — existing classes satisfy
  the interface without inheriting from it. Better for gradual migration.

### D004: Append-only journal over mutable rows
- **Chosen:** Insert events (TradeOpened, TradeClosed, TradeGraded)
- **Rejected:** UPDATE trade_logs SET exit_price = ...
- **Why:** Mutable rows caused 3 bugs this session (wrong P&L written,
  grade overwritten, exit_price clobbered). Append-only is safer.

### D005: InstrumentRegistry over scattered SYMBOL_MAP
- **Chosen:** Centralized Instrument with per-broker symbol mapping
- **Rejected:** SYMBOL_MAP dict in each broker file
- **Why:** Adding a new instrument currently requires editing 3 files.
  With registry, edit 1 place.

---

## Rules for Claude (put in CLAUDE.md)

```markdown
## Architecture Rules (v2)

1. NEVER import from execution/, data/, or alerts/ in business logic.
   Import from core/ports.py only.

2. Every change starts with a FAILING TEST.
   Run: pytest tests/unit/ -x  (should fail)
   Then write code. Then: pytest tests/ -q  (all pass)

3. Events for side effects. Don't call telegram from execution.
   Publish an event: await bus.publish(TradeClosed(...))

4. Pydantic at boundaries, dataclass internally.
   API models = Pydantic. Events = frozen dataclass.

5. < 400 lines per file. Split if longer.

6. Single source of truth:
   - Balance → broker.get_balance()
   - P&L → balance - original_deposit
   - Positions → broker.get_positions()
   - Trade history → journal (append-only)

7. Symbol mapping lives in InstrumentRegistry, not in broker code.

8. No global mutable state. Pass dependencies via constructors.

9. Run invariant tests after every change:
   pytest tests/invariant/ -q
```

---

## Success Criteria

After v2 migration, ALL of these must be true:

1. **`BROKER=paper pytest tests/ -q` passes** — full suite with mock broker
2. **`BROKER=binance_testnet pytest tests/ -q` passes** — same tests, real broker
3. **Adding CoinDCX = 1 new file** — zero changes to engine, strategies, or API
4. **P&L matches Binance within $0.01** — by construction, not by sync
5. **No file > 400 lines** — Claude can hold full context
6. **Every trade has: strategy, grade, lesson, feature snapshot** — complete data
7. **Invariant tests catch any accounting bug** — before it reaches dashboard
8. **No "fix X, break Y"** — events decouple, tests catch, DI isolates

---

## References

### Trading Architecture
- [NautilusTrader](https://github.com/nautechsystems/nautilus_trader)
- [pysystemtrade](https://github.com/robcarver17/pysystemtrade)
- [CCXT](https://github.com/ccxt/ccxt)
- [AsyncAlgoTrading/aat](https://github.com/AsyncAlgoTrading/aat)

### Software Engineering
- [Cosmic Python](https://www.cosmicpython.com/) — Ports & Adapters, Events, DI
- [SOLID in Python](https://realpython.com/solid-principles-python/)
- [Pydantic Settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)

### Data Engineering
- [Event Sourcing for Trading](https://durgaanalytics.com/event_sourcing_audit_trading)
- [15 Data Engineering Best Practices](https://lakefs.io/blog/data-engineering-best-practices/)

### ML Engineering
- [MLflow](https://mlflow.org)
- [Feature Stores Guide](https://chalk.ai/blog/what-is-a-feature-store)
- [RL for Strategy Weights](https://www.mdpi.com/1999-4893/16/1/23)

### AI-Assisted Development
- [TDD for AI Collaboration](https://8thlight.com/insights/tdd-effective-ai-collaboration)
- [Claude Code Best Practices](https://github.com/shanraisshan/claude-code-best-practice)
- [rosmur Claude Code Guide](https://github.com/rosmur/claudecode-best-practices)
