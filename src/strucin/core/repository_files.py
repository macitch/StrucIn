"""Read Python and documentation files only from within the selected repository."""

from __future__ import annotations

import errno
import os
import stat
from pathlib import Path

from strucin.exceptions import AnalysisError

FILE_POLICY_VERSION = "1"
_MISSING_OR_LOOP = {errno.ENOENT, errno.ENOTDIR, errno.ELOOP}


def resolve_repository_file(root: Path, path: Path) -> Path | None:
    """Return a regular file's contained target, or skip broken/external links."""
    root = root.resolve()
    candidate = path if path.is_absolute() else root / path
    try:
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(root) or not resolved.is_file():
            return None
    except RuntimeError:  # pathlib reports symlink loops this way before Python 3.13
        return None
    except OSError as exc:
        if exc.errno in _MISSING_OR_LOOP:
            return None
        raise
    return resolved


def _open_contained_file(root: Path, resolved: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    directory_flag = getattr(os, "O_DIRECTORY", 0)
    if os.open not in os.supports_dir_fd or not no_follow or not directory_flag:
        # Portable fallback uses the canonical path, not the original symlink.
        return os.open(resolved, flags | no_follow)
    directory_flags = os.O_RDONLY | directory_flag | no_follow
    directory_fd = os.open(root, directory_flags)
    try:
        relative = resolved.relative_to(root)
        for part in relative.parts[:-1]:
            next_fd = os.open(part, directory_flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        return os.open(relative.name, flags | no_follow, dir_fd=directory_fd)
    finally:
        os.close(directory_fd)


def read_repository_bytes(root: Path, path: Path) -> bytes:
    """Revalidate at each read; on POSIX, open components without following links."""
    root = root.resolve()
    resolved = resolve_repository_file(root, path)
    if resolved is None:
        raise AnalysisError(f"Repository file is missing, non-regular, or outside the root: {path}")
    try:
        with os.fdopen(_open_contained_file(root, resolved), "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise AnalysisError(f"Repository file is no longer a regular file: {path}")
            return stream.read()
    except OSError as exc:
        raise AnalysisError(f"Cannot safely read repository file: {path}") from exc


def read_repository_text(root: Path, path: Path) -> str:
    raw = read_repository_bytes(root, path)
    return raw.decode("utf-8", errors="ignore").replace("\r\n", "\n").replace("\r", "\n")
