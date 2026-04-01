"""Lab routes — broker is source of truth for positions, journal for history."""

import time

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
        # Observability fields — never return stale/unknown states
        "broker_connected": c.broker.is_connected,
        "consecutive_errors": c.lab_engine._consecutive_errors,
        "exec_log": c.lab_engine._last_exec_log,
    }


@router.get("/trades")
async def lab_trades(limit: int = 50, c: Container = Depends(get_container)):
    trades = c.journal.get_closed_trades(limit=limit)

    # Compute summary
    total_pnl = sum(t.get("pnl", 0) for t in trades)
    wins = [t for t in trades if t.get("pnl", 0) > 0]
    losses = [t for t in trades if t.get("pnl", 0) < 0]
    win_rate = round(len(wins) / max(len(trades), 1) * 100, 1)

    return {
        "trades": trades,
        "summary": {
            "total_trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "total_pnl": round(total_pnl, 4),
            "win_rate": win_rate,
        },
    }


@router.post("/force-close/{symbol}")
async def force_close_broker(symbol: str, c: Container = Depends(get_container)):
    """Force-close a broker position by symbol, bypassing the journal.

    Use when a position is stuck open on the exchange but has no journal entry,
    or when the normal close flow fails (e.g. bankruptcy-limit errors).
    """
    result = await c.broker.close_position(symbol)
    if result.success:
        # Best-effort: also close any matching journal entry
        if c.lab_engine:
            open_trades = c.journal.get_open_trades()
            for t in open_trades:
                if t.get("symbol") == symbol:
                    await c.lab_engine.close_trade(
                        t["trade_id"],
                        exit_price=result.filled_price or t.get("entry_price", 0),
                        reason="force_close",
                    )
        return {"ok": True, "symbol": symbol, "filled_price": result.filled_price}
    # Surface the real Delta error (stored in _last_request_error) not just "No position"
    delta_error = getattr(c.broker, "_last_request_error", "") or result.error
    return {"ok": False, "error": result.error, "delta_error": delta_error}


@router.post("/raw-close/{symbol}")
async def raw_close_broker(symbol: str, size: int = 0, c: Container = Depends(get_container)):
    """Debug endpoint: place a raw market order directly against Delta, skipping position lookup.

    Uses the broker's internal product_id cache and _request method.
    Returns the full Delta API response so we can see exactly what the exchange says.
    Set size=0 to auto-detect from current broker positions.
    """
    broker = c.broker
    positions = await broker.get_positions()

    pos = next((p for p in positions if p.symbol in (symbol, symbol.replace("USD", "USDT"))), None)
    if pos is None:
        return {"ok": False, "error": f"No position found for {symbol} in broker",
                "positions_seen": [p.symbol for p in positions]}

    close_side = "buy" if pos.direction.value == "short" else "sell"
    qty = size or int(pos.quantity)
    product_id = broker._product_ids.get(pos.symbol)

    if product_id is None:
        return {"ok": False, "error": f"No product_id for {pos.symbol}",
                "product_ids_keys": list(broker._product_ids.keys())[:20]}

    order_body = {
        "product_id": product_id,
        "size": qty,
        "side": close_side,
        "order_type": "market_order",
    }

    # pylint: disable=protected-access
    raw_result = await broker._request("post", "/v2/orders", body=order_body)
    last_err = getattr(broker, "_last_request_error", "")

    return {
        "ok": raw_result is not None,
        "symbol": pos.symbol,
        "product_id": product_id,
        "order_body": order_body,
        "delta_response": raw_result,
        "delta_error": last_err or None,
    }


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


