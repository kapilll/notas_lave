# Testing AI-Written Code — Research & Strategy

**Date:** 2026-03-27
**Context:** Notas Lave uses Claude to write most code. Need testing strategies that prevent circular validation (AI writes code + AI writes tests = tautological tests).

---

## The Core Problem

When Claude writes both code AND tests, you get **tautological tests** — tests that verify the function does what it does, without checking if what it does is *correct*.

Stats (2025-2026 research):
- 45% of AI-generated code contains security flaws (Veracode 2025)
- AI-authored PRs average 10.83 issues vs 6.45 for human code
- AI code is 2.74x more likely to introduce XSS vulnerabilities
- 59% of developers use AI-generated code they don't fully understand

---

## Testing Strategy for Notas Lave

### Layer 1: Human-Written Invariants (CRITICAL)

These encode domain knowledge about trading. Claude CAN'T fake these.

```python
# tests/invariant/ — the ground truth
def test_closed_trade_never_has_zero_pnl_when_price_moved(): ...
def test_balance_equals_deposit_plus_closed_pnl(): ...
def test_drawdown_never_negative(): ...
def test_pnl_sign_matches_direction(): ...
def test_position_size_never_exceeds_risk_budget(): ...
```

**Rule:** Every critical trading rule gets an invariant test BEFORE code is written.

### Layer 2: Property-Based Testing with Hypothesis

Instead of "given X, expect Y", define properties that must ALWAYS hold:

```python
from hypothesis import given
import hypothesis.strategies as st

@given(
    balance=st.floats(min_value=100, max_value=1_000_000),
    risk_pct=st.floats(min_value=0.001, max_value=0.05),
    stop_distance=st.floats(min_value=0.01, max_value=100)
)
def test_position_size_never_exceeds_risk(balance, risk_pct, stop_distance):
    size = calculate_position_size(balance, risk_pct, stop_distance)
    max_loss = size * stop_distance
    assert max_loss <= balance * risk_pct * 1.01  # 1% tolerance
```

Hypothesis generates hundreds of random inputs and finds edge cases.
Each property-based test finds **50x as many bugs** as a unit test (OOPSLA 2025).

### Layer 3: Unit Tests (Claude can write these)

Standard pytest tests for regressions and API contracts. Fine for Claude to write as *supplementary* coverage, but not the primary safety net.

### Layer 4: Mutation Testing with Mutmut

Answers: "Are my tests actually catching bugs?"

Deliberately introduces mutations (`>` to `>=`, `+` to `-`) and checks if tests catch them. If a mutant survives, tests are weak.

```bash
mutmut run --paths-to-mutate=src/notas_lave/engine/pnl.py
```

88.5% detection rate, 1200 mutants/min (PyCon 2025 benchmark).

### Layer 5: Integration Tests

Test against real broker APIs, not mocks. Already have `tests/integration/test_broker_contract.py`.

### Layer 6: Coverage Gate in CI

```yaml
pytest --cov=notas_lave --cov-fail-under=70
```

---

## Recommended Workflow: AI-TDD

1. **You** write failing tests (invariants, properties, specs)
2. **Claude** writes code to pass those tests
3. Tests run — binary pass/fail
4. Refactor

Tests become the *specification*, not a rubber stamp.

---

## What Hypothesis Does

Hypothesis is a **property-based testing** library. Instead of writing individual test cases:

```python
# Traditional: you pick specific inputs
def test_addition():
    assert add(2, 3) == 5
    assert add(-1, 1) == 0
    assert add(0, 0) == 0
```

You define a **property** (a rule that must always be true) and Hypothesis generates hundreds of random inputs:

```python
# Hypothesis: define the RULE, it finds the EDGE CASES
@given(st.integers(), st.integers())
def test_addition_commutative(a, b):
    assert add(a, b) == add(b, a)
```

### Why It's Perfect for Trading Systems

Trading has clear mathematical invariants:

