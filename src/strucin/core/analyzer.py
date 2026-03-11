"""Repository analysis orchestrator.

Orchestrates the full analysis pipeline:

1. Scan the repository for Python files (``indexer``).
2. Parse each file's AST, extracting imports, classes, functions, and
   cyclomatic complexity — in parallel via ``ThreadPoolExecutor``.
3. Resolve internal import targets and build the dependency graph
   (``import_resolver``).
4. Compute fan-in / fan-out and detect cycles (``metrics``).
5. Persist results to JSON artefacts.

Per-file results are cached by SHA-256 content hash (``analysis_cache``)
so incremental re-runs only re-parse changed files.

Note on executor choice
-----------------------
By default (``executor="auto"``) ``ThreadPoolExecutor`` is used because this
workload is I/O-bound for typical repository sizes: disk reads and file hashing
dominate ``ast.parse`` CPU time.  When ``executor="auto"`` and the repository
contains more than 2 000 files, ``ProcessPoolExecutor`` is selected instead to
exploit multiple CPU cores.  Use ``executor="thread"`` or ``executor="process"``
to force a specific backend regardless of corpus size.
"""

from __future__ import annotations

import ast
import hashlib
import json
import logging
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import asdict
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

from strucin.core.analysis_cache import (
    load_analysis_cache,
    make_cache_payload,
    restore_cached_analysis,
    write_analysis_cache,
)
from strucin.core.artifacts import build_artifact_metadata
from strucin.core.import_resolver import build_graph_edges
from strucin.core.indexer import FileMetadata, scan_repository
from strucin.core.metrics import build_adjacency, compute_fan_metrics, detect_cycles

# Re-export all models so existing callers continue to work without change:
#   from strucin.core.analyzer import AnalysisResult, FileAnalysis, ...
from strucin.core.models import AnalysisResult as AnalysisResult
from strucin.core.models import ClassInfo as ClassInfo
from strucin.core.models import DependencyEdge as DependencyEdge
from strucin.core.models import FileAnalysis as FileAnalysis
from strucin.core.models import FunctionInfo as FunctionInfo
from strucin.core.models import ImportInfo as ImportInfo

_logger = logging.getLogger(__name__)

BRANCH_NODES = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.Try,
    ast.ExceptHandler,
    ast.IfExp,
    ast.Match,
)

# ---------------------------------------------------------------------------
# AST extraction helpers
# ---------------------------------------------------------------------------


def _node_complexity(node: ast.AST) -> int:
    branch_count = sum(1 for child in ast.walk(node) if isinstance(child, BRANCH_NODES))
    return branch_count + 1


def _extract_imports(tree: ast.Module) -> list[ImportInfo]:
    imports: list[ImportInfo] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.append(
                ImportInfo(
                    kind="import",
                    module=None,
                    level=0,
                    names=[alias.name for alias in node.names],
                )
            )
        elif isinstance(node, ast.ImportFrom):
            imports.append(
                ImportInfo(
                    kind="from",
                    module=node.module,
                    level=node.level,
                    names=[alias.name for alias in node.names],
                )
            )
    return imports


def _extract_functions(tree: ast.Module) -> list[FunctionInfo]:
    functions: list[FunctionInfo] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(
                FunctionInfo(
                    name=node.name,
                    lineno=node.lineno,
                    docstring=ast.get_docstring(node),
                    cyclomatic_complexity=_node_complexity(node),
                )
            )
    return sorted(functions, key=lambda f: f.lineno)


def _extract_classes(tree: ast.Module) -> list[ClassInfo]:
    classes: list[ClassInfo] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            classes.append(
                ClassInfo(
                    name=node.name,
                    lineno=node.lineno,
                    docstring=ast.get_docstring(node),
                )
            )
    return sorted(classes, key=lambda c: c.lineno)


# ---------------------------------------------------------------------------
# Per-file analysis
# ---------------------------------------------------------------------------


