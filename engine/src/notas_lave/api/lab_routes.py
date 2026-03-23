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
        return {"trades": []}
    trades = c.lab_journal.get_closed_trades(limit=50)
    return {"trades": trades}


@router.get("/positions")
async def lab_positions(c: Container = Depends(get_container)):
    if not c.lab_journal:
        return {"positions": []}
    return {"positions": c.lab_journal.get_open_trades()}


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
        return {"strategies": []}
    perf = strategy_performance(c.lab_journal)
    return {
        "strategies": [
            {
                "strategy": name,
                "wins": data["wins"],
                "losses": data["losses"],
                "trades": data["wins"] + data["losses"],
                "total_pnl": round(data["total_pnl"], 4),
                "win_rate": round(data["wins"] / max(data["wins"] + data["losses"], 1) * 100, 1),
            }
            for name, data in perf.items()
        ]
    }


@router.get("/risk")
async def lab_risk(c: Container = Depends(get_container)):
    balance = await c.broker.get_balance()
    pnl = c.pnl.calculate(balance.total)
    open_trades = c.journal.get_open_trades()
    return {
        "balance": balance.total,
        "current_balance": balance.total,
        "original_deposit": pnl.original_deposit,
        "total_pnl": round(pnl.pnl, 2),
        "total_pnl_pct": round(pnl.pnl_pct, 2),
        "daily_pnl": 0,
        "daily_drawdown_used_pct": 0,
        "total_drawdown_used_pct": round(pnl.drawdown_from_peak_pct, 2),
        "trades_today": 0,
        "open_positions": len(open_trades),
        "is_halted": False,
        "can_trade": True,
        "max_daily_trades": 30,
        "max_concurrent": 5,
    }


@router.get("/markets")
async def lab_markets(c: Container = Depends(get_container)):
    from ..data.market_data import market_data

    instruments = [
        "BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD", "BNBUSD", "DOGEUSD",
        "ADAUSD", "AVAXUSD", "LINKUSD", "DOTUSD", "LTCUSD", "NEARUSD",
        "SUIUSD", "ARBUSD", "PEPEUSD", "WIFUSD", "FTMUSD", "ATOMUSD",
    ]
    results = []
    for sym in instruments:
        try:
            candles = await market_data.get_candles(sym, "1m", limit=1)
            price = candles[-1].close if candles else None
        except Exception:
            price = None
        results.append({"symbol": sym, "price": price, "enabled": True})
    return {"markets": results}
