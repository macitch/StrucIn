"""Diff two StrucIn analysis JSON artefacts and produce a structured report.

Typical usage::

    from pathlib import Path
    from strucin.core.diff import diff_analyses, render_diff_markdown

    result = diff_analyses(Path("before.json"), Path("after.json"))
    print(render_diff_markdown(result))
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from strucin.exceptions import AnalysisError

_logger = logging.getLogger(__name__)

__all__ = [
    "ComplexityDelta",
    "CouplingDelta",
    "DiffResult",
    "DiffSummary",
    "LocDelta",
    "diff_analyses",
    "load_analysis_json",
    "render_diff_json",
    "render_diff_markdown",
]

_REQUIRED_KEYS: frozenset[str] = frozenset(
    {"generated_at", "files", "cycles"}
)

_COUPLING_DELTA_THRESHOLD = 2


# ---------------------------------------------------------------------------
# Delta dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ComplexityDelta:
    """Change in cyclomatic complexity for a single module."""

    module_path: str
    before: int
    after: int
    delta: int


@dataclass(frozen=True)
class CouplingDelta:
    """Change in fan-in or fan-out for a single module."""

    module_path: str
    fan_in_before: int
    fan_in_after: int
    fan_out_before: int
    fan_out_after: int


@dataclass(frozen=True)
class LocDelta:
    """Change in lines of code for a single module."""

    module_path: str
    before: int
    after: int
    delta: int


@dataclass(frozen=True)
class DiffSummary:
    """Aggregate statistics for a diff run."""

    modules_added: int
    modules_removed: int
    cycles_new: int
    cycles_resolved: int
    total_loc_delta: int
    files_changed: int


@dataclass(frozen=True)
class DiffResult:
    """Complete diff between two StrucIn analysis snapshots."""

    before_generated_at: str
    after_generated_at: str
    added_modules: list[str]
    removed_modules: list[str]
    new_cycles: list[list[str]]
    resolved_cycles: list[list[str]]
    complexity_changes: list[ComplexityDelta]
    coupling_changes: list[CouplingDelta]
    loc_changes: list[LocDelta]
    summary: DiffSummary


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def load_analysis_json(path: Path) -> dict[str, object]:
    """Load and minimally validate an analysis JSON file.

    Args:
        path: Absolute or relative path to the analysis JSON artefact.

    Returns:
        Parsed JSON payload as a plain dict.

    Raises:
        AnalysisError: If the file cannot be read, is not valid JSON, or is
            missing any of the required top-level keys.
    """
    _logger.debug("loading analysis JSON from %s", path)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AnalysisError(f"cannot read analysis file {path}: {exc}") from exc

    try:
        payload: dict[str, object] = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AnalysisError(f"invalid JSON in {path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise AnalysisError(f"analysis file {path} must contain a JSON object at the top level")

    missing = _REQUIRED_KEYS - payload.keys()
    if missing:
        raise AnalysisError(
            f"analysis file {path} is missing required keys: {sorted(missing)}"
        )

    return payload


# ---------------------------------------------------------------------------
# Comparison helpers
# ---------------------------------------------------------------------------


def _files_by_module(payload: dict[str, object]) -> dict[str, dict[str, object]]:
    """Return a module_path → file-dict mapping from a parsed analysis payload."""
    files = payload.get("files", [])
    if not isinstance(files, list):
        return {}
    result: dict[str, dict[str, object]] = {}
    for entry in files:
        if isinstance(entry, dict):
            module_path = entry.get("module_path")
            if isinstance(module_path, str):
                result[module_path] = entry
    return result


def _cycles_as_frozensets(payload: dict[str, object]) -> set[frozenset[str]]:
    """Convert the ``cycles`` list to a set of frozensets for order-independent comparison."""
    cycles = payload.get("cycles", [])
    if not isinstance(cycles, list):
        return set()
    result: set[frozenset[str]] = set()
    for cycle in cycles:
        if isinstance(cycle, list) and all(isinstance(node, str) for node in cycle):
            result.add(frozenset(cycle))
    return result


def _int_field(entry: dict[str, object], key: str) -> int:
    value = entry.get(key, 0)
    return int(value) if isinstance(value, (int, float)) else 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def diff_analyses(before_path: Path, after_path: Path) -> DiffResult:
    """Compare two StrucIn analysis JSON files and return a structured diff.

    Args:
        before_path: Path to the baseline analysis JSON artefact.
        after_path: Path to the updated analysis JSON artefact.

    Returns:
        A :class:`DiffResult` describing all structural changes between the
        two snapshots.

    Raises:
        AnalysisError: If either file cannot be loaded or validated.
    """
    _logger.info("diffing %s -> %s", before_path, after_path)

    before = load_analysis_json(before_path)
    after = load_analysis_json(after_path)

    before_generated_at = str(before.get("generated_at", ""))
    after_generated_at = str(after.get("generated_at", ""))

    before_modules = _files_by_module(before)
    after_modules = _files_by_module(after)

    before_keys = set(before_modules)
    after_keys = set(after_modules)

    added_modules = sorted(after_keys - before_keys)
    removed_modules = sorted(before_keys - after_keys)

    before_cycles = _cycles_as_frozensets(before)
    after_cycles = _cycles_as_frozensets(after)

    new_cycle_sets = after_cycles - before_cycles
    resolved_cycle_sets = before_cycles - after_cycles

    new_cycles: list[list[str]] = sorted(
        [sorted(cycle) for cycle in new_cycle_sets],
        key=lambda c: (len(c), c),
    )
    resolved_cycles: list[list[str]] = sorted(
        [sorted(cycle) for cycle in resolved_cycle_sets],
        key=lambda c: (len(c), c),
    )

    complexity_changes: list[ComplexityDelta] = []
    coupling_changes: list[CouplingDelta] = []
    loc_changes: list[LocDelta] = []

    common_modules = sorted(before_keys & after_keys)

    for module_path in common_modules:
        b_entry = before_modules[module_path]
        a_entry = after_modules[module_path]

        b_complexity = _int_field(b_entry, "cyclomatic_complexity")
        a_complexity = _int_field(a_entry, "cyclomatic_complexity")
        if b_complexity != a_complexity:
            complexity_changes.append(
                ComplexityDelta(
                    module_path=module_path,
                    before=b_complexity,
                    after=a_complexity,
                    delta=a_complexity - b_complexity,
                )
            )

        b_fan_in = _int_field(b_entry, "fan_in")
        a_fan_in = _int_field(a_entry, "fan_in")
        b_fan_out = _int_field(b_entry, "fan_out")
        a_fan_out = _int_field(a_entry, "fan_out")
        if (
            abs(a_fan_in - b_fan_in) >= _COUPLING_DELTA_THRESHOLD
            or abs(a_fan_out - b_fan_out) >= _COUPLING_DELTA_THRESHOLD
        ):
            coupling_changes.append(
                CouplingDelta(
                    module_path=module_path,
                    fan_in_before=b_fan_in,
                    fan_in_after=a_fan_in,
                    fan_out_before=b_fan_out,
                    fan_out_after=a_fan_out,
                )
            )

        b_loc = _int_field(b_entry, "loc")
        a_loc = _int_field(a_entry, "loc")
        if b_loc != a_loc:
            loc_changes.append(
                LocDelta(
                    module_path=module_path,
                    before=b_loc,
                    after=a_loc,
                    delta=a_loc - b_loc,
                )
            )

    total_loc_delta = sum(delta.delta for delta in loc_changes)
    files_changed = len(
        {d.module_path for d in complexity_changes}
        | {d.module_path for d in coupling_changes}
        | {d.module_path for d in loc_changes}
    )

    summary = DiffSummary(
        modules_added=len(added_modules),
        modules_removed=len(removed_modules),
        cycles_new=len(new_cycles),
        cycles_resolved=len(resolved_cycles),
        total_loc_delta=total_loc_delta,
        files_changed=files_changed,
    )

    _logger.debug(
        "diff complete: +%d/-%d modules, %d new cycles, %d resolved cycles",
        len(added_modules),
        len(removed_modules),
        len(new_cycles),
        len(resolved_cycles),
    )

    return DiffResult(
        before_generated_at=before_generated_at,
        after_generated_at=after_generated_at,
        added_modules=added_modules,
        removed_modules=removed_modules,
        new_cycles=new_cycles,
        resolved_cycles=resolved_cycles,
        complexity_changes=complexity_changes,
        coupling_changes=coupling_changes,
        loc_changes=loc_changes,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def _md_module_list(lines: list[str], heading: str, modules: list[str]) -> None:
    lines.append(f"## {heading}")
    if modules:
        lines.extend(f"- `{m}`" for m in modules)
    else:
        lines.append("- None")
    lines.append("")


def _md_cycle_list(lines: list[str], heading: str, cycles: list[list[str]]) -> None:
    lines.append(f"## {heading}")
    if cycles:
        for cycle in cycles:
            lines.append(f"- {' -> '.join(f'`{node}`' for node in cycle)}")
    else:
        lines.append("- None")
    lines.append("")


def _md_complexity_section(lines: list[str], changes: list[ComplexityDelta]) -> None:
    lines.append("## Complexity Changes")
    if changes:
        for change in changes:
            lines.append(
                f"- `{change.module_path}`: {change.before} -> {change.after} "
                f"({change.delta:+d})"
            )
    else:
        lines.append("- None")
    lines.append("")


def _md_coupling_section(lines: list[str], changes: list[CouplingDelta]) -> None:
    lines.append("## Coupling Changes")
    if changes:
        for change in changes:
            fan_in_delta = change.fan_in_after - change.fan_in_before
            fan_out_delta = change.fan_out_after - change.fan_out_before
            lines.append(
                f"- `{change.module_path}`: "
                f"fan_in {change.fan_in_before} -> {change.fan_in_after} "
                f"({fan_in_delta:+d}), "
                f"fan_out {change.fan_out_before} -> {change.fan_out_after} "
                f"({fan_out_delta:+d})"
            )
    else:
        lines.append("- None")
    lines.append("")


def _md_loc_section(lines: list[str], changes: list[LocDelta]) -> None:
    lines.append("## LOC Changes")
    if changes:
        for change in changes:
            lines.append(
                f"- `{change.module_path}`: {change.before} -> {change.after} "
                f"({change.delta:+d})"
            )
    else:
        lines.append("- None")
    lines.append("")


def render_diff_markdown(diff: DiffResult) -> str:
    """Render a :class:`DiffResult` as a human-readable Markdown report.

    Args:
        diff: The diff result produced by :func:`diff_analyses`.

    Returns:
        A UTF-8-safe Markdown string.
    """
    lines: list[str] = []

    lines.append("# StrucIn Diff Report")
    lines.append("")

    lines.append("## Summary")
    lines.append(f"- Before snapshot: `{diff.before_generated_at}`")
    lines.append(f"- After snapshot:  `{diff.after_generated_at}`")
    lines.append(f"- Modules added: **{diff.summary.modules_added}**")
    lines.append(f"- Modules removed: **{diff.summary.modules_removed}**")
    lines.append(f"- New cycles: **{diff.summary.cycles_new}**")
    lines.append(f"- Resolved cycles: **{diff.summary.cycles_resolved}**")
    lines.append(f"- Total LOC delta: **{diff.summary.total_loc_delta:+d}**")
    lines.append(f"- Files changed: **{diff.summary.files_changed}**")
    lines.append("")

    _md_module_list(lines, "Added Modules", diff.added_modules)
    _md_module_list(lines, "Removed Modules", diff.removed_modules)
    _md_cycle_list(lines, "New Cycles", diff.new_cycles)
    _md_cycle_list(lines, "Resolved Cycles", diff.resolved_cycles)
    _md_complexity_section(lines, diff.complexity_changes)
    _md_coupling_section(lines, diff.coupling_changes)
    _md_loc_section(lines, diff.loc_changes)

    return "\n".join(lines)


def render_diff_json(diff: DiffResult) -> str:
    """Serialize a :class:`DiffResult` to a JSON string.

    Args:
        diff: The diff result produced by :func:`diff_analyses`.

    Returns:
        A pretty-printed JSON string (2-space indent, trailing newline).
    """
    return json.dumps(asdict(diff), indent=2) + "\n"
