from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest

from strucin.core import analysis_cache, cache_io, explainer


def write_cache(kind: str, path: Path) -> None:
    if kind == "analysis":
        analysis_cache.write_analysis_cache(path, {}, generated_at="2026-09-13T00:00:00+00:00")
    else:
        explainer._write_cache(
            path, {"new": {"content": "new narration", "generated_at": "2026-09-13T00:00:00+00:00"}}
        )


@pytest.mark.parametrize("kind", ["analysis", "explain"])
@pytest.mark.parametrize("failure_stage", ["serialize", "sync", "replace"])
@pytest.mark.parametrize("failure", [OSError, KeyboardInterrupt])
def test_interrupted_cache_write_preserves_previous_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    failure_stage: str,
    failure: type[BaseException],
) -> None:
    path = tmp_path / "cache.json"
    previous = b'{"previous": "complete cache"}\n'
    path.write_bytes(previous)

    def fail(*args: object, **kwargs: object) -> None:
        assert path.read_bytes() == previous
        raise failure("simulated interrupted write")

    if failure_stage == "serialize":

        def partial_dump(payload, stream, **kwargs):
            stream.write('{"partial":')
            stream.flush()
            fail()

        monkeypatch.setattr(cache_io.json, "dump", partial_dump)
    elif failure_stage == "sync":
        monkeypatch.setattr(cache_io.os, "fsync", fail)
    else:
        monkeypatch.setattr(Path, "replace", fail)

    with pytest.raises(failure, match="interrupted"):
        write_cache(kind, path)
    assert path.read_bytes() == previous
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("kind", ["analysis", "explain"])
def test_cache_is_complete_and_private_before_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    path = tmp_path / "cache.json"
    previous = b'{"previous": true}'
    path.write_bytes(previous)
    original_replace = Path.replace
    replaced: list[Path] = []

    def inspect_replace(self: Path, target: Path) -> Path:
        assert target == path
        assert self.parent == path.parent
        assert json.loads(self.read_bytes())["cache_version"]
        assert path.read_bytes() == previous
        if os.name == "posix":
            assert self.stat().st_mode & 0o077 == 0
        replaced.append(self)
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", inspect_replace)
    write_cache(kind, path)
    assert len(replaced) == 1
    assert json.loads(path.read_bytes())["cache_version"]
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("previous_exists", [False, True])
def test_serialization_error_never_publishes_invalid_json(
    tmp_path: Path, previous_exists: bool
) -> None:
    path = tmp_path / "cache.json"
    if previous_exists:
        path.write_text('{"old": true}', encoding="utf-8")
    with pytest.raises(TypeError):
        cache_io.write_cache_json(path, {"ok": "partial", "invalid": object()})
    if previous_exists:
        assert json.loads(path.read_text(encoding="utf-8")) == {"old": True}
        assert list(tmp_path.iterdir()) == [path]
    else:
        assert list(tmp_path.iterdir()) == []


def test_concurrent_cache_writers_publish_complete_snapshots(tmp_path: Path) -> None:
    path = tmp_path / "cache.json"
    cache_io.write_cache_json(path, {"value": "initial"})
    stop = Event()
    observed: list[dict] = []

    def read_snapshots() -> None:
        while not stop.is_set():
            observed.append(json.loads(path.read_text(encoding="utf-8")))

    def write_snapshots(worker: int) -> None:
        for index in range(8):
            cache_io.write_cache_json(path, {"value": f"{worker}:{index}" * 1000})

    with ThreadPoolExecutor(max_workers=5) as executor:
        reader = executor.submit(read_snapshots)
        writers = [executor.submit(write_snapshots, worker) for worker in range(4)]
        try:
            for writer in writers:
                writer.result()
        finally:
            stop.set()
        reader.result()
    assert observed
    assert all(set(snapshot) == {"value"} for snapshot in observed)
    assert list(tmp_path.iterdir()) == [path]
