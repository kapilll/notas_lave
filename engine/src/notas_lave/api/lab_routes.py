"""Lab routes — broker is source of truth for positions, journal for history."""

from fastapi import APIRouter, Depends

from .app import Container, get_container

router = APIRouter(prefix="/api/lab")


@router.post("/sync-positions")
async def sync_positions(c: Container = Depends(get_container)):
    """Force reconcile journal with broker."""
    if c.lab_engine:
        await c.lab_engine._reconcile()

    broker_positions = await c.broker.get_positions()
    balance = await c.broker.get_balance()
    return {
        "synced": True,
        "broker_positions": len(broker_positions),
        "positions": [
            {"symbol": bp.symbol, "direction": bp.direction.value,
             "entry": bp.entry_price, "pnl": bp.unrealized_pnl}
            for bp in broker_positions
        ],
        "balance": balance.total,
    }


@router.post("/sync-balance")
async def sync_balance(c: Container = Depends(get_container)):
    balance = await c.broker.get_balance()
    c.pnl.update_peak(balance.total)
    return {"synced": True, "balance": balance.total,
            "available": balance.available, "currency": balance.currency}


@router.get("/verify")
async def verify_data(c: Container = Depends(get_container)):
    broker_positions = await c.broker.get_positions()
    journal_open = c.journal.get_open_trades()

    broker_syms = set()
    for bp in broker_positions:
        key = bp.symbol.replace("USDT", "USD") if bp.symbol.endswith("USDT") else bp.symbol
        broker_syms.add(key)
    journal_syms = {t.get("symbol", "") for t in journal_open}

    checks = [
        {"check": "broker_connected", "passed": c.broker.is_connected, "detail": c.broker.name},
        {"check": "position_count_match", "passed": len(broker_positions) == len(journal_open),
         "diff": f"broker={len(broker_positions)} journal={len(journal_open)}"},
        {"check": "no_orphaned_journal", "passed": len(journal_syms - broker_syms) == 0,
         "diff": str(journal_syms - broker_syms) if journal_syms - broker_syms else ""},
        {"check": "no_orphaned_broker", "passed": len(broker_syms - journal_syms) == 0,
         "diff": str(broker_syms - journal_syms) if broker_syms - journal_syms else ""},
    ]
    return {"passed": all(c_["passed"] for c_ in checks), "checks": checks}


@router.get("/status")
async def lab_status(c: Container = Depends(get_container)):
    if not c.lab_engine:
        return {"lab_available": False, "running": False}

    broker_positions = await c.broker.get_positions()
    closed_trades = c.journal.get_closed_trades(limit=1000)
    balance = await c.broker.get_balance()
    wins = [t for t in closed_trades if t.get("pnl", 0) > 0]

    return {
        "lab_available": True, "running": True,
        "open_trades": len(broker_positions),
        "closed_trades": len(closed_trades),
        "balance": balance.total,
        "wins": len(wins),
        "losses": len(closed_trades) - len(wins),
        "win_rate": round(len(wins) / max(len(closed_trades), 1) * 100, 1),
    }


@router.get("/trades")
async def lab_trades(c: Container = Depends(get_container)):
    return {"trades": c.journal.get_closed_trades(limit=50)}


@router.get("/positions")
async def lab_positions(c: Container = Depends(get_container)):
    """Positions from BROKER (source of truth), enriched with journal SL/TP."""
    if c.lab_engine:
        return {"positions": await c.lab_engine.get_live_positions()}

    # Fallback: broker positions without journal enrichment
    broker_positions = await c.broker.get_positions()
    return {"positions": [
        {"symbol": bp.symbol, "direction": bp.direction.value,
         "quantity": bp.quantity, "entry_price": bp.entry_price,
         "current_price": bp.current_price,
         "unrealized_pnl": round(bp.unrealized_pnl, 4),
         "pnl": round(bp.unrealized_pnl, 4)}
        for bp in broker_positions
    ]}


@router.get("/summary")
async def lab_summary(c: Container = Depends(get_container)):
    from ..journal.projections import trade_summary
    return trade_summary(c.journal)


@router.get("/strategies")
async def lab_strategies(c: Container = Depends(get_container)):
    from ..journal.projections import strategy_performance
    perf = strategy_performance(c.journal)
    return {"strategies": [
        {"strategy": name, "wins": data["wins"], "losses": data["losses"],
         "trades": data["wins"] + data["losses"],
         "total_pnl": round(data["total_pnl"], 4),
         "win_rate": round(data["wins"] / max(data["wins"] + data["losses"], 1) * 100, 1)}
        for name, data in perf.items()
    ]}


