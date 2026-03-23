"""Learning, journal, and cost routes."""

from fastapi import APIRouter, Depends, Query

from ..journal.projections import strategy_performance, trade_summary
from .app import Container, get_container

router = APIRouter(prefix="/api")


@router.get("/learning/summary")
async def learning_summary(c: Container = Depends(get_container)):
    return trade_summary(c.journal)


@router.get("/learning/strategies")
async def learning_strategies(c: Container = Depends(get_container)):
    return strategy_performance(c.journal)


@router.get("/journal/trades")
async def journal_trades(
    limit: int = Query(default=50),
    c: Container = Depends(get_container),
):
    return {"trades": c.journal.get_closed_trades(limit=limit)}


@router.get("/journal/performance")
async def journal_performance(c: Container = Depends(get_container)):
    perf = strategy_performance(c.journal)
    return {
        "strategies": [
            {
                "strategy": name,
                "wins": data["wins"],
                "losses": data["losses"],
                "total_trades": data["wins"] + data["losses"],
                "total_pnl": round(data["total_pnl"], 4),
                "win_rate": round(data["wins"] / max(data["wins"] + data["losses"], 1) * 100, 1),
            }
            for name, data in perf.items()
        ]
    }


@router.get("/costs/summary")
async def costs_summary():
    return {
        "total_runtime_cost": 0.0,
        "total_build_cost": 0.0,
        "total_cost": 0.0,
        "runtime_calls": 0,
        "currency": "USD",
    }
