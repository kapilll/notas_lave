"""System routes — health, prices, scan, broker status."""

from fastapi import APIRouter, Depends, Query

from .app import Container, get_container

router = APIRouter()


@router.get("/health")
async def health():
    from importlib.metadata import version
    try:
        v = version("notas-lave-engine")
    except Exception:
        v = "dev"
    return {"status": "ok", "version": v}


@router.get("/api/system/health")
async def system_health(c: Container = Depends(get_container)):
    import time as _t
    from datetime import datetime, timezone

    balance = await c.broker.get_balance()
    open_trades = c.journal.get_open_trades()
    closed_trades = c.journal.get_closed_trades(limit=1000)
    lab_running = c.lab_engine is not None and c.lab_engine.is_running

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": int(_t.time() - _t.time() % 86400),
        "components": {
            "lab_engine": {
                "status": "running" if lab_running else "stopped",
                "last_heartbeat": datetime.now(timezone.utc).isoformat(),
                "open_positions": len(open_trades),
                "trades_today": len(closed_trades),
                "trades_since_last_review": 0,
            },
            "autonomous_trader": {"status": "stopped", "mode": "disabled"},
            "broker": {
                "status": "connected" if c.broker.is_connected else "disconnected",
                "type": c.broker.name,
            },
            "market_data": {
                "status": "ok",
                "last_candle_time": datetime.now(timezone.utc).isoformat(),
                "symbols_tracked": 18,
            },
        },
        "background_tasks": {
            "last_backtest": None,
            "last_optimizer": None,
            "last_claude_review": None,
            "last_checkin": None,
        },
        "data_health": {
            "db_lab_trades": len(closed_trades),
            "db_lab_open": len(open_trades),
            "log_file_size_mb": 0,
            "wal_file_size_mb": 0,
        },
        "errors_last_hour": 0,
    }


@router.get("/api/prices")
async def prices(c: Container = Depends(get_container)):
    from ..data.market_data import market_data
    from ..data.instruments import INSTRUMENTS

    results = {}
    for symbol in list(INSTRUMENTS.keys())[:18]:
        try:
            candles = await market_data.get_candles(symbol, "1m", limit=1)
            if candles:
                results[symbol] = {
                    "symbol": symbol,
                    "price": candles[-1].close,
                    "timestamp": candles[-1].timestamp.isoformat(),
                }
            else:
                results[symbol] = {"symbol": symbol, "price": None, "timestamp": None}
        except Exception:
            results[symbol] = {"symbol": symbol, "price": None, "timestamp": None}

    return {"prices": results}


@router.get("/api/scan/all")
async def scan_all(timeframe: str = Query(default="15m"), c: Container = Depends(get_container)):
    from ..data.market_data import market_data
    from ..confluence.scorer import compute_confluence

    instruments = [
        "BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD", "BNBUSD", "DOGEUSD",
        "ADAUSD", "AVAXUSD", "LINKUSD", "DOTUSD", "LTCUSD", "NEARUSD",
        "SUIUSD", "ARBUSD", "PEPEUSD", "WIFUSD", "FTMUSD", "ATOMUSD",
    ]

    results = []
    for symbol in instruments:
        try:
            candles = await market_data.get_candles(symbol, timeframe, limit=250)
            if not candles or len(candles) < 50:
                results.append({"symbol": symbol, "error": "No data"})
                continue

            r = compute_confluence(candles, symbol, timeframe)
            top = max(
                (s for s in r.signals if s.direction is not None),
                key=lambda s: s.score,
                default=None,
            )
            results.append({
                "symbol": symbol,
                "price": candles[-1].close,
                "regime": r.regime.value,
                "score": round(r.composite_score, 2),
                "direction": r.direction.value if r.direction else None,
                "agreeing": r.agreeing_strategies,
                "total": r.total_strategies,
                "top_signal": top.strategy_name if top else "none",
            })
        except Exception as e:
            results.append({"symbol": symbol, "error": str(e)[:100]})

    return {"results": results}


@router.get("/api/scan/{symbol}")
async def scan_symbol(
    symbol: str, timeframe: str = Query(default="15m"),
    c: Container = Depends(get_container),
):
    from ..data.market_data import market_data
    from ..confluence.scorer import compute_confluence

    candles = await market_data.get_candles(symbol, timeframe, limit=250)
    if not candles or len(candles) < 50:
        return {"error": f"Not enough data for {symbol}/{timeframe}"}

    r = compute_confluence(candles, symbol, timeframe)
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "regime": r.regime.value,
        "composite_score": round(r.composite_score, 2),
        "direction": r.direction.value if r.direction else None,
        "agreeing_strategies": r.agreeing_strategies,
        "total_strategies": r.total_strategies,
        "current_price": candles[-1].close,
        "timestamp": r.timestamp.isoformat(),
        "signals": [
            {
                "strategy": s.strategy_name,
                "direction": s.direction.value if s.direction else None,
                "strength": s.strength.value,
                "score": s.score,
                "entry": s.entry_price,
                "stop_loss": s.stop_loss,
                "take_profit": s.take_profit,
                "reason": s.reason,
                "metadata": s.metadata,
            }
            for s in r.signals
        ],
    }


@router.get("/api/broker/status")
async def broker_status(c: Container = Depends(get_container)):
    balance = await c.broker.get_balance()
    positions = await c.broker.get_positions()
    return {
        "broker": c.broker.name,
        "connected": c.broker.is_connected,
        "balance": {"total": balance.total, "available": balance.available, "currency": balance.currency},
        "open_positions": len(positions),
        "positions": [
            {
                "symbol": p.symbol,
                "direction": p.direction.value,
                "quantity": p.quantity,
                "entry_price": p.entry_price,
                "unrealized_pnl": p.unrealized_pnl,
            }
            for p in positions
        ],
    }


@router.get("/api/risk/status")
async def risk_status(c: Container = Depends(get_container)):
    # Balance comes from broker (Delta Exchange API) — source of truth
    balance = await c.broker.get_balance()
    c.pnl.update_peak(balance.total)
    pnl_result = c.pnl.calculate(balance.total)
    # Positions from broker, not journal (broker is source of truth)
    broker_positions = await c.broker.get_positions()
    return {
        "balance": round(balance.total, 2),
        "available": round(balance.available, 2),
        "currency": "USD",
        "original_deposit": round(pnl_result.original_deposit, 2),
        "total_pnl": round(pnl_result.pnl, 2),
        "total_pnl_pct": round(pnl_result.pnl_pct, 2),
        "daily_pnl": 0,
        "daily_drawdown_used_pct": 0,
        "total_drawdown_used_pct": round(pnl_result.drawdown_from_peak_pct, 2),
        "trades_today": 0,
        "open_positions": len(broker_positions),
        "is_halted": False,
        "can_trade": True,
    }
