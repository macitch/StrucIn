from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from dataclasses import replace as dc_replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from strucin.core.analyzer import AnalysisResult, FileAnalysis, analyze_repository
from strucin.core.artifacts import build_artifact_metadata
from strucin.core.config import LLMConfig

_logger = logging.getLogger(__name__)

#: Bump when the explain cache schema or key format changes to force re-generation.
CACHE_VERSION = "1"

MAX_CONTEXT_CHARS = 12_000
MAX_SUMMARY_FILES = 8
MAX_ONBOARDING_STEPS = 8

SECRET_PATTERNS = [
    re.compile(r"(?i)(password|passwd|pwd)\s*[:=]\s*['\"][^'\"]+['\"]"),
    re.compile(r"(?i)(api[_-]?key|token|secret)\s*[:=]\s*['\"][^'\"]+['\"]"),
    re.compile(r"(?i)authorization\s*[:=]\s*['\"][^'\"]+['\"]"),
    re.compile(r"(?i)\b(password|api[_-]?key|token|secret)\s*=\s*[^\s]+"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
        flags=re.MULTILINE,
    ),
    re.compile(r"(?i)(https?://[^:\s]+:)([^@\s]+)(@)"),
]


@dataclass(frozen=True)
class ExplainOutput:
    repo_root: str
    generated_at: str
    cache_key: str
    content: str


def _redact_text(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        if pattern.pattern.startswith("(?i)(https?://"):
            redacted = pattern.sub(r"\1[REDACTED_SECRET]\3", redacted)
        else:
            redacted = pattern.sub("[REDACTED_SECRET]", redacted)
    return redacted


def redact_analysis(analysis: AnalysisResult) -> AnalysisResult:
    """Return a copy of *analysis* with secrets redacted from all docstrings.

    Only ``docstring`` fields are modified; module names, paths, metrics, and
    dependency edges are intentionally preserved so the structural analysis
    remains accurate.  Uses :func:`dataclasses.replace` so new fields added
    to :class:`FileAnalysis` are automatically carried through.
    """
    redacted_files = [
        dc_replace(file_info, docstring=_redact_text(file_info.docstring))
        if file_info.docstring
        else file_info
        for file_info in analysis.files
    ]
    return dc_replace(analysis, files=redacted_files)


def _limited_context(analysis: AnalysisResult) -> str:
    payload = {
        "repo_root": analysis.repo_root,
        "file_count": analysis.file_count,
        "module_count": analysis.module_count,
        "cycles": analysis.cycles,
        "files": [
            {
                "module_path": file_info.module_path,
                "path": file_info.path,
                "loc": file_info.loc,
                "fan_in": file_info.fan_in,
                "fan_out": file_info.fan_out,
                "complexity": file_info.cyclomatic_complexity,
                "docstring": file_info.docstring,
            }
            for file_info in analysis.files
        ],
    }
    serialized = json.dumps(payload, sort_keys=True)
    return serialized[:MAX_CONTEXT_CHARS]


def _cache_key_from_analysis(analysis: AnalysisResult) -> str:
    context = _limited_context(analysis).encode("utf-8")
    return hashlib.sha256(context).hexdigest()


def _largest_files(analysis: AnalysisResult) -> list[FileAnalysis]:
    return sorted(analysis.files, key=lambda file_info: file_info.loc, reverse=True)


def _hotspots(analysis: AnalysisResult) -> list[FileAnalysis]:
    return sorted(
        analysis.files,
        key=lambda file_info: file_info.loc * file_info.fan_out,
        reverse=True,
    )


def _most_central(analysis: AnalysisResult) -> list[FileAnalysis]:
    return sorted(analysis.files, key=lambda file_info: file_info.fan_in, reverse=True)


def _render_cycle_explanations(analysis: AnalysisResult, safe_mode: bool) -> list[str]:
    lines: list[str] = []
    if not analysis.cycles:
        lines.append("- No dependency cycles were detected.")
        return lines
    for cycle in analysis.cycles:
        if safe_mode:
            lines.append("- Cycle detected between internal modules (names hidden in safe mode).")
        else:
            cycle_path = " -> ".join(f"`{node}`" for node in cycle)
            lines.append(f"- Cycle: {cycle_path}")
        lines.append(
            "  Impact: increases coupling and test setup overhead; changes ripple across modules."
        )
        lines.append(
            "  Suggested break: extract shared interfaces or move shared logic "
            "to a lower-level module."
        )
    return lines


def _render_onboarding_guide(analysis: AnalysisResult, safe_mode: bool) -> list[str]:
    guide: list[str] = []
    hotspots = _hotspots(analysis)[:3]
    central = _most_central(analysis)[:3]
    guide.append("1. Run `strucin scan <repo>` to baseline repository structure.")
    guide.append("2. Run `strucin analyze <repo>` to inspect dependencies and metrics.")
    for index, file_info in enumerate(hotspots, start=3):
        if safe_mode:
            guide.append(
                f"{index}. Review a top hotspot first "
                f"(loc={file_info.loc}, fan_out={file_info.fan_out})."
            )
        else:
            guide.append(
                f"{index}. Review hotspot `{file_info.module_path}` first "
                f"(loc={file_info.loc}, fan_out={file_info.fan_out})."
            )
    next_index = len(guide) + 1
    if central:
        if safe_mode:
            guide.append(
                f"{next_index}. Map inbound dependents around the top "
                f"{len(central)} central modules."
            )
        else:
            module_list = ", ".join(f"`{file_info.module_path}`" for file_info in central)
            guide.append(
                f"{next_index}. Map inbound dependents around central modules: {module_list}."
            )
        next_index += 1
    if analysis.cycles:
        guide.append(f"{next_index}. Resolve {len(analysis.cycles)} dependency cycle(s) early.")
    return guide[:MAX_ONBOARDING_STEPS]


_LLM_SYSTEM_PROMPT = """\
You are an expert software architect. Generate a Markdown architecture narration \
for a Python repository.

Use exactly these section headings (in this order):
# StrucIn Architecture Narration
## System Overview
## Module Summaries
### Top Hotspots
### Largest Modules
### Most Imported Modules
## Cycle Explanations
## Onboarding Guide

Focus on architectural insights and actionable advice, not just repeating metrics."""


def _detect_llm(llm_config: LLMConfig) -> tuple[str, str] | None:
    """Returns (provider, model) or None. Checks Anthropic first, then OpenAI."""
    import os

    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            import anthropic  # noqa: F401

            return ("anthropic", llm_config.anthropic_model)
        except ImportError:
            pass
    if os.environ.get("OPENAI_API_KEY"):
        try:
            import openai  # noqa: F401

            return ("openai", llm_config.openai_model)
        except ImportError:
            pass
    return None


def _call_llm(context: str, provider: str, model: str) -> str | None:
    """Call LLM API. Returns markdown string or None on any failure.

    The system prompt is passed via the provider's dedicated mechanism
    (``system=`` for Anthropic, a ``role:"system"`` message for OpenAI) rather
    than being concatenated into the user message.
    """
    user_content = f"Repository Analysis:\n{context}"
    try:
        if provider == "anthropic":
            import anthropic

            client = anthropic.Anthropic()
            msg = client.messages.create(
                model=model,
                max_tokens=2048,
                system=_LLM_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_content}],
            )
            block = msg.content[0]
            return str(getattr(block, "text", ""))
        if provider == "openai":
            import openai

            client = openai.OpenAI()
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _LLM_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
            )
            return resp.choices[0].message.content  # type: ignore[no-any-return]
    except Exception as exc:  # noqa: BLE001
        _logger.warning("LLM call failed (%s): %s", type(exc).__name__, type(exc).__qualname__)
        return None
    _logger.warning("Unknown LLM provider %r; skipping LLM call.", provider)
    return None


