# Notas Lave v2 — Production Architecture

**Goal:** A codebase where Claude can safely make changes, multiple brokers
plug in without code changes, and every number is verifiably correct.

**Principles applied:** SOLID, Event-Driven Architecture, Ports & Adapters,
TDD, Schema-First, Single Source of Truth, Dependency Injection.

---

## Target File Structure

```
engine/
├── pyproject.toml              # Single config: deps, mypy, pytest, ruff
├── src/
│   └── notas_lave/
│       ├── __init__.py
│       │
│       ├── core/               # DOMAIN — pure logic, zero I/O
│       │   ├── models.py       # Candle, Signal, Position, Trade (Pydantic)
│       │   ├── events.py       # Domain events (SignalGenerated, OrderFilled, etc.)
│       │   ├── ports.py        # ALL interfaces (Protocol classes)
│       │   └── errors.py       # Domain exceptions
│       │
│       ├── strategy/           # STRATEGIES — pluggable, stateless
│       │   ├── base.py         # StrategyProtocol
│       │   ├── registry.py     # Auto-discover + instantiate strategies
│       │   ├── ema_crossover.py
│       │   ├── bollinger_bands.py
│       │   ├── ...             # One file per strategy (< 150 lines each)
│       │   └── confluence.py   # Multi-strategy scorer
│       │
│       ├── execution/          # ADAPTERS — broker implementations
│       │   ├── broker_factory.py   # Creates correct broker from config
│       │   ├── binance.py          # Binance adapter (implements IBroker)
│       │   ├── coindcx.py          # CoinDCX adapter (implements IBroker)
│       │   ├── mt5.py              # MetaTrader5 adapter (implements IBroker)
│       │   ├── tradingview.py      # TradingView webhook adapter
│       │   └── paper.py            # Paper trading adapter (implements IBroker)
│       │
│       ├── data/               # MARKET DATA — multi-source
│       │   ├── provider_factory.py # Creates data provider from config
│       │   ├── binance_ws.py       # WebSocket stream (implements IDataProvider)
│       │   ├── twelve_data.py      # REST polling (implements IDataProvider)
│       │   ├── csv_loader.py       # Historical CSV (implements IDataProvider)
│       │   └── instruments.py      # Symbol specs, contract sizes, tick sizes
│       │
│       ├── risk/               # RISK — pre-trade validation
│       │   ├── manager.py      # RiskManager (implements IRiskManager)
│       │   ├── rules.py        # Individual risk rules (composable)
│       │   └── lab_risk.py     # Permissive lab risk (inherits manager)
│       │
│       ├── journal/            # PERSISTENCE — append-only trade log
│       │   ├── trade_log.py    # Event-sourced trade journal
│       │   ├── schemas.py      # Pydantic models for all DB tables
│       │   └── migrations.py   # Schema versioning
│       │
│       ├── learning/           # ML & LEARNING — experiment tracking
│       │   ├── grader.py       # Auto-grade trades (A-F)
│       │   ├── analyzer.py     # Performance analytics
│       │   ├── optimizer.py    # Walk-forward parameter optimization
│       │   ├── features.py     # Feature extraction for ML
│       │   └── review.py       # Claude-powered periodic review
│       │
│       ├── engine/             # ORCHESTRATION — ties everything together
│       │   ├── lab.py          # Lab engine (< 300 lines)
│       │   ├── production.py   # Production engine (< 300 lines)
│       │   ├── event_bus.py    # Pub/Sub message bus
│       │   └── scheduler.py   # Periodic tasks (heartbeat, backtest, review)
│       │
│       ├── api/                # HTTP LAYER — thin, no business logic
│       │   ├── app.py          # FastAPI app + lifespan
│       │   ├── lab_routes.py   # /api/lab/* endpoints
│       │   ├── trade_routes.py # /api/trade/* endpoints
│       │   ├── data_routes.py  # /api/data/*, /api/candles/*
│       │   └── system_routes.py # /api/health, /api/costs
│       │
│       ├── alerts/             # NOTIFICATIONS
│       │   ├── telegram.py     # Telegram adapter (implements IAlerter)
│       │   └── webhook.py      # Generic webhook adapter
│       │
│       └── config.py           # Pydantic Settings (env + YAML)
│
├── tests/
│   ├── conftest.py             # Test DB, mock broker, fixtures
│   ├── unit/                   # Pure logic tests (no I/O)
│   │   ├── test_models.py
│   │   ├── test_grader.py
│   │   ├── test_strategies.py
│   │   ├── test_risk_rules.py
│   │   └── test_confluence.py
│   ├── integration/            # Components together (mock exchange)
│   │   ├── test_trade_lifecycle.py
│   │   ├── test_position_sync.py
│   │   └── test_event_bus.py
│   └── smoke/                  # Real API calls (manual)
│       └── test_binance_live.py
│
└── dashboard/                  # Next.js (unchanged structure)
```

