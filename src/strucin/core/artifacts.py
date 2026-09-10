from __future__ import annotations

from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from strucin._version import __version__
from strucin.exceptions import ConfigError

ARTIFACT_SCHEMA_VERSION = "1.0"


def resolve_artifact_path(root: Path, relative_path: str | Path) -> Path:
    """Resolve an artifact destination within its caller-selected root.

    Validate before creating directories, reading caches, writing artifacts, or
    deleting stale files. Resolving existing symlinks also catches dangling
    links and symlinked parents that would redirect an operation outside root.
    The root itself may be a symlink, since it is selected by the caller.
    """
    path = Path(relative_path)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ConfigError(f"Artifact path must be relative and cannot contain '..': {str(path)!r}")
    try:
        resolved_root = root.resolve()
        resolved_path = (resolved_root / path).resolve()
        # Python 3.13+ suppresses symlink loops during non-strict resolution.
        # Missing output paths are valid; loops and other filesystem errors are not.
        with suppress(FileNotFoundError):
            resolved_path.stat()
    except (OSError, RuntimeError) as exc:
        raise ConfigError(f"Cannot resolve artifact path {str(path)!r}: {exc}") from exc
    if resolved_path == resolved_root or not resolved_path.is_relative_to(resolved_root):
        raise ConfigError(f"Artifact path escapes its output directory: {str(path)!r}")
    return resolved_path


@dataclass(frozen=True)
class ArtifactMetadata:
    artifact_type: str
    generated_at: str
    schema_version: str
    strucin_version: str


def build_artifact_metadata(artifact_type: str, generated_at: str | None = None) -> dict[str, str]:
    timestamp = generated_at or datetime.now(UTC).isoformat()
    return asdict(
        ArtifactMetadata(
            artifact_type=artifact_type,
            generated_at=timestamp,
            schema_version=ARTIFACT_SCHEMA_VERSION,
            strucin_version=__version__,
        )
    )
