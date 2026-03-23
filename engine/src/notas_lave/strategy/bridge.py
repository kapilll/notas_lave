"""Strategy bridge — discovers v1 strategies and exposes via IStrategy.

v1 strategies already have name, category, and analyze() — they satisfy
IStrategy via structural typing. This module just provides discovery
and lookup functions for the v2 layer.

No strategy rewriting needed. The bridge is the v2 entry point.
"""

import logging
from collections import defaultdict

from ..core.ports import IStrategy

logger = logging.getLogger(__name__)

# Lazy-loaded cache
_strategies: list[IStrategy] | None = None


def _load_strategies() -> list[IStrategy]:
    """Import v1 strategies and verify they satisfy IStrategy."""
    global _strategies
    if _strategies is not None:
        return _strategies

    from engine.src.strategies.registry import get_all_strategies as v1_get_all

    v1_strats = v1_get_all()
    verified = []

    for strat in v1_strats:
        if isinstance(strat, IStrategy):
            verified.append(strat)
        else:
            logger.warning(
                "Strategy %s does not satisfy IStrategy — skipping",
                getattr(strat, "name", strat.__class__.__name__),
            )

    _strategies = verified
    logger.info("Bridge loaded %d strategies", len(verified))
    return verified


def get_all_strategies() -> list[IStrategy]:
    """Get all strategies that satisfy IStrategy."""
    return _load_strategies()


def get_strategy(name: str) -> IStrategy | None:
    """Get a strategy by name. Returns None if not found."""
    for strat in _load_strategies():
        if strat.name == name:
            return strat
    return None


def list_strategy_names() -> list[str]:
    """Get names of all available strategies."""
    return [s.name for s in _load_strategies()]


def strategies_by_category() -> dict[str, list[IStrategy]]:
    """Group strategies by category."""
    by_cat: dict[str, list[IStrategy]] = defaultdict(list)
    for strat in _load_strategies():
        by_cat[strat.category].append(strat)
    return dict(by_cat)
