from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from strucin.core.semantic import (
    _ST_MODEL_CACHE,
    _embed_texts,
    _load_sentence_transformer,
    build_semantic_index,
    search_semantic_index,
)


def test_build_semantic_index_and_search(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "billing.py").write_text(
        "class InvoiceEngine:\n"
        "    def retry_failed_payment(self, gateway_error: str) -> bool:\n"
        "        if gateway_error:\n"
        "            return True\n"
        "        return False\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text(
        "# Billing service\n"
        "Retry failed payment flow handles transient gateway outage.\n",
        encoding="utf-8",
    )

    index = build_semantic_index(tmp_path)

    assert index.chunk_count >= 3
    kinds = {chunk.kind for chunk in index.chunks}
    assert "class" in kinds
    assert "function" in kinds
    assert "document" in kinds

    hits = search_semantic_index(index, "retry failed payment gateway", top_k=3)
    assert hits
    assert any("billing.py" in hit.chunk.path for hit in hits)


def test_cli_search_builds_index_and_prints_hits(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "utils.py").write_text(
        "def normalize_token(token: str) -> str:\n"
        "    return token.strip().lower()\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "strucin.cli",
            "search",
            "normalize token lowercase",
            "--path",
            str(tmp_path),
            "--top-k",
            "3",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    assert "Built semantic index" in result.stdout
    assert "Top 3 results for query:" in result.stdout
    assert "utils.py" in result.stdout
    assert (tmp_path / "semantic_index.json").exists()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeRow:
    """Minimal stand-in for a numpy row that has .tolist()."""

    def __init__(self, data: list[float]) -> None:
        self._data = data

    def tolist(self) -> list[float]:
        return self._data


# ---------------------------------------------------------------------------
# _load_sentence_transformer tests
# ---------------------------------------------------------------------------


def test_load_sentence_transformer_returns_cached_model() -> None:
    mock_model = MagicMock()
    with patch.dict(_ST_MODEL_CACHE, {"cached-model": mock_model}):
        result = _load_sentence_transformer("cached-model")
    assert result is mock_model


def test_load_sentence_transformer_loads_and_caches_model() -> None:
    mock_st_module = MagicMock()
    mock_model = MagicMock()
    mock_st_module.SentenceTransformer.return_value = mock_model

    with patch.dict(sys.modules, {"sentence_transformers": mock_st_module}), patch.dict(
        _ST_MODEL_CACHE, {}, clear=True
    ):
        result = _load_sentence_transformer("new-model-xyz")
        assert "new-model-xyz" in _ST_MODEL_CACHE
        assert result is mock_model

    mock_st_module.SentenceTransformer.assert_called_once_with("new-model-xyz")


def test_load_sentence_transformer_returns_none_on_import_error() -> None:
    with patch.dict(sys.modules, {"sentence_transformers": None}), patch.dict(  # type: ignore[dict-item]
        _ST_MODEL_CACHE, {}, clear=True
    ):
        result = _load_sentence_transformer("some-model")
    assert result is None


# ---------------------------------------------------------------------------
# _embed_texts tests
# ---------------------------------------------------------------------------


def test_embed_texts_neural_path() -> None:
    mock_model = MagicMock()
    mock_model.encode.return_value = [FakeRow([0.1, 0.2, 0.3]), FakeRow([0.4, 0.5, 0.6])]

    with patch("strucin.core.semantic._load_sentence_transformer", return_value=mock_model):
        vectors, dims, model_name = _embed_texts(["text one", "text two"], "my-neural-model", 256)

    assert vectors == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    assert dims == 3
    assert model_name == "my-neural-model"


def test_embed_texts_falls_back_to_hashing_when_model_unavailable() -> None:
    with patch("strucin.core.semantic._load_sentence_transformer", return_value=None):
        vectors, dims, model_name = _embed_texts(["some text"], "unavailable-model", 64)

    assert model_name == "hashing-v1"
    assert dims == 64
    assert len(vectors) == 1
    assert len(vectors[0]) == 64


def test_embed_texts_empty_texts_hashing() -> None:
    vectors, dims, model_name = _embed_texts([], "hashing-v1", 256)
    assert vectors == []
    assert dims == 256
    assert model_name == "hashing-v1"


def test_embed_texts_empty_texts_neural() -> None:
    mock_model = MagicMock()
    mock_model.encode.return_value = []

    with patch("strucin.core.semantic._load_sentence_transformer", return_value=mock_model):
        vectors, dims, model_name = _embed_texts([], "neural-model", 128)

    assert vectors == []
    assert dims == 128  # fallback_dimensions used when vectors is empty
    assert model_name == "neural-model"


# ---------------------------------------------------------------------------
# build_semantic_index / search_semantic_index integration (mocked ST)
# ---------------------------------------------------------------------------


def test_build_semantic_index_uses_neural_model_name(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text("def foo(): pass\n", encoding="utf-8")

    mock_model = MagicMock()

    def mock_encode(texts: list[str], **kwargs: object) -> list[FakeRow]:
        return [FakeRow([0.1, 0.2, 0.3]) for _ in texts]

    mock_model.encode.side_effect = mock_encode

    with patch("strucin.core.semantic._load_sentence_transformer", return_value=mock_model):
        index = build_semantic_index(tmp_path, embedding_model="test-model")

    assert index.model == "test-model"
    assert index.dimensions == 3


def test_search_semantic_index_raises_on_dimension_mismatch(tmp_path: Path) -> None:
    """search_semantic_index raises ValueError when query embedding dims != index dims."""
    (tmp_path / "mod.py").write_text("def foo(): pass\n", encoding="utf-8")

    # Build an index whose vectors have 3 dimensions
    mock_model = MagicMock()
    mock_model.encode.side_effect = lambda texts, **kw: [FakeRow([0.1, 0.2, 0.3]) for _ in texts]

    with patch("strucin.core.semantic._load_sentence_transformer", return_value=mock_model):
        index = build_semantic_index(tmp_path, embedding_model="test-model")

    assert index.dimensions == 3

    # Patch _embed_texts to return 4-dimensional query vector
    with patch(
        "strucin.core.semantic._embed_texts",
        return_value=([[0.1, 0.2, 0.3, 0.4]], 4, "test-model"),
    ):
        with pytest.raises(ValueError, match="4 dimensions"):
            search_semantic_index(index, "foo", top_k=3)


def test_search_uses_same_model_as_index(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text("def foo(): pass\n", encoding="utf-8")

    mock_model = MagicMock()

    def mock_encode(texts: list[str], **kwargs: object) -> list[FakeRow]:
        return [FakeRow([0.1, 0.2, 0.3]) for _ in texts]

    mock_model.encode.side_effect = mock_encode

    with patch("strucin.core.semantic._load_sentence_transformer", return_value=mock_model):
        index = build_semantic_index(tmp_path, embedding_model="my-specific-model")

    captured_model_names: list[str] = []

    def capturing_embed(
        texts: list[str], model_name: str, fallback_dimensions: int
    ) -> tuple[list[list[float]], int, str]:
        captured_model_names.append(model_name)
        vecs = [[0.1, 0.2, 0.3] for _ in texts]
        return vecs, 3, model_name

    with patch("strucin.core.semantic._embed_texts", side_effect=capturing_embed):
        search_semantic_index(index, "foo function", top_k=2)

    assert len(captured_model_names) == 1
    assert captured_model_names[0] == "my-specific-model"
