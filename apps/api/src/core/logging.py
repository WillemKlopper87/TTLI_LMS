"""Structured logging.

JSON in every environment except local, where a human has to read it.
"""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(*, level: str = "INFO", pretty: bool = False) -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper())

    renderer: structlog.types.Processor = (
        structlog.dev.ConsoleRenderer() if pretty else structlog.processors.JSONRenderer()
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[level.upper()]
        ),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger


__all__ = ["configure_logging", "get_logger"]
