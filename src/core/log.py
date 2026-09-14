"""
Blender Agent Terminal — Logging
Thin wrapper around Python logging with a consistent prefix.
"""

import logging
import sys

_LOG_PREFIX = "BAT"
_logger = logging.getLogger(_LOG_PREFIX)

# Avoid adding duplicate handlers if the module is reloaded (common in Blender)
if not _logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(
        logging.Formatter("[%(name)s] %(levelname)s — %(message)s")
    )
    _logger.addHandler(_handler)

_logger.setLevel(logging.DEBUG)
_logger.propagate = False


def get_logger(name: str) -> logging.Logger:
    """Return a child logger namespaced under the BAT prefix."""
    return _logger.getChild(name)
