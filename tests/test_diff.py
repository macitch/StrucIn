from __future__ import annotations

import json
from pathlib import Path

import pytest

from strucin.core.diff import diff_analyses, render_diff_json, render_diff_markdown
from strucin.exceptions import AnalysisError


def _write_analysis(path: Path, files: list[dict], cycles: list[list[str]]) -> None:
    payload = {
        "generated_at": "2025-01-01T00:00:00",
        "file_count": len(files),
        "module_count": len(files),
        "files": files,
        "dependency_graph": {"nodes": [], "edges": []},
        "cycles": cycles,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _make_file(
    module_path: str,
    loc: int = 10,
    fan_in: int = 0,
    fan_out: int = 0,
    cyclomatic_complexity: int = 1,
) -> dict:
    return {
        "path": f"{module_path.replace('.', '/')}.py",
        "module_path": module_path,
        "loc": loc,
        "size_bytes": loc * 40,
        "fan_in": fan_in,
        "fan_out": fan_out,
        "cyclomatic_complexity": cyclomatic_complexity,
    }


def test_diff_added_and_removed_modules(tmp_path: Path) -> None:
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    _write_analysis(before, [_make_file("pkg.a"), _make_file("pkg.b")], [])
    _write_analysis(after, [_make_file("pkg.b"), _make_file("pkg.c")], [])

    result = diff_analyses(before, after)
    assert result.added_modules == ["pkg.c"]
    assert result.removed_modules == ["pkg.a"]
    assert result.summary.modules_added == 1
    assert result.summary.modules_removed == 1


def test_diff_new_and_resolved_cycles(tmp_path: Path) -> None:
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    _write_analysis(before, [_make_file("a")], [["a", "b"]])
    _write_analysis(after, [_make_file("a")], [["c", "d"]])

    result = diff_analyses(before, after)
    assert len(result.new_cycles) == 1
    assert len(result.resolved_cycles) == 1


def test_diff_complexity_changes(tmp_path: Path) -> None:
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    _write_analysis(before, [_make_file("pkg.a", cyclomatic_complexity=5)], [])
    _write_analysis(after, [_make_file("pkg.a", cyclomatic_complexity=12)], [])

    result = diff_analyses(before, after)
    assert len(result.complexity_changes) == 1
    assert result.complexity_changes[0].delta == 7


def test_diff_loc_changes(tmp_path: Path) -> None:
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    _write_analysis(before, [_make_file("pkg.a", loc=100)], [])
    _write_analysis(after, [_make_file("pkg.a", loc=150)], [])

    result = diff_analyses(before, after)
    assert len(result.loc_changes) == 1
    assert result.loc_changes[0].delta == 50
    assert result.summary.total_loc_delta == 50


def test_diff_coupling_changes(tmp_path: Path) -> None:
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    _write_analysis(before, [_make_file("pkg.a", fan_out=1)], [])
    _write_analysis(after, [_make_file("pkg.a", fan_out=5)], [])

    result = diff_analyses(before, after)
    assert len(result.coupling_changes) == 1


def test_diff_no_changes(tmp_path: Path) -> None:
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    files = [_make_file("pkg.a")]
    _write_analysis(before, files, [])
    _write_analysis(after, files, [])

    result = diff_analyses(before, after)
    assert result.added_modules == []
    assert result.removed_modules == []
    assert result.summary.files_changed == 0


def test_diff_invalid_file(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    good = tmp_path / "good.json"
    _write_analysis(good, [], [])

    with pytest.raises(AnalysisError, match="invalid JSON"):
        diff_analyses(bad, good)


def test_diff_missing_keys(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    good = tmp_path / "good.json"
    _write_analysis(good, [], [])

    with pytest.raises(AnalysisError, match="missing required keys"):
        diff_analyses(bad, good)


def test_render_diff_markdown(tmp_path: Path) -> None:
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    _write_analysis(before, [_make_file("pkg.a", loc=10)], [])
    _write_analysis(after, [_make_file("pkg.a", loc=20), _make_file("pkg.b")], [])

    result = diff_analyses(before, after)
    md = render_diff_markdown(result)
    assert "# StrucIn Diff Report" in md
    assert "pkg.b" in md
    assert "LOC Changes" in md


def test_render_diff_json(tmp_path: Path) -> None:
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    _write_analysis(before, [], [])
    _write_analysis(after, [_make_file("pkg.a")], [])

    result = diff_analyses(before, after)
    output = render_diff_json(result)
    parsed = json.loads(output)
    assert "added_modules" in parsed
    assert "summary" in parsed
