from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

import pytest

from strucin.cli.hooks import main_complexity
from strucin.core import analyzer
from strucin.core.analysis_cache import CACHE_VERSION


@pytest.mark.parametrize(
    "source,expected",
    [
        pytest.param("pass", 1, id="straight-line"),
        pytest.param("if ready: run()", 2, id="if"),
        pytest.param("if ready: run()\nelse: stop()", 2, id="else"),
        pytest.param("if a: run()\nelif b: stop()\nelse: wait()", 3, id="elif"),
        pytest.param("value = a if ready else b", 2, id="conditional-expression"),
        pytest.param("result = a and b and c and d and e and f", 6, id="boolean-chain"),
        pytest.param("result = a or b or c or d or e or f", 6, id="or-chain"),
        pytest.param("result = (a and b) or (c and d)", 4, id="nested-booleans"),
        pytest.param("if a and b and c: run()", 4, id="boolean-condition"),
        pytest.param("result = not a", 1, id="negation"),
        pytest.param("result = a & b | c", 1, id="bitwise"),
        pytest.param("for item in items: run(item)", 2, id="for"),
        pytest.param("for item in items: run(item)\nelse: stop()", 2, id="loop-else"),
        pytest.param("while ready: run()", 2, id="while"),
        pytest.param("async def f():\n    async for item in items: run(item)", 2, id="async-for"),
        pytest.param("try: run()\nfinally: stop()", 1, id="try-finally"),
        pytest.param("try: run()\nexcept ValueError: stop()", 2, id="except"),
        pytest.param(
            "try: run()\nexcept ValueError: stop()\nexcept TypeError: wait()\n"
            "else: done()\nfinally: finish()",
            3,
            id="multiple-handlers",
        ),
        pytest.param("try: run()\nexcept* ValueError: stop()", 2, id="except-star"),
        pytest.param("with resource(): run()", 1, id="with"),
        pytest.param("async def f():\n    async with resource(): run()", 1, id="async-with"),
        pytest.param("assert ready", 2, id="assert"),
        pytest.param("assert a and b", 3, id="boolean-assert"),
        pytest.param("value = [x for x in items]", 2, id="list-comprehension"),
        pytest.param("value = {x for x in items if ready}", 3, id="set-comprehension"),
        pytest.param("value = {x: x for x in items if ready}", 3, id="dict-comprehension"),
        pytest.param("value = (x for x in items if ready)", 3, id="generator-expression"),
        pytest.param("value = [x for x in items if a if b]", 4, id="multiple-filters"),
        pytest.param("value = [x for x in items if a and b]", 4, id="boolean-filter"),
        pytest.param(
            "value = [(x, y) for x in items if a for y in others if b]",
            5,
            id="multiple-generators",
        ),
        pytest.param(
            "async def f():\n    return [x async for x in items if ready]",
            3,
            id="async-comprehension",
        ),
    ],
)
def test_complexity_decision_rules(source: str, expected: int) -> None:
    assert analyzer._node_complexity(ast.parse(source)) == expected


@pytest.mark.parametrize(
    "cases,expected",
    [
        pytest.param("case 1: pass\ncase 2: pass\ncase 3: pass\ncase _: pass", 4, id="four-arms"),
        pytest.param("case 1: pass\ncase 2: pass\ncase 3: pass\ncase 4: pass", 5, id="no-default"),
        pytest.param("case _: pass", 1, id="wildcard"),
        pytest.param("case captured: pass", 1, id="capture"),
        pytest.param("case _ as captured: pass", 1, id="wildcard-alias"),
        pytest.param("case 1 as captured: pass\ncase _: pass", 2, id="refutable-alias"),
        pytest.param("case captured if ready: pass", 2, id="guarded-capture"),
        pytest.param("case _ if a and b: pass", 3, id="boolean-default-guard"),
        pytest.param("case 1 if ready: pass\ncase _: pass", 3, id="refutable-guard"),
        pytest.param("case 1 if a and b: pass\ncase _: pass", 4, id="boolean-case-guard"),
        pytest.param("case 1 | 2: pass\ncase _: pass", 2, id="or-pattern"),
        pytest.param("case 1 | _: pass", 1, id="irrefutable-or-pattern"),
        pytest.param("case [x]: pass\ncase _: pass", 2, id="sequence"),
        pytest.param("case 1:\n    if ready: run()\ncase _: pass", 3, id="case-body"),
    ],
)
def test_match_complexity(cases: str, expected: int) -> None:
    source = "match value:\n" + "\n".join("    " + line for line in cases.splitlines())
    assert analyzer._node_complexity(ast.parse(source)) == expected


