from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from strucin.cli.main import main
from strucin.core import semantic


def configure(
    root: Path, *, model: str = "hashing-v1", dimensions: int = 64, extra: str = ""
) -> None:
    (root / ".strucin.toml").write_text(
        f'[search]\nembedding_model = "{model}"\ndimensions = {dimensions}\n'
        '[performance]\nmax_workers = 1\nexecutor = "thread"\n' + extra,
        encoding="utf-8",
    )


def source_text(extension: str, marker: str) -> str:
    return f"def {marker}():\n    return 1\n" if extension == ".py" else marker + "\n"


def search(root: Path, capsys: pytest.CaptureFixture[str], *options: str) -> dict:
    assert main(["search", "newwidget", "--path", str(root), "--json", *options]) == 0
    result = json.loads(capsys.readouterr().out)
    assert isinstance(result["results"], list)
    return json.loads((root / "semantic_index.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("extension", [".py", ".md", ".rst", ".txt", ".TXT"])
@pytest.mark.parametrize("change", ["edit", "add", "remove", "rename"])
def test_search_refreshes_file_contents_and_inventory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], extension: str, change: str
) -> None:
    configure(tmp_path)
    path = tmp_path / ("original" + extension)
    if change != "add":
        path.write_text(source_text(extension, "oldwidget"), encoding="utf-8")
    before = search(tmp_path, capsys)
    if change == "edit":
        old_stat = path.stat()
        path.write_text(source_text(extension, "newwidget"), encoding="utf-8")
        # Same size and timestamps: content must be checked, not just metadata.
        os.utime(path, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
        assert path.stat().st_size == old_stat.st_size
    elif change == "add":
        path.write_text(source_text(extension, "newwidget"), encoding="utf-8")
    elif change == "remove":
        path.unlink()
    else:
        path.rename(tmp_path / ("renamed" + extension))
    after = search(tmp_path, capsys)
    assert after["generated_at"] != before["generated_at"]
    assert after["input_fingerprint"] != before["input_fingerprint"]
    if change in {"edit", "add"}:
        assert "newwidget" in json.dumps(after["chunks"])
        assert "oldwidget" not in json.dumps(after["chunks"])
    elif change == "remove":
        assert after["chunks"] == []
    else:
        assert {chunk["path"] for chunk in after["chunks"]} == {"renamed" + extension}
        if extension == ".py":
            assert {chunk["module_path"] for chunk in after["chunks"]} == {"renamed"}


def test_unchanged_inputs_reuse_embeddings_despite_unrelated_changes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(tmp_path, extra='[scan]\nexclude_dirs = ["ignored"]\n')
    source = tmp_path / "sample.py"
    source.write_text(source_text(".py", "newwidget"), encoding="utf-8")
    search(tmp_path, capsys)
    cache = tmp_path / "semantic_index.json"
    before = cache.read_bytes()
    source.touch()
    (tmp_path / "unrelated.json").write_text("{}", encoding="utf-8")
    ignored = tmp_path / "ignored"
    ignored.mkdir()
    (ignored / "outside.py").write_text("ignored = 1", encoding="utf-8")
    configure(
        tmp_path,
        extra='[scan]\nexclude_dirs = ["ignored"]\n[observability]\ntiming_enabled = false\n',
    )
    original_embed = semantic._embed_texts
    calls: list[list[str]] = []

    def record(texts: list[str], model: str, dimensions: int) -> tuple[list[list[float]], int, str]:
        calls.append(texts)
        return original_embed(texts, model, dimensions)

    monkeypatch.setattr(semantic, "_embed_texts", record)
    search(tmp_path, capsys, "--top-k", "1")
    assert calls == [["newwidget"]]
    assert cache.read_bytes() == before


@pytest.mark.parametrize("exclude", [False, True])
def test_changed_exclusions_rebuild_search(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], exclude: bool
) -> None:
    extra = '[scan]\nexclude_dirs = ["optional"]\n'
    configure(tmp_path, extra="" if exclude else extra)
    folder = tmp_path / "optional"
    folder.mkdir()
    (folder / "sample.py").write_text(source_text(".py", "newwidget"), encoding="utf-8")
    before = search(tmp_path, capsys)
    configure(tmp_path, extra=extra if exclude else "")
    after = search(tmp_path, capsys)
    assert after["input_fingerprint"] != before["input_fingerprint"]
    assert bool(after["chunks"]) is not exclude


def test_changed_embedding_dimensions_rebuild_vectors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    configure(tmp_path, dimensions=64)
    (tmp_path / "sample.py").write_text(source_text(".py", "newwidget"), encoding="utf-8")
    before = search(tmp_path, capsys)
    configure(tmp_path, dimensions=128)
    after = search(tmp_path, capsys)
    assert before["dimensions"] == 64
    assert after["dimensions"] == 128
    assert all(len(vector) == 128 for vector in after["vectors"])


