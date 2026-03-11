from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from strucin.core.config import LLMConfig
from strucin.core.explainer import (
    _LLM_SYSTEM_PROMPT,
    CACHE_VERSION,
    _call_llm,
    _detect_llm,
    _write_cache,
    explain_repository,
    redact_analysis,
)


def test_explain_repository_generates_narration_and_cache(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "config.py").write_text(
        '"""password = "super-secret-value" """\nfrom . import service\n',
        encoding="utf-8",
    )
    (tmp_path / "pkg" / "service.py").write_text("from . import config\n", encoding="utf-8")

    first = explain_repository(tmp_path)
    second = explain_repository(tmp_path)
    refreshed = explain_repository(tmp_path, refresh=True)

    assert "# StrucIn Architecture Narration" in first.content
    assert "## Onboarding Guide" in first.content
    assert "REDACTED_SECRET" in first.content
    assert first.cache_key == second.cache_key
    assert first.generated_at == second.generated_at
    assert refreshed.generated_at != second.generated_at

    cache_file = tmp_path / ".strucin_cache" / "explain_cache.json"
    assert cache_file.exists()


def test_explain_repository_safe_mode_hides_module_identifiers(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "service.py").write_text(
        "def run() -> int:\n    return 1\n",
        encoding="utf-8",
    )

    output = explain_repository(tmp_path, safe_mode=True)

    assert "Safe mode is **enabled**." in output.content
    assert "`pkg.service`" not in output.content


def test_explain_repository_redacts_additional_secret_patterns(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "secrets.py").write_text(
        '"""API_KEY=abc123\n'
        "aws = AKIAABCDEFGHIJKLMNOP\n"
        "token = ghp_abcdefghijklmnopqrstuvwxyz123456\n"
        "url=https://user:s3cr3t@example.com/app\n"
        '"""',
        encoding="utf-8",
    )

    output = explain_repository(tmp_path)
    assert "REDACTED_SECRET" in output.content
    assert "AKIAABCDEFGHIJKLMNOP" not in output.content
    assert "ghp_abcdefghijklmnopqrstuvwxyz123456" not in output.content
    assert "s3cr3t@" not in output.content


def test_cli_explain_generates_files(tmp_path: Path) -> None:
    (tmp_path / "mod").mkdir()
    (tmp_path / "mod" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "mod" / "core.py").write_text(
        'def hello() -> str:\n    return "world"\n',
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, "-m", "strucin.cli", "explain", "--path", str(tmp_path)],
        capture_output=True,
        text=True,
        check=True,
    )

    assert "Generated architecture narration" in result.stdout
    assert "Wrote explanation metadata" in result.stdout
    assert (tmp_path / "docs" / "EXPLAIN.md").exists()
    assert (tmp_path / "explain.json").exists()


def test_cli_explain_safe_mode_flag(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "worker.py").write_text(
        "def work() -> int:\n    return 1\n", encoding="utf-8"
    )

    subprocess.run(
        [sys.executable, "-m", "strucin.cli", "explain", "--path", str(tmp_path), "--safe-mode"],
        capture_output=True,
        text=True,
        check=True,
    )

    explain_text = (tmp_path / "docs" / "EXPLAIN.md").read_text(encoding="utf-8")
    assert "Safe mode is **enabled**." in explain_text


# ---------------------------------------------------------------------------
# _detect_llm tests
# ---------------------------------------------------------------------------


def test_detect_llm_returns_anthropic_when_key_and_package_present() -> None:
    mock_anthropic = MagicMock()
    with (
        patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}, clear=True),
        patch.dict(sys.modules, {"anthropic": mock_anthropic}),
    ):
        result = _detect_llm(LLMConfig())
    assert result == ("anthropic", "claude-haiku-4-5-20251001")


def test_detect_llm_returns_openai_when_only_openai_key_present() -> None:
    mock_openai = MagicMock()
    with (
        patch.dict(os.environ, {"OPENAI_API_KEY": "sk-openai-test"}, clear=True),
        patch.dict(sys.modules, {"openai": mock_openai}),
    ):
        result = _detect_llm(LLMConfig())
    assert result == ("openai", "gpt-4o-mini")


def test_detect_llm_returns_none_when_no_keys() -> None:
    with patch.dict(os.environ, {}, clear=True):
        result = _detect_llm(LLMConfig())
    assert result is None


