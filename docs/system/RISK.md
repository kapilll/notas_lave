# Risk Management

> Last verified against code: v2.0.16 (2026-03-30)

## Overview

`risk/manager.py` — the final gatekeeper before trade execution.
Two modes with different rule sets. Same core principle: protect capital.

Lab Engine calls `RiskManager.validate_trade()` before every trade (fixed in v1.0.0). Loss streak throttle halves risk after 3 consecutive losses (added in v1.1.0).

## Modes

### Prop Mode (FundingPips)
| Rule | Limit | Enforcement |
|------|-------|-------------|
| Daily drawdown | 5% of starting balance | HARD BLOCK |
| Total drawdown | 10% of ORIGINAL balance (static) | HARD BLOCK |
| Consistency | No single day > 45% of total profits | HARD BLOCK (when total > 1% of balance) |
| Risk per trade | 1% of current balance | HARD BLOCK |
| Max concurrent | 3 positions | HARD BLOCK |
| Min R:R | 2:1 | HARD BLOCK |
| News blackout | 5 min before/after HIGH impact events | HARD BLOCK |
| Hedging | No opposing positions on same symbol | HARD BLOCK |
| HFT check | Trades < 60s flagged | WARNING only |
| Inactivity | 30 days max without trading | WARNING at 25 days |

### Personal Mode (CoinDCX)
| Rule | Limit | Enforcement |
|------|-------|-------------|
| Daily drawdown | 6% (configurable) | HARD BLOCK |
| Total drawdown | 20% (configurable) | HARD BLOCK |
| Consistency | NOT enforced | — |
| Risk per trade | 2% (configurable) | HARD BLOCK |
| Max concurrent | 2 (configurable) | HARD BLOCK |
| Min R:R | 1.5:1 | HARD BLOCK |
| News blackout | Optional (default OFF) | — |
| Hedging | Warn but allow | WARNING only |

## Key Implementation Details

### Total Drawdown (RC-04)
```python
# STATIC from original balance — never changes
max_total_loss = self.original_starting_balance * self._max_total_dd
```
FundingPips measures from the ORIGINAL $100K, not from peak or current balance.

### Daily Drawdown Includes Unrealized (RC-03)
```python
current_equity_dd = today.realized_pnl + today.unrealized_pnl
```
FundingPips monitors EQUITY (balance + unrealized), not just closed P&L.

### Consistency Rule (RC-02/RC-22)
- Hard block at 100% of 45% threshold
- Soft warning at 80%
- Only enforced when `total_pnl > starting_balance * 0.01` (noise filter)

### Day Rollover (RC-12/RC-18)
On midnight UTC:
- Carry forward `open_positions` count from previous day
- Carry forward `unrealized_pnl` for equity tracking

### Position Sizing (data/instruments.py)
```python
def calculate_position_size(entry, stop_loss, balance, risk_pct, leverage):
    # Constraint 1: Risk budget
    lots_from_risk = risk_amount / (price_risk * contract_size)
    # Constraint 2: Margin requirement (with leverage)
    lots_from_margin = balance / (entry * contract_size / leverage) * 0.80
    # Take smaller, round to lot_step, clamp to min/max
    # QR-07: If min_lot > risk budget, REJECT (return 0)
```

**v2.0.13 rule:** Always pass `balance.available` (not `balance.total`) to `calculate_position_size()` in the proposal dry-run. Open positions lock up margin; total overstates what Delta will actually accept. Using total caused READY proposals to fail execution with "Insufficient Margin".

### Risk State Persistence (Fix #8)
```python
save_risk_state(starting_balance, current_balance, total_pnl, peak_balance)
load_risk_state()  # Called on startup
```
Stored in `risk_state` table in SQLAlchemy database.

## Economic Calendar (data/economic_calendar.py)

Programmatically generates US economic events:
- NFP (1st Friday, 8:30 AM ET)
- CPI (~13th, 8:30 AM ET)
- FOMC (3rd Wednesday of meeting months, 2:00 PM ET)
- GDP (last Thursday, 8:30 AM ET)
- Retail Sales (~15th, 8:30 AM ET)
- Jobless Claims (every Thursday, 8:30 AM ET)

**Timezone handling:** US Eastern with proper EST/EDT via `zoneinfo`.

## Rules

- **Risk Manager must be called before EVERY trade execution.** No exceptions.
- **`original_starting_balance` is set ONCE and NEVER modified.**
- **Daily drawdown = realized + unrealized.** Not just closed trades.
- **Total drawdown is STATIC from original balance.** Not trailing from peak.
- **News blackout is MANDATORY in prop mode.** Optional in personal.
- **Weight bounds (0.05–0.50)** prevent learning engine from extreme adjustments.
- **Max 3 blacklists per week** prevents learning engine from disabling everything.
- **Audit log every risk decision** — pass or reject, with full context.
- **Module-level `risk_manager` singleton removed** (CQ-04 partial fix). RiskManager is now instantiated per-context.
