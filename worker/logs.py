"""Logging setup and a warn-once helper.

The owner-implemented stubs raise NotImplementedError until they're written.
The scheduler hits them once per source per check, so they'd flood the logs;
warn_once() reports each stub once per process instead.
"""

import logging
import os

_warned: set[str] = set()


def setup_logging() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def warn_once(logger: logging.Logger, key: str, message: str) -> None:
    if key in _warned:
        return
    _warned.add(key)
    logger.warning(message)


def reset_warn_once() -> None:
    """For tests."""
    _warned.clear()
