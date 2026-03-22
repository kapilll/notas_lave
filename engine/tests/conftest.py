"""Test configuration — redirect DB to in-memory SQLite.

Without this, tests that call open_position/close_position write
to the production notas_lave.db, creating ghost entries that
pollute the live system.
"""

import pytest
from engine.src.journal.database import _init_db


@pytest.fixture(autouse=True)
def use_test_db():
    """Redirect all DB operations to an in-memory SQLite for each test."""
    _init_db(db_key="default", db_path="sqlite:///:memory:")
    _init_db(db_key="lab", db_path="sqlite:///:memory:")
    yield
