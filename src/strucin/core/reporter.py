from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from strucin import __version__
from strucin.core.analyzer import AnalysisResult, FileAnalysis
from strucin.core.config import ReportConfig
from strucin.core.explainer import redact_analysis


@dataclass(frozen=True)
class RefactorSuggestion:
    target: str
    reason: str
    recommendation: str


def _top_hotspots(files: list[FileAnalysis], limit: int = 10) -> list[tuple[FileAnalysis, int]]:
    scored = [(file_info, file_info.loc * file_info.fan_out) for file_info in files]
    return sorted(scored, key=lambda item: item[1], reverse=True)[:limit]


def _largest_modules(files: list[FileAnalysis], limit: int = 10) -> list[FileAnalysis]:
    return sorted(files, key=lambda item: item.loc, reverse=True)[:limit]


def _largest_packages(files: list[FileAnalysis], limit: int = 10) -> list[tuple[str, int]]:
    package_loc: dict[str, int] = defaultdict(int)
    for file_info in files:
        parts = file_info.module_path.split(".")
        package = parts[0] if parts else file_info.module_path
        package_loc[package] += file_info.loc
    return sorted(package_loc.items(), key=lambda item: item[1], reverse=True)[:limit]


def _most_imported_modules(files: list[FileAnalysis], limit: int = 10) -> list[FileAnalysis]:
    return sorted(files, key=lambda item: item.fan_in, reverse=True)[:limit]


def _build_refactor_suggestions(
    analysis: AnalysisResult,
    report_config: ReportConfig,
) -> list[RefactorSuggestion]:
    suggestions: list[RefactorSuggestion] = []
    for file_info in analysis.files:
        if file_info.fan_out >= report_config.fan_out_threshold:
            suggestions.append(
                RefactorSuggestion(
                    target=file_info.module_path,
                    reason=f"High fan-out ({file_info.fan_out})",
                    recommendation=(
                        "Split orchestration from core logic and reduce direct dependencies."
                    ),
                )
            )
        if file_info.cyclomatic_complexity >= report_config.complexity_threshold:
            suggestions.append(
                RefactorSuggestion(
                    target=file_info.module_path,
                    reason=f"High complexity ({file_info.cyclomatic_complexity})",
                    recommendation=(
                        "Extract branches into smaller pure functions with focused tests."
                    ),
                )
            )
        if file_info.loc >= report_config.loc_threshold:
            suggestions.append(
                RefactorSuggestion(
                    target=file_info.module_path,
                    reason=f"Large module ({file_info.loc} LOC)",
                    recommendation="Split by responsibility into smaller modules within a package.",
                )
            )
        if file_info.docstring is None and (file_info.classes or file_info.functions):
            suggestions.append(
                RefactorSuggestion(
                    target=file_info.module_path,
                    reason="Missing module docstring",
                    recommendation=(
                        "Add a top-level docstring to clarify module intent and boundaries."
                    ),
                )
            )

    if analysis.cycles:
        cycle_preview = " -> ".join(analysis.cycles[0])
        suggestions.append(
            RefactorSuggestion(
                target="dependency graph",
                reason=f"Detected {len(analysis.cycles)} dependency cycle(s)",
                recommendation=(
                    "Break cycle edges with interfaces or inversion of control "
                    f"(example: {cycle_preview})."
                ),
            )
        )
    return suggestions[:20]


def generate_markdown_report(  # noqa: C901
    analysis: AnalysisResult,
    safe_mode: bool = False,
    report_config: ReportConfig | None = None,
) -> str:
    cfg = report_config or ReportConfig()
    active_analysis = redact_analysis(analysis) if safe_mode else analysis
    lines: list[str] = []
    lines.append("# StrucIn Architecture Report")
    lines.append("")
    lines.append("## Summary")
    lines.append(f"- Repository: `{active_analysis.repo_root}`")
    lines.append(f"- Generated at: `{active_analysis.generated_at}`")
    lines.append(f"- StrucIn version: `{__version__}`")
    lines.append(f"- Python files: **{active_analysis.file_count}**")
    lines.append(f"- Modules: **{active_analysis.module_count}**")
    lines.append(f"- Dependency edges: **{len(active_analysis.dependency_graph_edges)}**")
    lines.append(f"- Safe mode: **{'enabled' if safe_mode else 'disabled'}**")
    lines.append("")

    lines.append("## Top Hotspot Files (LOC x Fan-out)")
    hotspots = _top_hotspots(active_analysis.files)
    if not hotspots:
        lines.append("- None")
    else:
        if safe_mode:
            lines.append(f"- Top hotspots identified: {len(hotspots)} module(s)")
        else:
            for file_info, score in hotspots:
                lines.append(
                    f"- `{file_info.path}`: score={score} "
                    f"(loc={file_info.loc}, fan_out={file_info.fan_out})"
                )
    lines.append("")

    lines.append("## Largest Modules")
    if safe_mode:
        lines.append("- Module names hidden in safe mode.")
    else:
        for module in _largest_modules(active_analysis.files):
            lines.append(f"- `{module.module_path}`: {module.loc} LOC")
    lines.append("")

    lines.append("## Largest Packages")
    if safe_mode:
        lines.append("- Package names hidden in safe mode.")
    else:
        for package, loc in _largest_packages(active_analysis.files):
            lines.append(f"- `{package}`: {loc} LOC")
    lines.append("")

    lines.append("## Most Imported Modules")
    if safe_mode:
        lines.append("- Module names hidden in safe mode.")
    else:
        for module in _most_imported_modules(active_analysis.files):
            lines.append(f"- `{module.module_path}`: fan_in={module.fan_in}")
    lines.append("")

    lines.append("## Dependency Cycles")
    if not active_analysis.cycles:
        lines.append("- None detected")
    elif safe_mode:
        lines.append(f"- Detected {len(active_analysis.cycles)} cycle(s); module names hidden.")
    else:
        for cycle in active_analysis.cycles:
            lines.append(f"- {' -> '.join(f'`{node}`' for node in cycle)}")
    lines.append("")

    lines.append("## Refactor Suggestions")
    suggestions = _build_refactor_suggestions(active_analysis, cfg)
    if not suggestions:
        lines.append("- No immediate high-priority refactors identified.")
    else:
        if safe_mode:
            lines.append(f"- Generated {len(suggestions)} suggestion(s); targets hidden.")
        else:
            for suggestion in suggestions:
                lines.append(
                    f"- `{suggestion.target}`: {suggestion.reason}. "
                    f"Recommendation: {suggestion.recommendation}"
                )
    lines.append("")

    return "\n".join(lines)


def write_markdown_report(
    analysis: AnalysisResult,
    output_path: Path,
    safe_mode: bool = False,
    report_config: ReportConfig | None = None,
) -> None:
    output_path.write_text(
        generate_markdown_report(analysis, safe_mode=safe_mode, report_config=report_config),
        encoding="utf-8",
    )
