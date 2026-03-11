"""Tests for strucin.core.import_resolver.

Covers:
- _resolve_relative_base: level-1, level-2, __init__.py files, depth overflow
- _resolve_import_targets: absolute import, from-absolute, from-relative
- _resolve_internal_targets_for_import: known/unknown modules, fallback logic
- build_graph_edges: simple dep, mutual dep (cycle), no internal imports
"""

from __future__ import annotations

from strucin.core.import_resolver import (
    _resolve_import_targets,
    _resolve_internal_targets_for_import,
    _resolve_relative_base,
    build_graph_edges,
)
from strucin.core.indexer import FileMetadata
from strucin.core.models import DependencyEdge, ImportInfo


def _file(path: str, module_path: str) -> FileMetadata:
    return FileMetadata(path=path, module_path=module_path, loc=1, size_bytes=100)


# ---------------------------------------------------------------------------
# _resolve_relative_base
# ---------------------------------------------------------------------------


def test_relative_base_level_1_non_init() -> None:
    """Level-1 from a non-__init__ file stays in the current package."""
    assert _resolve_relative_base(_file("pkg/a.py", "pkg.a"), level=1) == "pkg"


def test_relative_base_level_1_init() -> None:
    """Level-1 from __init__.py stays in its own package."""
    assert _resolve_relative_base(_file("pkg/__init__.py", "pkg"), level=1) == "pkg"


def test_relative_base_level_2_nested() -> None:
    """Level-2 from pkg/sub/a.py ascends one level to pkg."""
    assert _resolve_relative_base(_file("pkg/sub/a.py", "pkg.sub.a"), level=2) == "pkg"


def test_relative_base_level_3_deep() -> None:
    """Level-3 from pkg/sub/a.py ascends two levels to the repo root."""
    assert _resolve_relative_base(_file("pkg/sub/a.py", "pkg.sub.a"), level=3) == ""


def test_relative_base_exceeds_depth_returns_empty() -> None:
    """Level beyond package depth returns empty string — no valid target."""
    assert _resolve_relative_base(_file("pkg/a.py", "pkg.a"), level=5) == ""


# ---------------------------------------------------------------------------
# _resolve_import_targets
# ---------------------------------------------------------------------------


def test_import_targets_plain_import() -> None:
    """``import os`` returns the name unchanged."""
    fm = _file("pkg/a.py", "pkg.a")
    info = ImportInfo(kind="import", module=None, level=0, names=["os"])
    assert _resolve_import_targets(fm, info) == ["os"]


def test_import_targets_from_absolute() -> None:
    """``from pkg.core import Cls`` returns ``pkg.core.Cls``."""
    fm = _file("pkg/a.py", "pkg.a")
    info = ImportInfo(kind="from", module="pkg.core", level=0, names=["Cls"])
    assert _resolve_import_targets(fm, info) == ["pkg.core.Cls"]


def test_import_targets_from_relative_level_1() -> None:
    """``from . import b`` from pkg/a.py returns ``pkg.b``."""
    fm = _file("pkg/a.py", "pkg.a")
    info = ImportInfo(kind="from", module=None, level=1, names=["b"])
    assert _resolve_import_targets(fm, info) == ["pkg.b"]


def test_import_targets_from_relative_level_2() -> None:
    """``from .. import util`` from pkg/sub/a.py returns ``pkg.util``."""
    fm = _file("pkg/sub/a.py", "pkg.sub.a")
    info = ImportInfo(kind="from", module=None, level=2, names=["util"])
    assert _resolve_import_targets(fm, info) == ["pkg.util"]


def test_import_targets_star_import_includes_module_root() -> None:
    """``from pkg import *`` includes ``pkg`` itself in the targets."""
    fm = _file("pkg/a.py", "pkg.a")
    info = ImportInfo(kind="from", module="pkg", level=0, names=["*"])
    targets = _resolve_import_targets(fm, info)
    assert "pkg" in targets


# ---------------------------------------------------------------------------
# _resolve_internal_targets_for_import
# ---------------------------------------------------------------------------


