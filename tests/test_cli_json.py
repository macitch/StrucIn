from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from strucin.cli import ui
from strucin.cli.main import main

QUERY = 'normalize "token" in Zürich\n'
PROGRESS = {
    "scan": "Scanning repository files",
    "analyze": "Running AST analysis",
    "search": "Loading semantic index",
}


def make_repo(root: Path, *, timing: bool = True, structured: bool = False) -> None:
    (root / "sample.py").write_text(
        "def normalize_token(token):\n    return token.strip().lower()\n", encoding="utf-8"
    )
    (root / ".strucin.toml").write_text(
        '[search]\nembedding_model = "hashing-v1"\n'
        '[performance]\nmax_workers = 1\nexecutor = "thread"\n'
        f"[observability]\ntiming_enabled = {str(timing).lower()}\n"
        f"structured_logging = {str(structured).lower()}\n",
        encoding="utf-8",
    )
    for name in ("before.json", "after.json"):
        (root / name).write_text(
            '{"generated_at": "2026-09-11T00:00:00", "files": [], "cycles": []}',
            encoding="utf-8",
        )


def arguments(command: str, root: Path) -> list[str]:
    if command == "search":
        return [command, QUERY, "--path", str(root)]
    if command == "diff":
        return [command, str(root / "before.json"), str(root / "after.json")]
    return [command, str(root)]


def check_payload(command: str, text: str, *, safe_mode: bool = False) -> None:
    # Parse the entire stream: banners, ANSI escapes, and extra JSON must all fail.
    payload = json.loads(text)
    assert isinstance(payload, dict)
    assert "\x1b" not in text
    if command in {"scan", "analyze"}:
        assert payload["file_count"] == 1
    elif command == "search":
        assert payload["query"] == ("[REDACTED_QUERY]" if safe_mode else QUERY)
        assert payload["results"]
        assert payload["results"][0]["rank"] == 1
    else:
        assert payload["summary"]["files_changed"] == 0


@pytest.mark.parametrize("command", ["scan", "analyze", "search", "diff"])
@pytest.mark.parametrize("safe_mode", [False, True])
def test_json_subprocess_output_is_one_document(
    tmp_path: Path, command: str, safe_mode: bool
) -> None:
    make_repo(tmp_path)
    argv = [*arguments(command, tmp_path), "--json"]
    if safe_mode:
        argv.append("--safe-mode")
    result = subprocess.run(
        [sys.executable, "-m", "strucin.cli", *argv],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    check_payload(command, result.stdout, safe_mode=safe_mode)
    if command in PROGRESS:
        assert PROGRESS[command] in result.stderr
        assert "Timing" in result.stderr


@pytest.mark.parametrize("command", ["scan", "analyze", "search"])
@pytest.mark.parametrize("rich", [False, True])
@pytest.mark.parametrize(
    "timing,structured", [(False, False), (False, True), (True, False), (True, True)]
)
def test_json_keeps_progress_timings_and_logs_on_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
    rich: bool,
    timing: bool,
    structured: bool,
) -> None:
    make_repo(tmp_path, timing=timing, structured=structured)
    monkeypatch.setattr(ui, "_rich_available", rich)

    assert main([*arguments(command, tmp_path), "--json"]) == 0

    captured = capsys.readouterr()
    check_payload(command, captured.out)
    assert PROGRESS[command] in captured.err
    assert ("Timing" in captured.err) is timing
    events = [json.loads(line) for line in captured.err.splitlines() if line.startswith("{")]
    assert len(events) == int(structured)
    if structured:
        assert events[0]["event"] == "command_completed"
        assert events[0]["command"] == command


@pytest.mark.parametrize("command", ["scan", "analyze", "search"])
@pytest.mark.parametrize("rich", [False, True])
def test_human_output_still_uses_stdout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
    rich: bool,
) -> None:
    make_repo(tmp_path)
    monkeypatch.setattr(ui, "_rich_available", rich)
    assert main(arguments(command, tmp_path)) == 0
    captured = capsys.readouterr()
    assert PROGRESS[command] in captured.out
    assert "Timing" in captured.out
    assert captured.err == ""


@pytest.mark.parametrize("command", ["scan", "analyze", "search", "diff"])
def test_json_missing_inputs_leave_stdout_empty(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    assert main([*arguments(command, tmp_path / "missing"), "--json"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "does not exist" in captured.err


@pytest.mark.parametrize("command", ["scan", "analyze", "search"])
def test_json_failure_after_progress_leaves_stdout_empty(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    make_repo(tmp_path)
    artifact = {
        "scan": "repo_index.json",
        "analyze": "analysis.json",
        "search": "semantic_index.json",
    }[command]
    (tmp_path / artifact).mkdir()

    assert main([*arguments(command, tmp_path), "--json"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert PROGRESS[command] in captured.err
    assert "Error:" in captured.err


def test_json_search_empty_and_cached_results_remain_parseable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_repo(tmp_path)
    (tmp_path / "sample.py").unlink()
    for _ in range(2):
        assert main([*arguments("search", tmp_path), "--json"]) == 0
        captured = capsys.readouterr()
        assert json.loads(captured.out)["results"] == []
        assert PROGRESS["search"] in captured.err
    assert (tmp_path / "semantic_index.json").is_file()


def test_json_configuration_warning_is_only_on_stderr(tmp_path: Path) -> None:
    make_repo(tmp_path)
    (tmp_path / ".strucin.toml").write_text("broken = [\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "strucin.cli", "analyze", str(tmp_path), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["file_count"] == 1
    assert ".strucin.toml is invalid TOML" in result.stderr