---

## Core Interfaces (ports.py)

Every component depends on these interfaces, never on implementations.
This is what makes multi-broker support work without code changes.

```python
"""Core interfaces — the CONTRACTS between components.

Every module depends on these Protocols, never on concrete classes.
Adding a new broker = implementing IBroker. Adding a new data source
= implementing IDataProvider. No other code changes needed.
"""

from typing import Protocol, runtime_checkable
from .models import (
    Candle, Signal, Position, Trade, TradeSetup,
    OrderResult, BalanceInfo, ExchangePosition,
)


# ═══════════════════════════════════════════════════
# BROKER — exchange operations
# ═══════════════════════════════════════════════════

@runtime_checkable
class IBroker(Protocol):
    """Anything that can execute trades.

    Implementations: BinanceBroker, CoinDCXBroker, MT5Broker, PaperBroker
    """
    @property
    def name(self) -> str: ...
    @property
    def is_connected(self) -> bool: ...

    async def connect(self) -> bool: ...
    async def disconnect(self) -> None: ...
    async def get_balance(self) -> BalanceInfo: ...
    async def get_positions(self) -> list[ExchangePosition]: ...
    async def place_order(self, setup: TradeSetup) -> OrderResult: ...
    async def close_position(self, symbol: str) -> OrderResult: ...
    async def cancel_all_orders(self, symbol: str) -> bool: ...


# ═══════════════════════════════════════════════════
# MARKET DATA — price feeds
# ═══════════════════════════════════════════════════

@runtime_checkable
class IDataProvider(Protocol):
    """Anything that provides candle data.

    Implementations: BinanceWebSocket, TwelveDataREST, CSVLoader
    """
    async def get_candles(
        self, symbol: str, timeframe: str, limit: int = 250,
    ) -> list[Candle]: ...

    async def get_current_price(self, symbol: str) -> float: ...


# ═══════════════════════════════════════════════════
# RISK — pre-trade validation
# ═══════════════════════════════════════════════════

@runtime_checkable
class IRiskManager(Protocol):
    """Validates trades before execution.

    Implementations: ProductionRisk (strict), LabRisk (permissive)
    """
    def check_trade(self, setup: TradeSetup) -> tuple[bool, list[str]]: ...
    def record_result(self, pnl: float) -> None: ...


# ═══════════════════════════════════════════════════
# TRADE JOURNAL — persistence
# ═══════════════════════════════════════════════════

@runtime_checkable
class ITradeLog(Protocol):
    """Append-only trade journal.

    Single source of truth for all trade history.
    """
    def log_signal(self, signal: Signal) -> int: ...
    def open_trade(self, trade: Trade) -> int: ...
    def close_trade(self, trade_id: int, result: TradeResult) -> None: ...
    def get_closed_trades(self, limit: int = 50) -> list[Trade]: ...
    def get_open_trades(self) -> list[Trade]: ...


# ═══════════════════════════════════════════════════
# STRATEGY — signal generation
# ═══════════════════════════════════════════════════

@runtime_checkable
class IStrategy(Protocol):
    """A trading strategy that analyzes candles and produces signals."""
    @property
    def name(self) -> str: ...
    def analyze(self, candles: list[Candle], symbol: str) -> Signal: ...


# ═══════════════════════════════════════════════════
# ALERTER — notifications
# ═══════════════════════════════════════════════════

@runtime_checkable
class IAlerter(Protocol):
    """Sends notifications (Telegram, email, webhook)."""
    async def send(self, message: str) -> bool: ...
```

---

## Domain Events (events.py)

Components communicate through events, not direct calls.
This is what prevents "fix X, break Y" — components don't know about each other.

