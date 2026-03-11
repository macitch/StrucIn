"""Custom exception hierarchy for StrucIn.

All exceptions raised by the public API are subclasses of :exc:`StrucInError`
so consumers can catch library errors without accidentally catching unrelated
built-in exceptions::

    from strucin import StrucInError
    try:
        analyze_repository(path)
    except StrucInError as exc:
        print(f"strucin failed: {exc}")
"""

from __future__ import annotations

__all__ = [
    "StrucInError",
    "ConfigError",
    "AnalysisError",
    "CacheError",
    "DashboardSchemaError",
]


class StrucInError(Exception):
    """Base class for all StrucIn errors."""


class ConfigError(StrucInError):
    """Raised when configuration is invalid or cannot be loaded."""


class AnalysisError(StrucInError):
    """Raised when repository analysis fails unrecoverably."""


class CacheError(StrucInError):
    """Raised when cache operations fail in a non-recoverable way."""


class DashboardSchemaError(StrucInError):
    """Raised when serialised dashboard data fails schema validation."""
