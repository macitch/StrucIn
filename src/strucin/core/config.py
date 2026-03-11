from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass
from os import cpu_count
from pathlib import Path
from typing import Any, cast

from strucin.core.indexer import EXCLUDED_DIRS

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OutputConfig:
    repo_index: str = "repo_index.json"
    analysis: str = "analysis.json"
    dependency_graph: str = "dependency_graph.json"
    report: str = "docs/REPORT.md"
    semantic_index: str = "semantic_index.json"
    explain_markdown: str = "docs/EXPLAIN.md"
    explain_metadata: str = "explain.json"


@dataclass(frozen=True)
class SearchConfig:
    top_k: int = 5
    dimensions: int = 256
    embedding_model: str = "all-MiniLM-L6-v2"


@dataclass(frozen=True)
class LLMConfig:
    anthropic_model: str = "claude-haiku-4-5-20251001"
    openai_model: str = "gpt-4o-mini"


_VALID_EXECUTORS = {"auto", "thread", "process"}


@dataclass(frozen=True)
class PerformanceConfig:
    max_workers: int = max(1, min(cpu_count() or 4, 16))
    executor: str = "auto"


@dataclass(frozen=True)
class LifecycleConfig:
    cache_retention_days: int = 14


@dataclass(frozen=True)
class SecurityConfig:
    safe_mode: bool = False


@dataclass(frozen=True)
class ObservabilityConfig:
    structured_logging: bool = False
    timing_enabled: bool = True


@dataclass(frozen=True)
class ReportConfig:
    fan_out_threshold: int = 5
    complexity_threshold: int = 15
    loc_threshold: int = 400


@dataclass(frozen=True)
class StrucInConfig:
    excluded_dirs: set[str]
    output: OutputConfig
    search: SearchConfig
    performance: PerformanceConfig
    lifecycle: LifecycleConfig
    security: SecurityConfig
    observability: ObservabilityConfig
    llm: LLMConfig
    report: ReportConfig


def default_config() -> StrucInConfig:
    return StrucInConfig(
        excluded_dirs=set(EXCLUDED_DIRS),
        output=OutputConfig(),
        search=SearchConfig(),
        performance=PerformanceConfig(),
        lifecycle=LifecycleConfig(),
        security=SecurityConfig(),
        observability=ObservabilityConfig(),
        llm=LLMConfig(),
        report=ReportConfig(),
    )


