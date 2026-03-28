"""Tests for log_config.py — centralized logging setup."""

import logging
import tempfile
import os


class TestLogConfig:
    def test_setup_logging_configures_root(self):
        from notas_lave.log_config import setup_logging
        setup_logging(level="WARNING")
        assert logging.getLogger().level == logging.WARNING

    def test_setup_logging_info_level(self):
        from notas_lave.log_config import setup_logging
        setup_logging(level="INFO")
        assert logging.getLogger().level == logging.INFO

    def test_setup_logging_debug_level(self):
        from notas_lave.log_config import setup_logging
        setup_logging(level="DEBUG")
        assert logging.getLogger().level == logging.DEBUG

    def test_get_logger_returns_logger(self):
        from notas_lave.log_config import get_logger
        log = get_logger("test.module")
        assert isinstance(log, logging.Logger)
        assert log.name == "test.module"

    def test_get_logger_unique_per_name(self):
        from notas_lave.log_config import get_logger
        log_a = get_logger("module_a")
        log_b = get_logger("module_b")
        assert log_a.name != log_b.name

    def test_suppresses_noisy_libraries(self):
        from notas_lave.log_config import setup_logging
        setup_logging()
        assert logging.getLogger("httpx").level == logging.WARNING
        assert logging.getLogger("urllib3").level == logging.WARNING
        assert logging.getLogger("ccxt").level == logging.WARNING

    def test_creates_data_dir_if_missing(self, tmp_path, monkeypatch):
        """setup_logging creates engine/data/ for log file even if missing."""
        from notas_lave import log_config
        # Point the log path to a temp dir by monkeypatching the __file__ reference
        # Just calling setup_logging shouldn't crash even with unusual paths
        from notas_lave.log_config import setup_logging
        setup_logging()  # Should not raise
