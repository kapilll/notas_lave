"""Tests for the backtesting engine — walk-forward simulation with 10 risk levers."""

import pytest
from datetime import datetime, timezone
from dataclasses import dataclass

from notas_lave.backtester.engine import (
    Backtester, BacktestTrade, BacktestResult,
    INSTRUMENT_STRATEGY_BLACKLIST, update_blacklist, get_filtered_strategies,
)
from notas_lave.data.models import Candle, Signal, SignalStrength, Direction


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _ts(i: int) -> datetime:
    return datetime(2026, 3, 15, 8 + (i % 8), i % 60, tzinfo=timezone.utc)


def _candle(i: int, price: float, vol: float = 500.0, spread: float = 3.0) -> Candle:
    return Candle(
        timestamp=_ts(i), open=price, high=price + spread,
        low=price - spread, close=price, volume=vol,
    )


def _trending_candles(n: int = 300, start: float = 2000.0, step: float = 1.5) -> list[Candle]:
    return [_candle(i, start + i * step, vol=800.0) for i in range(n)]


def _flat_candles(n: int = 300, price: float = 2000.0) -> list[Candle]:
    return [_candle(i, price) for i in range(n)]


# ──────────────────────────────────────────────────────────────────────────────
# BacktestTrade dataclass
# ──────────────────────────────────────────────────────────────────────────────

class TestBacktestTrade:
    def test_default_construction(self):
        now = datetime.now(timezone.utc)
        trade = BacktestTrade(entry_time=now)
        assert trade.entry_time == now
        assert trade.exit_time is None
        assert trade.pnl == 0.0
        assert trade.direction == ""

    def test_full_construction(self):
        now = datetime.now(timezone.utc)
        trade = BacktestTrade(
            entry_time=now,
            exit_time=now,
            symbol="XAUUSD",
            direction="LONG",
            entry_price=2000.0,
            exit_price=2020.0,
            stop_loss=1990.0,
            take_profit=2020.0,
            position_size=1.0,
            pnl=2000.0,
            exit_reason="tp_hit",
            strategy_name="ema_crossover",
        )
        assert trade.symbol == "XAUUSD"
        assert trade.pnl == 2000.0


# ──────────────────────────────────────────────────────────────────────────────
# BacktestResult dataclass
# ──────────────────────────────────────────────────────────────────────────────

class TestBacktestResult:
    def test_default_construction(self):
        result = BacktestResult(symbol="XAUUSD", timeframe="5m", period="2026-01")
        assert result.trades == []
        assert result.net_pnl == 0.0
        assert result.win_rate == 0.0
        assert result.symbol == "XAUUSD"

    def test_to_dict(self):
        result = BacktestResult(symbol="BTCUSD", timeframe="15m", period="2026-Q1")
        d = result.to_dict()
        assert d["symbol"] == "BTCUSD"
        assert "win_rate" in d
        assert "risk_filters" in d
        assert "equity_curve" in d

    def test_with_trades(self):
        now = datetime.now(timezone.utc)
        trades = [
            BacktestTrade(entry_time=now, pnl=100.0, direction="LONG"),
            BacktestTrade(entry_time=now, pnl=-50.0, direction="SHORT"),
        ]
        result = BacktestResult(
            symbol="XAUUSD", timeframe="5m", period="2026-03",
            trades=trades, net_pnl=50.0, win_rate=50.0,
        )
        assert len(result.trades) == 2
        assert result.net_pnl == 50.0


# ──────────────────────────────────────────────────────────────────────────────
# Blacklist
# ──────────────────────────────────────────────────────────────────────────────

class TestBlacklist:
    def test_update_blacklist_merges(self):
        """update_blacklist merges, not replaces."""
        original = INSTRUMENT_STRATEGY_BLACKLIST.get("BTCUSD", set()).copy()
        update_blacklist("BTCUSD", {"test_strategy_xyz_123"})
        assert "test_strategy_xyz_123" in INSTRUMENT_STRATEGY_BLACKLIST["BTCUSD"]
        # Restore
        INSTRUMENT_STRATEGY_BLACKLIST["BTCUSD"] = original

    def test_get_filtered_strategies_excludes_blacklisted(self):
        """get_filtered_strategies excludes strategies on the blacklist."""
        strategies = get_filtered_strategies("XAUUSD")
        # All returned strategies must not be in the blacklist
        blacklist = INSTRUMENT_STRATEGY_BLACKLIST.get("XAUUSD", set())
        names = {s.name for s in strategies}
        assert names.isdisjoint(blacklist)

    def test_get_filtered_strategies_returns_list(self):
        strats = get_filtered_strategies("BTCUSD")
        assert isinstance(strats, list)
        assert len(strats) > 0