def test_file_and_function_scores_aggregate_nested_definitions() -> None:
    tree = ast.parse(
        dedent("""
        def outer(ready):
            def inner(value):
                if value:
                    return 1
            if ready:
                return inner(ready)
        def other(value):
            return value or 1
        """)
    )
    scores = {item.name: item.cyclomatic_complexity for item in analyzer._extract_functions(tree)}
    assert scores == {"outer": 3, "inner": 2, "other": 2}
    assert analyzer._node_complexity(tree) == 4


def make_repo(root: Path, *, safe_mode: bool = False) -> None:
    (root / "private_rule.py").write_text(
        "def allowed(a, b, c, d, e, f):\n    return a and b and c and d and e and f\n",
        encoding="utf-8",
    )
    (root / ".strucin.toml").write_text(
        '[performance]\nmax_workers = 1\nexecutor = "thread"\n'
        f"[security]\nsafe_mode = {str(safe_mode).lower()}\n",
        encoding="utf-8",
    )


def test_old_complexity_cache_is_recomputed_then_reused(tmp_path: Path) -> None:
    make_repo(tmp_path)
    analyzer.analyze_repository(tmp_path, max_workers=1)
    path = tmp_path / ".strucin_cache/analysis_cache.json"
    legacy = json.loads(path.read_text(encoding="utf-8"))
    legacy["cache_version"] = "1"
    legacy["files"]["private_rule.py"]["analysis"]["cyclomatic_complexity"] = 1
    legacy["files"]["private_rule.py"]["analysis"]["functions"][0]["cyclomatic_complexity"] = 1
    path.write_text(json.dumps(legacy), encoding="utf-8")

    with patch.object(
        analyzer, "_analyze_single_file", wraps=analyzer._analyze_single_file
    ) as parse:
        result = analyzer.analyze_repository(tmp_path, max_workers=1)
        assert parse.call_count == 1
        assert result.files[0].cyclomatic_complexity == 6
        assert result.files[0].functions[0].cyclomatic_complexity == 6
        cached = analyzer.analyze_repository(tmp_path, max_workers=1)
        assert parse.call_count == 1
        assert cached.files == result.files
    repaired = json.loads(path.read_text(encoding="utf-8"))
    assert repaired["cache_version"] == CACHE_VERSION != "1"


@pytest.mark.parametrize("safe_mode", [False, True])
def test_cli_analysis_and_hook_use_corrected_scores(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], safe_mode: bool
) -> None:
    make_repo(tmp_path, safe_mode=safe_mode)
    result = subprocess.run(
        [sys.executable, "-m", "strucin.cli", "analyze", str(tmp_path), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["file_count"] == 1
    text = (tmp_path / "analysis.json").read_text(encoding="utf-8")
    file = json.loads(text)["files"][0]
    assert file["cyclomatic_complexity"] == file["functions"][0]["cyclomatic_complexity"] == 6
    assert main_complexity([str(tmp_path), "--threshold", "5"]) == 1
    assert main_complexity([str(tmp_path), "--threshold", "6"]) == 0
    captured = capsys.readouterr()
    assert "complexity=6" in captured.err
    if safe_mode:
        assert "private_rule" not in text + captured.out + captured.err
        assert not (tmp_path / ".strucin_cache").exists()
