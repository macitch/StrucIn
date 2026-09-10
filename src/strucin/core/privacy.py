"""Privacy boundaries for shareable output; raw analysis stays in memory.

Labels are local to an export, not persistent identities across snapshots.
No reverse mapping is serialized or sent to a provider.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import replace
from pathlib import PurePath
from typing import TYPE_CHECKING

from strucin.core.models import AnalysisResult

if TYPE_CHECKING:
    from strucin.core.diff import DiffResult
    from strucin.core.indexer import RepoIndex
    from strucin.core.semantic import SemanticHit, SemanticIndex

REDACTED_REPOSITORY = "[REDACTED_REPOSITORY]"


def _labels(values: Iterable[str], prefix: str) -> dict[str, str]:
    return {value: f"{prefix}_{i:04d}" for i, value in enumerate(sorted(set(values)), 1)}


def anonymize_index(index: RepoIndex) -> RepoIndex:
    modules = _labels((file.module_path for file in index.files), "module")
    paths = _labels((file.path for file in index.files), "file")
    return replace(
        index,
        repo_root=REDACTED_REPOSITORY,
        files=[
            replace(file, path=f"{paths[file.path]}.py", module_path=modules[file.module_path])
            for file in index.files
        ],
    )


def anonymize_analysis(analysis: AnalysisResult) -> AnalysisResult:
    module_names = set(analysis.dependency_graph_nodes)
    for edge in analysis.dependency_graph_edges:
        module_names.update((edge.source, edge.target))
    for cycle in analysis.cycles:
        module_names.update(cycle)
    symbol_names: set[str] = set()
    for file in analysis.files:
        module_names.add(file.module_path)
        symbol_names.update(item.name for item in file.classes)
        symbol_names.update(item.name for item in file.functions)
        for item in file.imports:
            if item.module is not None:
                module_names.add(item.module)
            if item.kind == "import":
                module_names.update(item.names)
            else:
                symbol_names.update(item.names)
    modules = _labels(module_names, "module")
    symbols = _labels(symbol_names, "symbol")
    paths = _labels((file.path for file in analysis.files), "file")
    return replace(
        analysis,
        repo_root=REDACTED_REPOSITORY,
        files=[
            replace(
                file,
                path=f"{paths[file.path]}.py",
                module_path=modules[file.module_path],
                docstring=None,
                classes=[
                    replace(item, name=symbols[item.name], docstring=None) for item in file.classes
                ],
                functions=[
                    replace(item, name=symbols[item.name], docstring=None)
                    for item in file.functions
                ],
                imports=[
                    replace(
                        item,
                        module=modules[item.module] if item.module is not None else None,
                        names=[
                            (modules if item.kind == "import" else symbols)[name]
                            for name in item.names
                        ],
                    )
                    for item in file.imports
                ],
            )
            for file in analysis.files
        ],
        dependency_graph_nodes=[modules[name] for name in analysis.dependency_graph_nodes],
        dependency_graph_edges=[
            replace(edge, source=modules[edge.source], target=modules[edge.target])
            for edge in analysis.dependency_graph_edges
        ],
        cycles=[[modules[name] for name in cycle] for cycle in analysis.cycles],
    )


def redact_identifiers(text: str, analysis: AnalysisResult) -> str:
    """Filter known identifiers in provider/cache text as defense in depth.

    The primary boundary is anonymization *before* the provider call. This
    filter also catches known names echoed by a provider or an older cache.
    """
    values = {analysis.repo_root, *analysis.dependency_graph_nodes}
    values.update(PurePath(analysis.repo_root).parts)
    for file in analysis.files:
        values.update((file.path, file.module_path))
        values.update(PurePath(file.path).parts)
        values.update(item.name for item in file.classes)
        values.update(item.name for item in file.functions)
        for item in file.imports:
            values.update(item.names)
            if item.module:
                values.add(item.module)
        if file.docstring:
            values.add(file.docstring)
        values.update(item.docstring for item in file.classes if item.docstring)
        values.update(item.docstring for item in file.functions if item.docstring)
    values.update(part for value in list(values) for part in re.split(r"[./\\]+", value))
    values.difference_update({"", "/", ".", "..", "py"})
    if not values:
        return text
    pattern = r"(?<!\w)(?:" + "|".join(re.escape(v) for v in sorted(values, key=len, reverse=True))
    return re.sub(pattern + r")(?!\w)", "[REDACTED_IDENTIFIER]", text, flags=re.IGNORECASE)


def anonymize_hits(hits: list[SemanticHit], index: SemanticIndex) -> list[SemanticHit]:
    paths = _labels((chunk.path for chunk in index.chunks), "file")
    modules = _labels((chunk.module_path for chunk in index.chunks if chunk.module_path), "module")
    symbols = _labels((chunk.symbol for chunk in index.chunks if chunk.symbol), "symbol")
    return [
        replace(
            hit,
            chunk=replace(
                hit.chunk,
                id=f"chunk_{rank:04d}",
                path=paths[hit.chunk.path],
                module_path=modules[hit.chunk.module_path] if hit.chunk.module_path else None,
                symbol=symbols[hit.chunk.symbol] if hit.chunk.symbol else None,
                text="",
            ),
            preview="",
        )
        for rank, hit in enumerate(hits, 1)
    ]


def anonymize_diff(result: DiffResult) -> DiffResult:
    names = {*result.added_modules, *result.removed_modules}
    for cycle in [*result.new_cycles, *result.resolved_cycles]:
        names.update(cycle)
    names.update(item.module_path for item in result.complexity_changes)
    names.update(item.module_path for item in result.coupling_changes)
    names.update(item.module_path for item in result.loc_changes)
    modules = _labels(names, "module")
    return replace(
        result,
        added_modules=[modules[name] for name in result.added_modules],
        removed_modules=[modules[name] for name in result.removed_modules],
        new_cycles=[[modules[name] for name in cycle] for cycle in result.new_cycles],
        resolved_cycles=[[modules[name] for name in cycle] for cycle in result.resolved_cycles],
        complexity_changes=[
            replace(item, module_path=modules[item.module_path])
            for item in result.complexity_changes
        ],
        coupling_changes=[
            replace(item, module_path=modules[item.module_path]) for item in result.coupling_changes
        ],
        loc_changes=[
            replace(item, module_path=modules[item.module_path]) for item in result.loc_changes
        ],
    )
