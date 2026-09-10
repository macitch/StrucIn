"""Run the composite GitHub Action against one fresh in-memory analysis."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, fields
from pathlib import Path
from uuid import uuid4

from strucin.core.analyzer import analyze_repository, write_analysis
from strucin.core.artifacts import resolve_artifact_path
from strucin.core.config import load_config
from strucin.core.indexer import scan_repository, write_repo_index
from strucin.core.lifecycle import cleanup_stale_artifacts
from strucin.core.reporter import write_markdown_report
from strucin.exceptions import ConfigError, StrucInError


@dataclass(frozen=True)
class ActionResult:
    analysis_path: Path
    report_path: Path | None
    cycle_count: int


def run_action(
    repo_path: Path, command: str = "report", *, safe_mode: bool = False
) -> ActionResult:
    """Write requested artifacts and derive the gate from this run's analysis.

    Every supported command writes fresh analysis and graph JSON. Report mode
    renders the very same analysis; no previous report or snapshot is consulted.
    ``safe_mode=True`` enables privacy; False preserves repository configuration.
    """
    if command not in {"scan", "analyze", "report"}:
        raise ConfigError("Action command must be scan, analyze, or report")
    root = repo_path.resolve()
    if not root.is_dir():
        raise ConfigError(f"Repository is not a directory: {root}")
    config = load_config(root)
    safe_mode = safe_mode or config.security.safe_mode
    analysis_path = resolve_artifact_path(root, config.output.analysis)
    graph_path = resolve_artifact_path(root, config.output.dependency_graph)
    requested_path = None
    if command == "scan":
        requested_path = resolve_artifact_path(root, config.output.repo_index)
    elif command == "report":
        requested_path = resolve_artifact_path(root, config.output.report)
    destinations = [analysis_path, graph_path]
    if requested_path is not None:
        destinations.append(requested_path)
    if len(set(destinations)) != len(destinations):
        raise ConfigError("Action output paths must be distinct for each generated artifact")
    cleanup_stale_artifacts(
        root,
        {getattr(config.output, field.name) for field in fields(config.output)},
        config.lifecycle.cache_retention_days,
    )
    analysis = analyze_repository(
        root,
        excluded_dirs=config.excluded_dirs,
        max_workers=config.performance.max_workers,
        executor=config.performance.executor,
        source_roots=config.source_roots,
        use_cache=not safe_mode,
    )
    for destination in destinations:
        destination.parent.mkdir(parents=True, exist_ok=True)
    write_analysis(analysis, analysis_path, graph_path, safe_mode=safe_mode)
    if command == "scan" and requested_path is not None:
        index = scan_repository(
            root,
            excluded_dirs=config.excluded_dirs,
            max_workers=config.performance.max_workers,
            source_roots=config.source_roots,
        )
        write_repo_index(index, requested_path, safe_mode=safe_mode)
    elif command == "report" and requested_path is not None:
        write_markdown_report(
            analysis, requested_path, safe_mode=safe_mode, report_config=config.report
        )
    return ActionResult(
        analysis_path=analysis_path,
        report_path=requested_path if command == "report" else None,
        cycle_count=len(analysis.cycles),
    )


def _boolean_input(name: str) -> bool:
    value = os.environ.get(name, "false").strip().lower()
    if value not in {"true", "false"}:
        raise ConfigError(f"{name} must be true or false")
    return value == "true"


def _write_outputs(path: Path, result: ActionResult) -> None:
    outputs = {
        "analysis-path": str(result.analysis_path),
        "report-path": str(result.report_path) if result.report_path is not None else "",
        "cycles-found": str(result.cycle_count > 0).lower(),
        "cycle-count": str(result.cycle_count),
    }
    # Delimit values so unusual filenames cannot create extra workflow outputs.
    with path.open("a", encoding="utf-8") as stream:
        for name, value in outputs.items():
            delimiter = f"strucin_{uuid4().hex}"
            stream.write(f"{name}<<{delimiter}\n{value}\n{delimiter}\n")


def main() -> int:
    logging.basicConfig(format="%(message)s", level=logging.WARNING)
    try:
        output_file = os.environ.get("GITHUB_OUTPUT")
        if not output_file:
            raise ConfigError("GITHUB_OUTPUT is required when running the StrucIn Action")
        fail_on_cycles = _boolean_input("STRUCIN_FAIL_ON_CYCLES")
        result = run_action(
            Path(os.environ.get("STRUCIN_PATH", ".")),
            os.environ.get("STRUCIN_COMMAND", "report"),
            safe_mode=_boolean_input("STRUCIN_SAFE_MODE"),
        )
        _write_outputs(Path(output_file), result)
        print(f"StrucIn detected {result.cycle_count} dependency cycle(s) in the current analysis.")
        if fail_on_cycles and result.cycle_count:
            print("::error::Dependency cycles detected; fail-on-cycles is enabled.")
            return 1
    except (StrucInError, OSError, ValueError) as exc:
        message = str(exc).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::error::StrucIn Action failed: {message}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
