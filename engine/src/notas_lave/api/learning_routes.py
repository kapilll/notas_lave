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


@router.get("/learning/recommendations")
async def learning_recommendations(c: Container = Depends(get_container)):
    """Actionable suggestions from the learning engine."""
    from ..learning.recommendations import generate_all_recommendations
    return generate_all_recommendations()


@router.get("/learning/trade-grades")
async def learning_trade_grades(
    limit: int = Query(default=50),
    c: Container = Depends(get_container),
):
    """Recent trades with grades and lessons."""
    from ..journal.database import get_db, TradeLog
    db = get_db()
    trades = (
        db.query(TradeLog)
        .filter(TradeLog.exit_price.isnot(None))
        .order_by(TradeLog.id.desc())
        .limit(limit)
        .all()
    )
    return {
        "trades": [
            {
                "id": t.id,
                "symbol": t.symbol,
                "direction": t.direction,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "pnl": t.pnl,
                "grade": t.outcome_grade,
                "lesson": t.lessons_learned,
                "exit_reason": t.exit_reason,
                "proposing_strategy": t.proposing_strategy,
                "closed_at": str(t.closed_at) if t.closed_at else None,
            }
            for t in trades
        ],
        "total": len(trades),
    }


@router.post("/learning/analyze-now")
async def learning_analyze_now(c: Container = Depends(get_container)):
    """Trigger a full analysis run on demand."""
    from ..learning.analyzer import run_full_analysis
    return run_full_analysis()


@router.get("/learning/patterns")
async def learning_patterns(c: Container = Depends(get_container)):
    """Pattern insights: hour-of-day, score buckets, exit reasons."""
    from ..learning.analyzer import (
        analyze_by_hour,
        analyze_by_score_bucket,
        analyze_exit_reasons,
    )
    return {
        "by_hour": analyze_by_hour(),
        "by_score_bucket": analyze_by_score_bucket(),
        "exit_reasons": analyze_exit_reasons(),
    }


@router.get("/learning/accuracy")
async def learning_accuracy(
    days: int = Query(default=30, ge=1, le=365),
    c: Container = Depends(get_container),
):
    """Prediction accuracy scores and breakdowns."""
    from ..learning.accuracy import get_accuracy_score
    return get_accuracy_score(max_age_days=days)


@router.post("/learning/review")
async def learning_review(c: Container = Depends(get_container)):
    """Trigger a Claude weekly review and send via Telegram."""
    from ..learning.claude_review import generate_review
    return await generate_review()


@router.post("/learning/optimize/{symbol}")
async def learning_optimize(
    symbol: str,
    timeframe: str = Query(default="15m"),
    days: int = Query(default=90, ge=14, le=365),
    c: Container = Depends(get_container),
):
    """Walk-forward optimize all strategies for a symbol."""
    from ..data.market_data import MarketDataService
    from ..learning.optimizer import optimize_all_strategies, save_results

    market_data = MarketDataService()
    candles = await market_data.get_historical_candles(symbol, timeframe, limit=days * 96)

    if not candles or len(candles) < 300:
        return {"error": f"Insufficient data for {symbol}: {len(candles) if candles else 0} candles"}

    results = optimize_all_strategies(candles, symbol, timeframe)
    save_results(symbol, results)

    improved = [r for r in results if r["improvement_pct"] > 0]
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "strategies_optimized": len(results),
        "strategies_improved": len(improved),
        "results": results,
    }


@router.get("/learning/reports")
async def learning_reports(
    limit: int = Query(default=20, ge=1, le=200),
):
    """List recent trade autopsy reports (metadata only)."""
    from ..learning.trade_autopsy import list_reports
    return {"reports": list_reports(limit=limit)}


@router.get("/learning/reports/{trade_id}")
async def learning_report_detail(trade_id: str):
    """Full content of a trade autopsy report."""
    from ..learning.trade_autopsy import get_report_content
    content = get_report_content(trade_id)
    if content is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Report for trade #{trade_id} not found")
    return {"trade_id": trade_id, "content": content}


@router.get("/learning/edge-analysis")
async def learning_edge_analysis(week: str = Query(default="")):
    """Read the weekly edge analysis. week format: 2026-W13 (defaults to current week)."""
    from ..learning.trade_autopsy import get_edge_analysis
    content = get_edge_analysis(week=week if week else None)
    if content is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"No edge analysis found for week '{week or 'current'}'")
    return {"week": week, "content": content}


@router.post("/learning/analyze-edges")
async def learning_analyze_edges(week: str = Query(default="")):
    """Trigger on-demand edge analysis for a week (defaults to current week)."""
    from ..learning.trade_autopsy import compile_weekly_summary, analyze_edges
    summary = compile_weekly_summary(week=week if week else None)
    result = analyze_edges(summary, week=week if week else None)
    if not result:
        return {"status": "skipped", "reason": "No Claude API key or no reports found", "summary": summary}
    return {"status": "ok", "week": week or "current", "analysis": result}


@router.get("/costs/summary")
async def costs_summary():
    return {
        "total_runtime_cost": 0.0,
        "total_build_cost": 0.0,
        "total_cost": 0.0,
        "runtime_calls": 0,
        "currency": "USD",
    }
