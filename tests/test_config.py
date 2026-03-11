from __future__ import annotations

import logging
from pathlib import Path

import pytest

from strucin.core.config import (  # type: ignore[attr-defined]
    _as_executor_type,
    _as_filename,
    default_config,
    load_config,
)


def test_load_config_reads_performance_workers(tmp_path: Path) -> None:
    (tmp_path / ".strucin.toml").write_text(
        "\n".join(
            [
                "[scan]",
                'exclude_dirs = [".git", "build"]',
                "",
                "[search]",
                "top_k = 9",
                "dimensions = 64",
                "",
                "[performance]",
                "max_workers = 3",
                "",
                "[lifecycle]",
                "cache_retention_days = 21",
                "",
                "[security]",
                "safe_mode = true",
                "",
                "[observability]",
                "structured_logging = true",
                "timing_enabled = false",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(tmp_path)

    assert config.performance.max_workers == 3
    assert config.lifecycle.cache_retention_days == 21
    assert config.security.safe_mode is True
    assert config.observability.structured_logging is True
    assert config.observability.timing_enabled is False
    assert config.search.top_k == 9
    assert config.search.dimensions == 64
    assert "build" in config.excluded_dirs


def test_load_config_parses_llm_table(tmp_path: Path) -> None:
    (tmp_path / ".strucin.toml").write_text(
        "[llm]\n"
        'anthropic_model = "claude-opus-4-6"\n'
        'openai_model = "gpt-4o"\n',
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    assert config.llm.anthropic_model == "claude-opus-4-6"
    assert config.llm.openai_model == "gpt-4o"


def test_load_config_llm_invalid_type_falls_back(tmp_path: Path) -> None:
    (tmp_path / ".strucin.toml").write_text(
        "[llm]\nanthropic_model = 999\n",
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    assert config.llm.anthropic_model == "claude-haiku-4-5-20251001"


def test_load_config_llm_empty_string_falls_back(tmp_path: Path) -> None:
    (tmp_path / ".strucin.toml").write_text(
        '[llm]\nanthropic_model = ""\n',
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    assert config.llm.anthropic_model == "claude-haiku-4-5-20251001"


def test_load_config_embedding_model_parsed(tmp_path: Path) -> None:
    (tmp_path / ".strucin.toml").write_text(
        '[search]\nembedding_model = "paraphrase-MiniLM-L3-v2"\n',
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    assert config.search.embedding_model == "paraphrase-MiniLM-L3-v2"


def test_default_config_has_llm_config() -> None:
    config = default_config()
    assert config.llm.anthropic_model == "claude-haiku-4-5-20251001"
    assert config.search.embedding_model == "all-MiniLM-L6-v2"


def test_default_config_has_report_defaults() -> None:
    config = default_config()
    assert config.report.fan_out_threshold == 5
    assert config.report.complexity_threshold == 15
    assert config.report.loc_threshold == 400


def test_load_config_parses_report_table(tmp_path: Path) -> None:
    (tmp_path / ".strucin.toml").write_text(
        "[report]\n"
        "fan_out_threshold = 3\n"
        "complexity_threshold = 10\n"
        "loc_threshold = 200\n",
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    assert config.report.fan_out_threshold == 3
    assert config.report.complexity_threshold == 10
    assert config.report.loc_threshold == 200


def test_load_config_report_invalid_type_falls_back(tmp_path: Path) -> None:
    (tmp_path / ".strucin.toml").write_text(
        '[report]\nfan_out_threshold = "bad"\ncomplexity_threshold = []\n',
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    assert config.report.fan_out_threshold == 5
    assert config.report.complexity_threshold == 15


def test_load_config_report_below_minimum_is_clamped(tmp_path: Path) -> None:
    (tmp_path / ".strucin.toml").write_text(
        "[report]\nfan_out_threshold = 0\nloc_threshold = -10\n",
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    assert config.report.fan_out_threshold == 1
    assert config.report.loc_threshold == 1


def test_load_config_malformed_toml_falls_back_to_defaults(tmp_path: Path) -> None:
    """A broken .strucin.toml must not raise — fall back to defaults."""
    (tmp_path / ".strucin.toml").write_text("broken = [\n", encoding="utf-8")
    config = load_config(tmp_path)
    assert config.report.fan_out_threshold == 5  # default
    assert config.performance.max_workers >= 1


def test_load_config_exclude_dirs_merges_with_defaults(tmp_path: Path) -> None:
    """User-supplied exclude_dirs adds to defaults, never replaces them."""
    (tmp_path / ".strucin.toml").write_text(
        '[scan]\nexclude_dirs = ["my_build"]\n', encoding="utf-8"
    )
    config = load_config(tmp_path)
    assert "my_build" in config.excluded_dirs
    assert ".git" in config.excluded_dirs
    assert "__pycache__" in config.excluded_dirs


def test_as_filename_allows_relative_paths() -> None:
    """_as_filename allows relative paths like docs/REPORT.md."""
    result = _as_filename("docs/REPORT.md", "REPORT.md")
    assert result == "docs/REPORT.md"


def test_as_filename_strips_absolute_path(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """_as_filename warns and returns only the basename for absolute paths."""
    with caplog.at_level(logging.WARNING, logger="strucin.core.config"):
        result = _as_filename("/abs/path/analysis.json", "analysis.json")
    assert result == "analysis.json"
    assert "absolute" in caplog.text


def test_as_filename_plain_name_no_warning(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="strucin.core.config"):
        result = _as_filename("analysis.json", "analysis.json")
    assert result == "analysis.json"
    assert caplog.text == ""


# ---------------------------------------------------------------------------
# executor config
# ---------------------------------------------------------------------------


def test_default_config_executor_is_auto() -> None:
    config = default_config()
    assert config.performance.executor == "auto"


def test_load_config_parses_executor(tmp_path: Path) -> None:
    (tmp_path / ".strucin.toml").write_text(
        "[performance]\nexecutor = \"process\"\n", encoding="utf-8"
    )
    config = load_config(tmp_path)
    assert config.performance.executor == "process"


def test_load_config_executor_invalid_falls_back(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / ".strucin.toml").write_text(
        "[performance]\nexecutor = \"foobar\"\n", encoding="utf-8"
    )
    with caplog.at_level(logging.WARNING, logger="strucin.core.config"):
        config = load_config(tmp_path)
    assert config.performance.executor == "auto"
    assert "foobar" in caplog.text


def test_as_executor_type_valid_values() -> None:
    for value in ("auto", "thread", "process"):
        assert _as_executor_type(value, "auto") == value


def test_as_executor_type_invalid_falls_back(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="strucin.core.config"):
        result = _as_executor_type("bad", "auto")
    assert result == "auto"
    assert "bad" in caplog.text


def test_as_executor_type_none_returns_fallback_silently(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="strucin.core.config"):
        result = _as_executor_type(None, "thread")
    assert result == "thread"
    assert caplog.text == ""


# ---------------------------------------------------------------------------
# bool as int guard (Fix 6)
# ---------------------------------------------------------------------------


def test_load_config_bool_max_workers_falls_back(tmp_path: Path) -> None:
    """max_workers = true is a bool in TOML; must fall back to default, not become 1."""
    (tmp_path / ".strucin.toml").write_text(
        "[performance]\nmax_workers = true\n", encoding="utf-8"
    )
    config = load_config(tmp_path)
    assert config.performance.max_workers > 1  # default, not bool-cast-to-int


def test_load_config_table_as_string_falls_back(tmp_path: Path) -> None:
    """[performance] = 'string' must not crash; table falls back to empty dict."""
    # TOML won't allow [performance] = "string" syntax, so test via search table
    (tmp_path / ".strucin.toml").write_text(
        "search = \"not_a_table\"\n", encoding="utf-8"
    )
    config = load_config(tmp_path)
    assert config.search.top_k == 5  # default preserved
