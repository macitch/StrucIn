from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path


def cleanup_stale_artifacts(
    repo_root: Path,
    artifact_filenames: set[str],
    cache_retention_days: int,
) -> list[Path]:
    retention_days = max(cache_retention_days, 1)
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    removed: list[Path] = []

    for filename in artifact_filenames:
        artifact_path = repo_root / filename
        if not artifact_path.exists() or not artifact_path.is_file():
            continue
        if datetime.fromtimestamp(artifact_path.stat().st_mtime, tz=UTC) < cutoff:
            artifact_path.unlink(missing_ok=True)
            removed.append(artifact_path)

    cache_dir = repo_root / ".strucin_cache"
    if cache_dir.exists() and cache_dir.is_dir():
        for entry in sorted(cache_dir.iterdir()):
            if not entry.is_file():
                continue
            if datetime.fromtimestamp(entry.stat().st_mtime, tz=UTC) < cutoff:
                entry.unlink(missing_ok=True)
                removed.append(entry)

    return removed