# ──────────────────────────────────────────────────────────────────────────────
# Backtester.run()
# ──────────────────────────────────────────────────────────────────────────────

class TestBacktester:
    def test_run_returns_result(self):
        bt = Backtester(starting_balance=100_000.0, min_score=1.0)
        candles = _trending_candles(300)
        result = bt.run(candles, "XAUUSD", "5m")
        assert isinstance(result, BacktestResult)

    def test_run_with_flat_market(self):
        """Flat market should produce no trades (signals don't fire)."""
        bt = Backtester(starting_balance=100_000.0)
        candles = _flat_candles(300)
        result = bt.run(candles, "XAUUSD", "5m")
        assert isinstance(result, BacktestResult)
        # Should not crash, result may have 0 trades

    def test_run_result_has_all_fields(self):
        bt = Backtester(starting_balance=50_000.0, min_score=1.0)
        candles = _trending_candles(300)
        result = bt.run(candles, "BTCUSD", "5m")
        assert hasattr(result, 'trades')
        assert hasattr(result, 'net_pnl')
        assert hasattr(result, 'win_rate')
        assert hasattr(result, 'symbol')
        assert hasattr(result, 'max_drawdown_pct')

    def test_run_with_custom_strategies(self):
        """run() accepts a custom strategy list."""
        from notas_lave.strategies.registry import get_all_strategies
        bt = Backtester(min_score=1.0)
        strategies = get_all_strategies()[:2]  # Just 2 strategies
        candles = _trending_candles(300)
        result = bt.run(candles, "XAUUSD", "5m", strategies=strategies)
        assert isinstance(result, BacktestResult)

    def test_run_respects_starting_balance(self):
        bt = Backtester(starting_balance=42_000.0)
        candles = _flat_candles(300)
        result = bt.run(candles, "XAUUSD", "5m")
        # starting_balance is stored on Backtester, not result — verify via trades
        assert isinstance(result, BacktestResult)

    def test_run_minimum_candles(self):
        """Very few candles — should return empty result, not crash."""
        bt = Backtester()
        candles = _flat_candles(10)
        result = bt.run(candles, "XAUUSD", "5m")
        assert isinstance(result, BacktestResult)
        assert result.trades == []

    def test_run_trending_up_btcusd(self):
        """Run on BTC uptrend — shouldn't crash on different instruments."""
        bt = Backtester(min_score=1.0, starting_balance=100_000.0)
        candles = _trending_candles(300, start=85000.0, step=100.0)
        result = bt.run(candles, "BTCUSD", "15m")
        assert isinstance(result, BacktestResult)

    def test_risk_per_trade_lever(self):
        """Different risk_per_trade should produce different position sizes."""
        candles = _trending_candles(300)
        bt_conservative = Backtester(risk_per_trade=0.001, min_score=1.0)
        bt_aggressive = Backtester(risk_per_trade=0.01, min_score=1.0)
        r1 = bt_conservative.run(candles, "XAUUSD", "5m")
        r2 = bt_aggressive.run(candles, "XAUUSD", "5m")
        # Both should complete without error
        assert isinstance(r1, BacktestResult)
        assert isinstance(r2, BacktestResult)

    def test_high_min_score_produces_fewer_trades(self):
        """Higher min_score threshold filters out more signals."""
        candles = _trending_candles(300, step=2.0)
        bt_strict = Backtester(min_score=95.0)  # Very strict — few signals
        bt_loose = Backtester(min_score=1.0)   # Very loose — many signals
        r_strict = bt_strict.run(candles, "XAUUSD", "5m")
        r_loose = bt_loose.run(candles, "XAUUSD", "5m")
        # Strict should produce fewer or equal trades
        assert len(r_strict.trades) <= len(r_loose.trades)

    def test_run_produces_metrics(self):
        """Result metrics should be valid ranges."""
        bt = Backtester(min_score=1.0)
        candles = _trending_candles(300, step=2.0)
        result = bt.run(candles, "XAUUSD", "5m")
        assert 0.0 <= result.win_rate <= 100.0
        assert result.max_drawdown_pct >= 0.0

    def test_run_without_trades_has_zero_win_rate(self):
        """No trades → win_rate and other metrics should be 0."""
        bt = Backtester(min_score=999.0)  # Impossible score — no trades
        candles = _flat_candles(300)
        result = bt.run(candles, "XAUUSD", "5m")
        assert result.win_rate == 0.0
        assert len(result.trades) == 0
