from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from strucin.cli.main import main
from strucin.core import analysis_cache, analyzer, explainer
from strucin.core.analyzer import analyze_repository
from strucin.exceptions import ConfigError


@pytest.fixture(autouse=True)
def no_live_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(explainer, "_detect_llm", lambda config: None)


def make_repo(root: Path) -> None:
    (root / "sample.py").write_text(
        '"""SYNTHETIC_PRIVATE_DOCSTRING"""\n'
        "import os\nclass Example:\n    pass\n"
        "def run(value):\n    if value:\n        return 1\n    return 0\n",
        encoding="utf-8",
    )
    (root / ".strucin.toml").write_text(
        '[performance]\nmax_workers = 1\nexecutor = "thread"\n', encoding="utf-8"
    )


def cache_path(root: Path, kind: str) -> Path:
    return (
        root
        / ".strucin_cache"
        / {
            "analysis": "analysis_cache.json",
            "explain": "explain_cache.json",
            "safe_explain": "explain_safe_cache.json",
        }[kind]
    )


def run_command(root: Path, kind: str) -> int:
    if kind == "analysis":
        return main(["analyze", str(root), "--json"])
    options = ["--safe-mode"] if kind == "safe_explain" else []
    return main(["explain", "--path", str(root), *options])


@pytest.mark.parametrize("kind", ["analysis", "explain", "safe_explain"])
@pytest.mark.parametrize(
    "bad_content",
    [
        b"{",
        b"\xff\xfe",
        b"[]",
        b"null",
        b'{"files": NaN}',
        pytest.param(b"[" * 2000 + b"]" * 2000, id="deep-json"),
    ],
)
def test_cli_recovers_from_damaged_caches(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    kind: str,
    bad_content: bytes,
) -> None:
    make_repo(tmp_path)
    path = cache_path(tmp_path, kind)
    path.parent.mkdir()
    path.write_bytes(bad_content)
    assert run_command(tmp_path, kind) == 0
    captured = capsys.readouterr()
    if kind == "analysis":
        assert json.loads(captured.out)["file_count"] == 1
    else:
        assert (tmp_path / "docs/EXPLAIN.md").is_file()
    repaired = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(repaired, dict)
    assert "cache" in caplog.text.lower()
    if kind == "safe_explain":
        assert "SYNTHETIC_PRIVATE_DOCSTRING" not in path.read_text(encoding="utf-8")
        assert not cache_path(tmp_path, "analysis").exists()


@pytest.mark.parametrize("kind", ["analysis", "explain", "safe_explain"])
@pytest.mark.parametrize("error", [PermissionError, OSError, FileNotFoundError])
def test_cache_read_errors_recompute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    kind: str,
    error: type[OSError],
) -> None:
    make_repo(tmp_path)
    path = cache_path(tmp_path, kind)
    path.parent.mkdir()
    path.write_text("old cache", encoding="utf-8")
    original_read = Path.read_text

    def unreadable(self: Path, *args: object, **kwargs: object) -> str:
        if self == path:
            raise error("simulated read failure with PRIVATE_CONTENT")
        return original_read(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", unreadable)
    assert run_command(tmp_path, kind) == 0
    assert json.loads(path.read_bytes())["cache_version"]
    assert "PRIVATE_CONTENT" not in caplog.text


@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("path", "different.py"),
        ("module_path", "different"),
        ("loc", "not a number"),
        ("loc", True),
        ("loc", -1),
        ("size_bytes", float("inf")),
        ("docstring", []),
        ("imports", [{"kind": "import", "module": None, "level": 0, "names": [42]}]),
        ("imports", [{"kind": "from", "module": {}, "level": 1, "names": ["thing"]}]),
        ("imports", [{"kind": "invalid", "module": None, "level": 0, "names": []}]),
        ("imports", [{"kind": "from", "module": "os", "level": -1, "names": []}]),
        ("classes", [{"name": [], "lineno": 1, "docstring": None}]),
        ("classes", [{"name": "Example", "lineno": "one", "docstring": None}]),
        (
            "functions",
            [{"name": "run", "lineno": 1, "docstring": None, "cyclomatic_complexity": "two"}],
        ),
        ("cyclomatic_complexity", False),
    ],
)
def test_invalid_analysis_entries_are_recomputed(
    tmp_path: Path, field: str, bad_value: object
) -> None:
    make_repo(tmp_path)
    original = analyze_repository(tmp_path, max_workers=1)
    path = cache_path(tmp_path, "analysis")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["files"]["sample.py"]["analysis"][field] = bad_value
    path.write_text(json.dumps(payload), encoding="utf-8")
    repaired = analyze_repository(tmp_path, max_workers=1)
    assert repaired.files == original.files
    assert repaired.dependency_graph_edges == original.dependency_graph_edges
    assert json.loads(path.read_text(encoding="utf-8"))["files"]["sample.py"]["analysis"] == (
        analysis_cache.make_cache_payload(original.files[0], original.files[0].imports)
    )


