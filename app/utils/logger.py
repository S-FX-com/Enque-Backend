import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler
from typing import Dict


class LogManager:
    """
    Centralised, reusable logging factory.

    It guarantees that:
    • All loggers share consistent console/file formatting.
    • Handlers are created only once (avoids duplicated log entries).
    • Consumers can simply call LogManager.get_logger(name).

    Back-compatibility: the module still exposes `logger`, `ms_logger`,
    `important_logger`, and `log_important` so existing imports continue to work.
    """

    _initialized: bool = False
    _loggers: Dict[str, logging.Logger] = {}

    # ------------------------------------------------------------------ #
    # Paths & formats
    # ------------------------------------------------------------------ #
    LOG_DIR = Path("logs")
    LOG_DIR.mkdir(exist_ok=True)

    CONSOLE_FMT = "%(levelname)s - %(message)s"
    FILE_FMT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    # Cached default handlers (created on first initialisation)
    _default_handlers: list[logging.Handler] = []

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    @classmethod
    def _create_handler(
        cls,
        *,
        to_console: bool,
        level: int,
        filename: str | None = None,
    ) -> logging.Handler:
        """Factory for console/file handlers with unified formatting."""
        fmt = logging.Formatter(cls.CONSOLE_FMT if to_console else cls.FILE_FMT)

        if to_console:
            handler: logging.Handler = logging.StreamHandler(sys.stdout)
        else:
            path = cls.LOG_DIR / filename  # type: ignore[arg-type]
            handler = RotatingFileHandler(
                path,
                maxBytes=10_485_760,  # 10 MB
                backupCount=10,
            )

        handler.setFormatter(fmt)
        handler.setLevel(level)
        return handler

    @classmethod
    def _initialise_defaults(cls) -> None:
        """Create base handlers once for the whole application."""
        if cls._initialized:
            return

        # Console handler (DEBUG to aid development)
        console_debug = cls._create_handler(to_console=True, level=logging.DEBUG)

        # File handler for whole application
        file_handler = cls._create_handler(
            to_console=False, level=logging.DEBUG, filename="enque.log"
        )

        cls._default_handlers = [console_debug, file_handler]
        cls._initialized = True

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    @classmethod
    def get_logger(cls, name: str, level: int = logging.INFO) -> logging.Logger:
        """Return a configured logger (creates it if not existing)."""
        cls._initialise_defaults()

        if name not in cls._loggers:
            logger = logging.getLogger(name)
            logger.setLevel(level)

            # Attach default handlers only once
            if not logger.handlers:
                for handler in cls._default_handlers:
                    logger.addHandler(handler)

            cls._loggers[name] = logger

        return cls._loggers[name]

    @classmethod
    def set_level(cls, level: int, *logger_names: str) -> None:
        """Convenience method to adjust level at runtime for multiple loggers."""
        for name in logger_names:
            cls.get_logger(name).setLevel(level)


# ---------------------------------------------------------------------- #
# Pre-configured loggers (backwards-compatible exports)
# ---------------------------------------------------------------------- #
logger = LogManager.get_logger("enque", level=logging.DEBUG)
ms_logger = LogManager.get_logger("enque.microsoft", level=logging.INFO)
important_logger = LogManager.get_logger("enque.important", level=logging.INFO)

# Additional handler for "important" messages with distinct prefix
_important_console = LogManager._create_handler(to_console=True, level=logging.INFO)
_important_console.setFormatter(logging.Formatter("IMPORTANT - %(message)s"))

if not any(
    isinstance(h, logging.StreamHandler)
    and getattr(h, "formatter", None)
    and h.formatter._fmt.startswith("IMPORTANT")
    for h in important_logger.handlers
):
    important_logger.addHandler(_important_console)


def log_important(message: str) -> None:
    """Log important events that should be visible in console even at INFO level."""
    important_logger.info(message)
