"""Discover import roots without importing packages or executing build scripts."""

from __future__ import annotations

import configparser
import hashlib
import json
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from strucin.exceptions import ConfigError


@dataclass(frozen=True)
class SourceRoot:
    path: Path
    package: str = ""


def parse_source_roots(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise ConfigError("scan.source_roots must be a non-empty list of relative directories")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ConfigError("Each source root must be a non-empty directory name")
    return tuple(item.strip() for item in value)


def _table(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _pyproject_roots(path: Path) -> list[tuple[str, str]]:
    if not path.is_file():
        return []
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise ConfigError("Cannot read pyproject.toml; set scan.source_roots explicitly") from exc
    tool = _table(data.get("tool"))
    setuptools = _table(tool.get("setuptools"))
    mapping = setuptools.get("package-dir")
    if mapping is not None:
        if not isinstance(mapping, dict) or any(not isinstance(v, str) for v in mapping.values()):
            raise ConfigError("tool.setuptools.package-dir must map package names to directories")
        if mapping:
            return [(directory or ".", package) for package, directory in mapping.items()]
    find = _table(_table(setuptools.get("packages")).get("find"))
    if "where" in find:
        return [(directory, "") for directory in parse_source_roots(find["where"])]
    if find or "find" in _table(setuptools.get("packages")):
        return [(".", "")]
    poetry = _table(tool.get("poetry"))
    if "packages" in poetry:
        packages = poetry["packages"]
        if not isinstance(packages, list) or any(not isinstance(item, dict) for item in packages):
            raise ConfigError("tool.poetry.packages must be a list of package tables")
        return [
            (directory, "")
            for directory in parse_source_roots([item.get("from", ".") for item in packages])
        ]
    # Explicit flat packages/modules disable the conventional src heuristic.
    if "packages" in setuptools or "py-modules" in setuptools:
        return [(".", "")]
    return []


def _setup_cfg_roots(path: Path) -> list[tuple[str, str]]:
    if not path.is_file():
        return []
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(path.read_text(encoding="utf-8"))
    except (configparser.Error, UnicodeError) as exc:
        raise ConfigError("Cannot read setup.cfg; set scan.source_roots explicitly") from exc
    mapping = parser.get("options", "package_dir", fallback="")
    if mapping.strip():
        roots = []
        for line in mapping.splitlines():
            if not line.strip():
                continue
            package, separator, directory = line.partition("=")
            if not separator:
                raise ConfigError("options.package_dir must map package names to directories")
            roots.append((directory.strip() or ".", package.strip()))
        return roots
    where = parser.get("options.packages.find", "where", fallback="")
    if where.strip():
        return [
            (directory, "")
            for directory in parse_source_roots(
                [line.strip() for line in where.splitlines() if line.strip()]
            )
        ]
    if parser.has_option("options", "packages") or parser.has_option("options", "py_modules"):
        return [(".", "")]
    return []


def _validate_root(root: Path, directory: str, package: str) -> SourceRoot:
    relative = Path(directory)
    if relative.is_absolute() or ".." in relative.parts:
        raise ConfigError(f"Source root must be relative and cannot contain '..': {directory!r}")
    if package and any(not part.isidentifier() for part in package.split(".")):
        raise ConfigError(f"Invalid source-root package name: {package!r}")
    try:
        resolved = (root / relative).resolve()
    except (OSError, RuntimeError) as exc:
        raise ConfigError(f"Cannot resolve source root: {directory!r}") from exc
    if not resolved.is_relative_to(root):
        raise ConfigError(f"Source root escapes the repository: {directory!r}")
    if not resolved.is_dir():
        raise ConfigError(f"Source root is not a directory: {directory!r}")
    # os.walk visits the real directory rather than traversing directory symlinks.
    return SourceRoot(resolved, package)


def resolve_source_roots(
    root: Path, overrides: Sequence[str] | None = None
) -> tuple[SourceRoot, ...]:
    root = root.resolve()
    if overrides is not None:
        configured = [(directory, "") for directory in parse_source_roots(overrides)]
    else:
        configured = _pyproject_roots(root / "pyproject.toml") or _setup_cfg_roots(
            root / "setup.cfg"
        )
        if not configured and (root / "src").is_dir() and not (root / "src/__init__.py").exists():
            configured = [("src", "")]
    roots: dict[Path, SourceRoot] = {}
    for directory, package in configured:
        item = _validate_root(root, directory, package)
        if item.path in roots and roots[item.path].package != package:
            raise ConfigError(f"Conflicting package names for source root: {directory!r}")
        roots[item.path] = item
    roots.setdefault(root, SourceRoot(root))
    return tuple(sorted(roots.values(), key=lambda item: (-len(item.path.parts), str(item.path))))


def source_roots_key(root: Path, overrides: Sequence[str] | None = None) -> str:
    """Fingerprint import mapping rules for persistent semantic-index compatibility."""
    root = root.resolve()
    mappings = [
        (item.path.relative_to(root).as_posix(), item.package)
        for item in resolve_source_roots(root, overrides)
    ]
    return hashlib.sha256(json.dumps(["source-roots-v1", mappings]).encode("utf-8")).hexdigest()