@router.get("/risk")
async def lab_risk(c: Container = Depends(get_container)):
    balance = await c.broker.get_balance()
    pnl = c.pnl.calculate(balance.total)
    broker_positions = await c.broker.get_positions()
    closed_trades = c.journal.get_closed_trades(limit=1000)
    return {
        "balance": balance.total, "current_balance": balance.total,
        "original_deposit": pnl.original_deposit,
        "total_pnl": round(pnl.pnl, 2), "total_pnl_pct": round(pnl.pnl_pct, 2),
        "daily_pnl": 0, "daily_drawdown_used_pct": 0,
        "total_drawdown_used_pct": round(pnl.drawdown_from_peak_pct, 2),
        "trades_today": len(closed_trades),
        "open_positions": len(broker_positions),
        "is_halted": False, "can_trade": True,
        "max_daily_trades": 30, "max_concurrent": 5,
    }


@router.get("/pace")
async def lab_pace(c: Container = Depends(get_container)):
    if not c.lab_engine:
        return {"pace": "balanced", "available": list(PACE_PRESETS.keys())}
    from ..engine.lab import PACE_PRESETS, CONTEXT_TIMEFRAMES
    current = c.lab_engine.pace
    settings = PACE_PRESETS.get(current, {})
    return {
        "pace": current,
        "entry_tfs": settings.get("entry_tfs", []),
        "context_tfs": CONTEXT_TIMEFRAMES,
        "min_rr": settings.get("min_rr", 0),
        "max_concurrent": settings.get("max_concurrent", 0),
        "available": list(PACE_PRESETS.keys()),
        "mode": "arena",
    }


@router.post("/pace/{pace}")
async def set_lab_pace(pace: str, c: Container = Depends(get_container)):
    if not c.lab_engine:
        return {"error": "Lab engine not running"}
    from ..engine.lab import PACE_PRESETS
    if pace not in PACE_PRESETS:
        return {"error": f"Unknown pace. Available: {list(PACE_PRESETS.keys())}"}
    c.lab_engine.set_pace(pace)
    return {"pace": pace, "entry_tfs": PACE_PRESETS[pace]["entry_tfs"],
            "min_rr": PACE_PRESETS[pace]["min_rr"]}


@router.get("/arena")
async def lab_arena(c: Container = Depends(get_container)):
    """Full arena state — leaderboard + active proposals."""
    if not c.lab_engine:
        return {"leaderboard": [], "active_proposals": [], "active_strategies": []}
    return c.lab_engine.get_arena_status()


@router.get("/arena/leaderboard")
async def lab_arena_leaderboard(
    sort_by: str = "trust_score",
    c: Container = Depends(get_container),
):
    """Strategy leaderboard sorted by chosen metric."""
    if not c.lab_engine:
        return {"leaderboard": []}
    return {"leaderboard": c.lab_engine.leaderboard.get_leaderboard(sort_by)}


@router.get("/arena/{strategy_name}")
async def lab_arena_strategy(strategy_name: str, c: Container = Depends(get_container)):
    """Single strategy detail + recent trades by that strategy."""
    if not c.lab_engine:
        return {"error": "Lab engine not running"}

    record = c.lab_engine.leaderboard.get_strategy(strategy_name)
    if not record:
        return {"error": f"Strategy '{strategy_name}' not found"}

    # Get recent trades by this strategy
    closed = c.journal.get_closed_trades(limit=200)
    strategy_trades = [
        t for t in closed
        if t.get("proposing_strategy") == strategy_name
        or t.get("strategy_name") == strategy_name
    ][:20]

    return {"strategy": record, "recent_trades": strategy_trades}


@router.get("/proposals")
async def lab_proposals(c: Container = Depends(get_container)):
    """Current active proposals from the last tick."""
    if not c.lab_engine:
        return {"proposals": []}
    return {"proposals": c.lab_engine._last_proposals}


@router.get("/markets")
async def lab_markets(c: Container = Depends(get_container)):
    from ..data.market_data import market_data
    instruments = [
        "BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD", "BNBUSD", "DOGEUSD",
        "ADAUSD", "AVAXUSD", "LINKUSD", "DOTUSD", "LTCUSD", "NEARUSD",
        "SUIUSD", "ARBUSD", "PEPEUSD", "WIFUSD", "FTMUSD", "ATOMUSD",
    ]

    # Get live positions from broker for highlighting
    broker_positions = await c.broker.get_positions()
    pos_by_sym: dict[str, dict] = {}
    for bp in broker_positions:
        key = bp.symbol.replace("USDT", "USD") if bp.symbol.endswith("USDT") else bp.symbol
        pos_by_sym[key] = {
            "direction": bp.direction.value,
            "pnl": round(bp.unrealized_pnl, 4),
        }

    results = []
    for sym in instruments:
        try:
            candles = await market_data.get_candles(sym, "1m", limit=1)
            price = candles[-1].close if candles else None
        except Exception:
            price = None

        pos = pos_by_sym.get(sym)
        results.append({
            "symbol": sym,
            "price": price,
            "enabled": True,
            "has_position": pos is not None,
            "direction": pos["direction"] if pos else None,
            "pnl": pos["pnl"] if pos else 0,
        })
    return {"markets": results}
