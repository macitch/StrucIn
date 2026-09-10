"""Exercise the Action runner with fresh, stale, malformed, and failed analyses."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from strucin.cli import action
from strucin.core.analyzer import analyze_repository


def make_repo(root: Path, *, cyclic: bool, custom_paths: bool = False) -> dict[str, Path]:
    source = root / "src/private_pkg"
    source.mkdir(parents=True)
    (source / "a.py").write_text("import private_pkg.b\n", encoding="utf-8")
    (source / "b.py").write_text(
        "import private_pkg.a\n" if cyclic else "x = 1\n", encoding="utf-8"
    )
    filenames = {
        "analysis": "analysis.json",
        "graph": "dependency_graph.json",
        "report": "docs/REPORT.md",
        "index": "repo_index.json",
    }
    if custom_paths:
        filenames = {
            "analysis": "outputs/analysis.json",
            "graph": "graphs/deps.json",
            "report": "reports/custom report.md",
            "index": "indexes/repo.json",
        }
        (root / ".strucin.toml").write_text(
            "[output]\n"
            + "\n".join(
                f"{key} = {json.dumps(filenames[name])}"
                for key, name in [
                    ("analysis", "analysis"),
                    ("dependency_graph", "graph"),
                    ("report", "report"),
                    ("repo_index", "index"),
                ]
            ),
            encoding="utf-8",
        )
    return {name: root / filename for name, filename in filenames.items()}


def outputs(path: Path) -> dict[str, str]:
    lines = iter(path.read_text(encoding="utf-8").splitlines())
    parsed: dict[str, str] = {}
    for header in lines:
        name, delimiter = header.split("<<", 1)
        value = []
        for line in lines:
            if line == delimiter:
                break
            value.append(line)
        else:
            pytest.fail("Unterminated GitHub output")
        parsed[name] = "\n".join(value)
    return parsed


def action_env(monkeypatch: pytest.MonkeyPatch, root: Path, output: Path, **inputs: str) -> None:
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("STRUCIN_PATH", str(root))
    for name, default in [
        ("COMMAND", "report"),
        ("FAIL_ON_CYCLES", "true"),
        ("SAFE_MODE", "false"),
    ]:
        monkeypatch.setenv(f"STRUCIN_{name}", inputs.get(name, default))


@pytest.mark.parametrize("command", ["scan", "analyze", "report"])
@pytest.mark.parametrize("cyclic", [False, True])
@pytest.mark.parametrize("custom_paths", [False, True])
@pytest.mark.parametrize("strict", [False, True])
def test_action_gate_matches_current_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    cyclic: bool,
    custom_paths: bool,
    strict: bool,
) -> None:
    root = tmp_path / "repo"
    paths = make_repo(root, cyclic=cyclic, custom_paths=custom_paths)
    output = tmp_path / "github-output"
    action_env(monkeypatch, root, output, COMMAND=command, FAIL_ON_CYCLES=str(strict).lower())
    assert action.main() == int(cyclic and strict)
    result = outputs(output)
    assert result["cycles-found"] == str(cyclic).lower()
    assert result["cycle-count"] == str(int(cyclic))
    assert result["analysis-path"] == str(paths["analysis"])
    assert result["report-path"] == (str(paths["report"]) if command == "report" else "")
    analysis = json.loads(paths["analysis"].read_text(encoding="utf-8"))
    assert len(analysis["cycles"]) == int(cyclic)
    assert paths["graph"].is_file()
    if command == "report":
        assert paths["report"].is_file()
    if command == "scan":
        assert paths["index"].is_file()


@pytest.mark.parametrize("command", ["scan", "analyze", "report"])
@pytest.mark.parametrize("cyclic", [False, True])
@pytest.mark.parametrize("old_json", ["malformed", "stale"])
def test_action_replaces_old_snapshots_and_never_claims_old_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str, cyclic: bool, old_json: str
) -> None:
    root = tmp_path / "repo"
    paths = make_repo(root, cyclic=cyclic, custom_paths=True)
    paths["analysis"].parent.mkdir()
    paths["analysis"].write_text(
        "{broken"
        if old_json == "malformed"
        else json.dumps({"cycles": [] if cyclic else [["stale"]]}),
        encoding="utf-8",
    )
    # A misleading file at the former hardcoded path must have no effect either.
    (root / "analysis.json").write_text('{"cycles": [["wrong-path"]]}', encoding="utf-8")
    paths["report"].parent.mkdir()
    paths["report"].write_text("STALE REPORT", encoding="utf-8")
    output = tmp_path / "github-output"
    action_env(monkeypatch, root, output, COMMAND=command)
    assert action.main() == int(cyclic)
    result = outputs(output)
    assert result["cycles-found"] == str(cyclic).lower()
    assert len(json.loads(paths["analysis"].read_text(encoding="utf-8"))["cycles"]) == int(cyclic)
    if command == "report":
        assert "STALE REPORT" not in paths["report"].read_text(encoding="utf-8")
    else:
        assert result["report-path"] == ""
        assert paths["report"].read_text(encoding="utf-8") == "STALE REPORT"


def test_report_and_gate_share_one_analysis(tmp_path: Path) -> None:
    paths = make_repo(tmp_path, cyclic=True)
    with patch.object(action, "analyze_repository", wraps=analyze_repository) as analyze:
        result = action.run_action(tmp_path)
    assert analyze.call_count == 1
    snapshot = json.loads(paths["analysis"].read_text(encoding="utf-8"))
    report = paths["report"].read_text(encoding="utf-8")
    assert snapshot["generated_at"] in report
    assert result.cycle_count == len(snapshot["cycles"]) == 1


@pytest.mark.parametrize("command", ["scan", "analyze", "report"])
@pytest.mark.parametrize("configured", [False, True])
def test_safe_mode_does_not_disable_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str, configured: bool
) -> None:
    root = tmp_path / "repo"
    paths = make_repo(root, cyclic=True)
    if configured:
        (root / ".strucin.toml").write_text("[security]\nsafe_mode = true\n", encoding="utf-8")
    output = tmp_path / "github-output"
    action_env(monkeypatch, root, output, COMMAND=command, SAFE_MODE=str(not configured).lower())
    assert action.main() == 1
    assert outputs(output)["cycles-found"] == "true"
    assert "private_pkg" not in paths["analysis"].read_text(encoding="utf-8")
    if command == "report":
        assert "private_pkg" not in paths["report"].read_text(encoding="utf-8")
    assert not (root / ".strucin_cache/analysis_cache.json").exists()


@pytest.mark.parametrize(
    "operation", ["analyze_repository", "write_analysis", "write_markdown_report"]
)
@pytest.mark.parametrize("strict", [False, True])
def test_analysis_or_write_error_never_emits_false_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str, strict: bool
) -> None:
    root = tmp_path / "repo"
    make_repo(root, cyclic=False)
    output = tmp_path / "github-output"
    action_env(monkeypatch, root, output, FAIL_ON_CYCLES=str(strict).lower())
    with patch.object(action, operation, side_effect=OSError("injected failure")):
        assert action.main() == 1
    assert not output.exists()


def test_corrupt_internal_cache_fails_instead_of_reporting_no_cycles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    make_repo(root, cyclic=True)
    cache = root / ".strucin_cache/analysis_cache.json"
    cache.parent.mkdir()
    cache.write_text("{broken", encoding="utf-8")
    output = tmp_path / "github-output"
    action_env(monkeypatch, root, output)
    assert action.main() == 1
    assert not output.exists()


@pytest.mark.parametrize("value", ["perhaps", "1", ""])
@pytest.mark.parametrize("name", ["SAFE_MODE", "FAIL_ON_CYCLES"])
def test_invalid_boolean_inputs_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str, name: str
) -> None:
    root = tmp_path / "repo"
    make_repo(root, cyclic=True)
    output = tmp_path / "github-output"
    action_env(monkeypatch, root, output, **{name: value})
    assert action.main() == 1
    assert not output.exists()
    assert not (root / "analysis.json").exists()


def test_missing_repository_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "github-output"
    action_env(monkeypatch, tmp_path / "missing", output)
    assert action.main() == 1
    assert not output.exists()


def test_missing_github_output_fails_before_artifact_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_repo(tmp_path, cyclic=False)
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.setenv("STRUCIN_PATH", str(tmp_path))
    assert action.main() == 1
    assert not (tmp_path / "analysis.json").exists()


def test_command_is_data_not_shell_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    make_repo(root, cyclic=True)
    output = tmp_path / "github-output"
    sentinel = tmp_path / "should-not-exist"
    action_env(monkeypatch, root, output, COMMAND=f"report; touch {sentinel}")
    assert action.main() == 1
    assert not sentinel.exists()
    assert not output.exists()


def test_unusual_path_round_trips_without_injecting_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo ' $(literal)\ncycles-found=false"
    make_repo(root, cyclic=True, custom_paths=True)
    output = tmp_path / "github-output"
    action_env(monkeypatch, root, output)
    assert action.main() == 1
    result = outputs(output)
    assert set(result) == {"analysis-path", "report-path", "cycles-found", "cycle-count"}
    assert result["analysis-path"] == str(root / "outputs/analysis.json")
    assert result["cycles-found"] == "true"


def test_colliding_artifact_paths_fail_before_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_repo(tmp_path, cyclic=True)
    (tmp_path / ".strucin.toml").write_text(
        '[output]\nreport = "analysis.json"\n', encoding="utf-8"
    )
    output = tmp_path / "github-output"
    action_env(monkeypatch, tmp_path, output)
    assert action.main() == 1
    assert not output.exists()
    assert not (tmp_path / "analysis.json").exists()
