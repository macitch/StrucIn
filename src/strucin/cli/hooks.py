"""Pre-commit hook entry points for StrucIn.

Provides two hooks that can be wired into ``.pre-commit-config.yaml`` via the
``strucin-check-cycles`` and ``strucin-check-complexity`` console scripts:

- ``check_cycles``      — fails (exit 1) when dependency cycles are detected.
- ``check_complexity``  — fails (exit 1) when any module exceeds the configured
                          cyclomatic-complexity threshold.

Each function is intentionally self-contained: it runs the full analysis
pipeline so that the hook works in a freshly-cloned environment with no
pre-existing artefacts on disk.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from strucin.cli.ui import print_error
from strucin.core.analyzer import AnalysisResult, analyze_repository
from strucin.core.config import load_config

_logger = logging.getLogger(__name__)

_DEFAULT_COMPLEXITY_THRESHOLD = 15


# ---------------------------------------------------------------------------
# Core hook logic
# ---------------------------------------------------------------------------


def check_cycles(repo_path: Path) -> int:
    """Run the analysis pipeline and report any dependency cycles found.

    Args:
        repo_path: Absolute path to the repository root being checked.

    Returns:
        0 if no cycles are present, 1 otherwise.
    """
    config = load_config(repo_path)
    analysis: AnalysisResult = analyze_repository(
        repo_path,
        excluded_dirs=config.excluded_dirs,
        max_workers=config.performance.max_workers,
        executor=config.performance.executor,
    )

    if not analysis.cycles:
        return 0

    print_error(
        f"Dependency cycles detected in {repo_path} — "
        f"{len(analysis.cycles)} cycle(s) found."
    )
    for index, cycle in enumerate(analysis.cycles, start=1):
        cycle_repr = " -> ".join(cycle) + f" -> {cycle[0]}"
        print(f"  Cycle {index}: {cycle_repr}", file=sys.stderr)

    return 1


def check_complexity(repo_path: Path, threshold: int = _DEFAULT_COMPLEXITY_THRESHOLD) -> int:
    """Run the analysis pipeline and report modules that exceed *threshold*.

    Args:
        repo_path: Absolute path to the repository root being checked.
        threshold: Maximum allowed cyclomatic complexity per module.
                   Modules whose ``cyclomatic_complexity`` strictly exceeds
                   this value are reported as failures.

    Returns:
        0 if every module is within the threshold, 1 otherwise.
    """
    config = load_config(repo_path)
    analysis: AnalysisResult = analyze_repository(
        repo_path,
        excluded_dirs=config.excluded_dirs,
        max_workers=config.performance.max_workers,
        executor=config.performance.executor,
    )

    offenders = [fa for fa in analysis.files if fa.cyclomatic_complexity > threshold]

    if not offenders:
        return 0

    print_error(
        f"Complexity threshold exceeded in {repo_path} — "
        f"{len(offenders)} module(s) above threshold of {threshold}."
    )
    for fa in sorted(offenders, key=lambda f: f.cyclomatic_complexity, reverse=True):
        print(
            f"  {fa.path}  (complexity={fa.cyclomatic_complexity}, threshold={threshold})",
            file=sys.stderr,
        )

    return 1


# ---------------------------------------------------------------------------
# Argument parsers
# ---------------------------------------------------------------------------


def _build_cycles_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="strucin-check-cycles",
        description="Fail if dependency cycles are found in the repository.",
    )
    parser.add_argument(
        "path",
        type=Path,
        nargs="?",
        default=Path(),
        help="Path to the repository root (default: current directory).",
    )
    return parser


def _build_complexity_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="strucin-check-complexity",
        description="Fail if any module exceeds the configured complexity threshold.",
    )
    parser.add_argument(
        "path",
        type=Path,
        nargs="?",
        default=Path(),
        help="Path to the repository root (default: current directory).",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=_DEFAULT_COMPLEXITY_THRESHOLD,
        metavar="N",
        help=(
            f"Maximum allowed cyclomatic complexity per module "
            f"(default: {_DEFAULT_COMPLEXITY_THRESHOLD})."
        ),
    )
    return parser


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def main_cycles(argv: list[str] | None = None) -> int:
    """Entry point for the ``strucin-check-cycles`` pre-commit hook.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]`` when *None*).

    Returns:
        Process exit code: 0 on success, 1 when cycles are detected.
    """
    logging.basicConfig(format="%(message)s", level=logging.WARNING)
    args = _build_cycles_parser().parse_args(argv)
    repo_path = args.path.resolve()

    if not repo_path.is_dir():
        print_error(f"Path is not a directory: {repo_path}")
        return 1

    try:
        return check_cycles(repo_path)
    except (PermissionError, FileNotFoundError, ValueError) as exc:
        print_error(str(exc))
        return 1
    except Exception as exc:  # pragma: no cover - defensive fallback
        print_error(f"Unexpected failure: {exc}")
        return 1


def main_complexity(argv: list[str] | None = None) -> int:
    """Entry point for the ``strucin-check-complexity`` pre-commit hook.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]`` when *None*).

    Returns:
        Process exit code: 0 on success, 1 when complexity violations exist.
    """
    logging.basicConfig(format="%(message)s", level=logging.WARNING)
    args = _build_complexity_parser().parse_args(argv)
    repo_path = args.path.resolve()

    if not repo_path.is_dir():
        print_error(f"Path is not a directory: {repo_path}")
        return 1

    try:
        return check_complexity(repo_path, threshold=args.threshold)
    except (PermissionError, FileNotFoundError, ValueError) as exc:
        print_error(str(exc))
        return 1
    except Exception as exc:  # pragma: no cover - defensive fallback
        print_error(f"Unexpected failure: {exc}")
        return 1
