from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

from strucin.core.artifacts import build_artifact_metadata

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


def _count_loc(file_path: Path) -> int:
    with file_path.open("r", encoding="utf-8", errors="ignore") as file:
        return sum(1 for _ in file)


def _build_file_metadata(root: Path, file_path: Path) -> FileMetadata:
    relative_path = file_path.relative_to(root)
    return FileMetadata(
        path=relative_path.as_posix(),
        module_path=_module_path_from_relative(relative_path),
        loc=_count_loc(file_path),
        size_bytes=file_path.stat().st_size,
    )


def scan_repository(
    repo_path: Path,
    excluded_dirs: set[str] | None = None,
    max_workers: int | None = None,
) -> RepoIndex:
    root = repo_path.resolve()
    files: list[FileMetadata] = []
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
        files = [_build_file_metadata(root, file_path) for file_path in python_file_paths]
    else:
        build_metadata = partial(_build_file_metadata, root)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            files = list(executor.map(build_metadata, python_file_paths))

    files.sort(key=lambda item: item.path)
    return RepoIndex(
        repo_root=str(root),
        generated_at=datetime.now(UTC).isoformat(),
        file_count=len(files),
        files=files,
    )


def write_repo_index(index: RepoIndex, output_path: Path) -> None:
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
