"""JSON logs on stderr (stdout is for command results), one event per line. Callers log ids, counts and timings,
never document contents or request headers."""

from __future__ import annotations

import logging
import sys

import structlog


def configure(level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stderr, level=level)
    for noisy in ("httpx", "botocore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def get(name: str) -> structlog.typing.FilteringBoundLogger:
    logger: structlog.typing.FilteringBoundLogger = structlog.get_logger(name)
    return logger
