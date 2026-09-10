from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from strucin.cli.hooks import main_complexity, main_cycles
from strucin.core.analyzer import analyze_repository
from strucin.core.artifacts import resolve_artifact_path
from strucin.core.config import load_config
from strucin.core.explainer import explain_repository
from strucin.core.lifecycle import cleanup_stale_artifacts
from strucin.exceptions import ConfigError
from strucin.web.dashboard import build_dashboard


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "sample.py").write_text("VALUE = 1\n", encoding="utf-8")
    return repo


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "strucin.cli", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_nested_artifact_path_does_not_create_directories(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert resolve_artifact_path(repo, "reports/nested/report.md") == (
        repo / "reports/nested/report.md"
    )
    assert not (repo / "reports").exists()


@pytest.mark.parametrize("path", ["", ".", "../outside.json", "docs/../../outside.json"])
def test_reject_invalid_artifact_paths(tmp_path: Path, path: str) -> None:
    with pytest.raises(ConfigError, match="Artifact path"):
        resolve_artifact_path(tmp_path, path)


def test_reject_absolute_artifact_path(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="Artifact path"):
        resolve_artifact_path(tmp_path / "repo", tmp_path / "outside.json")


@pytest.mark.parametrize("existing_target", [False, True])
def test_reject_external_file_symlink(tmp_path: Path, existing_target: bool) -> None:
    repo = _repo(tmp_path)
    outside = tmp_path / "outside.json"
    if existing_target:
        outside.write_text("sentinel", encoding="utf-8")
    (repo / "analysis.json").symlink_to(outside)

    with pytest.raises(ConfigError, match="escapes"):
        resolve_artifact_path(repo, "analysis.json")


def test_reject_symlinked_parent(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (repo / "reports").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ConfigError, match="escapes"):
        resolve_artifact_path(repo, "reports/nested/report.md")
    assert list(outside.iterdir()) == []


def test_allow_symlinked_repo_root_and_internal_parent(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "reports").mkdir()
    (repo / "docs").symlink_to(repo / "reports", target_is_directory=True)
    alias = tmp_path / "repo-alias"
    alias.symlink_to(repo, target_is_directory=True)
    assert resolve_artifact_path(alias, "docs/report.md") == repo / "reports/report.md"


def test_reject_symlink_loop_with_config_error(tmp_path: Path) -> None:
    (tmp_path / "loop").symlink_to("loop")
    with pytest.raises(ConfigError, match="Cannot resolve"):
        resolve_artifact_path(tmp_path, "loop/report.md")


@pytest.mark.parametrize(
    "output_name",
    [
        "repo_index",
        "analysis",
        "dependency_graph",
        "report",
        "semantic_index",
        "explain_markdown",
        "explain_metadata",
    ],
)
def test_cli_rejects_all_escaping_outputs_before_cleanup(tmp_path: Path, output_name: str) -> None:
    repo = _repo(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text("outside sentinel", encoding="utf-8")
    os.utime(outside, (1, 1))
    stale_name = "analysis.json" if output_name != "analysis" else "repo_index.json"
    stale = repo / stale_name
    stale.write_text("retained artifact", encoding="utf-8")
    os.utime(stale, (1, 1))
    (repo / ".strucin.toml").write_text(
        f'[output]\n{output_name} = "../outside.json"\n', encoding="utf-8"
    )

    result = _run_cli("scan", str(repo))

    assert result.returncode == 1
    assert "Artifact path" in result.stderr
    assert "Traceback" not in result.stderr
    assert outside.read_text(encoding="utf-8") == "outside sentinel"
    assert stale.read_text(encoding="utf-8") == "retained artifact"
    assert not (repo / ".strucin_cache").exists()


@pytest.mark.parametrize("config_text", [None, "broken = [\n", "[performance]\nmax_workers = 1\n"])
def test_validate_default_outputs_for_missing_invalid_and_valid_config(
    tmp_path: Path, config_text: str | None
) -> None:
    repo = _repo(tmp_path)
    if config_text is not None:
        (repo / ".strucin.toml").write_text(config_text, encoding="utf-8")
    (repo / "analysis.json").symlink_to(tmp_path / "outside.json")
    with pytest.raises(ConfigError, match="escapes"):
        load_config(repo)


@pytest.mark.parametrize("command", ["scan", "analyze", "report", "search", "explain", "web"])
def test_commands_reject_output_symlink_escape(tmp_path: Path, command: str) -> None:
    repo = _repo(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text("outside sentinel", encoding="utf-8")
    (repo / "repo_index.json").symlink_to(outside)
    args = [command]
    if command == "search":
        args.append("query")
    if command in {"search", "explain", "web"}:
        args.append("--path")
    args.append(str(repo))

    result = _run_cli(*args)

    assert result.returncode == 1
    assert "escapes" in result.stderr
    assert "Traceback" not in result.stderr
    assert outside.read_text(encoding="utf-8") == "outside sentinel"


@pytest.mark.parametrize("absolute", [False, True])
def test_cleanup_validates_all_paths_before_deleting(tmp_path: Path, absolute: bool) -> None:
    repo = _repo(tmp_path)
    stale = repo / "a.json"
    stale.write_text("retained", encoding="utf-8")
    os.utime(stale, (1, 1))
    unsafe = str(tmp_path / "outside.json") if absolute else "z/../../outside.json"
    with pytest.raises(ConfigError):
        cleanup_stale_artifacts(repo, {"a.json", unsafe}, 1)
    assert stale.read_text(encoding="utf-8") == "retained"


def test_cleanup_unlinks_internal_symlink_without_deleting_its_target(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    target = repo / "retained.txt"
    target.write_text("retained", encoding="utf-8")
    os.utime(target, (1, 1))
    link = repo / "analysis.json"
    link.symlink_to(target)
    assert cleanup_stale_artifacts(repo, {"analysis.json"}, 1) == [link]
    assert not link.is_symlink()
    assert target.read_text(encoding="utf-8") == "retained"


@pytest.mark.parametrize("link_directory", [False, True])
def test_cleanup_rejects_external_cache_links(tmp_path: Path, link_directory: bool) -> None:
    repo = _repo(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "cache.json"
    sentinel.write_text("retained", encoding="utf-8")
    os.utime(sentinel, (1, 1))
    cache = repo / ".strucin_cache"
    if link_directory:
        cache.symlink_to(outside, target_is_directory=True)
    else:
        cache.mkdir()
        (cache / "cache.json").symlink_to(sentinel)
    with pytest.raises(ConfigError, match="escapes"):
        cleanup_stale_artifacts(repo, set(), 1)
    assert sentinel.read_text(encoding="utf-8") == "retained"


@pytest.mark.parametrize(
    ("analyze", "filename"),
    [
        (analyze_repository, "analysis_cache.json"),
        (explain_repository, "explain_cache.json"),
    ],
)
@pytest.mark.parametrize("link_directory", [False, True])
def test_public_analysis_rejects_cache_escape(
    tmp_path: Path, analyze: Callable[..., object], filename: str, link_directory: bool
) -> None:
    repo = _repo(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / filename
    sentinel.write_text("{}", encoding="utf-8")
    cache = repo / ".strucin_cache"
    if link_directory:
        cache.symlink_to(outside, target_is_directory=True)
    else:
        cache.mkdir()
        (cache / filename).symlink_to(sentinel)
    with pytest.raises(ConfigError, match="escapes"):
        analyze(repo, max_workers=1)
    assert sentinel.read_text(encoding="utf-8") == "{}"
    assert list(outside.iterdir()) == [sentinel]


@pytest.mark.parametrize("entry", [main_cycles, main_complexity])
def test_hooks_return_clean_failure_for_escaping_cache(
    tmp_path: Path, entry: Callable[[list[str]], int], capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (repo / ".strucin_cache").symlink_to(outside, target_is_directory=True)
    assert entry([str(repo)]) == 1
    error = capsys.readouterr().err
    assert "escapes" in error
    assert "Unexpected failure" not in error
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("filename", ["data.json", "index.html", "app.js", "styles.css"])
def test_dashboard_rejects_file_escape_before_writing(tmp_path: Path, filename: str) -> None:
    repo = _repo(tmp_path)
    output = tmp_path / "export"
    output.mkdir()
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("retained", encoding="utf-8")
    (output / filename).symlink_to(sentinel)
    with pytest.raises(ConfigError, match="escapes"):
        build_dashboard(repo, output, max_workers=1)
    assert sentinel.read_text(encoding="utf-8") == "retained"
    assert list(output.iterdir()) == [output / filename]
    assert not (repo / ".strucin_cache").exists()


def test_web_rejects_implicit_external_output_directory(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    output = tmp_path / "outside"
    output.mkdir()
    (repo / ".strucin_web").symlink_to(output, target_is_directory=True)
    result = _run_cli("web", "--path", str(repo))
    assert result.returncode == 1
    assert list(output.iterdir()) == []


def test_web_allows_explicit_external_export(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    output = tmp_path / "export"
    result = _run_cli("web", "--path", str(repo), "--out", str(output))
    assert result.returncode == 0, result.stderr
    assert json.loads((output / "data.json").read_text(encoding="utf-8"))["file_count"] == 1
    assert (output / "index.html").is_file()


def test_init_force_cannot_follow_external_config_symlink(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    sentinel = tmp_path / "outside.toml"
    sentinel.write_text("retained", encoding="utf-8")
    (repo / ".strucin.toml").symlink_to(sentinel)
    result = _run_cli("init", "--path", str(repo), "--force")
    assert result.returncode == 1
    assert sentinel.read_text(encoding="utf-8") == "retained"


def test_scan_allows_configured_nested_output(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / ".strucin.toml").write_text(
        '[output]\nrepo_index = "artifacts/nested/index.json"\n', encoding="utf-8"
    )
    result = _run_cli("scan", str(repo))
    assert result.returncode == 0, result.stderr
    index = json.loads((repo / "artifacts/nested/index.json").read_text(encoding="utf-8"))
    assert index["file_count"] == 1
