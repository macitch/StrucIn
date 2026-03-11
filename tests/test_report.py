from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from strucin.core.analyzer import analyze_repository
from strucin.core.config import ReportConfig
from strucin.core.reporter import generate_markdown_report


def test_generate_markdown_report_includes_phase3_sections(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "a.py").write_text(
        "from . import b\n\n"
        "def run(flag: bool) -> int:\n"
        "    if flag:\n"
        "        return 1\n"
        "    return 0\n",
        encoding="utf-8",
    )
    (tmp_path / "pkg" / "b.py").write_text("from . import a\n", encoding="utf-8")

    analysis = analyze_repository(tmp_path)
    report = generate_markdown_report(analysis)

    assert "# StrucIn Architecture Report" in report
    assert "## Top Hotspot Files (LOC x Fan-out)" in report
    assert "## Largest Modules" in report
    assert "## Largest Packages" in report
    assert "## Most Imported Modules" in report
    assert "## Dependency Cycles" in report
    assert "## Refactor Suggestions" in report
    assert "`pkg.a`" in report
    assert "Detected 1 dependency cycle(s)" in report


def test_cli_report_generates_report_md(tmp_path: Path) -> None:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "service.py").write_text(
        'def ping() -> str:\n    return "pong"\n',
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, "-m", "strucin.cli", "report", str(tmp_path)],
        capture_output=True,
        text=True,
        check=True,
    )

    assert "Generated report for 2 Python files." in result.stdout
    report_path = tmp_path / "docs" / "REPORT.md"
    assert report_path.exists()

    report_text = report_path.read_text(encoding="utf-8")
    assert "# StrucIn Architecture Report" in report_text
    assert "## Summary" in report_text


def test_fan_out_threshold_suppresses_suggestion_when_high(tmp_path: Path) -> None:
    """A module with fan_out=1 should not appear under default threshold of 5."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "a.py").write_text("from . import b\n", encoding="utf-8")
    (tmp_path / "pkg" / "b.py").write_text("value = 1\n", encoding="utf-8")

    analysis = analyze_repository(tmp_path)
    report = generate_markdown_report(analysis)

    # fan_out of pkg.a is 1, below the default threshold of 5
    assert "High fan-out (1)" not in report


def test_fan_out_threshold_fires_when_lowered(tmp_path: Path) -> None:
    """Lowering fan_out_threshold to 1 makes the same module trigger a suggestion."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "a.py").write_text("from . import b\n", encoding="utf-8")
    (tmp_path / "pkg" / "b.py").write_text("value = 1\n", encoding="utf-8")

    analysis = analyze_repository(tmp_path)
    report = generate_markdown_report(analysis, report_config=ReportConfig(fan_out_threshold=1))

    assert "High fan-out (1)" in report


def test_loc_threshold_suppresses_suggestion_when_high(tmp_path: Path) -> None:
    """A small module should not trigger a LOC suggestion under the default threshold."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "small.py").write_text(
        "def ping() -> str:\n    return 'pong'\n", encoding="utf-8"
    )

    analysis = analyze_repository(tmp_path)
    report = generate_markdown_report(analysis)

    assert "Large module" not in report


def test_loc_threshold_fires_when_lowered(tmp_path: Path) -> None:
    """Setting loc_threshold=1 makes every non-empty module trigger a LOC suggestion."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "small.py").write_text(
        "def ping() -> str:\n    return 'pong'\n", encoding="utf-8"
    )

    analysis = analyze_repository(tmp_path)
    report = generate_markdown_report(analysis, report_config=ReportConfig(loc_threshold=1))

    assert "Large module" in report


def test_complexity_threshold_fires_when_lowered(tmp_path: Path) -> None:
    """Lowering complexity_threshold to 1 makes any function body trigger a suggestion."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "simple.py").write_text(
        "def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8"
    )

    analysis = analyze_repository(tmp_path)
    report = generate_markdown_report(analysis, report_config=ReportConfig(complexity_threshold=1))

    assert "High complexity" in report


def test_report_safe_mode_redacts_module_names(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "a.py").write_text("def run() -> int:\n    return 1\n", encoding="utf-8")

    analysis = analyze_repository(tmp_path)
    report = generate_markdown_report(analysis, safe_mode=True)

    assert "Safe mode: **enabled**" in report
    assert "`pkg.a`" not in report
