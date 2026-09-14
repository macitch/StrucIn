from __future__ import annotations

import json
from pathlib import Path

import pytest

from strucin.cli.main import main
from strucin.core import explainer

OUTPUTS = {
    "repo_index": "indexes/deep/repository.json",
    "analysis": "analyses/deep/analysis.json",
    "dependency_graph": "graphs/deep/dependencies.json",
    "report": "reports/deep/report.md",
    "semantic_index": "semantic/deep/index.json",
    "explain_markdown": "narration/deep/explain.md",
    "explain_metadata": "metadata/deep/explain.json",
}
COMMAND_OUTPUTS = {
    "scan": ["repo_index"],
    "analyze": ["analysis", "dependency_graph"],
    "report": ["report"],
    "search": ["semantic_index"],
    "explain": ["explain_markdown", "explain_metadata"],
}


@pytest.fixture(autouse=True)
def no_live_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(explainer, "_detect_llm", lambda config: None)


def configure(root: Path, outputs: dict[str, str]) -> None:
    (root / "private_module.py").write_text(
        '"""PRIVATE_DOCSTRING"""\ndef private_function():\n    return 1\n', encoding="utf-8"
    )
    (root / ".strucin.toml").write_text(
        "[output]\n"
        + "\n".join(f"{key} = {json.dumps(value)}" for key, value in outputs.items())
        + '\n[search]\nembedding_model = "hashing-v1"\n'
        + '[performance]\nmax_workers = 1\nexecutor = "thread"\n',
        encoding="utf-8",
    )


def command_args(root: Path, command: str, safe_mode: bool = False) -> list[str]:
    if command == "search":
        args = [command, "private_function", "--path", str(root), "--json"]
    elif command == "explain":
        args = [command, "--path", str(root)]
    else:
        args = [command, str(root)]
        if command in {"scan", "analyze"}:
            args.append("--json")
    if safe_mode:
        args.append("--safe-mode")
    return args


@pytest.mark.parametrize("command", COMMAND_OUTPUTS)
@pytest.mark.parametrize("safe_mode", [False, True])
def test_each_command_creates_independent_nested_output_directories(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: str, safe_mode: bool
) -> None:
    configure(tmp_path, OUTPUTS)
    assert main(command_args(tmp_path, command, safe_mode)) == 0
    captured = capsys.readouterr()
    if command in {"scan", "analyze", "search"}:
        assert isinstance(json.loads(captured.out), dict)
    expected = set(COMMAND_OUTPUTS[command])
    if command == "search" and safe_mode:
        expected = set()
    for name, relative in OUTPUTS.items():
        path = tmp_path / relative
        assert path.is_file() == (name in expected)
        if name not in expected:
            continue
        content = path.read_text(encoding="utf-8")
        if path.suffix == ".json":
            assert isinstance(json.loads(content), dict)
        else:
            assert content.startswith("# StrucIn")
        if safe_mode:
            assert "private_module" not in content
            assert "private_function" not in content
            assert "PRIVATE_DOCSTRING" not in content
    if safe_mode:
        assert "private_function" not in captured.out + captured.err
        assert not (tmp_path / ".strucin_cache/analysis_cache.json").exists()


@pytest.mark.parametrize("command", ["analyze", "explain"])
@pytest.mark.parametrize("existing_primary", [False, True])
@pytest.mark.parametrize("safe_mode", [False, True])
def test_secondary_parent_failure_precedes_both_artifact_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
    existing_primary: bool,
    safe_mode: bool,
) -> None:
    configure(tmp_path, OUTPUTS)
    primary_name, secondary_name = COMMAND_OUTPUTS[command]
    primary = tmp_path / OUTPUTS[primary_name]
    secondary = tmp_path / OUTPUTS[secondary_name]
    previous = "PREVIOUS_ARTIFACT"
    if existing_primary:
        primary.parent.mkdir(parents=True)
        primary.write_text(previous, encoding="utf-8")
    original_mkdir = Path.mkdir

    def fail_secondary_parent(self: Path, *args: object, **kwargs: object) -> None:
        if self == secondary.parent:
            raise PermissionError("injected output directory failure")
        original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fail_secondary_parent)
    assert main(command_args(tmp_path, command, safe_mode)) == 1
    captured = capsys.readouterr()
    assert "injected output directory failure" in captured.err
    assert "Traceback" not in captured.err
    if existing_primary:
        assert primary.read_text(encoding="utf-8") == previous
    else:
        assert not primary.exists()
    assert not secondary.exists()


@pytest.mark.parametrize("command", ["analyze", "explain"])
@pytest.mark.parametrize("target_exists", [False, True])
def test_secondary_parent_escape_is_rejected_before_output_creation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: str, target_exists: bool
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside"
    if target_exists:
        outside.mkdir()
    (root / "linked").symlink_to(outside, target_is_directory=True)
    primary_name, secondary_name = COMMAND_OUTPUTS[command]
    outputs = OUTPUTS | {secondary_name: "linked/nested/result.json"}
    configure(root, outputs)
    assert main(command_args(root, command)) == 1
    assert "escapes" in capsys.readouterr().err
    assert not (root / outputs[primary_name]).parent.exists()
    assert not (root / ".strucin_cache").exists()
    assert outside.exists() == target_exists
    if target_exists:
        assert list(outside.iterdir()) == []


@pytest.mark.parametrize("command", ["analyze", "explain"])
def test_internal_dangling_parent_link_can_create_nested_outputs(
    tmp_path: Path, command: str
) -> None:
    _, secondary_name = COMMAND_OUTPUTS[command]
    (tmp_path / "linked").symlink_to("internal", target_is_directory=True)
    outputs = OUTPUTS | {secondary_name: "linked/nested/result.json"}
    configure(tmp_path, outputs)
    assert main(command_args(tmp_path, command)) == 0
    assert isinstance(
        json.loads((tmp_path / "internal/nested/result.json").read_text(encoding="utf-8")), dict
    )
