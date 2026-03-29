"""Backtest routes — arena backtesting, walk-forward validation, trust seeding."""

import logging

from fastapi import APIRouter, Depends, Query

from .app import Container, get_container

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/backtest")


@router.post("/arena/{symbol}")
async def run_arena_backtest(
    symbol: str,
    timeframe: str = Query(default="15m"),
    days: int = Query(default=90, ge=7, le=365),
    seed_trust: bool = Query(default=False),
    c: Container = Depends(get_container),
):
    """Run arena-mode backtest: all 6 strategies compete, best arena_score wins.

    Optionally seed trust scores if Monte Carlo validation passes.
    """
    from ..data.market_data import MarketDataService
    from ..backtester.engine import Backtester
    from ..backtester.monte_carlo import run_monte_carlo
    from ..engine.leaderboard import StrategyLeaderboard
    from ..data.instruments import get_instrument

    spec = get_instrument(symbol)
    market_data = MarketDataService()
    candles = await market_data.get_historical_candles(symbol, timeframe, limit=days * 96)

    if not candles or len(candles) < 300:
        return {"error": f"Insufficient data for {symbol}: {len(candles) if candles else 0} candles"}

    leaderboard = StrategyLeaderboard()
    bt = Backtester(
        arena_mode=True,
        leaderboard=leaderboard,
        leverage=spec.max_leverage,
        risk_per_trade=0.05,
    )

    result = bt.run(candles, symbol, timeframe)

    response = {
        "symbol": symbol,
        "timeframe": timeframe,
        "period": result.period,
        "total_trades": result.total_trades,
        "wins": result.wins,
        "losses": result.losses,
        "win_rate": round(result.win_rate, 1),
        "net_pnl": round(result.net_pnl, 2),
        "profit_factor": round(result.profit_factor, 2),
        "max_drawdown_pct": round(result.max_drawdown_pct, 1),
        "sharpe_ratio": round(result.sharpe_ratio, 2),
        "strategy_stats": result.strategy_stats,
    }

    if seed_trust and result.trades:
        mc = run_monte_carlo(result.trades, starting_balance=bt.starting_balance)
        response["monte_carlo"] = {
            "is_robust": mc.get("is_robust", False),
            "edge_significant": mc.get("edge_significant", False),
            "probability_of_ruin_pct": mc.get("probability_of_ruin_pct"),
            "p_value": mc.get("p_value"),
            "summary": mc.get("summary"),
        }

        if mc.get("is_robust") and mc.get("edge_significant"):
            seeded = leaderboard.seed_from_backtest(result)
            response["trust_seeded"] = seeded
            response["seed_status"] = "seeded"
        else:
            response["seed_status"] = "rejected"
            response["seed_reason"] = (
                "Monte Carlo validation failed: "
                f"robust={mc.get('is_robust')}, "
                f"edge_significant={mc.get('edge_significant')}"
            )

    return response


@router.post("/walk-forward/{symbol}")
async def run_walk_forward(
    symbol: str,
    timeframe: str = Query(default="15m"),
    days: int = Query(default=180, ge=30, le=730),
    folds: int = Query(default=5, ge=2, le=10),
    c: Container = Depends(get_container),
):
    """N-fold walk-forward validation with arena mode."""
    from ..data.market_data import MarketDataService
    from ..backtester.engine import Backtester
    from ..engine.leaderboard import StrategyLeaderboard
    from ..data.instruments import get_instrument

    spec = get_instrument(symbol)
    market_data = MarketDataService()
    candles = await market_data.get_historical_candles(symbol, timeframe, limit=days * 96)

    if not candles or len(candles) < 300:
        return {"error": f"Insufficient data for {symbol}: {len(candles) if candles else 0} candles"}

    fold_size = len(candles) // folds
    fold_results = []

    for fold in range(folds):
        start = fold * fold_size
        end = start + fold_size if fold < folds - 1 else len(candles)
        fold_candles = candles[start:end]

        if len(fold_candles) < 300:
            continue

        bt = Backtester(
            arena_mode=True,
            leaderboard=StrategyLeaderboard(),
            leverage=spec.max_leverage,
            risk_per_trade=0.05,
        )
        result = bt.run(fold_candles, symbol, timeframe)
        fold_results.append({
            "fold": fold + 1,
            "period": result.period,
            "trades": result.total_trades,
            "win_rate": round(result.win_rate, 1),
            "net_pnl": round(result.net_pnl, 2),
            "profit_factor": round(result.profit_factor, 2),
            "max_drawdown_pct": round(result.max_drawdown_pct, 1),
            "strategy_stats": result.strategy_stats,
        })

    profitable_folds = sum(1 for f in fold_results if f["net_pnl"] > 0)

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "folds": len(fold_results),
        "profitable_folds": profitable_folds,
        "consistency": round(profitable_folds / max(len(fold_results), 1) * 100, 1),
        "results": fold_results,
    }


@router.get("/leaderboard")
async def get_leaderboard(c: Container = Depends(get_container)):
    """Show current trust scores (seeded vs default)."""
    from ..engine.leaderboard import StrategyLeaderboard

    leaderboard = StrategyLeaderboard()
    records = leaderboard.get_leaderboard()

    return {
        "strategies": records,
        "total": len(records),
        "active": sum(1 for r in records if r.get("status") != "suspended"),
        "suspended": sum(1 for r in records if r.get("status") == "suspended"),
    }
