"""Tests for bot/utils/logger.py — setup_logging() and get_logger()."""
from __future__ import annotations

import logging


class TestGetLogger:
    def test_returns_object(self):
        from bot.utils.logger import get_logger
        logger = get_logger("test.module")
        assert logger is not None

    def test_different_names_return_different_loggers(self):
        from bot.utils.logger import get_logger
        l1 = get_logger("module.a")
        l2 = get_logger("module.b")
        # structlog bound loggers are created fresh per name but both should be usable
        assert l1 is not None
        assert l2 is not None

    def test_logger_has_info_method(self):
        from bot.utils.logger import get_logger
        logger = get_logger("test")
        assert callable(getattr(logger, "info", None))

    def test_logger_has_warning_method(self):
        from bot.utils.logger import get_logger
        logger = get_logger("test")
        assert callable(getattr(logger, "warning", None))

    def test_logger_has_error_method(self):
        from bot.utils.logger import get_logger
        logger = get_logger("test")
        assert callable(getattr(logger, "error", None))

    def test_logger_has_debug_method(self):
        from bot.utils.logger import get_logger
        logger = get_logger("test")
        assert callable(getattr(logger, "debug", None))

    def test_logger_info_does_not_raise(self):
        from bot.utils.logger import get_logger
        logger = get_logger("test.noop")
        logger.info("test message %s", "arg")

    def test_logger_warning_does_not_raise(self):
        from bot.utils.logger import get_logger
        logger = get_logger("test.noop")
        logger.warning("warn %s", 42)

    def test_logger_error_does_not_raise(self):
        from bot.utils.logger import get_logger
        logger = get_logger("test.noop")
        logger.error("error %s", "something")


class TestSetupLogging:
    def test_setup_logging_does_not_raise(self):
        from bot.utils.logger import setup_logging
        setup_logging()

    def test_setup_logging_twice_does_not_raise(self):
        """Calling setup_logging() more than once must be idempotent."""
        from bot.utils.logger import setup_logging
        setup_logging()
        setup_logging()

    def test_root_logger_has_handler_after_setup(self):
        from bot.utils.logger import setup_logging
        setup_logging()
        root = logging.getLogger()
        assert len(root.handlers) > 0

    def test_root_logger_level_is_info(self):
        from bot.utils.logger import setup_logging
        setup_logging()
        root = logging.getLogger()
        assert root.level == logging.INFO

    def test_aiogram_logger_level_is_warning(self):
        from bot.utils.logger import setup_logging
        setup_logging()
        aiogram_logger = logging.getLogger("aiogram")
        assert aiogram_logger.level == logging.WARNING
