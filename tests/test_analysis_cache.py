from __future__ import annotations

import json
from pathlib import Path

from strucin.core.analysis_cache import (
    CACHE_VERSION,
    load_analysis_cache,
    make_cache_payload,
    restore_cached_analysis,
    write_analysis_cache,
)
from strucin.core.models import FileAnalysis


def test_load_analysis_cache_returns_empty_when_file_absent(tmp_path: Path) -> None:
    result = load_analysis_cache(tmp_path / "nonexistent.json")
    assert result == {}


def test_load_analysis_cache_returns_empty_on_version_mismatch(tmp_path: Path) -> None:
    """A cache written with a different version is silently discarded."""
    cache_path = tmp_path / "cache.json"
    payload = {
        "cache_version": "0",
        "files": {
            "pkg/a.py": {"sha256": "abc", "module_path": "pkg.a"},
        },
    }
    cache_path.write_text(json.dumps(payload), encoding="utf-8")

    result = load_analysis_cache(cache_path)
    assert result == {}


def test_load_analysis_cache_returns_empty_when_version_absent(tmp_path: Path) -> None:
    """A cache without a cache_version field (legacy format) is discarded."""
    cache_path = tmp_path / "cache.json"
    payload = {
        "files": {
            "pkg/a.py": {"sha256": "abc", "module_path": "pkg.a"},
        },
    }
    cache_path.write_text(json.dumps(payload), encoding="utf-8")

    result = load_analysis_cache(cache_path)
    assert result == {}


def test_load_analysis_cache_returns_entries_on_version_match(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    entry: dict[str, object] = {"sha256": "abc", "module_path": "pkg.a"}
    payload = {
        "cache_version": CACHE_VERSION,
        "files": {"pkg/a.py": entry},
    }
    cache_path.write_text(json.dumps(payload), encoding="utf-8")

    result = load_analysis_cache(cache_path)
    assert "pkg/a.py" in result
    assert result["pkg/a.py"]["sha256"] == "abc"


def test_write_and_reload_analysis_cache_roundtrip(tmp_path: Path) -> None:
    """write_analysis_cache then load_analysis_cache preserves all entries."""
    cache_path = tmp_path / "cache.json"
    entry: dict[str, object] = {
        "sha256": "def456",
        "module_path": "app.main",
        "analysis": {},
    }
    write_analysis_cache(
        cache_path,
        {"app/main.py": entry},
        generated_at="2025-01-01T00:00:00+00:00",
    )

    result = load_analysis_cache(cache_path)
    assert "app/main.py" in result
    assert result["app/main.py"]["sha256"] == "def456"


def test_write_analysis_cache_stores_version_field(tmp_path: Path) -> None:
    """The written JSON must contain cache_version so future reads validate correctly."""
    cache_path = tmp_path / "cache.json"
    write_analysis_cache(cache_path, {}, generated_at="2025-01-01T00:00:00+00:00")

    raw = json.loads(cache_path.read_text(encoding="utf-8"))
    assert raw.get("cache_version") == CACHE_VERSION


# ---------------------------------------------------------------------------
# make_cache_payload / restore_cached_analysis
# ---------------------------------------------------------------------------

_SAMPLE_FILE_ANALYSIS = FileAnalysis(
    path="pkg/a.py",
    module_path="pkg.a",
    loc=10,
    size_bytes=200,
    docstring="A module.",
    imports=[],
    classes=[],
    functions=[],
    cyclomatic_complexity=2,
    fan_in=1,
    fan_out=3,
)


def test_make_cache_payload_restore_roundtrip() -> None:
    """make_cache_payload → restore_cached_analysis recreates the FileAnalysis."""
    payload = make_cache_payload(_SAMPLE_FILE_ANALYSIS, [])
    result = restore_cached_analysis(payload)
    assert result is not None
    restored_fa, restored_imports = result
    assert restored_fa.path == "pkg/a.py"
    assert restored_fa.module_path == "pkg.a"
    assert restored_fa.loc == 10
    assert restored_fa.docstring == "A module."
    assert restored_fa.cyclomatic_complexity == 2
    assert restored_imports == []


def test_restore_cached_analysis_none_docstring() -> None:
    """A payload with docstring=None restores cleanly."""
    fa = FileAnalysis(
        path="pkg/b.py",
        module_path="pkg.b",
        loc=5,
        size_bytes=50,
        docstring=None,
        imports=[],
        classes=[],
        functions=[],
        cyclomatic_complexity=1,
        fan_in=0,
        fan_out=0,
    )
    payload = make_cache_payload(fa, [])
    result = restore_cached_analysis(payload)
    assert result is not None
    assert result[0].docstring is None


def test_restore_cached_analysis_returns_none_on_missing_key() -> None:
    """A payload missing a required key triggers the fallback and returns None."""
    payload: dict[str, object] = {
        "path": "pkg/a.py",
        # "module_path" deliberately omitted
        "loc": 5,
        "size_bytes": 50,
        "docstring": None,
        "imports": [],
        "classes": [],
        "functions": [],
        # "cyclomatic_complexity" deliberately omitted
    }
    assert restore_cached_analysis(payload) is None


def test_restore_cached_analysis_returns_none_when_imports_not_list() -> None:
    """A payload where 'imports' is not a list triggers the fallback."""
    payload: dict[str, object] = {
        "path": "pkg/a.py",
        "module_path": "pkg.a",
        "loc": 5,
        "size_bytes": 50,
        "docstring": None,
        "imports": "not-a-list",
        "classes": [],
        "functions": [],
        "cyclomatic_complexity": 1,
    }
    assert restore_cached_analysis(payload) is None
