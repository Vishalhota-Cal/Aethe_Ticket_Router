"""
observability/logging_config.py

Sets up structured logging so every log line can be tied back to the
specific ticket (via correlation_id) that produced it.
"""

import logging
import sys


def configure_logging() -> None:
    """Call once, at app startup, to set a consistent log format for
    the whole application.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        stream=sys.stdout,
    )


def get_logger(name: str) -> logging.Logger:
    """Return a logger scoped to one module, e.g. get_logger(__name__)."""
    return logging.getLogger(name)