```python
"""Domain events — decouple components via publish/subscribe.

Instead of:  lab_trader → paper_trader → risk_manager → telegram → DB
Do:          lab_trader publishes TradeOpened → bus notifies all subscribers

Adding a new side effect (e.g., Discord alerts) = subscribing to events.
No existing code changes needed.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class SignalGenerated:
    symbol: str
    timeframe: str
    strategy: str
    direction: str
    score: float
    entry: float
    stop_loss: float
    take_profit: float
    regime: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class TradeOpened:
    trade_id: int
    symbol: str
    direction: str
    entry_price: float
    stop_loss: float
    take_profit: float
    position_size: float
    strategy: str
    broker: str  # "binance", "paper", "mt5"


@dataclass(frozen=True)
class TradeClosed:
    trade_id: int
    symbol: str
    direction: str
    entry_price: float
    exit_price: float
    pnl: float
    exit_reason: str
    duration_seconds: int
    strategy: str
    grade: str      # A/B/C/D/F
    lesson: str


@dataclass(frozen=True)
class BalanceChanged:
    old_balance: float
    new_balance: float
    reason: str  # "trade_closed", "deposit", "sync"


@dataclass(frozen=True)
class IntegrityCheckFailed:
    check_name: str
    expected: str
    actual: str
    details: str
```

---

## Event Bus (event_bus.py)

```python
"""Simple in-process event bus — pub/sub for domain events.

Usage:
    bus = EventBus()
    bus.subscribe(TradeOpened, telegram.on_trade_opened)
    bus.subscribe(TradeOpened, journal.on_trade_opened)
    bus.subscribe(TradeClosed, grader.on_trade_closed)

    # Somewhere in execution code:
    bus.publish(TradeOpened(trade_id=1, symbol="BTCUSD", ...))
    # → telegram and journal both notified, independently
"""

import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable

logger = logging.getLogger(__name__)


class EventBus:
    def __init__(self):
        self._handlers: dict[type, list[Callable]] = defaultdict(list)

    def subscribe(self, event_type: type, handler: Callable) -> None:
        self._handlers[event_type].append(handler)

    async def publish(self, event: Any) -> None:
        for handler in self._handlers.get(type(event), []):
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error("Event handler error: %s on %s: %s",
                            handler.__name__, type(event).__name__, e)
```

---

## Broker Factory (broker_factory.py)

```python
"""Create the right broker from config — no if/elif chains in business logic."""

from ..core.ports import IBroker
from ..config import Settings


def create_broker(settings: Settings) -> IBroker:
    """Factory: config determines which broker, business logic doesn't care."""
    match settings.broker:
        case "binance_testnet":
            from .binance import BinanceBroker
            return BinanceBroker(
                api_key=settings.binance_key,
                api_secret=settings.binance_secret,
                testnet=True,
            )
        case "binance":
            from .binance import BinanceBroker
            return BinanceBroker(
                api_key=settings.binance_key,
                api_secret=settings.binance_secret,
                testnet=False,
            )
        case "coindcx":
            from .coindcx import CoinDCXBroker
            return CoinDCXBroker(
                api_key=settings.coindcx_key,
                api_secret=settings.coindcx_secret,
            )
        case "mt5":
            from .mt5 import MT5Broker
            return MT5Broker(
                login=settings.mt5_login,
                password=settings.mt5_password,
                server=settings.mt5_server,
            )
        case "paper" | _:
            from .paper import PaperBroker
            return PaperBroker(starting_balance=settings.paper_balance)
```

---

## Lab Engine (< 300 lines)

```python
"""Lab Engine — aggressive trading for learning.

ONLY orchestration. No business logic. Delegates everything:
- Scanning → strategies via confluence scorer
- Execution → broker via IBroker
- Risk → risk_manager via IRiskManager
- Persistence → journal via ITradeLog
- Notifications → alerter via IAlerter
- Side effects → event bus (grading, learning, heartbeats)
"""

class LabEngine:
    def __init__(
        self,
        broker: IBroker,
        data: IDataProvider,
        risk: IRiskManager,
        journal: ITradeLog,
        bus: EventBus,
        config: LabConfig,
    ):
        self.broker = broker
        self.data = data
        self.risk = risk
        self.journal = journal
        self.bus = bus
        self.config = config
        self._running = False

    async def start(self):
        self._running = True
        while self._running:
            await self._scan_and_trade()
            await asyncio.sleep(self.config.scan_interval)

    async def _scan_and_trade(self):
        for symbol in self.config.instruments:
            for tf in self.config.timeframes:
                candles = await self.data.get_candles(symbol, tf)
                if not candles:
                    continue

                signal = self._evaluate(candles, symbol, tf)
                if not signal:
                    continue

                ok, reasons = self.risk.check_trade(signal)
                if not ok:
                    continue

                result = await self.broker.place_order(signal)
                if result.filled:
                    trade_id = self.journal.open_trade(...)
                    await self.bus.publish(TradeOpened(...))

    async def _check_positions(self):
        """Positions come from BROKER (source of truth)."""
        positions = await self.broker.get_positions()
        # Compare with journal, detect closes, publish events
        ...
```