def test_requested_model_changes_invalidate_even_when_both_fall_back(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(semantic, "_load_sentence_transformer", lambda name: None)
    configure(tmp_path, model="unavailable-model-a")
    (tmp_path / "sample.py").write_text(source_text(".py", "newwidget"), encoding="utf-8")
    before = search(tmp_path, capsys)
    assert search(tmp_path, capsys)["generated_at"] == before["generated_at"]
    configure(tmp_path, model="unavailable-model-b")
    after = search(tmp_path, capsys)
    assert after["model"] == before["model"] == "hashing-v1"
    assert after["input_fingerprint"] != before["input_fingerprint"]
    assert search(tmp_path, capsys)["generated_at"] == after["generated_at"]


def test_legacy_fingerprint_is_rebuilt(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    configure(tmp_path)
    (tmp_path / "sample.py").write_text(source_text(".py", "newwidget"), encoding="utf-8")
    old = search(tmp_path, capsys)
    old.pop("input_fingerprint", None)
    old["chunks"][0]["text"] = "stale legacy text"
    (tmp_path / "semantic_index.json").write_text(json.dumps(old), encoding="utf-8")
    after = search(tmp_path, capsys)
    assert after["input_fingerprint"]
    assert "stale legacy text" not in json.dumps(after)


def test_refresh_bypasses_existing_index(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    configure(tmp_path)
    (tmp_path / "sample.py").write_text(source_text(".py", "newwidget"), encoding="utf-8")
    before = search(tmp_path, capsys)
    refreshed = search(tmp_path, capsys, "--refresh")
    assert refreshed["generated_at"] != before["generated_at"]
    assert refreshed["input_fingerprint"] == before["input_fingerprint"]
    (tmp_path / "semantic_index.json").write_text("{", encoding="utf-8")
    assert search(tmp_path, capsys, "--refresh")["chunks"]


@pytest.mark.parametrize("extension", [".py", ".md"])
def test_link_becoming_external_removes_cached_content(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], extension: str
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    configure(root)
    internal = root / "content.data"
    internal.write_text(source_text(extension, "oldwidget"), encoding="utf-8")
    link = root / ("linked" + extension)
    link.symlink_to(internal)
    before = search(root, capsys)
    assert before["chunks"]
    outside = tmp_path / "outside.data"
    outside.write_text("OUTSIDE_CONTENT", encoding="utf-8")
    link.unlink()
    link.symlink_to(outside)
    after = search(root, capsys)
    assert after["chunks"] == []
    assert "OUTSIDE_CONTENT" not in json.dumps(after)


def test_safe_refresh_keeps_index_in_memory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    configure(tmp_path)
    (tmp_path / "sample.py").write_text(source_text(".py", "newwidget"), encoding="utf-8")
    cache = tmp_path / "semantic_index.json"
    cache.write_text("private old cache", encoding="utf-8")
    assert (
        main(["search", "newwidget", "--path", str(tmp_path), "--json", "--refresh", "--safe-mode"])
        == 0
    )
    output = capsys.readouterr().out
    assert json.loads(output)["results"]
    assert "newwidget" not in output
    assert cache.read_text(encoding="utf-8") == "private old cache"


def test_cli_refresh_uses_configured_index_path(tmp_path: Path) -> None:
    configure(tmp_path, extra='[output]\nsemantic_index = "custom/nested/search.json"\n')
    (tmp_path / "sample.py").write_text(source_text(".py", "newwidget"), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "strucin.cli",
            "search",
            "newwidget",
            "--path",
            str(tmp_path),
            "--refresh",
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["results"]
    assert (tmp_path / "custom/nested/search.json").is_file()
    assert not (tmp_path / "semantic_index.json").exists()


@pytest.mark.parametrize("workers", [1, 2])
def test_fingerprint_describes_the_bytes_used_for_embeddings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, workers: int
) -> None:
    source = tmp_path / "sample.py"
    source.write_text(source_text(".py", "oldwidget"), encoding="utf-8")
    original_embed = semantic._embed_texts

    def edit_while_embedding(
        texts: list[str], model: str, dimensions: int
    ) -> tuple[list[list[float]], int, str]:
        source.write_text(source_text(".py", "newwidget"), encoding="utf-8")
        return original_embed(texts, model, dimensions)

    monkeypatch.setattr(semantic, "_embed_texts", edit_while_embedding)
    before = semantic.build_semantic_index(
        tmp_path, embedding_model="hashing-v1", max_workers=workers
    )
    assert "oldwidget" in before.chunks[0].text
    after = semantic.build_semantic_index(
        tmp_path, embedding_model="hashing-v1", cached_index=before, max_workers=workers
    )
    assert after is not before
    assert "newwidget" in after.chunks[0].text
    assert after.input_fingerprint != before.input_fingerprint
    assert (
        semantic.build_semantic_index(
            tmp_path, embedding_model="hashing-v1", cached_index=after, max_workers=workers
        )
        is after
    )


def test_fixed_neural_dimensions_do_not_cause_perpetual_rebuilds(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def neural_vectors(
        texts: list[str], model: str, dimensions: int
    ) -> tuple[list[list[float]], int, str]:
        return [semantic.embed_text(text, 4) for text in texts], 4, model

    monkeypatch.setattr(semantic, "_embed_texts", neural_vectors)
    configure(tmp_path, model="fixed-width-model", dimensions=64)
    (tmp_path / "sample.py").write_text(source_text(".py", "newwidget"), encoding="utf-8")
    before = search(tmp_path, capsys)
    assert before["dimensions"] == 4
    assert search(tmp_path, capsys)["generated_at"] == before["generated_at"]
    configure(tmp_path, model="fixed-width-model", dimensions=128)
    after = search(tmp_path, capsys)
    assert after["dimensions"] == 4
    assert after["input_fingerprint"] != before["input_fingerprint"]
    assert search(tmp_path, capsys)["generated_at"] == after["generated_at"]


@pytest.mark.parametrize("filename", [".md", ".rst", ".txt"])
def test_hidden_document_names_still_participate_in_freshness(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], filename: str
) -> None:
    configure(tmp_path)
    path = tmp_path / filename
    path.write_text("oldwidget", encoding="utf-8")
    before = search(tmp_path, capsys)
    assert before["chunks"][0]["path"] == filename
    path.write_text("newwidget", encoding="utf-8")
    after = search(tmp_path, capsys)
    assert after["chunks"][0]["text"] == "newwidget"
    assert after["input_fingerprint"] != before["input_fingerprint"]
