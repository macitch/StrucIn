from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from strucin.core.analyzer import analyze_repository


def test_analyze_repository_builds_graph_cycles_and_metrics(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "a.py").write_text(
        '"""A module docstring."""\n'
        "import os\n"
        "from . import b\n\n"
        "def run(x: int) -> int:\n"
        '    """Run action."""\n'
        "    if x > 0:\n"
        "        return x\n"
        "    return 0\n",
        encoding="utf-8",
    )
    (tmp_path / "pkg" / "b.py").write_text(
        "from . import a\n\n"
        "class Worker:\n"
        "    def work(self, ready: bool) -> int:\n"
        "        if ready:\n"
        "            return 1\n"
        "        return 0\n",
        encoding="utf-8",
    )

    analysis = analyze_repository(tmp_path)

    assert analysis.file_count == 3
    assert analysis.module_count == 3

    edges = {(edge.source, edge.target) for edge in analysis.dependency_graph_edges}
    assert ("pkg.a", "pkg.b") in edges
    assert ("pkg.b", "pkg.a") in edges

    cycle_sets = {frozenset(cycle) for cycle in analysis.cycles}
    assert frozenset({"pkg.a", "pkg.b"}) in cycle_sets

    file_map = {file.module_path: file for file in analysis.files}
    assert file_map["pkg.a"].docstring == "A module docstring."
    assert file_map["pkg.a"].fan_in == 1
    assert file_map["pkg.a"].fan_out == 1
    assert file_map["pkg.a"].cyclomatic_complexity >= 2
    assert file_map["pkg.a"].functions[0].name == "run"
    assert file_map["pkg.a"].functions[0].docstring == "Run action."
    assert file_map["pkg.b"].classes[0].name == "Worker"


def test_cli_analyze_generates_analysis_and_graph_json(tmp_path: Path) -> None:
    (tmp_path / "sample").mkdir()
    (tmp_path / "sample" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "sample" / "core.py").write_text(
        "from . import __init__\n\ndef ok() -> bool:\n    return True\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, "-m", "strucin.cli", "analyze", str(tmp_path)],
        capture_output=True,
        text=True,
        check=True,
    )

    assert "Analyzed 2 Python files." in result.stdout
    analysis_path = tmp_path / "analysis.json"
    dependency_path = tmp_path / "dependency_graph.json"
    assert analysis_path.exists()
    assert dependency_path.exists()

    analysis_payload = json.loads(analysis_path.read_text(encoding="utf-8"))
    assert analysis_payload["module_count"] == 2
    assert "cycles" in analysis_payload
    assert analysis_payload["artifact_metadata"]["artifact_type"] == "analysis"

    dependency_payload = json.loads(dependency_path.read_text(encoding="utf-8"))
    assert "nodes" in dependency_payload
    assert "edges" in dependency_payload
    assert dependency_payload["artifact_metadata"]["artifact_type"] == "dependency_graph"


def test_analyze_repository_skips_files_with_syntax_errors(tmp_path: Path) -> None:
    """A Python file that cannot be parsed must not crash analyze_repository."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "good.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "pkg" / "broken.py").write_text("def bad(:\n", encoding="utf-8")

    analysis = analyze_repository(tmp_path)

    assert analysis.file_count == 3
    module_map = {f.module_path: f for f in analysis.files}
    assert module_map["pkg.good"].loc == 1
    # broken.py is present but has zero imports, classes, and functions
    assert module_map["pkg.broken"].imports == []
    assert module_map["pkg.broken"].classes == []
    assert module_map["pkg.broken"].functions == []
    assert module_map["pkg.broken"].cyclomatic_complexity == 0


def test_analyze_repository_executor_thread(tmp_path: Path) -> None:
    """executor='thread' must complete without error and return valid results."""
    (tmp_path / "mod.py").write_text("x = 1\n", encoding="utf-8")

    analysis = analyze_repository(tmp_path, executor="thread")

    assert analysis.file_count == 1


def test_analyze_repository_executor_process(tmp_path: Path) -> None:
    """executor='process' must complete without error and return valid results."""
    (tmp_path / "mod.py").write_text("x = 1\n", encoding="utf-8")

    analysis = analyze_repository(tmp_path, executor="process")

    assert analysis.file_count == 1


def test_analyze_repository_executor_auto_small_repo(tmp_path: Path) -> None:
    """executor='auto' with a small repo defaults to ThreadPoolExecutor (no error)."""
    (tmp_path / "mod.py").write_text("x = 1\n", encoding="utf-8")

    analysis = analyze_repository(tmp_path, executor="auto")

    assert analysis.file_count == 1


def test_analyze_repository_invalid_utf8_does_not_crash(tmp_path: Path) -> None:
    """A file with invalid UTF-8 bytes must not crash; decode with errors='replace'."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    # Write raw bytes that are not valid UTF-8
    (tmp_path / "pkg" / "latin.py").write_bytes(b"x = 1\n# \xff\xfe invalid utf-8\n")

    analysis = analyze_repository(tmp_path)

    assert analysis.file_count == 2
    module_map = {f.module_path: f for f in analysis.files}
    assert "pkg.latin" in module_map
    # The file was parsed (comment line has replacement chars but is still valid Python)
    assert module_map["pkg.latin"].loc >= 1