def load_config(repo_root: Path) -> StrucInConfig:
    config_path = repo_root / ".strucin.toml"
    if not config_path.exists():
        return default_config()

    try:
        raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        _logger.warning(".strucin.toml is invalid TOML: %s", exc)
        return default_config()
    base = default_config()

    scan_table = _as_table(raw.get("scan"))
    search_table = _as_table(raw.get("search"))
    performance_table = _as_table(raw.get("performance"))
    lifecycle_table = _as_table(raw.get("lifecycle"))
    security_table = _as_table(raw.get("security"))
    observability_table = _as_table(raw.get("observability"))
    output_table = _as_table(raw.get("output"))
    llm_table = _as_table(raw.get("llm"))
    report_table = _as_table(raw.get("report"))

    excluded_dirs = _parse_str_list(
        scan_table.get("exclude_dirs"),
        fallback=base.excluded_dirs,
    )
    top_k = _as_int(search_table.get("top_k"), fallback=base.search.top_k, minimum=1)
    dimensions = _as_int(
        search_table.get("dimensions"),
        fallback=base.search.dimensions,
        minimum=16,
    )
    embedding_model = _as_str(
        search_table.get("embedding_model"),
        fallback=base.search.embedding_model,
    )
    max_workers = _as_int(
        performance_table.get("max_workers"),
        fallback=base.performance.max_workers,
        minimum=1,
    )
    executor = _as_executor_type(
        performance_table.get("executor"),
        fallback=base.performance.executor,
    )
    cache_retention_days = _as_int(
        lifecycle_table.get("cache_retention_days"),
        fallback=base.lifecycle.cache_retention_days,
        minimum=1,
    )
    safe_mode = _as_bool(security_table.get("safe_mode"), fallback=base.security.safe_mode)
    structured_logging = _as_bool(
        observability_table.get("structured_logging"),
        fallback=base.observability.structured_logging,
    )
    timing_enabled = _as_bool(
        observability_table.get("timing_enabled"),
        fallback=base.observability.timing_enabled,
    )

    output = OutputConfig(
        repo_index=_as_filename(output_table.get("repo_index"), base.output.repo_index),
        analysis=_as_filename(output_table.get("analysis"), base.output.analysis),
        dependency_graph=_as_filename(
            output_table.get("dependency_graph"),
            base.output.dependency_graph,
        ),
        report=_as_filename(output_table.get("report"), base.output.report),
        semantic_index=_as_filename(output_table.get("semantic_index"), base.output.semantic_index),
        explain_markdown=_as_filename(
            output_table.get("explain_markdown"),
            base.output.explain_markdown,
        ),
        explain_metadata=_as_filename(
            output_table.get("explain_metadata"),
            base.output.explain_metadata,
        ),
    )
    anthropic_model = _as_str(
        llm_table.get("anthropic_model"),
        fallback=base.llm.anthropic_model,
    )
    openai_model = _as_str(
        llm_table.get("openai_model"),
        fallback=base.llm.openai_model,
    )
    fan_out_threshold = _as_int(
        report_table.get("fan_out_threshold"),
        fallback=base.report.fan_out_threshold,
        minimum=1,
    )
    complexity_threshold = _as_int(
        report_table.get("complexity_threshold"),
        fallback=base.report.complexity_threshold,
        minimum=1,
    )
    loc_threshold = _as_int(
        report_table.get("loc_threshold"),
        fallback=base.report.loc_threshold,
        minimum=1,
    )
    return StrucInConfig(
        excluded_dirs=excluded_dirs,
        output=output,
        search=SearchConfig(top_k=top_k, dimensions=dimensions, embedding_model=embedding_model),
        performance=PerformanceConfig(max_workers=max_workers, executor=executor),
        lifecycle=LifecycleConfig(cache_retention_days=cache_retention_days),
        security=SecurityConfig(safe_mode=safe_mode),
        observability=ObservabilityConfig(
            structured_logging=structured_logging,
            timing_enabled=timing_enabled,
        ),
        llm=LLMConfig(anthropic_model=anthropic_model, openai_model=openai_model),
        report=ReportConfig(
            fan_out_threshold=fan_out_threshold,
            complexity_threshold=complexity_threshold,
            loc_threshold=loc_threshold,
        ),
    )


def _parse_str_list(value: object, fallback: set[str]) -> set[str]:
    """Merge user-supplied directory names with the *fallback* set.

    Core exclusions (.git, __pycache__, etc.) are never removed — user entries
    are **added** on top of the defaults, not used as a replacement.
    """
    if not isinstance(value, list):
        return set(fallback)
    additions = {item for item in value if isinstance(item, str) and item.strip()}
    return set(fallback) | additions


def _as_str(value: object, fallback: str) -> str:
    if not isinstance(value, str) or not value.strip():
        return fallback
    return value.strip()


def _as_table(value: object) -> dict[str, Any]:
    """Return *value* if it is a TOML table (dict), else an empty dict.

    Replaces ``cast(dict[str, Any], ...)`` with an actual runtime check so a
    hand-edited config that has, e.g., ``scan = "string"`` does not produce a
    confusing ``AttributeError`` later.
    """
    if isinstance(value, dict):
        return cast(dict[str, Any], value)
    return {}


def _as_int(value: object, fallback: int, minimum: int) -> int:
    # bool is a subclass of int in Python, so check it first.
    if isinstance(value, bool) or not isinstance(value, int):
        return fallback
    return max(value, minimum)


def _as_filename(value: object, fallback: str) -> str:
    if not isinstance(value, str) or not value.strip():
        return fallback
    cleaned = value.strip()
    if Path(cleaned).is_absolute():
        name = Path(cleaned).name
        _logger.warning(
            "config: output path %r is absolute; using %r instead.",
            value,
            name,
        )
        return name
    return cleaned


def _as_bool(value: object, fallback: bool) -> bool:
    if not isinstance(value, bool):
        return fallback
    return value


def _as_executor_type(value: object, fallback: str) -> str:
    """Return *value* if it is one of the accepted executor strings, else *fallback*."""
    if isinstance(value, str) and value.strip().lower() in _VALID_EXECUTORS:
        return value.strip().lower()
    if value is not None:
        _logger.warning(
            "config: unknown executor %r; must be one of %s. Falling back to %r.",
            value,
            sorted(_VALID_EXECUTORS),
            fallback,
        )
    return fallback
