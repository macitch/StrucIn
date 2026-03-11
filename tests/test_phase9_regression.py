from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path

from strucin.core.analyzer import analyze_repository
from strucin.core.explainer import generate_explanation, redact_analysis
from strucin.core.reporter import generate_markdown_report


def _copy_fixture(tmp_path: Path, fixture_name: str) -> Path:
    source = Path(__file__).resolve().parent / "fixtures" / fixture_name
    destination = tmp_path / fixture_name
    shutil.copytree(source, destination)
    return destination


def test_phase9_golden_report_fixture(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path, "cycle_repo")
    expected = (
        Path(__file__).resolve().parent / "fixtures" / "golden" / "report_cycle_repo.md"
    ).read_text(encoding="utf-8")

    analysis = analyze_repository(repo, max_workers=1)
    analysis = replace(analysis, repo_root="/repo", generated_at="2026-01-01T00:00:00+00:00")
    rendered = generate_markdown_report(analysis)

    assert rendered == expected


def test_phase9_golden_explain_fixture(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path, "cycle_repo")
    expected = (
        Path(__file__).resolve().parent / "fixtures" / "golden" / "explain_cycle_repo.md"
    ).read_text(encoding="utf-8")

    analysis = analyze_repository(repo, max_workers=1)
    analysis = replace(analysis, repo_root="/repo", generated_at="2026-01-01T00:00:00+00:00")
    rendered = generate_explanation(redact_analysis(analysis))

    assert rendered == expected
