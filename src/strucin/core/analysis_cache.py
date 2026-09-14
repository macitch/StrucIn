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
import logging
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import cast

from strucin.core.artifacts import build_artifact_metadata
from strucin.core.cache_io import read_cache_json, write_cache_json
from strucin.core.models import ClassInfo, FileAnalysis, FunctionInfo, ImportInfo

#: Bump this constant whenever the schema or analysis semantics change to force a full
#: re-analysis on all existing installations.
CACHE_VERSION = "2"

_logger = logging.getLogger(__name__)


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


def _nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _optional_text(value: object) -> bool:
    return value is None or isinstance(value, str)


def _valid_import(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != {"kind", "module", "level", "names"}:
        return False
    names = value["names"]
    return (
        value["kind"] in ("import", "from")
        and _optional_text(value["module"])
        and _nonnegative_int(value["level"])
        and isinstance(names, list)
        and all(isinstance(name, str) and bool(name) for name in names)
    )


def _valid_symbol(value: object, *, function: bool = False) -> bool:
    fields = {"name", "lineno", "docstring"}
    if function:
        fields.add("cyclomatic_complexity")
    if not isinstance(value, dict) or set(value) != fields:
        return False
    return (
        isinstance(value["name"], str)
        and bool(value["name"])
        and _nonnegative_int(value["lineno"])
        and value["lineno"] > 0
        and _optional_text(value["docstring"])
        and (not function or _nonnegative_int(value["cyclomatic_complexity"]))
    )


def _valid_records(value: object, validator: Callable[[object], bool]) -> bool:
    return isinstance(value, list) and all(validator(item) for item in value)


def _valid_analysis_payload(payload: object) -> bool:
    if not isinstance(payload, dict) or "docstring" not in payload:
        return False
    return (
        all(
            isinstance(payload.get(key), str) and bool(payload[key])
            for key in ("path", "module_path")
        )
        and all(
            _nonnegative_int(payload.get(key))
            for key in ("loc", "size_bytes", "cyclomatic_complexity")
        )
        and _optional_text(payload["docstring"])
        and _valid_records(payload.get("imports"), _valid_import)
        and _valid_records(payload.get("classes"), _valid_symbol)
        and _valid_records(
            payload.get("functions"), lambda item: _valid_symbol(item, function=True)
        )
    )


def _valid_cache_entry(relative_path: str, entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    digest = entry.get("sha256")
    analysis = entry.get("analysis")
    return (
        isinstance(digest, str)
        and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest)
        and isinstance(analysis, dict)
        and _valid_analysis_payload(analysis)
        and analysis["path"] == relative_path
        and analysis["module_path"] == entry.get("module_path")
    )


def restore_cached_analysis(
    payload: dict[str, object],
) -> tuple[FileAnalysis, list[ImportInfo]] | None:
    """Reconstruct a ``(FileAnalysis, imports)`` pair from a cache payload.

    Returns ``None`` if the payload is structurally invalid so the caller
    can fall back to a fresh analysis pass.
    """
    if not _valid_analysis_payload(payload):
        return None
    try:
        imports = [ImportInfo(**item) for item in payload["imports"]]  # type: ignore[attr-defined]
        classes = [ClassInfo(**item) for item in payload["classes"]]  # type: ignore[attr-defined]
        functions = [FunctionInfo(**item) for item in payload["functions"]]  # type: ignore[attr-defined]
        file_analysis = FileAnalysis(
            path=cast(str, payload["path"]),
            module_path=cast(str, payload["module_path"]),
            loc=cast(int, payload["loc"]),
            size_bytes=cast(int, payload["size_bytes"]),
            docstring=payload["docstring"] if isinstance(payload["docstring"], str) else None,
            imports=imports,
            classes=classes,
            functions=functions,
            cyclomatic_complexity=cast(int, payload["cyclomatic_complexity"]),
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
    payload = read_cache_json(cache_path, kind="analysis cache")
    if payload is None or payload.get("cache_version") != CACHE_VERSION:
        return {}
    files_payload = payload.get("files")
    if not isinstance(files_payload, dict):
        _logger.warning("Ignoring analysis cache with invalid entries; rebuilding.")
        return {}
    entries: dict[str, dict[str, object]] = {}
    for relative_path, entry in files_payload.items():
        if not isinstance(relative_path, str) or not _valid_cache_entry(relative_path, entry):
            continue
        entries[relative_path] = entry
    if len(entries) != len(files_payload):
        _logger.warning(
            "Ignoring %d invalid analysis cache entries; recomputing.",
            len(files_payload) - len(entries),
        )
    return entries


def write_analysis_cache(
    cache_path: Path,
    entries: dict[str, dict[str, object]],
    generated_at: str,
) -> None:
    """Persist *entries* to *cache_path* as JSON."""
    payload = {
        "cache_version": CACHE_VERSION,
        "artifact_metadata": build_artifact_metadata("analysis_cache", generated_at=generated_at),
        "files": entries,
    }
    write_cache_json(cache_path, payload)
