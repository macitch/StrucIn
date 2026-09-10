from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from strucin.core.artifacts import resolve_artifact_path


def cleanup_stale_artifacts(
    repo_root: Path,
    artifact_filenames: set[str],
    cache_retention_days: int,
) -> list[Path]:
    retention_days = max(cache_retention_days, 1)
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    removed: list[Path] = []

    root = repo_root.resolve()
    artifact_paths: list[Path] = []
    for filename in sorted(artifact_filenames):
        resolve_artifact_path(root, filename)
        artifact_paths.append(root / filename)
    resolve_artifact_path(root, ".strucin_cache")
    cache_dir = root / ".strucin_cache"
    if cache_dir.is_dir():
        for entry in sorted(cache_dir.iterdir()):
            if entry.is_file():
                resolve_artifact_path(root, entry.relative_to(root))
                artifact_paths.append(entry)

    # Validate the entire set before deleting any stale artifacts.
    # Unlink the requested entry, not a symlink's resolved target: a safe
    # in-repository link must never cause cleanup to delete its source file.
    for artifact_path in dict.fromkeys(artifact_paths):
        if not artifact_path.exists() or not artifact_path.is_file():
            continue
        if datetime.fromtimestamp(artifact_path.stat().st_mtime, tz=UTC) < cutoff:
            artifact_path.unlink(missing_ok=True)
            removed.append(artifact_path)

    return removed
