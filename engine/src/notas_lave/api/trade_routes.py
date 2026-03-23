"""Trade routes — balance, positions, P&L, trade execution."""

from fastapi import APIRouter, Depends

from .app import Container, get_container

router = APIRouter(prefix="/api")


@router.get("/trade/balance")
@router.get("/broker/balance")
async def get_balance(c: Container = Depends(get_container)):
    balance = await c.broker.get_balance()
    return {
        "total": balance.total,
        "available": balance.available,
        "currency": balance.currency,
    }


@router.get("/trade/positions")
@router.get("/broker/positions")
async def get_positions(c: Container = Depends(get_container)):
    positions = await c.broker.get_positions()
    return [
        {
            "symbol": p.symbol,
            "direction": p.direction.value,
            "quantity": p.quantity,
            "entry_price": p.entry_price,
            "current_price": p.current_price,
            "unrealized_pnl": p.unrealized_pnl,
        }
        for p in positions
    ]


@router.get("/trade/pnl")
async def get_pnl(c: Container = Depends(get_container)):
    balance = await c.broker.get_balance()
    result = c.pnl.calculate(current_balance=balance.total)
    return {
        "pnl": result.pnl,
        "pnl_pct": result.pnl_pct,
        "original_deposit": result.original_deposit,
        "current_balance": result.current_balance,
        "drawdown_from_peak": result.drawdown_from_peak,
        "drawdown_from_peak_pct": result.drawdown_from_peak_pct,
    }


@router.get("/trade/summary")
async def trade_summary(c: Container = Depends(get_container)):
    from ..journal.projections import trade_summary as _summary
    return _summary(c.journal)


@router.get("/trade/positions")
async def trade_positions(c: Container = Depends(get_container)):
    return c.journal.get_open_trades()


@router.get("/trade/history")
async def trade_history(c: Container = Depends(get_container)):
    return c.journal.get_closed_trades(limit=50)
