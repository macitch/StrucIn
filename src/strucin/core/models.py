"""Shared dataclass models for the StrucIn analysis pipeline.

All core analysis types live here so that sub-modules (import_resolver,
metrics, analysis_cache) can import them without creating circular
dependencies with analyzer.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = [
    "AnalysisResult",
    "ClassInfo",
    "DependencyEdge",
    "FileAnalysis",
    "FunctionInfo",
    "ImportInfo",
]


@dataclass(frozen=True)
class FunctionInfo:
    name: str
    lineno: int
    docstring: str | None
    cyclomatic_complexity: int


@dataclass(frozen=True)
class ClassInfo:
    name: str
    lineno: int
    docstring: str | None


@dataclass(frozen=True)
class ImportInfo:
    kind: Literal["import", "from"]
    module: str | None
    level: int
    names: list[str]


@dataclass(frozen=True)
class FileAnalysis:
    path: str
    module_path: str
    loc: int
    size_bytes: int
    docstring: str | None
    imports: list[ImportInfo]
    classes: list[ClassInfo]
    functions: list[FunctionInfo]
    cyclomatic_complexity: int
    fan_in: int
    fan_out: int


@dataclass(frozen=True)
class DependencyEdge:
    source: str
    target: str


@dataclass(frozen=True)
class AnalysisResult:
    repo_root: str
    generated_at: str
    file_count: int
    module_count: int
    files: list[FileAnalysis]
    dependency_graph_nodes: list[str]
    dependency_graph_edges: list[DependencyEdge]
    cycles: list[list[str]]
