"""Verify every symbol listed in strucin.__all__ is importable and has the expected type."""

from __future__ import annotations

import strucin


def test_all_symbols_are_importable() -> None:
    """Every name in __all__ must be resolvable from the top-level package."""
    for name in strucin.__all__:
        assert hasattr(strucin, name), f"strucin.{name} is in __all__ but not importable"


def test_version_is_a_non_empty_string() -> None:
    assert isinstance(strucin.__version__, str)
    assert strucin.__version__ != ""


def test_public_callables_are_callable() -> None:
    for name in (
        "analyze_repository",
        "explain_repository",
        "build_semantic_index",
        "search_semantic_index",
        "load_config",
    ):
        obj = getattr(strucin, name)
        assert callable(obj), f"strucin.{name} must be callable"


def test_exception_hierarchy() -> None:
    """All custom exceptions are subclasses of StrucInError."""
    from strucin import AnalysisError, CacheError, ConfigError, DashboardSchemaError, StrucInError

    for exc_class in (ConfigError, AnalysisError, CacheError, DashboardSchemaError):
        assert issubclass(exc_class, StrucInError), (
            f"{exc_class.__name__} must subclass StrucInError"
        )


def test_dataclasses_are_not_callable_as_functions() -> None:
    """AnalysisResult, FileAnalysis, SemanticHit, ExplainOutput, StrucInConfig are classes."""
    for name in ("AnalysisResult", "FileAnalysis", "SemanticHit", "ExplainOutput", "StrucInConfig"):
        obj = getattr(strucin, name)
        assert isinstance(obj, type), f"strucin.{name} must be a class, got {type(obj)}"