---

## Single Source of Truth — P&L

```python
"""P&L is NEVER a running counter. It's a FACT computed from Binance balance.

    total_pnl = current_binance_balance - original_deposit

That's it. No sync. No drift. No reset. Just subtraction.
"""

class PnLService:
    def __init__(self, broker: IBroker, original_deposit: float):
        self.broker = broker
        self.deposit = original_deposit

    async def get_total_pnl(self) -> float:
        balance = await self.broker.get_balance()
        return balance.total - self.deposit

    async def get_unrealized_pnl(self) -> float:
        positions = await self.broker.get_positions()
        return sum(p.unrealized_pnl for p in positions)
```

---

## TDD Workflow — Mandatory for Every Change

```
1. WRITE THE FAILING TEST
   pytest tests/unit/test_new_feature.py -x  # Should FAIL

2. WRITE MINIMUM CODE TO PASS
   # Only touch the ONE file that needs changing

3. RUN ALL TESTS
   pytest tests/ -q  # ALL must pass, not just the new one

4. COMMIT
   git add <specific files> && git commit
```

**Pre-commit hook (enforced):**
```bash
#!/bin/sh
# .git/hooks/pre-commit
python -m pytest tests/unit/ -q --tb=short || exit 1
python -m mypy src/notas_lave/ --strict --ignore-missing-imports || exit 1
```

---

## Migration Path (Incremental)

### Wave 1: Foundation (Next Session)
- [ ] Create `core/ports.py` with all Protocol interfaces
- [ ] Create `core/events.py` with domain events
- [ ] Create `core/models.py` with Pydantic models
- [ ] Create `engine/event_bus.py`
- [ ] Add pre-commit hook (pytest + mypy)
- [ ] Write integration test: full trade lifecycle

### Wave 2: Extract Broker (After Wave 1)
- [ ] Implement `IBroker` for Binance (extract from binance_testnet.py)
- [ ] Implement `IBroker` for Paper (extract from paper_trader.py)
- [ ] Create `broker_factory.py`
- [ ] Lab engine uses `IBroker` — no direct Binance imports

### Wave 3: Extract P&L + Position Manager (After Wave 2)
- [ ] Create `PnLService` — delete all running counters
- [ ] Positions always read from broker, overlay local health data
- [ ] Remove 38 `use_db()` calls — use DI instead

### Wave 4: Split God Files (After Wave 3)
- [ ] Split server.py into route modules
- [ ] Split lab_trader.py into engine + monitor + learning
- [ ] Each file < 500 lines

### Wave 5: Multi-Broker Ready (After Wave 4)
- [ ] Add CoinDCX adapter
- [ ] Add MT5 adapter stub
- [ ] Add TradingView webhook adapter
- [ ] Config switch: `BROKER=coindcx` → uses CoinDCX, zero code changes

---

## Design Rules for Claude

1. **One file, one job.** If a file does two things, split it.
2. **Depend on ports.py, never on implementations.** Import `IBroker`, not `BinanceBroker`.
3. **Test first.** No PR without a failing test that the code fixes.
4. **Events for side effects.** Don't call telegram from execution code. Publish an event.
5. **Pydantic at all boundaries.** API input/output, config, DB models — all Pydantic.
6. **No mutable global state.** Pass dependencies through constructors.
7. **< 500 lines per file.** If longer, it's doing too much.
8. **Single source of truth.** Balance = Binance. P&L = balance - deposit. Positions = broker.

---

## References

- [NautilusTrader](https://github.com/nautechsystems/nautilus_trader) — event-driven, multi-venue, Rust+Python
- [Cosmic Python](https://www.cosmicpython.com/) — Ports & Adapters, event bus, DI in Python
- [CCXT](https://github.com/ccxt/ccxt) — unified broker interface for 120+ exchanges
- [pysystemtrade](https://github.com/robcarver17/pysystemtrade) — production systematic trading
- [TDD as Protocol for AI Collaboration](https://8thlight.com/insights/tdd-effective-ai-collaboration)
- [SOLID Principles in Python](https://realpython.com/solid-principles-python/)
- [Event Sourcing for Trading](https://durgaanalytics.com/event_sourcing_audit_trading)