@router.post("/close/{trade_id}")
async def lab_close_trade(trade_id: int, c: Container = Depends(get_container)):
    """Manually close an open trade by trade_id."""
    if not c.lab_engine:
        return {"error": "Lab engine not running"}

    # Get current price from broker for exit
    positions = await c.broker.get_positions()
    open_trades = c.journal.get_open_trades()
    trade_info = next((t for t in open_trades if t.get("trade_id") == trade_id), None)
    if not trade_info:
        return {"error": f"Trade {trade_id} not found in journal"}

    symbol = trade_info.get("symbol", "")
    # Find the current price from broker positions
    exit_price = 0.0
    for p in positions:
        broker_sym = p.symbol.replace("USDT", "USD") if p.symbol.endswith("USDT") else p.symbol
        if broker_sym == symbol:
            exit_price = p.current_price
            break

    if exit_price <= 0:
        exit_price = trade_info.get("entry_price", 0)

    # Close broker position FIRST — if it fails, don't mark journal as closed.
    broker_result = await c.broker.close_position(symbol)
    if not broker_result.success:
        # If broker says no position found, it was already closed — still clean up journal.
        already_gone = broker_result.error and (
            "No position" in broker_result.error or "not found" in broker_result.error.lower()
        )
        if not already_gone:
            return {"ok": False, "error": broker_result.error or "Broker rejected close"}

    await c.lab_engine.close_trade(trade_id, exit_price=exit_price, reason="manual")
    return {"ok": True, "trade_id": trade_id, "exit_price": exit_price}


@router.post("/execute-proposal/{rank}")
async def execute_proposal(rank: int, c: Container = Depends(get_container)):
    """Manually execute a ranked proposal. Returns success or detailed rejection reason."""
    if not c.lab_engine:
        return {"ok": False, "reason": "Lab engine not running"}
    return await c.lab_engine.execute_proposal(rank)


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
    """Current active proposals from the last tick.

    Each proposal includes `expires_at` (unix timestamp). If `now > expires_at`,
    the proposal is stale — the market has likely moved on from that setup.
    """
    if not c.lab_engine:
        return {"proposals": []}

    now = time.time()
    proposals = []
    for p in c.lab_engine._last_proposals:
        expires_at = p.get("expires_at", 0)
        proposals.append({**p, "is_stale": now > expires_at})

    return {"proposals": proposals}


@router.get("/markets")
async def lab_markets(c: Container = Depends(get_container)):
    from ..data.market_data import market_data
    instruments = [
        "BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD", "BNBUSD",
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


@router.get("/debug/execution")
async def lab_debug_execution(c: Container = Depends(get_container)):
    """Debug endpoint — shows exactly why trades aren't executing."""
    if not c.lab_engine:
        return {"error": "Lab engine not initialized"}

    broker = c.broker
    delta_info = {}
    if hasattr(broker, '_connected'):
        delta_info["connected"] = broker._connected
        delta_info["products_loaded"] = len(getattr(broker, '_product_ids', {}))
        delta_info["contract_values"] = getattr(broker, '_contract_values', {})
        delta_info["last_exec_attempt"] = getattr(broker, '_last_exec_attempt', None)

    balance = await broker.get_balance()

    from ..engine.lab import LAB_INSTRUMENTS
    from ..data.instruments import get_instrument

    risk_per_trade = c.lab_engine._settings.get("risk_per_trade", 0.05)

    sizing_checks = []
    for sym in LAB_INSTRUMENTS:
        try:
            spec = get_instrument(sym)
            has_delta = bool(spec.exchange_symbols.get("delta"))
            size = spec.calculate_position_size(
                entry=1.0, stop_loss=0.99, account_balance=balance.total,
                risk_pct=risk_per_trade, leverage=spec.max_leverage,
            )
            sizing_checks.append({
                "symbol": sym, "delta_mapping": has_delta,
                "max_leverage": spec.max_leverage,
                "test_pos_size": size, "can_size": size > 0,
            })
        except Exception as e:
            sizing_checks.append({"symbol": sym, "error": str(e)})

    return {
        "broker": delta_info,
        "balance": {"total": balance.total, "available": balance.available},
        "risk_per_trade": risk_per_trade,
        "lab_instruments": LAB_INSTRUMENTS,
        "sizing_checks": sizing_checks,
        "last_exec_log": c.lab_engine._last_exec_log,
        "proposals_count": len(c.lab_engine._last_proposals),
        "total_trades": c.lab_engine._total_trades,
    }
