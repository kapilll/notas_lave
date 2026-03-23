"""Lab routes — lab engine status, trades, positions.

Uses the lab_broker and lab_journal from the DI container.
If no lab dependencies are configured, returns empty/unavailable.
"""

from fastapi import APIRouter, Depends

from .app import Container, get_container

router = APIRouter(prefix="/api/v2/lab")


@router.get("/status")
async def lab_status(c: Container = Depends(get_container)):
    if not c.lab_journal:
        return {"lab_available": False}

    open_trades = c.lab_journal.get_open_trades()
    closed_trades = c.lab_journal.get_closed_trades(limit=1000)

    balance_info = None
    if c.lab_broker:
        try:
            balance_info = await c.lab_broker.get_balance()
        except Exception:
            pass

    return {
        "lab_available": True,
        "open_trades": len(open_trades),
        "closed_trades": len(closed_trades),
        "balance": balance_info.total if balance_info else 0,
    }


@router.get("/trades")
async def lab_trades(c: Container = Depends(get_container)):
    if not c.lab_journal:
        return []
    return c.lab_journal.get_closed_trades(limit=50)
