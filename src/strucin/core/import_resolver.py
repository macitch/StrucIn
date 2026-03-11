"""Import resolution: maps raw import statements to internal module targets.

Algorithm overview
------------------
For each file we walk its ``ImportInfo`` list and attempt to map every
imported name to a module that exists in the indexed repository.

Relative imports (``from . import x``, ``from .. import y``) are first
resolved to an absolute package path based on the importing file's position
in the package hierarchy, then matched against the set of known modules.

    ``level=1`` (``from . import x``)  — stay in the current package.
    ``level=2`` (``from .. import x``) — ascend one level, and so on.

If the level exceeds the package depth, an empty string is returned and
the import is treated as unresolvable (no edge added).

Absolute imports are matched via a longest-prefix search: ``from pkg.sub
import Cls`` will match ``pkg.sub`` even if ``Cls`` itself is not a
top-level module.

Unknown targets (third-party or stdlib) are silently discarded — only
internal edges are recorded in the dependency graph.
"""

from __future__ import annotations

from strucin.core.indexer import FileMetadata
from strucin.core.models import DependencyEdge, ImportInfo


def _candidate_prefix_modules(module: str) -> list[str]:
    """Return every dot-prefix of *module*, longest first."""
    parts = module.split(".")
    return [".".join(parts[:i]) for i in range(len(parts), 0, -1)]


def _resolve_to_internal(module: str, known_modules: set[str]) -> str | None:
    """Return the longest prefix of *module* that is a known internal module."""
    for candidate in _candidate_prefix_modules(module):
        if candidate in known_modules:
            return candidate
    return None


def _package_parts(file_metadata: FileMetadata) -> list[str]:
    """Return the package component list for the file's containing package."""
    parts = file_metadata.module_path.split(".")
    if file_metadata.path.endswith("__init__.py"):
        return parts
    return parts[:-1]


def _resolve_relative_base(file_metadata: FileMetadata, level: int) -> str:
    """Return the dotted package prefix reached by ascending *level* steps.

    ``level=1`` stays in the current package; ``level=2`` ascends one
    package, and so on.  Returns an empty string when *level* exceeds the
    package depth — the caller treats this as an unresolvable import.
    """
    package = _package_parts(file_metadata)
    ascend_count = max(level - 1, 0)
    if ascend_count > len(package):
        return ""
    return ".".join(package[: len(package) - ascend_count])


def _join_module(base: str, suffix: str) -> str:
    if not base:
        return suffix
    if not suffix:
        return base
    return f"{base}.{suffix}"


def _resolve_import_targets(file_metadata: FileMetadata, import_info: ImportInfo) -> list[str]:
    """Expand an ``ImportInfo`` into candidate dotted module paths."""
    if import_info.kind == "import":
        return import_info.names

    base_module = import_info.module or ""
    if import_info.level > 0:
        relative_base = _resolve_relative_base(file_metadata, import_info.level)
        base_module = _join_module(relative_base, base_module)

    if base_module:
        targets = [_join_module(base_module, name) for name in import_info.names]
        if not import_info.names or import_info.names == ["*"]:
            targets.append(base_module)
        return targets

    return list(import_info.names)


def _resolve_internal_targets_for_import(
    file_metadata: FileMetadata,
    import_info: ImportInfo,
    known_modules: set[str],
) -> set[str]:
    if import_info.kind == "import":
        targets: set[str] = set()
        for raw_target in _resolve_import_targets(file_metadata, import_info):
            internal = _resolve_to_internal(raw_target, known_modules)
            if internal is not None:
                targets.add(internal)
        return targets

    resolved: set[str] = set()
    for raw_target in _resolve_import_targets(file_metadata, import_info):
        internal = _resolve_to_internal(raw_target, known_modules)
        if internal is not None:
            resolved.add(internal)

    if resolved:
        return resolved

    # Fallback: try resolving just the module root (e.g. ``from pkg.sub import
    # Cls`` where ``Cls`` is not itself a module, but ``pkg.sub`` is).
    if import_info.module is None:
        return set()

    base_module = import_info.module
    if import_info.level > 0:
        relative_base = _resolve_relative_base(file_metadata, import_info.level)
        base_module = _join_module(relative_base, base_module)

    if not base_module:
        return set()

    fallback = _resolve_to_internal(base_module, known_modules)
    return {fallback} if fallback is not None else set()


def build_graph_edges(
    file_map: dict[str, FileMetadata],
    imports_by_module: dict[str, list[ImportInfo]],
) -> list[DependencyEdge]:
    """Build directed dependency graph edges from resolved import information."""
    known_modules = set(file_map)
    edges: set[tuple[str, str]] = set()
    for module, imports in imports_by_module.items():
        file_metadata = file_map[module]
        for import_info in imports:
            for target in _resolve_internal_targets_for_import(
                file_metadata, import_info, known_modules
            ):
                edges.add((module, target))
    return [
        DependencyEdge(source=src, target=tgt)
        for src, tgt in sorted(edges, key=lambda item: (item[0], item[1]))
    ]
