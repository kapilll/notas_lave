"""Tests for v2 PnLService — balance minus deposit.

P&L = current_balance - original_deposit. That's it.
No running counters, no formula-based calculation.
The broker balance is the single source of truth.
"""

import pytest


def test_pnl_profit():
    from notas_lave.engine.pnl import PnLService

    svc = PnLService(original_deposit=5000.0)
    result = svc.calculate(current_balance=5500.0)
    assert result.pnl == 500.0
    assert result.pnl_pct == pytest.approx(10.0)


def test_pnl_loss():
    from notas_lave.engine.pnl import PnLService

    svc = PnLService(original_deposit=5000.0)
    result = svc.calculate(current_balance=4200.0)
    assert result.pnl == -800.0
    assert result.pnl_pct == pytest.approx(-16.0)


def test_pnl_breakeven():
    from notas_lave.engine.pnl import PnLService

    svc = PnLService(original_deposit=5000.0)
    result = svc.calculate(current_balance=5000.0)
    assert result.pnl == 0.0
    assert result.pnl_pct == 0.0


def test_pnl_zero_deposit():
    from notas_lave.engine.pnl import PnLService

    svc = PnLService(original_deposit=0.0)
    result = svc.calculate(current_balance=100.0)
    assert result.pnl == 100.0
    assert result.pnl_pct == 0.0  # Can't divide by zero


def test_pnl_result_has_all_fields():
    from notas_lave.engine.pnl import PnLService

    svc = PnLService(original_deposit=5000.0)
    result = svc.calculate(current_balance=5500.0)
    assert hasattr(result, 'pnl')
    assert hasattr(result, 'pnl_pct')
    assert hasattr(result, 'original_deposit')
    assert hasattr(result, 'current_balance')
    assert result.original_deposit == 5000.0
    assert result.current_balance == 5500.0


def test_pnl_drawdown_from_peak():
    from notas_lave.engine.pnl import PnLService

    svc = PnLService(original_deposit=5000.0)
    svc.update_peak(5800.0)
    result = svc.calculate(current_balance=5500.0)
    assert result.drawdown_from_peak == pytest.approx(300.0)
    assert result.drawdown_from_peak_pct == pytest.approx(300.0 / 5800.0 * 100)


def test_pnl_peak_tracks_highest():
    from notas_lave.engine.pnl import PnLService

    svc = PnLService(original_deposit=5000.0)
    svc.update_peak(5500.0)
    svc.update_peak(5800.0)
    svc.update_peak(5600.0)  # Lower — peak should stay at 5800
    result = svc.calculate(current_balance=5400.0)
    assert result.drawdown_from_peak == pytest.approx(400.0)
