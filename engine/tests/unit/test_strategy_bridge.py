"""Tests for v2 strategy bridge — v1 strategies satisfy IStrategy.

The bridge discovers existing strategies and verifies they
satisfy the v2 IStrategy protocol without any rewriting.
"""

import pytest

from notas_lave.core.ports import IStrategy


def test_v1_strategies_satisfy_istrategy():
    """All v1 strategies must satisfy the IStrategy protocol."""
    from notas_lave.strategies.bridge import get_all_strategies

    strategies = get_all_strategies()
    assert len(strategies) >= 6  # 6 composite strategies

    for strat in strategies:
        assert isinstance(strat, IStrategy), (
            f"{strat.__class__.__name__} does not satisfy IStrategy"
        )
        assert isinstance(strat.name, str)
        assert len(strat.name) > 0
        assert isinstance(strat.category, str)
        assert len(strat.category) > 0
        assert callable(strat.analyze)


def test_get_strategy_by_name():
    from notas_lave.strategies.bridge import get_strategy

    strat = get_strategy("trend_momentum")
    assert strat is not None
    assert strat.name == "trend_momentum"
    assert isinstance(strat, IStrategy)


def test_get_unknown_strategy():
    from notas_lave.strategies.bridge import get_strategy

    result = get_strategy("nonexistent_strategy_xyz")
    assert result is None


def test_list_strategy_names():
    from notas_lave.strategies.bridge import list_strategy_names

    names = list_strategy_names()
    assert isinstance(names, list)
    assert "trend_momentum" in names
    assert "mean_reversion" in names
    assert "breakout_system" in names


def test_strategies_grouped_by_category():
    from notas_lave.strategies.bridge import strategies_by_category

    by_cat = strategies_by_category()
    assert isinstance(by_cat, dict)
    assert len(by_cat) >= 2  # At least 2 categories

    for cat, strats in by_cat.items():
        assert isinstance(cat, str)
        assert len(strats) > 0
        for s in strats:
            assert isinstance(s, IStrategy)
