"""Real LLM integration tests.

These tests make actual API calls. They are SKIPPED automatically when the
required environment variables or packages are absent, so they are safe to
include in the normal test collection without breaking CI.

Requirements
------------
Anthropic tests:
    export ANTHROPIC_API_KEY="sk-ant-..."
    pip install "strucin[llm]"

OpenAI tests:
    export OPENAI_API_KEY="sk-..."
    pip install "strucin[llm]"

Usage
-----
Run all integration tests:
    pytest -m integration -v

Run only Anthropic:
    pytest -m integration -v -k anthropic

Run only OpenAI:
    pytest -m integration -v -k openai

Normal CI run (skips integration tests automatically):
    pytest --cov=src/strucin --cov-fail-under=85
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

from strucin.core.config import LLMConfig
from strucin.core.explainer import _call_llm, _detect_llm, explain_repository

# ---------------------------------------------------------------------------
# Availability guards (evaluated once at collection time)
# ---------------------------------------------------------------------------

_ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
_OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")
_HAS_ANTHROPIC_PKG = importlib.util.find_spec("anthropic") is not None
_HAS_OPENAI_PKG = importlib.util.find_spec("openai") is not None

requires_anthropic = pytest.mark.skipif(
    not _ANTHROPIC_KEY or not _HAS_ANTHROPIC_PKG,
    reason="Requires ANTHROPIC_API_KEY and `pip install strucin[llm]`",
)

requires_openai = pytest.mark.skipif(
    not _OPENAI_KEY or not _HAS_OPENAI_PKG,
    reason="Requires OPENAI_API_KEY and `pip install strucin[llm]`",
)

# Mark every test in this module as integration
pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Minimal repo fixture
# ---------------------------------------------------------------------------

_MINIMAL_CONTEXT = (
    '{"repo_root": "/test", "file_count": 2, "module_count": 2, "cycles": [], "files": ['
    '{"module_path": "pkg.core", "path": "pkg/core.py", "loc": 25, '
    '"fan_in": 0, "fan_out": 1, "complexity": 3, "docstring": "Core business logic."}, '
    '{"module_path": "pkg.utils", "path": "pkg/utils.py", "loc": 10, '
    '"fan_in": 1, "fan_out": 0, "complexity": 1, "docstring": "Utility helpers."}'
    "]}"
)


def _build_minimal_repo(root: Path) -> None:
    """Write a tiny but structurally valid Python repo for end-to-end tests."""
    pkg = root / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "core.py").write_text(
        '"""Core business logic."""\n'
        "from pkg import utils\n\n"
        "def process(data: list[str]) -> list[str]:\n"
        "    return [utils.clean(item) for item in data]\n",
        encoding="utf-8",
    )
    (pkg / "utils.py").write_text(
        '"""Utility helpers."""\n\n'
        "def clean(text: str) -> str:\n"
        "    return text.strip().lower()\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text(
        "# Minimal Test Repo\nA small Python package used for LLM integration tests.\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# _detect_llm — real packages
# ---------------------------------------------------------------------------


@requires_anthropic
def test_detect_llm_identifies_anthropic_with_real_package() -> None:
    """_detect_llm should return ("anthropic", model) when key + package are present."""
    result = _detect_llm(LLMConfig())
    assert result is not None
    provider, model = result
    assert provider == "anthropic"
    assert model == LLMConfig().anthropic_model


@requires_openai
def test_detect_llm_identifies_openai_when_only_openai_key_set() -> None:
    """_detect_llm falls through to OpenAI when no Anthropic key is present."""
    if _ANTHROPIC_KEY and _HAS_ANTHROPIC_PKG:
        pytest.skip("Anthropic takes priority — cannot isolate OpenAI path with both keys set")
    result = _detect_llm(LLMConfig())
    assert result is not None
    provider, model = result
    assert provider == "openai"
    assert model == LLMConfig().openai_model


# ---------------------------------------------------------------------------
# _call_llm — real API round-trips
# ---------------------------------------------------------------------------


@requires_anthropic
def test_call_llm_anthropic_returns_non_empty_markdown() -> None:
    """Real Anthropic call returns a non-empty string with at least one heading."""
    result = _call_llm(_MINIMAL_CONTEXT, "anthropic", LLMConfig().anthropic_model)

    assert result is not None, (
        "API returned None — verify ANTHROPIC_API_KEY is valid and the account has credits"
    )
    assert isinstance(result, str)
    assert len(result) > 80
    assert "#" in result  # LLM should produce at least one markdown heading


@requires_openai
def test_call_llm_openai_returns_non_empty_markdown() -> None:
    """Real OpenAI call returns a non-empty string with at least one heading."""
    result = _call_llm(_MINIMAL_CONTEXT, "openai", LLMConfig().openai_model)

    assert result is not None, (
        "API returned None — verify OPENAI_API_KEY is valid and the account has credits"
    )
    assert isinstance(result, str)
    assert len(result) > 80
    assert "#" in result


@requires_anthropic
def test_call_llm_anthropic_bad_model_returns_none() -> None:
    """An invalid model name should cause the API to raise, returning None gracefully."""
    result = _call_llm(_MINIMAL_CONTEXT, "anthropic", "claude-nonexistent-model-xyz")
    assert result is None


@requires_openai
def test_call_llm_openai_bad_model_returns_none() -> None:
    """An invalid model name should cause the API to raise, returning None gracefully."""
    result = _call_llm(_MINIMAL_CONTEXT, "openai", "gpt-nonexistent-model-xyz")
    assert result is None


# ---------------------------------------------------------------------------
# explain_repository — full end-to-end
# ---------------------------------------------------------------------------


@requires_anthropic
def test_explain_repository_anthropic_end_to_end(tmp_path: Path) -> None:
    """explain_repository calls Anthropic and stores real LLM output in cache."""
    _build_minimal_repo(tmp_path)

    output = explain_repository(tmp_path, llm_config=LLMConfig(), refresh=True)

    # Provider is encoded in the cache key
    assert "anthropic:" in output.cache_key
    assert output.content
    assert len(output.content) > 80
    assert output.repo_root == str(tmp_path)

    # Cache file must exist after first run
    cache_file = tmp_path / ".strucin_cache" / "explain_cache.json"
    assert cache_file.exists()


@requires_anthropic
def test_explain_repository_anthropic_second_call_uses_cache(tmp_path: Path) -> None:
    """Second call returns the cached result without a new API round-trip."""
    _build_minimal_repo(tmp_path)

    first = explain_repository(tmp_path, llm_config=LLMConfig(), refresh=True)
    second = explain_repository(tmp_path, llm_config=LLMConfig())

    assert first.cache_key == second.cache_key
    assert first.generated_at == second.generated_at
    assert first.content == second.content


@requires_anthropic
def test_explain_repository_anthropic_refresh_produces_new_timestamp(tmp_path: Path) -> None:
    """refresh=True bypasses cache and calls the LLM again."""
    _build_minimal_repo(tmp_path)

    first = explain_repository(tmp_path, llm_config=LLMConfig(), refresh=True)
    refreshed = explain_repository(tmp_path, llm_config=LLMConfig(), refresh=True)

    # Content may differ but timestamps must differ (new generation)
    assert refreshed.generated_at != first.generated_at


@requires_openai
def test_explain_repository_openai_end_to_end(tmp_path: Path) -> None:
    """explain_repository calls OpenAI when Anthropic is unavailable."""
    if _ANTHROPIC_KEY and _HAS_ANTHROPIC_PKG:
        pytest.skip("Anthropic takes priority — cannot isolate OpenAI path with both keys set")

    _build_minimal_repo(tmp_path)

    output = explain_repository(tmp_path, llm_config=LLMConfig(), refresh=True)

    assert "openai:" in output.cache_key
    assert output.content
    assert len(output.content) > 80
