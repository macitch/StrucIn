"""Analysis cache: SHA-256-keyed per-file persistence for AST analysis results.

Cache entries are keyed by relative file path.  Each entry stores:

- ``sha256``      — content hash of the source file at analysis time.
- ``module_path`` — the resolved module path (invalidates on rename).
- ``analysis``    — serialised ``FileAnalysis`` + ``ImportInfo`` payload.

On read, both the hash and module_path must match before the cached entry
is used.  Any mismatch triggers a fresh analysis pass.

The top-level JSON payload includes a ``cache_version`` field.  If the
field is absent or does not equal :data:`CACHE_VERSION`, the entire cache
file is discarded so stale entries can never surface after a schema change.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from strucin.core.artifacts import build_artifact_metadata
from strucin.core.models import ClassInfo, FileAnalysis, FunctionInfo, ImportInfo

#: Bump this constant whenever the cache schema changes to force a full
#: re-analysis on all existing installations.
CACHE_VERSION = "1"


def hash_file(path: Path) -> str:
    """Return the SHA-256 hex digest of the file at *path*."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def make_cache_payload(
    file_analysis: FileAnalysis,
    imports: list[ImportInfo],
) -> dict[str, object]:
    """Serialise a ``FileAnalysis`` + imports list for cache storage."""
    return {
        "path": file_analysis.path,
        "module_path": file_analysis.module_path,
        "loc": file_analysis.loc,
        "size_bytes": file_analysis.size_bytes,
        "docstring": file_analysis.docstring,
        "imports": [asdict(item) for item in imports],
        "classes": [asdict(item) for item in file_analysis.classes],
        "functions": [asdict(item) for item in file_analysis.functions],
        "cyclomatic_complexity": file_analysis.cyclomatic_complexity,
    }


def restore_cached_analysis(
    payload: dict[str, object],
) -> tuple[FileAnalysis, list[ImportInfo]] | None:
    """Reconstruct a ``(FileAnalysis, imports)`` pair from a cache payload.

    Returns ``None`` if the payload is structurally invalid so the caller
    can fall back to a fresh analysis pass.
    """
    try:
        imports = [ImportInfo(**item) for item in payload["imports"]]  # type: ignore[attr-defined]
        classes = [ClassInfo(**item) for item in payload["classes"]]  # type: ignore[attr-defined]
        functions = [FunctionInfo(**item) for item in payload["functions"]]  # type: ignore[attr-defined]
        file_analysis = FileAnalysis(
            path=str(payload["path"]),
            module_path=str(payload["module_path"]),
            loc=int(payload["loc"]),  # type: ignore[call-overload]
            size_bytes=int(payload["size_bytes"]),  # type: ignore[call-overload]
            docstring=payload["docstring"] if isinstance(payload["docstring"], str) else None,
            imports=imports,
            classes=classes,
            functions=functions,
            cyclomatic_complexity=int(payload["cyclomatic_complexity"]),  # type: ignore[call-overload]
            fan_in=0,
            fan_out=0,
        )
    except (KeyError, TypeError, ValueError):
        return None
    return file_analysis, imports


def load_analysis_cache(cache_path: Path) -> dict[str, dict[str, object]]:
    """Load per-file cache entries from *cache_path*; returns empty dict on miss.

    Returns an empty dict when the file is absent, unreadable, or was written
    by a different :data:`CACHE_VERSION` so callers always get a clean slate.
    """
    if not cache_path.exists():
        return {}
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("cache_version") != CACHE_VERSION:
        return {}
    files_payload = payload.get("files")
    if not isinstance(files_payload, dict):
        return {}
    entries: dict[str, dict[str, object]] = {}
    for relative_path, entry in files_payload.items():
        if not isinstance(relative_path, str) or not isinstance(entry, dict):
            continue
        entries[relative_path] = entry
    return entries


def write_analysis_cache(
    cache_path: Path,
    entries: dict[str, dict[str, object]],
    generated_at: str,
) -> None:
    """Persist *entries* to *cache_path* as JSON."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "cache_version": CACHE_VERSION,
        "artifact_metadata": build_artifact_metadata("analysis_cache", generated_at=generated_at),
        "files": entries,
    }
    cache_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