def test_detect_llm_skips_provider_when_package_not_installed() -> None:
    mock_openai = MagicMock()
    env = {"ANTHROPIC_API_KEY": "sk-ant-test", "OPENAI_API_KEY": "sk-openai-test"}
    # None in sys.modules causes ImportError on import
    sys_modules_patch: dict[str, object] = {"anthropic": None, "openai": mock_openai}
    with patch.dict(os.environ, env, clear=True), patch.dict(sys.modules, sys_modules_patch):
        result = _detect_llm(LLMConfig())
    assert result == ("openai", "gpt-4o-mini")


# ---------------------------------------------------------------------------
# _call_llm tests
# ---------------------------------------------------------------------------


def test_call_llm_anthropic_returns_content() -> None:
    mock_anthropic = MagicMock()
    mock_client = MagicMock()
    mock_msg = MagicMock()
    mock_msg.content[0].text = "# Narration"
    mock_client.messages.create.return_value = mock_msg
    mock_anthropic.Anthropic.return_value = mock_client

    with patch.dict(sys.modules, {"anthropic": mock_anthropic}):
        result = _call_llm("repo context", "anthropic", "claude-haiku-4-5-20251001")

    assert result == "# Narration"


def test_call_llm_openai_returns_content() -> None:
    mock_openai = MagicMock()
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = "# Narration"
    mock_client.chat.completions.create.return_value = mock_resp
    mock_openai.OpenAI.return_value = mock_client

    with patch.dict(sys.modules, {"openai": mock_openai}):
        result = _call_llm("repo context", "openai", "gpt-4o-mini")

    assert result == "# Narration"


def test_call_llm_returns_none_on_exception() -> None:
    mock_anthropic = MagicMock()
    mock_anthropic.Anthropic.side_effect = RuntimeError("API error")

    with patch.dict(sys.modules, {"anthropic": mock_anthropic}):
        result = _call_llm("repo context", "anthropic", "claude-haiku-4-5-20251001")

    assert result is None


# ---------------------------------------------------------------------------
# explain_repository LLM integration tests
# ---------------------------------------------------------------------------


