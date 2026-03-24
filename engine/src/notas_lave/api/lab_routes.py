"""Lab routes — lab engine status, trades, positions."""

from fastapi import APIRouter, Depends

from .app import Container, get_container

router = APIRouter(prefix="/api/lab")


@router.post("/sync-positions")
async def sync_positions(c: Container = Depends(get_container)):
    """Sync journal open trades with actual broker positions."""
    broker_positions = await c.broker.get_positions()
    journal_open = c.journal.get_open_trades()

    broker_syms = set()
    for bp in broker_positions:
        key = bp.symbol.replace("USDT", "USD") if bp.symbol.endswith("USDT") else bp.symbol
        broker_syms.add(key)

    journal_syms = {t.get("symbol", "") for t in journal_open}
    orphaned = journal_syms - broker_syms  # In journal but not on exchange

    # Close orphaned journal entries + duplicates (keep latest per symbol)
    closed = 0
    seen_symbols: set[str] = set()
    # Sort by trade_id descending so we keep the latest
    for trade in sorted(journal_open, key=lambda t: t.get("trade_id", 0), reverse=True):
        sym = trade.get("symbol", "")
        should_close = sym in orphaned or sym in seen_symbols
        if should_close:
            c.journal.record_close(
                trade.get("trade_id", 0),
                exit_price=trade.get("entry_price", 0),
                reason="sync_cleanup",
                pnl=0,
            )
            closed += 1
        else:
            seen_symbols.add(sym)

    return {
        "synced": True,
        "broker_positions": len(broker_positions),
        "journal_open": len(journal_open),
        "orphaned_entries_closed": closed,
        "positions": [
            {"symbol": bp.symbol, "direction": bp.direction.value,
             "entry": bp.entry_price, "pnl": bp.unrealized_pnl}
            for bp in broker_positions
        ],
        "balance": (await c.broker.get_balance()).total,
    }


@router.post("/sync-balance")
async def sync_balance(c: Container = Depends(get_container)):
    """Refresh balance from broker."""
    balance = await c.broker.get_balance()
    c.pnl.update_peak(balance.total)
    return {
        "synced": True,
        "balance": balance.total,
        "available": balance.available,
        "currency": balance.currency,
    }


@router.get("/verify")
async def verify_data(c: Container = Depends(get_container)):
    """Verify journal matches broker state."""
    broker_positions = await c.broker.get_positions()
    journal_open = c.journal.get_open_trades()

    broker_syms = set()
    for bp in broker_positions:
        key = bp.symbol.replace("USDT", "USD") if bp.symbol.endswith("USDT") else bp.symbol
        broker_syms.add(key)
    journal_syms = {t.get("symbol", "") for t in journal_open}

    checks = [
        {"check": "broker_connected", "passed": c.broker.is_connected,
         "detail": c.broker.name},
        {"check": "position_count_match",
         "passed": len(broker_positions) == len(journal_open),
         "diff": f"broker={len(broker_positions)} journal={len(journal_open)}"},
        {"check": "no_orphaned_journal",
         "passed": len(journal_syms - broker_syms) == 0,
         "diff": str(journal_syms - broker_syms) if journal_syms - broker_syms else ""},
        {"check": "no_orphaned_broker",
         "passed": len(broker_syms - journal_syms) == 0,
         "diff": str(broker_syms - journal_syms) if broker_syms - journal_syms else ""},
    ]

    return {
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
    }


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

    open_trades = c.lab_journal.get_open_trades()

    # Enrich with live prices from broker
    broker_positions = await c.broker.get_positions()
    broker_by_sym = {}
    for bp in broker_positions:
        # Map BTCUSDT -> BTCUSD for matching
        key = bp.symbol.replace("USDT", "USD") if bp.symbol.endswith("USDT") else bp.symbol
        broker_by_sym[key] = bp

    enriched = []
    for t in open_trades:
        sym = t.get("symbol", "")
        bp = broker_by_sym.get(sym)
        entry = t.get("entry_price", 0)
        direction = t.get("direction", "LONG")
        size = t.get("position_size", 0)

        if bp:
            current = bp.current_price
            pnl = bp.unrealized_pnl
        else:
            current = entry
            pnl = 0

        enriched.append({
            **t,
            "current_price": current,
            "unrealized_pnl": round(pnl, 4),
            "pnl": round(pnl, 4),
        })

    return {"positions": enriched}


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
    closed_trades = c.journal.get_closed_trades(limit=1000)
    return {
        "balance": balance.total,
        "current_balance": balance.total,
        "original_deposit": pnl.original_deposit,
        "total_pnl": round(pnl.pnl, 2),
        "total_pnl_pct": round(pnl.pnl_pct, 2),
        "daily_pnl": 0,
        "daily_drawdown_used_pct": 0,
        "total_drawdown_used_pct": round(pnl.drawdown_from_peak_pct, 2),
        "trades_today": len(closed_trades),
        "open_positions": len(open_trades),
        "is_halted": False,
        "can_trade": True,
        "max_daily_trades": 30,
        "max_concurrent": 5,
    }


@router.get("/pace")
async def lab_pace(c: Container = Depends(get_container)):
    if not c.lab_engine:
        return {"pace": "balanced", "available": list({"conservative", "balanced", "aggressive"})}

    from ..engine.lab import PACE_PRESETS, CONTEXT_TIMEFRAMES
    current = c.lab_engine.pace
    settings = PACE_PRESETS.get(current, {})
    return {
        "pace": current,
        "entry_tfs": settings.get("entry_tfs", []),
        "context_tfs": CONTEXT_TIMEFRAMES,
        "min_score": settings.get("min_score", 0),
        "min_rr": settings.get("min_rr", 0),
        "max_concurrent": settings.get("max_concurrent", 0),
        "available": list(PACE_PRESETS.keys()),
    }


@router.post("/pace/{pace}")
async def set_lab_pace(pace: str, c: Container = Depends(get_container)):
    if not c.lab_engine:
        return {"error": "Lab engine not running"}

    from ..engine.lab import PACE_PRESETS
    if pace not in PACE_PRESETS:
        return {"error": f"Unknown pace. Available: {list(PACE_PRESETS.keys())}"}

    c.lab_engine.set_pace(pace)
    settings = PACE_PRESETS[pace]
    return {
        "pace": pace,
        "entry_tfs": settings["entry_tfs"],
        "min_score": settings["min_score"],
        "max_concurrent": settings["max_concurrent"],
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
