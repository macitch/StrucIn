"""Keep source and document reads inside the repository, including cache rebuilds."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

import pytest

from strucin.cli.main import main
from strucin.core import repository_files, semantic
from strucin.core.analyzer import _analyze_file_with_cache, analyze_repository
from strucin.core.indexer import _count_loc, scan_repository
from strucin.core.repository_files import read_repository_bytes, resolve_repository_file
from strucin.exceptions import AnalysisError

OUTSIDE_MARKER = "SYNTHETIC_OUTSIDE_PRIVATE_CONTENT"


def make_link(root: Path, outside: Path, extension: str, kind: str) -> Path:
    link = root / f"linked{extension}"
    if kind == "external":
        link.symlink_to(outside)
    elif kind == "dangling":
        link.symlink_to(outside.with_name("missing"))
    elif kind == "loop":
        link.symlink_to(link)
    elif kind == "chain":
        alias = root / "alias"
        alias.symlink_to(outside)
        link.symlink_to(alias)
    else:
        pytest.fail(f"Unknown test link kind: {kind}")
    return link


@pytest.mark.parametrize("kind", ["external", "dangling", "loop", "chain"])
@pytest.mark.parametrize("executor", ["thread", "process"])
def test_python_links_do_not_enter_analysis_or_cache(
    tmp_path: Path, kind: str, executor: str
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "private.py"
    outside.write_text(f'"""{OUTSIDE_MARKER}"""\n', encoding="utf-8")
    (root / "local.py").write_text("VALUE = 1\n", encoding="utf-8")
    make_link(root, outside, ".py", kind)
    scan = scan_repository(root, max_workers=2)
    assert [file.path for file in scan.files] == ["local.py"]
    result = analyze_repository(root, executor=executor, max_workers=2)
    assert [file.path for file in result.files] == ["local.py"]
    assert OUTSIDE_MARKER not in json.dumps(asdict(result))
    cache = (root / ".strucin_cache/analysis_cache.json").read_text(encoding="utf-8")
    assert OUTSIDE_MARKER not in cache and "linked.py" not in cache


@pytest.mark.parametrize("kind", ["external", "dangling", "loop", "chain"])
@pytest.mark.parametrize("extension", [".py", ".md", ".rst", ".txt", ".TXT"])
def test_linked_source_and_documents_do_not_enter_search(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, extension: str
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "private.txt"
    outside.write_text(f'"""{OUTSIDE_MARKER}"""\n', encoding="utf-8")
    make_link(root, outside, extension, kind)
    (root / "README.md").write_text("Local documentation", encoding="utf-8")
    monkeypatch.setattr(semantic, "_load_sentence_transformer", lambda model: None)
    result = semantic.build_semantic_index(root)
    assert [chunk.path for chunk in result.chunks] == ["README.md"]
    assert OUTSIDE_MARKER not in json.dumps(asdict(result))


def test_contained_symlinks_preserve_paths_and_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "pkg"
    source.mkdir()
    (source / "original.py").write_text('"""Local module"""\nVALUE = 1\n', encoding="utf-8")
    (tmp_path / "linked.py").symlink_to(source / "original.py")
    (source / "README.md").write_text("Local documentation", encoding="utf-8")
    (tmp_path / "linked.md").symlink_to(source / "README.md")
    analysis = analyze_repository(tmp_path, use_cache=False)
    linked = next(file for file in analysis.files if file.path == "linked.py")
    assert linked.module_path == "linked"
    assert linked.docstring == "Local module"
    monkeypatch.setattr(semantic, "_load_sentence_transformer", lambda model: None)
    index = semantic.build_semantic_index(tmp_path)
    assert any(
        chunk.path == "linked.md" and chunk.text == "Local documentation" for chunk in index.chunks
    )


def test_directory_links_are_not_walked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "private"
    outside.mkdir()
    (outside / "source.py").write_text(f'"""{OUTSIDE_MARKER}"""\n', encoding="utf-8")
    (outside / "README.md").write_text(OUTSIDE_MARKER, encoding="utf-8")
    (root / "linked-dir").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(semantic, "_load_sentence_transformer", lambda model: None)
    assert scan_repository(root).files == []
    assert semantic.build_semantic_index(root).chunks == []


@pytest.mark.parametrize("consumer", ["analysis", "search"])
def test_retarget_after_discovery_is_rejected(tmp_path: Path, consumer: str) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "local.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    metadata = scan_repository(root).files[0]
    outside = tmp_path / "private.py"
    outside.write_text(f'"""{OUTSIDE_MARKER}"""\n', encoding="utf-8")
    source.unlink()
    source.symlink_to(outside)
    with pytest.raises(AnalysisError, match="outside the root"):
        if consumer == "analysis":
            _analyze_file_with_cache(metadata, root, {})
        else:
            semantic._read_python_source(root, metadata)


@pytest.mark.skipif(
    os.open not in os.supports_dir_fd or not hasattr(os, "O_NOFOLLOW"),
    reason="POSIX no-follow opens",
)
@pytest.mark.parametrize("replace_parent", [False, True])
def test_retarget_between_resolution_and_open_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, replace_parent: bool
) -> None:
    root = tmp_path / "repo"
    directory = root / "package"
    directory.mkdir(parents=True)
    source = directory / "local.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    outside = tmp_path / "private"
    outside.mkdir()
    (outside / "local.py").write_text(OUTSIDE_MARKER, encoding="utf-8")
    original_open = repository_files._open_contained_file

    def retarget(repo: Path, resolved: Path) -> int:
        if replace_parent:
            directory.rename(root / "original")
            directory.symlink_to(outside, target_is_directory=True)
        else:
            source.unlink()
            source.symlink_to(outside / "local.py")
        return original_open(repo, resolved)

    monkeypatch.setattr(repository_files, "_open_contained_file", retarget)
    with pytest.raises(AnalysisError, match="Cannot safely read"):
        read_repository_bytes(root, source)


def test_portable_reader_still_checks_containment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "local.py").write_bytes(b"VALUE = 1\r\n")
    outside = tmp_path / "private.py"
    outside.write_text(OUTSIDE_MARKER, encoding="utf-8")
    link = root / "linked.py"
    link.symlink_to(outside)
    monkeypatch.setattr(os, "supports_dir_fd", set())
    assert read_repository_bytes(root, root / "local.py") == b"VALUE = 1\r\n"
    with pytest.raises(AnalysisError):
        read_repository_bytes(root, link)


@pytest.mark.parametrize("old_policy", [None, "old-policy"])
def test_cli_search_rebuilds_indexes_from_before_containment_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, old_policy: str | None
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "README.md").write_text("Local documentation", encoding="utf-8")
    outside = tmp_path / "private.txt"
    outside.write_text(OUTSIDE_MARKER, encoding="utf-8")
    (root / "linked.txt").symlink_to(outside)
    monkeypatch.setattr(semantic, "_load_sentence_transformer", lambda model: None)
    index = semantic.build_semantic_index(root)
    cache = root / "semantic_index.json"
    semantic.write_semantic_index(index, cache)
    payload = json.loads(cache.read_text(encoding="utf-8"))
    payload["chunks"][0]["text"] = OUTSIDE_MARKER
    if old_policy is None:
        del payload["file_policy_version"]
    else:
        payload["file_policy_version"] = old_policy
    cache.write_text(json.dumps(payload), encoding="utf-8")
    assert main(["search", "documentation", "--path", str(root)]) == 0
    updated = cache.read_text(encoding="utf-8")
    assert OUTSIDE_MARKER not in updated
    assert json.loads(updated)["file_policy_version"] == repository_files.FILE_POLICY_VERSION


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO support required")
def test_special_files_are_skipped_without_blocking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    os.mkfifo(tmp_path / "named_pipe.py")
    os.mkfifo(tmp_path / "named_pipe.txt")
    monkeypatch.setattr(semantic, "_load_sentence_transformer", lambda model: None)
    assert scan_repository(tmp_path).files == []
    assert semantic.build_semantic_index(tmp_path).chunks == []
    assert resolve_repository_file(tmp_path, tmp_path) is None


@pytest.mark.parametrize(
    ("raw", "lines"), [(b"", 0), (b"\xff", 0), (b"a\r\nb\rc\n", 3), (b"a\vb", 1)]
)
def test_line_count_keeps_existing_newline_and_decoding_behavior(raw: bytes, lines: int) -> None:
    assert _count_loc(raw) == lines