def generate_explanation(analysis: AnalysisResult, safe_mode: bool = False) -> str:
    hottest = _hotspots(analysis)[:MAX_SUMMARY_FILES]
    largest = _largest_files(analysis)[:MAX_SUMMARY_FILES]
    central = _most_central(analysis)[:MAX_SUMMARY_FILES]

    lines: list[str] = []
    lines.append("# StrucIn Architecture Narration")
    lines.append("")
    lines.append("## System Overview")
    lines.append(
        f"This repository contains **{analysis.file_count} Python files** and "
        f"**{analysis.module_count} modules** connected by "
        f"**{len(analysis.dependency_graph_edges)} internal dependencies**."
    )
    lines.append(f"Safe mode is **{'enabled' if safe_mode else 'disabled'}**.")
    if analysis.cycles:
        lines.append(
            f"There are **{len(analysis.cycles)} dependency cycle(s)** "
            "that should be prioritized."
        )
    else:
        lines.append("No dependency cycles were detected in the current graph.")
    lines.append("")

    lines.append("## Module Summaries")
    lines.append("### Top Hotspots")
    for file_info in hottest:
        score = file_info.loc * file_info.fan_out
        if safe_mode:
            lines.append(
                f"- hotspot={score}, loc={file_info.loc}, fan_out={file_info.fan_out}, "
                f"complexity={file_info.cyclomatic_complexity}"
            )
        else:
            lines.append(
                f"- `{file_info.module_path}` ({file_info.path}): "
                f"hotspot={score}, loc={file_info.loc}, fan_out={file_info.fan_out}, "
                f"complexity={file_info.cyclomatic_complexity}"
            )
            if file_info.docstring:
                preview = file_info.docstring[:80]
                lines.append(f"  docstring: {preview}")
    lines.append("")
    lines.append("### Largest Modules")
    for file_info in largest:
        if safe_mode:
            lines.append(
                f"- loc={file_info.loc}, fan_in={file_info.fan_in}, fan_out={file_info.fan_out}"
            )
        else:
            lines.append(
                f"- `{file_info.module_path}`: loc={file_info.loc}, "
                f"fan_in={file_info.fan_in}, fan_out={file_info.fan_out}"
            )
    lines.append("")
    lines.append("### Most Imported Modules")
    for file_info in central:
        if safe_mode:
            lines.append(f"- fan_in={file_info.fan_in}")
        else:
            lines.append(f"- `{file_info.module_path}`: fan_in={file_info.fan_in}")
    lines.append("")

    lines.append("## Cycle Explanations")
    lines.extend(_render_cycle_explanations(analysis, safe_mode=safe_mode))
    lines.append("")

    lines.append("## Onboarding Guide")
    lines.extend(_render_onboarding_guide(analysis, safe_mode=safe_mode))
    lines.append("")

    return "\n".join(lines)


