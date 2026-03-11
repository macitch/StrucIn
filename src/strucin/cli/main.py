from __future__ import annotations

import argparse
import json
import logging
import traceback
from pathlib import Path
from time import perf_counter

from strucin._version import __version__
from strucin.cli.ui import format_table, print_error, print_progress, print_success
from strucin.core.analyzer import analyze_repository, write_analysis
from strucin.core.config import StrucInConfig, load_config
from strucin.core.explainer import explain_repository, write_explain_metadata, write_explanation
from strucin.core.indexer import scan_repository, write_repo_index
from strucin.core.lifecycle import cleanup_stale_artifacts
from strucin.core.reporter import write_markdown_report
from strucin.core.semantic import (
    build_semantic_index,
    load_semantic_index,
    search_semantic_index,
    write_semantic_index,
)
from strucin.utils.logging import CommandTiming, emit_structured_log
from strucin.web.dashboard import build_dashboard, serve_dashboard

_INIT_TEMPLATE = """\
# StrucIn configuration
# See https://github.com/macitch/StrucIn for full documentation.

[scan]
# Additional directories to exclude (core exclusions like .git are always applied)
# exclude_dirs = ["docs", "scripts"]

[search]
# top_k = 5
# dimensions = 256
# embedding_model = "all-MiniLM-L6-v2"

[performance]
# max_workers = 8
# executor = "auto"  # "auto", "thread", or "process"

[lifecycle]
# cache_retention_days = 14

[security]
# safe_mode = false

[observability]
# structured_logging = false
# timing_enabled = true

[llm]
# anthropic_model = "claude-haiku-4-5-20251001"
# openai_model = "gpt-4o-mini"

[output]
# repo_index = "repo_index.json"
# analysis = "analysis.json"
# dependency_graph = "dependency_graph.json"
# report = "docs/REPORT.md"
# semantic_index = "semantic_index.json"
# explain_markdown = "docs/EXPLAIN.md"
# explain_metadata = "docs/explain.json"

[report]
# fan_out_threshold = 5
# complexity_threshold = 15
# loc_threshold = 400
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="strucin",
        description="Structural Intelligence for Software Systems",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command")

    # --- init ---
    init_parser = subparsers.add_parser("init", help="Scaffold a .strucin.toml configuration file")
    init_parser.add_argument(
        "--path",
        type=Path,
        default=Path(),
        help="Directory to create .strucin.toml in (default: current directory)",
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing .strucin.toml",
    )

    # --- scan ---
    scan_parser = subparsers.add_parser("scan", help="Scan a repository")
    scan_parser.add_argument("path", type=Path, help="Path to a Python repository")
    scan_parser.add_argument("--json", dest="json_output", action="store_true", help="Output JSON")

    # --- analyze ---
    analyze_parser = subparsers.add_parser("analyze", help="Run static analysis")
    analyze_parser.add_argument("path", type=Path, help="Path to a Python repository")
    analyze_parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Output JSON"
    )

    # --- report ---
    report_parser = subparsers.add_parser("report", help="Generate architecture report")
    report_parser.add_argument("path", type=Path, help="Path to a Python repository")
    report_parser.add_argument(
        "--safe-mode",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Redact sensitive details from report output",
    )

    # --- search ---
    search_parser = subparsers.add_parser("search", help="Semantic code search")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument(
        "--path",
        type=Path,
        default=Path(),
        help="Path to a Python repository (default: current directory)",
    )
    search_parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of results to return (default: 5)",
    )
    search_parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Output JSON"
    )

    # --- explain ---
    explain_parser = subparsers.add_parser("explain", help="Generate architecture narration")
    explain_parser.add_argument(
        "--path",
        type=Path,
        default=Path(),
        help="Path to a Python repository (default: current directory)",
    )
    explain_parser.add_argument(
        "--refresh",
        action="store_true",
        help="Regenerate explanation and bypass cache",
    )
    explain_parser.add_argument(
        "--safe-mode",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Redact sensitive details from explain output",
    )

    # --- diff ---
    diff_parser = subparsers.add_parser("diff", help="Compare two analysis snapshots")
    diff_parser.add_argument("before", type=Path, help="Path to earlier analysis.json")
    diff_parser.add_argument("after", type=Path, help="Path to later analysis.json")
    diff_parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Output JSON instead of Markdown"
    )

    # --- web ---
    web_parser = subparsers.add_parser("web", help="Generate interactive architecture dashboard")
    web_parser.add_argument(
        "--path",
        type=Path,
        default=Path(),
        help="Path to a Python repository (default: current directory)",
    )
    web_parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output directory for dashboard files (default: <repo>/.strucin_web)",
    )
    web_parser.add_argument(
        "--serve",
        action="store_true",
        help="Serve dashboard locally after generation",
    )
    web_parser.add_argument("--host", default="127.0.0.1", help="Host to bind local web server")
    web_parser.add_argument("--port", type=int, default=8765, help="Port to bind local web server")

    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(format="%(message)s", level=logging.WARNING)
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    try:
        if args.command == "init":
            return _run_init(args.path, args.force)
        if args.command == "scan":
            return _run_scan(args.path, json_output=args.json_output)
        if args.command == "analyze":
            return _run_analyze(args.path, json_output=args.json_output)
        if args.command == "report":
            return _run_report(args.path, args.safe_mode)
        if args.command == "search":
            return _run_search(args.path, args.query, args.top_k, json_output=args.json_output)
        if args.command == "explain":
            return _run_explain(args.path, args.refresh, args.safe_mode)
        if args.command == "diff":
            return _run_diff(args.before, args.after, json_output=args.json_output)
        if args.command == "web":
            return _run_web(args.path, args.out, args.serve, args.host, args.port)
    except (PermissionError, FileNotFoundError, ValueError) as exc:
        print_error(str(exc))
        return 1
    except Exception as exc:  # pragma: no cover - defensive fallback
        print_error(f"Unexpected failure: {exc}")
        traceback.print_exc()
        return 1

    print_error(f"Unknown command: {args.command}")
    return 1


def _validate_repo_path(target_path: Path) -> bool:
    if not target_path.exists():
        print_error(f"Path does not exist: {target_path}")
        return False
    if not target_path.is_dir():
        print_error(f"Path is not a directory: {target_path}")
        return False
    return True


def _resolve_config(target_path: Path) -> StrucInConfig:
    return load_config(target_path)


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


def _run_init(path: Path, force: bool) -> int:
    target_path = path.resolve()
    config_path = target_path / ".strucin.toml"
    if config_path.exists() and not force:
        print_error(f"{config_path} already exists. Use --force to overwrite.")
        return 1
    config_path.write_text(_INIT_TEMPLATE, encoding="utf-8")
    print_success(f"Created {config_path}")
    return 0


# ---------------------------------------------------------------------------
# scan
# ---------------------------------------------------------------------------


def _run_scan(path: Path, *, json_output: bool = False) -> int:
    timings: list[CommandTiming] = []
    target_path = path.resolve()
    if not _validate_repo_path(target_path):
        return 1
    config = _resolve_config(target_path)
    _run_lifecycle_cleanup(target_path, config)

    print_progress(1, 2, "Scanning repository files")
    started = perf_counter()
    repo_index = scan_repository(
        target_path,
        excluded_dirs=config.excluded_dirs,
        max_workers=config.performance.max_workers,
    )
    _record_timing(timings, "scan_repository", started)
    print_progress(2, 2, "Writing repository index")
    output_path = target_path / config.output.repo_index
    output_path.parent.mkdir(parents=True, exist_ok=True)
    started = perf_counter()
    write_repo_index(repo_index, output_path)
    _record_timing(timings, "write_repo_index", started)

    if json_output:
        print(
            json.dumps(
                {
                    "repo_root": str(target_path),
                    "file_count": repo_index.file_count,
                    "output": str(output_path),
                },
                indent=2,
            )
        )
    else:
        print(f"Scanned {repo_index.file_count} Python files.")
        table = format_table(
            headers=["Metric", "Value"],
            rows=[
                ["Repo Root", str(target_path)],
                ["Output", str(output_path)],
                ["Excluded Dirs", ", ".join(sorted(config.excluded_dirs))],
                ["Workers", str(config.performance.max_workers)],
            ],
        )
        print(table)
    _emit_command_summary("scan", target_path, timings, config)
    return 0


# ---------------------------------------------------------------------------
# analyze
# ---------------------------------------------------------------------------


def _run_analyze(path: Path, *, json_output: bool = False) -> int:
    timings: list[CommandTiming] = []
    target_path = path.resolve()
    if not _validate_repo_path(target_path):
        return 1
    config = _resolve_config(target_path)
    _run_lifecycle_cleanup(target_path, config)

    print_progress(1, 2, "Running AST analysis")
    started = perf_counter()
    analysis = analyze_repository(
        target_path,
        excluded_dirs=config.excluded_dirs,
        max_workers=config.performance.max_workers,
        executor=config.performance.executor,
    )
    _record_timing(timings, "analyze_repository", started)
    analysis_path = target_path / config.output.analysis
    dependency_graph_path = target_path / config.output.dependency_graph
    analysis_path.parent.mkdir(parents=True, exist_ok=True)
    print_progress(2, 2, "Writing analysis artifacts")
    started = perf_counter()
    write_analysis(analysis, analysis_path, dependency_graph_path)
    _record_timing(timings, "write_analysis", started)

    if json_output:
        print(
            json.dumps(
                {
                    "file_count": analysis.file_count,
                    "module_count": analysis.module_count,
                    "dependency_edges": len(analysis.dependency_graph_edges),
                    "cycles": len(analysis.cycles),
                    "analysis_path": str(analysis_path),
                    "dependency_graph_path": str(dependency_graph_path),
                },
                indent=2,
            )
        )
    else:
        print(f"Analyzed {analysis.file_count} Python files.")
        table = format_table(
            headers=["Metric", "Value"],
            rows=[
                ["Modules", str(analysis.module_count)],
                ["Dependency Edges", str(len(analysis.dependency_graph_edges))],
                ["Cycles", str(len(analysis.cycles))],
                ["Workers", str(config.performance.max_workers)],
            ],
        )
        print(table)
        print(f"Analysis file: {analysis_path}")
        print(f"Dependency graph: {dependency_graph_path}")
    _emit_command_summary("analyze", target_path, timings, config)
    return 0


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------


def _run_report(path: Path, safe_mode_override: bool | None) -> int:
    timings: list[CommandTiming] = []
    target_path = path.resolve()
    if not _validate_repo_path(target_path):
        return 1
    config = _resolve_config(target_path)
    _run_lifecycle_cleanup(target_path, config)
    safe_mode = _resolve_safe_mode(config, safe_mode_override)

    print_progress(1, 2, "Computing repository analysis")
    started = perf_counter()
    analysis = analyze_repository(
        target_path,
        excluded_dirs=config.excluded_dirs,
        max_workers=config.performance.max_workers,
        executor=config.performance.executor,
    )
    _record_timing(timings, "analyze_repository", started)
    print_progress(2, 2, "Rendering markdown report")
    output_path = target_path / config.output.report
    output_path.parent.mkdir(parents=True, exist_ok=True)
    started = perf_counter()
    write_markdown_report(analysis, output_path, safe_mode=safe_mode, report_config=config.report)
    _record_timing(timings, "write_report", started)
    print(f"Generated report for {analysis.file_count} Python files.")
    print(f"Wrote report to {output_path}")
    _emit_command_summary("report", target_path, timings, config, {"safe_mode": safe_mode})
    return 0


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


def _run_search(path: Path, query: str, top_k: int, *, json_output: bool = False) -> int:
    timings: list[CommandTiming] = []
    target_path = path.resolve()
    if not _validate_repo_path(target_path):
        return 1
    config = _resolve_config(target_path)
    _run_lifecycle_cleanup(target_path, config)

    requested_top_k = top_k if top_k > 0 else config.search.top_k
    dimensions = config.search.dimensions
    index_path = target_path / config.output.semantic_index
    index_path.parent.mkdir(parents=True, exist_ok=True)

    print_progress(1, 2, "Loading semantic index")
    started = perf_counter()
    if index_path.exists():
        semantic_index = load_semantic_index(index_path)
    else:
        semantic_index = build_semantic_index(
            target_path,
            dimensions=dimensions,
            embedding_model=config.search.embedding_model,
            excluded_dirs=config.excluded_dirs,
            max_workers=config.performance.max_workers,
        )
        write_semantic_index(semantic_index, index_path)
        if not json_output:
            print(f"Built semantic index with {semantic_index.chunk_count} chunks at {index_path}")
    _record_timing(timings, "load_or_build_semantic_index", started)

    print_progress(2, 2, "Executing semantic query")
    started = perf_counter()
    hits = search_semantic_index(semantic_index, query, top_k=requested_top_k)
    _record_timing(timings, "search_semantic_index", started)

    if json_output:
        results = [
            {
                "rank": rank,
                "score": round(hit.score, 4),
                "kind": hit.chunk.kind,
                "module_path": hit.chunk.module_path,
                "symbol": hit.chunk.symbol,
                "path": hit.chunk.path,
                "start_line": hit.chunk.start_line,
                "end_line": hit.chunk.end_line,
            }
            for rank, hit in enumerate(hits, start=1)
        ]
        print(json.dumps({"query": query, "top_k": requested_top_k, "results": results}, indent=2))
        _emit_command_summary("search", target_path, timings, config)
        return 0

    print(f"Top {requested_top_k} results for query: {query!r}")
    if not hits:
        print("No semantic matches found.")
        _emit_command_summary("search", target_path, timings, config)
        return 0

    rows: list[list[str]] = []
    for rank, hit in enumerate(hits, start=1):
        location = f"{hit.chunk.path}:{hit.chunk.start_line}"
        rows.append(
            [
                str(rank),
                f"{hit.score:.3f}",
                hit.chunk.kind,
                hit.chunk.module_path or "-",
                hit.chunk.symbol or "-",
                location,
            ]
        )
    print(
        format_table(
            headers=["Rank", "Score", "Kind", "Module", "Symbol", "Location"],
            rows=rows,
        )
    )
    _emit_command_summary("search", target_path, timings, config)
    return 0


# ---------------------------------------------------------------------------
# explain
# ---------------------------------------------------------------------------


def _run_explain(path: Path, refresh: bool, safe_mode_override: bool | None) -> int:
    timings: list[CommandTiming] = []
    target_path = path.resolve()
    if not _validate_repo_path(target_path):
        return 1
    config = _resolve_config(target_path)
    _run_lifecycle_cleanup(target_path, config)
    safe_mode = _resolve_safe_mode(config, safe_mode_override)

    print_progress(1, 2, "Generating architecture narration")
    started = perf_counter()
    explanation = explain_repository(
        target_path,
        refresh=refresh,
        safe_mode=safe_mode,
        excluded_dirs=config.excluded_dirs,
        max_workers=config.performance.max_workers,
        llm_config=config.llm,
    )
    _record_timing(timings, "explain_repository", started)
    explain_path = target_path / config.output.explain_markdown
    metadata_path = target_path / config.output.explain_metadata
    explain_path.parent.mkdir(parents=True, exist_ok=True)
    print_progress(2, 2, "Writing narration artifacts")
    started = perf_counter()
    write_explanation(explanation, explain_path)
    write_explain_metadata(explanation, metadata_path)
    _record_timing(timings, "write_explain_artifacts", started)
    print(f"Generated architecture narration at {explain_path}")
    print(f"Wrote explanation metadata to {metadata_path}")
    _emit_command_summary(
        "explain",
        target_path,
        timings,
        config,
        {"safe_mode": safe_mode, "refresh": refresh},
    )
    return 0


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------


def _run_diff(before: Path, after: Path, *, json_output: bool = False) -> int:
    from strucin.core.diff import diff_analyses, render_diff_json, render_diff_markdown

    before_path = before.resolve()
    after_path = after.resolve()
    for path in (before_path, after_path):
        if not path.exists():
            print_error(f"File does not exist: {path}")
            return 1

    result = diff_analyses(before_path, after_path)
    if json_output:
        print(render_diff_json(result))
    else:
        print(render_diff_markdown(result))
    return 0


# ---------------------------------------------------------------------------
# web
# ---------------------------------------------------------------------------


def _run_web(path: Path, out: Path | None, serve: bool, host: str, port: int) -> int:
    timings: list[CommandTiming] = []
    target_path = path.resolve()
    if not _validate_repo_path(target_path):
        return 1
    if port <= 0 or port > 65535:
        raise ValueError(f"Port out of range: {port}")

    config = _resolve_config(target_path)
    _run_lifecycle_cleanup(target_path, config)
    output_dir = out.resolve() if out is not None else target_path / ".strucin_web"

    print_progress(1, 2, "Building web dashboard artifacts")
    started = perf_counter()
    html_path = build_dashboard(
        target_path,
        output_dir,
        excluded_dirs=config.excluded_dirs,
        max_workers=config.performance.max_workers,
        executor=config.performance.executor,
    )
    _record_timing(timings, "build_dashboard", started)
    print_progress(2, 2, "Dashboard build complete")
    print(f"Dashboard generated at {html_path}")

    if not serve:
        print("Tip: run with --serve to start a local server.")
        _emit_command_summary("web", target_path, timings, config, {"served": False})
        return 0

    server = serve_dashboard(output_dir, host=host, port=port)
    url = f"http://{host}:{port}/index.html"
    print(f"Serving dashboard at {url}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
    finally:
        server.server_close()
    _emit_command_summary("web", target_path, timings, config, {"served": True})
    return 0


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _run_lifecycle_cleanup(repo_root: Path, config: StrucInConfig) -> None:
    artifact_filenames = {
        config.output.repo_index,
        config.output.analysis,
        config.output.dependency_graph,
        config.output.report,
        config.output.semantic_index,
        config.output.explain_markdown,
        config.output.explain_metadata,
    }
    cleanup_stale_artifacts(
        repo_root=repo_root,
        artifact_filenames=artifact_filenames,
        cache_retention_days=config.lifecycle.cache_retention_days,
    )


def _resolve_safe_mode(config: StrucInConfig, override: bool | None) -> bool:
    if override is None:
        return config.security.safe_mode
    return override


def _record_timing(timings: list[CommandTiming], stage: str, started_at: float) -> None:
    timings.append(CommandTiming(stage=stage, duration_ms=(perf_counter() - started_at) * 1000.0))


def _emit_command_summary(
    command: str,
    repo_root: Path,
    timings: list[CommandTiming],
    config: StrucInConfig,
    extra_fields: dict[str, object] | None = None,
) -> None:
    if not timings:
        return
    total_ms = sum(item.duration_ms for item in timings)
    bottleneck = max(timings, key=lambda item: item.duration_ms)
    if config.observability.timing_enabled:
        print(
            format_table(
                headers=["Timing", "Value"],
                rows=[
                    ["Total (ms)", f"{total_ms:.2f}"],
                    ["Bottleneck", f"{bottleneck.stage} ({bottleneck.duration_ms:.2f} ms)"],
                ],
            )
        )

    payload: dict[str, object] = {
        "command": command,
        "repo_root": str(repo_root),
        "total_ms": round(total_ms, 3),
        "bottleneck_stage": bottleneck.stage,
        "bottleneck_ms": round(bottleneck.duration_ms, 3),
        "timings": {item.stage: round(item.duration_ms, 3) for item in timings},
    }
    if extra_fields:
        payload.update(extra_fields)
    emit_structured_log(config.observability.structured_logging, "command_completed", **payload)
