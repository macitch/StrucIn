from __future__ import annotations

import json
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from strucin.cli.main import main


@pytest.mark.parametrize("command", ["scan", "analyze", "report", "search", "explain", "web"])
@pytest.mark.parametrize("path_is_file", [False, True], ids=["missing", "file"])
def test_commands_reject_invalid_repository_paths(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    command: str,
    path_is_file: bool,
) -> None:
    target = tmp_path / "repository"
    if path_is_file:
        target.write_text("Keep this file intact.\n", encoding="utf-8")
    if command == "search":
        arguments = [command, "query", "--path", str(target)]
    elif command in {"explain", "web"}:
        arguments = [command, "--path", str(target)]
    else:
        arguments = [command, str(target)]

    assert main(arguments) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert ("not a directory" if path_is_file else "does not exist") in captured.err
    assert "Traceback" not in captured.err
    if path_is_file:
        assert target.read_text(encoding="utf-8") == "Keep this file intact.\n"
    else:
        assert not target.exists()


def test_empty_search_reports_no_matches_when_index_is_built_and_reused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".strucin.toml").write_text(
        '[search]\nembedding_model = "hashing-v1"\n', encoding="utf-8"
    )
    for _ in range(2):
        assert main(["search", "nonexistent symbol", "--path", str(tmp_path)]) == 0
        captured = capsys.readouterr()
        assert "No semantic matches found." in captured.out
        assert captured.err == ""
    assert (tmp_path / "semantic_index.json").is_file()


@pytest.mark.parametrize("port", [-1, 0, 65536])
def test_web_rejects_invalid_ports_before_writing_artifacts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], port: int
) -> None:
    output = tmp_path / "dashboard"

    assert main(["web", "--path", str(tmp_path), "--out", str(output), "--port", str(port)]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert f"Port out of range: {port}" in captured.err
    assert not output.exists()


@pytest.mark.parametrize("shutdown", ["return", "interrupt", "error"])
def test_web_serve_closes_server_on_every_exit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], shutdown: str
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / "sample.py").write_text("value = 1\n", encoding="utf-8")
    output = tmp_path / "dashboard"
    server = Mock(spec=ThreadingHTTPServer)
    if shutdown == "interrupt":
        server.serve_forever.side_effect = KeyboardInterrupt
    elif shutdown == "error":
        server.serve_forever.side_effect = PermissionError("Cannot serve dashboard")

    # Generate real dashboard files, replacing only the blocking network server.
    with patch("strucin.cli.main.serve_dashboard", return_value=server) as serve:
        result = main(
            [
                "web",
                "--path",
                str(repository),
                "--out",
                str(output),
                "--serve",
                "--host",
                "127.0.0.1",
                "--port",
                "8766",
            ]
        )

    assert result == (1 if shutdown == "error" else 0)
    serve.assert_called_once_with(output.resolve(), host="127.0.0.1", port=8766)
    server.serve_forever.assert_called_once_with()
    server.server_close.assert_called_once_with()
    for name in ("index.html", "app.js", "styles.css", "data.json"):
        assert (output / name).is_file()
    payload = json.loads((output / "data.json").read_text(encoding="utf-8"))
    assert payload["file_count"] == 1
    captured = capsys.readouterr()
    assert "Serving dashboard at http://127.0.0.1:8766/index.html" in captured.out
    if shutdown == "error":
        assert "Cannot serve dashboard" in captured.err
        assert "Traceback" not in captured.err
    else:
        assert captured.err == ""
    if shutdown == "interrupt":
        assert "Stopping server..." in captured.out