| Property | Test |
|----------|------|
| Position size must never risk > X% | `size * stop_loss <= balance * risk_pct` |
| P&L sign must match direction | LONG + price_up = positive P&L |
| Leverage must not exceed limit | `notional / margin <= max_leverage` |
| Drawdown is never negative | `drawdown >= 0` always |
| Fee is always non-negative | `calculate_fee(amount) >= 0` |
| Liquidation price is between 0 and entry | For longs: `0 < liq_price < entry` |

### Strategies (Input Generators)

```python
import hypothesis.strategies as st

st.integers()                           # Any integer
st.floats(min_value=0.01, max_value=1e6)  # Bounded floats
st.sampled_from(["BTCUSDT", "ETHUSDT"])   # Pick from list
st.sampled_from(Direction)                # Pick from enum
st.builds(TradeSetup, ...)                # Build Pydantic models
st.lists(st.floats(), min_size=1)         # Lists of values
```

### Shrinking

When Hypothesis finds a failing input, it **shrinks** it to the simplest case that still fails. Instead of "fails with balance=847293.1847", you get "fails with balance=0.01".

### Integration with pytest

Hypothesis works as a pytest plugin. Just add `@given(...)` to any test:

```python
@given(candles=st.lists(st.builds(Candle, ...), min_size=5))
def test_strategy_never_crashes(candles):
    signal = my_strategy.analyze(candles)
    assert signal is None or 0 <= signal.score <= 100
```

---

## Trading-Specific Properties to Test

### Position Sizing
- `position_size(balance, risk, stop) * stop <= balance * risk` (never over-risks)
- `position_size >= 0` (never negative)
- `position_size == 0` when `stop_distance == 0` (no stop = no trade)
- Doubling balance doubles position size (linearity)

### P&L Calculation
- `pnl(LONG, entry, exit) == -pnl(SHORT, entry, exit)` (symmetry)
- `pnl(direction, price, price) == 0` (no movement = no P&L)
- `pnl(LONG, low, high) > 0` (long profits when price goes up)

### Risk Manager
- Rejected trade can't become accepted by retrying
- Max positions enforced regardless of trade quality
- Daily drawdown limit is hard (never breached)

### Instrument Registry
- Every instrument has a valid exchange symbol
- Pip value is always positive
- Min lot size is always positive
- `get_instrument(symbol).symbol == symbol` (round-trip)

---

## Dev Dependencies

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
    "pytest-cov>=5.0.0",
    "hypothesis>=6.100.0",
    "mutmut>=3.0.0",
]
```

---

## CI/CD Integration

```yaml
# In .github/workflows/deploy.yml
- name: Tests with coverage
  run: |
    python -m pytest tests/ \
      --cov=notas_lave \
      --cov-report=term-missing \
      --cov-fail-under=70 \
      -x -q --tb=short

- name: Detect skipped tests
  run: |
    SKIPPED=$(python -m pytest tests/ -v --no-header 2>&1 | grep -c "SKIPPED" || true)
    if [ "$SKIPPED" -gt 2 ]; then
      echo "::warning::$SKIPPED tests skipped"
    fi
```

---

## Anti-Patterns to Avoid

1. **Claude writes test + code in same session** — tests mirror implementation assumptions
2. **Mocking the database** — burned before (mock passed, prod migration failed)
3. **Testing implementation, not behavior** — "function called X" vs "result is correct"
4. **No coverage gate** — tests exist but cover nothing
5. **Trusting `pytest.skip()`** — silent test removal goes unnoticed
6. **Example-only tests** — miss edge cases that property tests catch

---

## Sources

- Anthropic: How Anthropic teams use Claude Code (2026)
- Claude Code Review launch (March 2026)
- Veracode: 45% of AI code has security flaws (2025)
- OOPSLA 2025: Property-based tests find 50x more mutations
- PyCon 2025: Mutmut benchmark on 50 repos
- Agentic Property-Based Testing (arXiv, October 2025)
- Augment Code: 8 Failure Patterns in AI Code (2025)
- Builder.io: TDD with AI (2025)
