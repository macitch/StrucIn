from __future__ import annotations

import io
import json
import os
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

from strucin.core.artifacts import build_artifact_metadata
from strucin.core.privacy import anonymize_index
from strucin.core.repository_files import read_repository_bytes, resolve_repository_file
from strucin.core.source_roots import SourceRoot, resolve_source_roots
from strucin.exceptions import AnalysisError

EXCLUDED_DIRS = {".git", "__pycache__", "node_modules", "venv", ".venv"}


@dataclass(frozen=True)
class FileMetadata:
    path: str
    module_path: str
    loc: int
    size_bytes: int


@dataclass(frozen=True)
class RepoIndex:
    repo_root: str
    generated_at: str
    file_count: int
    files: list[FileMetadata]


def _module_path_from_relative(relative_path: Path) -> str:
    without_suffix = relative_path.with_suffix("")
    parts = list(without_suffix.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]

    if not parts:
        return "__init__"

    return ".".join(parts)


def _count_loc(raw: bytes) -> int:
    with io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8", errors="ignore") as file:
        return sum(1 for _ in file)


def _build_file_metadata(
    root: Path, file_path: Path, *, source_roots: tuple[SourceRoot, ...] = ()
) -> FileMetadata | None:
    if resolve_repository_file(root, file_path) is None:
        return None
    raw = read_repository_bytes(root, file_path)
    relative_path = file_path.relative_to(root)
    module_path = _module_path_from_relative(relative_path)
    for source_root in source_roots:
        if file_path.is_relative_to(source_root.path):
            import_path = file_path.relative_to(source_root.path)
            module_path = _module_path_from_relative(import_path)
            if source_root.package:
                suffix = "" if import_path == Path("__init__.py") else f".{module_path}"
                module_path = f"{source_root.package}{suffix}"
            break
    return FileMetadata(
        path=relative_path.as_posix(),
        module_path=module_path,
        loc=_count_loc(raw),
        size_bytes=len(raw),
    )


def scan_repository(
    repo_path: Path,
    excluded_dirs: set[str] | None = None,
    max_workers: int | None = None,
    *,
    source_roots: Sequence[str] | None = None,
) -> RepoIndex:
    root = repo_path.resolve()
    import_roots = resolve_source_roots(root, source_roots)
    active_excluded_dirs = excluded_dirs if excluded_dirs is not None else EXCLUDED_DIRS
    python_file_paths: list[Path] = []

    for current_root, dir_names, file_names in os.walk(root, topdown=True):
        dir_names[:] = [dir_name for dir_name in dir_names if dir_name not in active_excluded_dirs]

        current_root_path = Path(current_root)
        for file_name in file_names:
            if not file_name.endswith(".py"):
                continue
            python_file_paths.append(current_root_path / file_name)

    if max_workers == 1:
        candidates = [
            _build_file_metadata(root, file_path, source_roots=import_roots)
            for file_path in python_file_paths
        ]
    else:
        build_metadata = partial(_build_file_metadata, root, source_roots=import_roots)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            candidates = list(executor.map(build_metadata, python_file_paths))

    files = [file for file in candidates if file is not None]
    files.sort(key=lambda item: item.path)
    modules: dict[str, str] = {}
    for file in files:
        if file.module_path in modules:
            raise AnalysisError(
                f"Ambiguous module {file.module_path!r}: {modules[file.module_path]!r} "
                f"and {file.path!r}. Adjust source roots or exclude the duplicate directory."
            )
        modules[file.module_path] = file.path
    return RepoIndex(
        repo_root=str(root),
        generated_at=datetime.now(UTC).isoformat(),
        file_count=len(files),
        files=files,
    )


def write_repo_index(index: RepoIndex, output_path: Path, *, safe_mode: bool = False) -> None:
    if safe_mode:
        index = anonymize_index(index)
    payload = {
        "artifact_metadata": build_artifact_metadata("repo_index", generated_at=index.generated_at),
        "repo_root": index.repo_root,
        "generated_at": index.generated_at,
        "file_count": index.file_count,
        "files": [asdict(file_info) for file_info in index.files],
    }
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2)
        file.write("\n")