def _analyze_single_file(
    file_metadata: FileMetadata,
    source: str,
) -> tuple[FileAnalysis, list[ImportInfo]]:
    """Parse *source* and return a ``(FileAnalysis, imports)`` pair.

    *source* should already be decoded (with ``errors='replace'`` so any invalid
    bytes are visible as U+FFFD rather than silently dropped).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        _logger.debug("skipping %s: SyntaxError during parsing", file_metadata.path)
        return (
            FileAnalysis(
                path=file_metadata.path,
                module_path=file_metadata.module_path,
                loc=file_metadata.loc,
                size_bytes=file_metadata.size_bytes,
                docstring=None,
                imports=[],
                classes=[],
                functions=[],
                cyclomatic_complexity=0,
                fan_in=0,
                fan_out=0,
            ),
            [],
        )
    imports = _extract_imports(tree)
    analysis = FileAnalysis(
        path=file_metadata.path,
        module_path=file_metadata.module_path,
        loc=file_metadata.loc,
        size_bytes=file_metadata.size_bytes,
        docstring=ast.get_docstring(tree),
        imports=imports,
        classes=_extract_classes(tree),
        functions=_extract_functions(tree),
        cyclomatic_complexity=_node_complexity(tree),
        fan_in=0,
        fan_out=0,
    )
    return analysis, imports


def _analyze_file_with_cache(
    file_metadata: FileMetadata,
    root: Path,
    cache_entries: dict[str, dict[str, object]],
) -> tuple[FileAnalysis, list[ImportInfo], str]:
    """Read the file once as raw bytes, hash it, decode, then analyse.

    Reading as bytes ensures the SHA-256 hash and the parsed source text are
    derived from the same bytes.  ``errors='replace'`` makes any invalid UTF-8
    bytes visible (as U+FFFD) rather than silently dropping them.
    """
    file_path = root / file_metadata.path
    raw = file_path.read_bytes()
    sha256 = hashlib.sha256(raw).hexdigest()
    cached_entry = cache_entries.get(file_metadata.path)
    if (
        isinstance(cached_entry, dict)
        and cached_entry.get("sha256") == sha256
        and cached_entry.get("module_path") == file_metadata.module_path
    ):
        cached_payload = cached_entry.get("analysis")
        if isinstance(cached_payload, dict):
            restored = restore_cached_analysis(cached_payload)
            if restored is not None:
                return restored[0], restored[1], sha256
    source = raw.decode("utf-8", errors="replace")
    analysis, imports = _analyze_single_file(file_metadata, source)
    return analysis, imports, sha256


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


_AUTO_PROCESS_THRESHOLD = 2000


def analyze_repository(
    repo_path: Path,
    excluded_dirs: set[str] | None = None,
    max_workers: int | None = None,
    executor: str = "auto",
) -> AnalysisResult:
    index = scan_repository(repo_path, excluded_dirs=excluded_dirs, max_workers=max_workers)
    root = Path(index.repo_root)
    cache_path = root / ".strucin_cache" / "analysis_cache.json"
    cache_entries = load_analysis_cache(cache_path)
    file_map: dict[str, FileMetadata] = {f.module_path: f for f in index.files}

    use_process = executor == "process" or (
        executor == "auto" and len(index.files) > _AUTO_PROCESS_THRESHOLD
    )

    if max_workers == 1:
        analyzed = [
            _analyze_file_with_cache(fm, root=root, cache_entries=cache_entries)
            for fm in index.files
        ]
    else:
        analyze_fn = partial(_analyze_file_with_cache, root=root, cache_entries=cache_entries)
        pool_cls = ProcessPoolExecutor if use_process else ThreadPoolExecutor
        with pool_cls(max_workers=max_workers) as pool:
            analyzed = list(pool.map(analyze_fn, index.files))

    imports_by_module: dict[str, list[ImportInfo]] = {}
    updated_cache: dict[str, dict[str, object]] = {}
    for file_analysis, imports, sha256 in analyzed:
        imports_by_module[file_analysis.module_path] = imports
        updated_cache[file_analysis.path] = {
            "sha256": sha256,
            "module_path": file_analysis.module_path,
            "analysis": make_cache_payload(file_analysis, imports),
        }

    nodes = sorted(file_map)
    edges = build_graph_edges(file_map, imports_by_module)
    adjacency = build_adjacency(edges)
    fan_in, fan_out = compute_fan_metrics(nodes, edges, adjacency)

    file_analyses = sorted([t[0] for t in analyzed], key=lambda f: f.path)
    updated_files: list[FileAnalysis] = [
        FileAnalysis(
            path=fa.path,
            module_path=fa.module_path,
            loc=fa.loc,
            size_bytes=fa.size_bytes,
            docstring=fa.docstring,
            imports=fa.imports,
            classes=fa.classes,
            functions=fa.functions,
            cyclomatic_complexity=fa.cyclomatic_complexity,
            fan_in=fan_in[fa.module_path],
            fan_out=fan_out[fa.module_path],
        )
        for fa in file_analyses
    ]

    cycles = detect_cycles(nodes, adjacency)
    generated_at = datetime.now(UTC).isoformat()
    try:
        write_analysis_cache(cache_path, updated_cache, generated_at=generated_at)
    except Exception as exc:  # noqa: BLE001
        _logger.warning("cache write failed (continuing without cache): %s", exc)
    return AnalysisResult(
        repo_root=index.repo_root,
        generated_at=generated_at,
        file_count=index.file_count,
        module_count=len(nodes),
        files=updated_files,
        dependency_graph_nodes=nodes,
        dependency_graph_edges=edges,
        cycles=cycles,
    )


def write_analysis(
    analysis: AnalysisResult,
    analysis_path: Path,
    dependency_graph_path: Path,
) -> None:
    analysis_payload = {
        "artifact_metadata": build_artifact_metadata(
            "analysis", generated_at=analysis.generated_at
        ),
        "repo_root": analysis.repo_root,
        "generated_at": analysis.generated_at,
        "file_count": analysis.file_count,
        "module_count": analysis.module_count,
        "files": [asdict(fa) for fa in analysis.files],
        "dependency_graph": {
            "nodes": analysis.dependency_graph_nodes,
            "edges": [asdict(e) for e in analysis.dependency_graph_edges],
        },
        "cycles": analysis.cycles,
    }
    with analysis_path.open("w", encoding="utf-8") as fh:
        json.dump(analysis_payload, fh, indent=2)
        fh.write("\n")

    dependency_payload = {
        "artifact_metadata": build_artifact_metadata(
            "dependency_graph", generated_at=analysis.generated_at
        ),
        "nodes": analysis.dependency_graph_nodes,
        "edges": [asdict(e) for e in analysis.dependency_graph_edges],
    }
    with dependency_graph_path.open("w", encoding="utf-8") as fh:
        json.dump(dependency_payload, fh, indent=2)
        fh.write("\n")