def test_explain_repository_uses_llm_when_available(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text("def foo(): pass\n", encoding="utf-8")

    with (
        patch("strucin.core.explainer._detect_llm", return_value=("anthropic", "m")),
        patch("strucin.core.explainer._call_llm", return_value="# LLM Output"),
    ):
        output = explain_repository(tmp_path, llm_config=LLMConfig())

    assert "# LLM Output" in output.content
    assert "anthropic:" in output.cache_key


def test_explain_repository_falls_back_to_template_when_llm_fails(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text("def foo(): pass\n", encoding="utf-8")

    with (
        patch("strucin.core.explainer._detect_llm", return_value=("anthropic", "m")),
        patch("strucin.core.explainer._call_llm", return_value=None),
    ):
        output = explain_repository(tmp_path, llm_config=LLMConfig(), refresh=True)

    assert "# StrucIn Architecture Narration" in output.content


def test_explain_repository_uses_template_when_no_llm_config(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text("def foo(): pass\n", encoding="utf-8")

    output = explain_repository(tmp_path)

    assert "template" in output.cache_key


# ---------------------------------------------------------------------------
# Cache versioning
# ---------------------------------------------------------------------------


def test_explain_repository_ignores_stale_cache_version(tmp_path: Path) -> None:
    """A cache file written with version != CACHE_VERSION is treated as a miss."""
    (tmp_path / "mod.py").write_text("def foo(): pass\n", encoding="utf-8")

    cache_path = tmp_path / ".strucin_cache" / "explain_cache.json"
    cache_path.parent.mkdir(parents=True)
    stale = {
        "cache_version": "0",
        "entries": {
            "stale_key": {
                "generated_at": "2020-01-01T00:00:00+00:00",
                "content": "STALE CONTENT",
            }
        },
    }
    cache_path.write_text(json.dumps(stale), encoding="utf-8")

    output = explain_repository(tmp_path)

    assert "STALE CONTENT" not in output.content
    assert "# StrucIn Architecture Narration" in output.content


def test_redact_analysis_uses_dataclasses_replace(tmp_path: Path) -> None:
    """redact_analysis must preserve all non-docstring fields via dataclasses.replace."""
    (tmp_path / "mod.py").write_text('"""password = "super-secret"\n"""\nx = 1\n', encoding="utf-8")
    from strucin.core.analyzer import analyze_repository

    analysis = analyze_repository(tmp_path)
    redacted = redact_analysis(analysis)

    original_file = analysis.files[0]
    redacted_file = redacted.files[0]

    # Secret redacted from docstring
    assert "super-secret" not in (redacted_file.docstring or "")
    assert "REDACTED_SECRET" in (redacted_file.docstring or "")
    # All structural fields preserved
    assert redacted_file.path == original_file.path
    assert redacted_file.module_path == original_file.module_path
    assert redacted_file.loc == original_file.loc
    assert redacted_file.fan_in == original_file.fan_in
    assert redacted_file.fan_out == original_file.fan_out


def test_explain_cache_written_with_current_version(tmp_path: Path) -> None:
    """After explain_repository runs, the cache file must contain the current CACHE_VERSION."""
    (tmp_path / "mod.py").write_text("def foo(): pass\n", encoding="utf-8")

    explain_repository(tmp_path)

    cache_path = tmp_path / ".strucin_cache" / "explain_cache.json"
    raw = json.loads(cache_path.read_text(encoding="utf-8"))
    assert raw.get("cache_version") == CACHE_VERSION


# ---------------------------------------------------------------------------
# Fix 10 — cache eviction (max 50 entries)
# ---------------------------------------------------------------------------


def test_write_cache_evicts_oldest_entries_when_over_limit(tmp_path: Path) -> None:
    """_write_cache must evict oldest entries when the cache exceeds 50 items."""
    cache_path = tmp_path / "explain_cache.json"

    # Build 51 entries: timestamps "2024-01-01" through "2024-02-20"
    entries: dict[str, dict[str, str]] = {}
    for i in range(51):
        key = f"key-{i:03d}"
        # Lexicographic sort works: "2024-01-01" < "2024-01-02" ... < "2024-02-20"
        entries[key] = {"generated_at": f"2024-01-{i + 1:02d}T00:00:00+00:00", "content": "x"}

    _write_cache(cache_path, entries)

    written = json.loads(cache_path.read_text(encoding="utf-8"))
    remaining = written["entries"]
    assert len(remaining) == 50
    # The oldest entry (key-000, "2024-01-01") must have been evicted
    assert "key-000" not in remaining
    # The newest entry (key-050) must still be present
    assert "key-050" in remaining


# ---------------------------------------------------------------------------
# Fix 12 — system prompt is sent via dedicated parameter
# ---------------------------------------------------------------------------


def test_call_llm_anthropic_uses_system_parameter() -> None:
    """_call_llm must pass _LLM_SYSTEM_PROMPT via system= kwarg, not in user message."""
    mock_anthropic = MagicMock()
    mock_client = MagicMock()
    mock_msg = MagicMock()
    mock_msg.content[0].text = "# Narration"
    mock_client.messages.create.return_value = mock_msg
    mock_anthropic.Anthropic.return_value = mock_client

    with patch.dict(sys.modules, {"anthropic": mock_anthropic}):
        _call_llm("repo context", "anthropic", "claude-haiku-4-5-20251001")

    call_kwargs = mock_client.messages.create.call_args
    assert call_kwargs.kwargs.get("system") == _LLM_SYSTEM_PROMPT
    # User message must NOT contain the system prompt text
    messages = call_kwargs.kwargs.get("messages", [])
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert _LLM_SYSTEM_PROMPT not in messages[0]["content"]


def test_call_llm_openai_uses_system_role_message() -> None:
    """_call_llm must send _LLM_SYSTEM_PROMPT as role='system' first message for OpenAI."""
    mock_openai = MagicMock()
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = "# Narration"
    mock_client.chat.completions.create.return_value = mock_resp
    mock_openai.OpenAI.return_value = mock_client

    with patch.dict(sys.modules, {"openai": mock_openai}):
        _call_llm("repo context", "openai", "gpt-4o-mini")

    call_kwargs = mock_client.chat.completions.create.call_args
    messages = call_kwargs.kwargs.get("messages", [])
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == _LLM_SYSTEM_PROMPT
    assert messages[1]["role"] == "user"


# ---------------------------------------------------------------------------
# Fix 18 — unknown provider warning
# ---------------------------------------------------------------------------


def test_call_llm_unknown_provider_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    """An unknown provider must log a warning and return None."""
    with caplog.at_level(logging.WARNING, logger="strucin.core.explainer"):
        result = _call_llm("context", "unknown_provider", "model-x")
    assert result is None
    assert "unknown_provider" in caplog.text
