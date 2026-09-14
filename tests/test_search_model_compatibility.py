from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from strucin.cli.main import main
from strucin.core import semantic


class FakeRow:
    def tolist(self) -> list[float]:
        return [1.0, 0.0, 0.0]


@pytest.fixture
def neural_model() -> MagicMock:
    model = MagicMock()
    model.encode.side_effect = lambda texts, **kwargs: [FakeRow() for _ in texts]
    return model


def make_repo(root: Path, *, model: str = "test-neural-model") -> None:
    (root / "sample.py").write_text("def normalize_token():\n    return 1\n", encoding="utf-8")
    (root / ".strucin.toml").write_text(
        f'[search]\nembedding_model = "{model}"\ndimensions = 64\n'
        '[performance]\nmax_workers = 1\nexecutor = "thread"\n',
        encoding="utf-8",
    )


def test_unavailable_index_model_fails_before_scoring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, neural_model: MagicMock
) -> None:
    make_repo(tmp_path)
    monkeypatch.setattr(semantic, "_load_sentence_transformer", lambda name: neural_model)
    index = semantic.build_semantic_index(
        tmp_path, embedding_model="test-neural-model", max_workers=1
    )
    assert semantic.search_semantic_index(index, "normalize_token")[0].score == 1.0
    monkeypatch.setattr(semantic, "_load_sentence_transformer", lambda name: None)
    # Fallback vectors have the same width, so a dimension check cannot catch this.
    vectors, dimensions, model = semantic._embed_texts(
        ["normalize_token"], index.model, index.dimensions
    )
    assert len(vectors[0]) == dimensions == index.dimensions
    assert model == "hashing-v1"
    scorer = MagicMock(return_value=1.0)
    monkeypatch.setattr(semantic, "_dot", scorer)
    with pytest.raises(ValueError, match="embedding model does not match"):
        semantic.search_semantic_index(index, "normalize_token")
    scorer.assert_not_called()


def test_different_neural_model_with_same_dimensions_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, neural_model: MagicMock
) -> None:
    make_repo(tmp_path)
    monkeypatch.setattr(semantic, "_load_sentence_transformer", lambda name: neural_model)
    index = semantic.build_semantic_index(
        tmp_path, embedding_model="test-neural-model", max_workers=1
    )
    monkeypatch.setattr(
        semantic, "_embed_texts", lambda *args: ([[1.0, 0.0, 0.0]], 3, "another-neural-model")
    )
    with pytest.raises(ValueError, match="embedding model does not match"):
        semantic.search_semantic_index(index, "normalize_token")


@pytest.mark.parametrize("requested_model", ["hashing-v1", "unavailable-neural-model"])
def test_hashing_index_search_remains_compatible_when_neural_model_becomes_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, requested_model: str
) -> None:
    make_repo(tmp_path)
    monkeypatch.setattr(semantic, "_load_sentence_transformer", lambda name: None)
    index = semantic.build_semantic_index(
        tmp_path, embedding_model=requested_model, dimensions=64, max_workers=1
    )
    assert index.model == "hashing-v1"
    loader = MagicMock(side_effect=AssertionError("Hashing search must not load a neural model"))
    monkeypatch.setattr(semantic, "_load_sentence_transformer", loader)
    hits = semantic.search_semantic_index(index, "normalize_token")
    assert hits and hits[0].chunk.path == "sample.py"
    loader.assert_not_called()


@pytest.mark.parametrize("json_output", [False, True])
@pytest.mark.parametrize("index_state", ["cached", "fresh", "safe"])
def test_cli_rejects_mismatch_and_can_rebuild_with_explicit_hashing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    neural_model: MagicMock,
    json_output: bool,
    index_state: str,
) -> None:
    make_repo(tmp_path)
    monkeypatch.setattr(semantic, "_load_sentence_transformer", lambda name: neural_model)
    path = tmp_path / "semantic_index.json"
    previous = None
    if index_state == "cached":
        index = semantic.build_semantic_index(
            tmp_path, embedding_model="test-neural-model", dimensions=64, max_workers=1
        )
        semantic.write_semantic_index(index, path)
        previous = path.read_bytes()
        monkeypatch.setattr(semantic, "_load_sentence_transformer", lambda name: None)
    else:
        # The model becomes unavailable between index creation and query embedding.
        monkeypatch.setattr(
            semantic, "_load_sentence_transformer", MagicMock(side_effect=[neural_model, None])
        )
    options = ["--json"] if json_output else []
    if index_state == "safe":
        options.append("--safe-mode")
    command = ["search", "normalize_token", "--path", str(tmp_path), *options]
    assert main(command) == 1
    output = capsys.readouterr()
    error = " ".join(output.err.split())
    assert "embedding model does not match" in error
    assert "hashing-v1" in error and "--refresh" in error
    assert "Traceback" not in error
    assert "normalize_token" not in output.out + output.err
    if json_output:
        assert output.out == ""
    else:
        assert "results for query" not in output.out
    if previous is not None:
        assert path.read_bytes() == previous
    elif index_state == "safe":
        assert not path.exists()
    else:
        assert semantic.load_semantic_index(path).model == "test-neural-model"

    # Follow the error's recovery instructions and embed every chunk with hashing.
    make_repo(tmp_path, model="hashing-v1")
    monkeypatch.setattr(
        semantic, "_load_sentence_transformer", MagicMock(side_effect=AssertionError("No neural"))
    )
    assert main([*command, "--refresh"]) == 0
    recovered = capsys.readouterr()
    if json_output:
        assert json.loads(recovered.out)["results"]
    else:
        assert "results for query" in recovered.out
    if index_state == "safe":
        assert not path.exists()
        assert "normalize_token" not in recovered.out + recovered.err
    else:
        rebuilt = semantic.load_semantic_index(path)
        assert rebuilt.model == "hashing-v1"
        assert rebuilt.vectors == [semantic.embed_text(chunk.text, 64) for chunk in rebuilt.chunks]