def test_internal_absolute_known_module() -> None:
    """``import pkg.b`` resolves to ``pkg.b`` when it is a known module."""
    fm = _file("pkg/a.py", "pkg.a")
    info = ImportInfo(kind="import", module=None, level=0, names=["pkg.b"])
    assert _resolve_internal_targets_for_import(fm, info, {"pkg.a", "pkg.b"}) == {"pkg.b"}


def test_internal_absolute_unknown_module_returns_empty() -> None:
    """Third-party import does not crash and returns an empty set."""
    fm = _file("pkg/a.py", "pkg.a")
    info = ImportInfo(kind="import", module=None, level=0, names=["requests"])
    assert _resolve_internal_targets_for_import(fm, info, {"pkg.a", "pkg.b"}) == set()


def test_internal_relative_level_1_resolves() -> None:
    """``from . import b`` from pkg/a.py resolves to ``pkg.b``."""
    fm = _file("pkg/a.py", "pkg.a")
    info = ImportInfo(kind="from", module=None, level=1, names=["b"])
    assert _resolve_internal_targets_for_import(fm, info, {"pkg.a", "pkg.b"}) == {"pkg.b"}


def test_internal_relative_exceeds_depth_returns_empty() -> None:
    """Relative import that ascends beyond the root returns empty set without crashing."""
    fm = _file("pkg/a.py", "pkg.a")
    info = ImportInfo(kind="from", module=None, level=5, names=["x"])
    assert _resolve_internal_targets_for_import(fm, info, {"pkg.a"}) == set()


def test_internal_falls_back_to_module_root() -> None:
    """``from pkg.sub import Cls`` falls back to ``pkg.sub`` when Cls is not a module."""
    fm = _file("pkg/a.py", "pkg.a")
    info = ImportInfo(kind="from", module="pkg.sub", level=0, names=["Cls"])
    assert _resolve_internal_targets_for_import(fm, info, {"pkg.a", "pkg.sub"}) == {"pkg.sub"}


def test_internal_from_unknown_module_and_unknown_root_returns_empty() -> None:
    """Unknown from-import with unknown module root returns empty set."""
    fm = _file("pkg/a.py", "pkg.a")
    info = ImportInfo(kind="from", module="third_party.core", level=0, names=["Cls"])
    assert _resolve_internal_targets_for_import(fm, info, {"pkg.a"}) == set()


# ---------------------------------------------------------------------------
# build_graph_edges
# ---------------------------------------------------------------------------


def test_build_edges_simple_dependency() -> None:
    """a imports b → single directed edge a→b."""
    fm_a = _file("pkg/a.py", "pkg.a")
    fm_b = _file("pkg/b.py", "pkg.b")
    file_map = {"pkg.a": fm_a, "pkg.b": fm_b}
    imports_by_module = {
        "pkg.a": [ImportInfo(kind="from", module=None, level=1, names=["b"])],
        "pkg.b": [],
    }
    edges = build_graph_edges(file_map, imports_by_module)
    assert DependencyEdge(source="pkg.a", target="pkg.b") in edges
    assert len(edges) == 1


def test_build_edges_mutual_dependency_forms_cycle() -> None:
    """a imports b and b imports a → two directed edges."""
    fm_a = _file("pkg/a.py", "pkg.a")
    fm_b = _file("pkg/b.py", "pkg.b")
    file_map = {"pkg.a": fm_a, "pkg.b": fm_b}
    imports_by_module = {
        "pkg.a": [ImportInfo(kind="from", module=None, level=1, names=["b"])],
        "pkg.b": [ImportInfo(kind="from", module=None, level=1, names=["a"])],
    }
    edges = build_graph_edges(file_map, imports_by_module)
    edge_pairs = {(e.source, e.target) for e in edges}
    assert ("pkg.a", "pkg.b") in edge_pairs
    assert ("pkg.b", "pkg.a") in edge_pairs


def test_build_edges_stdlib_only_imports_returns_no_edges() -> None:
    """Only stdlib imports → no internal edges."""
    fm_a = _file("pkg/a.py", "pkg.a")
    file_map = {"pkg.a": fm_a}
    imports_by_module = {
        "pkg.a": [ImportInfo(kind="import", module=None, level=0, names=["os", "sys"])],
    }
    assert build_graph_edges(file_map, imports_by_module) == []