def test_valid_analysis_entries_survive_neighbor_corruption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_repo(tmp_path)
    (tmp_path / "other.py").write_text("x = 1\n", encoding="utf-8")
    analyze_repository(tmp_path, max_workers=1)
    path = cache_path(tmp_path, "analysis")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["files"]["other.py"]["analysis"]["loc"] = None
    payload["files"]["bad.py"] = []
    path.write_text(json.dumps(payload), encoding="utf-8")
    original_parse = analyzer._analyze_single_file
    parsed: list[str] = []

    def record_parse(metadata, source):
        parsed.append(metadata.path)
        return original_parse(metadata, source)

    monkeypatch.setattr(analyzer, "_analyze_single_file", record_parse)
    assert analyze_repository(tmp_path, max_workers=1).file_count == 2
    assert parsed == ["other.py"]


@pytest.mark.parametrize(
    "invalid_entry",
    [
        None,
        [],
        "bad",
        {"content": "bad"},
        {"content": [], "generated_at": "2026-09-13T00:00:00+00:00"},
        {"content": "bad", "generated_at": 123},
        {"content": "bad", "generated_at": "not-a-date"},
    ],
)
def test_narration_discards_invalid_entries_before_eviction(
    tmp_path: Path, invalid_entry: object
) -> None:
    make_repo(tmp_path)
    path = cache_path(tmp_path, "explain")
    path.parent.mkdir()
    entries = {f"bad-{i}": copy.deepcopy(invalid_entry) for i in range(60)}
    entries["valid"] = {"content": "Keep this entry", "generated_at": "2026-09-13T00:00:00+00:00"}
    path.write_text(
        json.dumps({"cache_version": explainer.CACHE_VERSION, "entries": entries}), encoding="utf-8"
    )
    output = explainer.explain_repository(tmp_path, max_workers=1)
    repaired = json.loads(path.read_text(encoding="utf-8"))["entries"]
    assert set(repaired) == {"valid", output.cache_key}
    assert repaired["valid"]["content"] == "Keep this entry"


@pytest.mark.parametrize("safe_mode", [False, True])
def test_explain_refresh_never_loads_old_narration_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, safe_mode: bool
) -> None:
    make_repo(tmp_path)

    def unexpected_read(path: Path):
        pytest.fail("refresh must bypass the narration cache read")

    monkeypatch.setattr(explainer, "_load_cache", unexpected_read)
    output = explainer.explain_repository(
        tmp_path, refresh=True, safe_mode=safe_mode, max_workers=1
    )
    assert "StrucIn Architecture Narration" in output.content


@pytest.mark.parametrize("kind", ["analysis", "explain", "safe_explain"])
def test_cache_write_failure_keeps_computed_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, kind: str
) -> None:
    make_repo(tmp_path)

    def failed_write(*args: object, **kwargs: object) -> None:
        raise PermissionError("simulated persistence failure")

    if kind == "analysis":
        monkeypatch.setattr(analyzer, "write_analysis_cache", failed_write)
        assert analyze_repository(tmp_path, max_workers=1).file_count == 1
    else:
        monkeypatch.setattr(explainer, "_write_cache", failed_write)
        output = explainer.explain_repository(
            tmp_path, safe_mode=kind == "safe_explain", max_workers=1
        )
        assert "StrucIn Architecture Narration" in output.content
    assert "cache" in caplog.text.lower()


@pytest.mark.parametrize("kind", ["analysis", "explain", "safe_explain"])
def test_cache_path_escape_still_fails(tmp_path: Path, kind: str) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    make_repo(root)
    outside = tmp_path / "outside.json"
    outside.write_text("OUTSIDE_SENTINEL", encoding="utf-8")
    path = cache_path(root, kind)
    path.parent.mkdir()
    path.symlink_to(outside)
    with pytest.raises(ConfigError, match="escapes"):
        if kind == "analysis":
            analyze_repository(root, max_workers=1)
        else:
            explainer.explain_repository(root, safe_mode=kind == "safe_explain", max_workers=1)
    assert outside.read_text(encoding="utf-8") == "OUTSIDE_SENTINEL"


def test_cli_recovery_warning_preserves_json_and_omits_cache_contents(tmp_path: Path) -> None:
    make_repo(tmp_path)
    path = cache_path(tmp_path, "analysis")
    path.parent.mkdir()
    path.write_text('{"secret": "SYNTHETIC_CACHE_SECRET"', encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "strucin.cli", "analyze", str(tmp_path), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["file_count"] == 1
    assert "analysis cache" in result.stderr
    assert "SYNTHETIC_CACHE_SECRET" not in result.stdout + result.stderr
