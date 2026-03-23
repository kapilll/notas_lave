"""Lab routes — lab engine status, trades, positions."""

from fastapi import APIRouter, Depends

from .app import Container, get_container

router = APIRouter(prefix="/api/lab")


@router.get("/status")
async def lab_status(c: Container = Depends(get_container)):
    if not c.lab_journal:
        return {"lab_available": False, "running": False}

    open_trades = c.lab_journal.get_open_trades()
    closed_trades = c.lab_journal.get_closed_trades(limit=1000)
    balance = await c.broker.get_balance()

    wins = [t for t in closed_trades if t.get("pnl", 0) > 0]

    return {
        "lab_available": True,
        "running": True,
        "open_trades": len(open_trades),
        "closed_trades": len(closed_trades),
        "balance": balance.total,
        "wins": len(wins),
        "losses": len(closed_trades) - len(wins),
        "win_rate": round(len(wins) / max(len(closed_trades), 1) * 100, 1),
    }


@router.get("/trades")
async def lab_trades(c: Container = Depends(get_container)):
    if not c.lab_journal:
        return []
    return c.lab_journal.get_closed_trades(limit=50)


@router.get("/positions")
async def lab_positions(c: Container = Depends(get_container)):
    if not c.lab_journal:
        return []
    return c.lab_journal.get_open_trades()


@router.get("/summary")
async def lab_summary(c: Container = Depends(get_container)):
    from ..journal.projections import trade_summary
    if not c.lab_journal:
        return {"total_trades": 0}
    return trade_summary(c.lab_journal)


@router.get("/strategies")
async def lab_strategies(c: Container = Depends(get_container)):
    from ..journal.projections import strategy_performance
    if not c.lab_journal:
        return {}
    return strategy_performance(c.lab_journal)
