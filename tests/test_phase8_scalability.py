from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from strucin.core.analyzer import analyze_repository
from strucin.core.lifecycle import cleanup_stale_artifacts


def _seed_repo(tmp_path: Path) -> Path:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "a.py").write_text(
        "from . import b\n\n"
        "def load() -> int:\n"
        "    return b.value()\n",
        encoding="utf-8",
    )
    (tmp_path / "pkg" / "b.py").write_text(
        "def value() -> int:\n"
        "    return 1\n",
        encoding="utf-8",
    )
    return tmp_path


def test_phase8_incremental_analysis_cache_hashes_only_changed_files(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path)

    analyze_repository(repo, max_workers=1)
    cache_path = repo / ".strucin_cache" / "analysis_cache.json"
    assert cache_path.exists()
    before_cache = json.loads(cache_path.read_text(encoding="utf-8"))["files"]

    (repo / "pkg" / "b.py").write_text(
        "def value() -> int:\n"
        "    return 2\n",
        encoding="utf-8",
    )
    analyze_repository(repo, max_workers=1)
    after_cache = json.loads(cache_path.read_text(encoding="utf-8"))["files"]

    assert before_cache["pkg/b.py"]["sha256"] != after_cache["pkg/b.py"]["sha256"]
    assert before_cache["pkg/a.py"]["sha256"] == after_cache["pkg/a.py"]["sha256"]
    assert before_cache["pkg/__init__.py"]["sha256"] == after_cache["pkg/__init__.py"]["sha256"]


def test_phase8_cleanup_policy_removes_stale_cache_and_outputs(tmp_path: Path) -> None:
    old_output = tmp_path / "analysis.json"
    old_output.write_text("{}", encoding="utf-8")
    cache_dir = tmp_path / ".strucin_cache"
    cache_dir.mkdir()
    old_cache = cache_dir / "analysis_cache.json"
    old_cache.write_text("{}", encoding="utf-8")

    stale_epoch = (datetime.now() - timedelta(days=4)).timestamp()
    old_output.touch()
    old_cache.touch()
    old_output.chmod(0o644)
    old_cache.chmod(0o644)
    os.utime(old_output, (stale_epoch, stale_epoch))
    os.utime(old_cache, (stale_epoch, stale_epoch))

    removed = cleanup_stale_artifacts(
        repo_root=tmp_path,
        artifact_filenames={"analysis.json"},
        cache_retention_days=1,
    )

    assert old_output in removed
    assert old_cache in removed
    assert not old_output.exists()
    assert not old_cache.exists()
