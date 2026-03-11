from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def _copy_fixture(tmp_path: Path, fixture_name: str) -> Path:
    source = Path(__file__).resolve().parent / "fixtures" / fixture_name
    destination = tmp_path / fixture_name
    shutil.copytree(source, destination)
    return destination


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "strucin.cli", *args],
        capture_output=True,
        text=True,
        check=True,
    )


def test_phase6_regression_workflow_default_outputs(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path, "cycle_repo")

    _run_cli("scan", str(repo))
    _run_cli("analyze", str(repo))
    _run_cli("report", str(repo))
    _run_cli("search", "worker class", "--path", str(repo), "--top-k", "3")
    _run_cli("explain", "--path", str(repo))

    assert (repo / "repo_index.json").exists()
    assert (repo / "analysis.json").exists()
    assert (repo / "dependency_graph.json").exists()
    assert (repo / "docs" / "REPORT.md").exists()
    assert (repo / "semantic_index.json").exists()
    assert (repo / "docs" / "EXPLAIN.md").exists()
    assert (repo / "explain.json").exists()

    analysis_payload = json.loads((repo / "analysis.json").read_text(encoding="utf-8"))
    cycles = analysis_payload["cycles"]
    assert cycles
    assert any(set(cycle) == {"pkg.a", "pkg.b"} for cycle in cycles)

    report_text = (repo / "docs" / "REPORT.md").read_text(encoding="utf-8")
    assert "## Dependency Cycles" in report_text


def test_phase6_regression_respects_config_overrides(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path, "configured_repo")

    _run_cli("scan", str(repo))
    _run_cli("analyze", str(repo))
    _run_cli("report", str(repo))
    search_result = _run_cli("search", "normalize value", "--path", str(repo), "--top-k", "0")
    _run_cli("explain", "--path", str(repo))

    assert (repo / "custom_index.json").exists()
    assert (repo / "custom_analysis.json").exists()
    assert (repo / "custom_dependency_graph.json").exists()
    assert (repo / "CUSTOM_REPORT.md").exists()
    assert (repo / "custom_semantic_index.json").exists()
    assert (repo / "CUSTOM_EXPLAIN.md").exists()
    assert (repo / "custom_explain.json").exists()

    index_payload = json.loads((repo / "custom_index.json").read_text(encoding="utf-8"))
    file_paths = {item["path"] for item in index_payload["files"]}
    assert "src/core.py" in file_paths
    assert "vendor/ignored.py" not in file_paths

    assert "Top 2 results for query:" in search_result.stdout
