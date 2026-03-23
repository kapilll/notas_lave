"""Learning routes — trade summary, strategy performance.

Reads from journal projections. No direct DB queries.
"""

from fastapi import APIRouter, Depends

from ..journal.projections import strategy_performance, trade_summary
from .app import Container, get_container

router = APIRouter(prefix="/api/learning")


@router.get("/summary")
async def learning_summary(c: Container = Depends(get_container)):
    return trade_summary(c.journal)


@router.get("/strategies")
async def learning_strategies(c: Container = Depends(get_container)):
    return strategy_performance(c.journal)
