"""StrucIn — Structural Intelligence for Python codebases.

Primary public API::

    from strucin import analyze_repository, AnalysisResult
    from strucin import explain_repository
    from strucin import build_semantic_index, search_semantic_index
    from strucin import load_config, StrucInConfig
    from strucin import StrucInError
"""

from __future__ import annotations

from strucin._version import __version__
from strucin.core.analyzer import AnalysisResult, FileAnalysis, analyze_repository
from strucin.core.config import StrucInConfig, load_config
from strucin.core.explainer import ExplainOutput, explain_repository
from strucin.core.semantic import SemanticHit, build_semantic_index, search_semantic_index
from strucin.exceptions import (
    AnalysisError,
    CacheError,
    ConfigError,
    DashboardSchemaError,
    StrucInError,
)

__all__ = [
    "__version__",
    # Analysis
    "analyze_repository",
    "AnalysisResult",
    "FileAnalysis",
    # Config
    "load_config",
    "StrucInConfig",
    # Explain
    "explain_repository",
    "ExplainOutput",
    # Semantic search
    "build_semantic_index",
    "search_semantic_index",
    "SemanticHit",
    # Exceptions
    "StrucInError",
    "ConfigError",
    "AnalysisError",
    "CacheError",
    "DashboardSchemaError",
]