def _load_cache(cache_path: Path) -> dict[str, dict[str, str]]:
    """Return cached entries keyed by cache_key.

    Returns an empty dict when the file is absent, unparseable, or was written
    by a different :data:`CACHE_VERSION`.
    """
    if not cache_path.exists():
        return {}
    parsed = json.loads(cache_path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict) or parsed.get("cache_version") != CACHE_VERSION:
        return {}
    entries = parsed.get("entries", {})
    if not isinstance(entries, dict):
        return {}
    return cast(dict[str, dict[str, str]], entries)


_MAX_CACHE_ENTRIES = 50


def _write_cache(cache_path: Path, cache: dict[str, dict[str, str]]) -> None:
    if len(cache) > _MAX_CACHE_ENTRIES:
        oldest_keys = sorted(cache, key=lambda k: cache[k].get("generated_at", ""))
        for key in oldest_keys[: len(cache) - _MAX_CACHE_ENTRIES]:
            del cache[key]
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"cache_version": CACHE_VERSION, "entries": cache}
    cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def explain_repository(
    repo_path: Path,
    refresh: bool = False,
    safe_mode: bool = False,
    excluded_dirs: set[str] | None = None,
    max_workers: int | None = None,
    executor: str = "auto",
    llm_config: LLMConfig | None = None,
) -> ExplainOutput:
    analysis = analyze_repository(
        repo_path,
        excluded_dirs=excluded_dirs,
        max_workers=max_workers,
        executor=executor,
    )
    redacted = redact_analysis(analysis)
    llm_info = _detect_llm(llm_config) if llm_config is not None else None
    llm_tag = f"{llm_info[0]}:{llm_info[1]}" if llm_info else "template"
    cache_key = f"safe_mode={safe_mode}:llm={llm_tag}:{_cache_key_from_analysis(redacted)}"
    root = Path(redacted.repo_root)
    cache_path = root / ".strucin_cache" / "explain_cache.json"
    cache = _load_cache(cache_path)

    if not refresh and cache_key in cache:
        cached = cache[cache_key]
        return ExplainOutput(
            repo_root=redacted.repo_root,
            generated_at=cached["generated_at"],
            cache_key=cache_key,
            content=cached["content"],
        )

    if llm_info:
        context = _limited_context(redacted)
        content = _call_llm(context, llm_info[0], llm_info[1]) or generate_explanation(
            redacted, safe_mode=safe_mode
        )
    else:
        content = generate_explanation(redacted, safe_mode=safe_mode)
    generated_at = datetime.now(UTC).isoformat()
    cache[cache_key] = {"generated_at": generated_at, "content": content}
    _write_cache(cache_path, cache)
    return ExplainOutput(
        repo_root=redacted.repo_root,
        generated_at=generated_at,
        cache_key=cache_key,
        content=content,
    )


def write_explanation(output: ExplainOutput, output_path: Path) -> None:
    output_path.write_text(output.content, encoding="utf-8")


def write_explain_metadata(output: ExplainOutput, output_path: Path) -> None:
    metadata = {
        "artifact_metadata": build_artifact_metadata(
            "explain_metadata",
            generated_at=output.generated_at,
        ),
        "repo_root": output.repo_root,
        "generated_at": output.generated_at,
        "cache_key": output.cache_key,
    }
    output_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
