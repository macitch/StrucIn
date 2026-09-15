from __future__ import annotations

import runpy
import subprocess
import sys
from pathlib import Path

import pytest

from strucin._version import __version__


def test_cli_help_shows_usage() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "strucin.cli", "--help"],
        capture_output=True,
        text=True,
        check=True,
    )

    assert "usage: strucin" in result.stdout
    assert "scan" in result.stdout


@pytest.mark.parametrize(
    "arguments,exit_code,message",
    [
        ([], 0, "usage: strucin"),
        (["--help"], 0, "usage: strucin"),
        (["--version"], 0, f"strucin {__version__}"),
        (["scan", "missing-repository"], 1, "Path does not exist"),
        (["unknown-command"], 2, "invalid choice"),
        (["scan"], 2, "the following arguments are required: path"),
    ],
)
def test_module_entrypoint_exit_status_and_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
    exit_code: int,
    message: str,
) -> None:
    # Exercise the actual module entry point in-process so coverage measures it too.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["strucin", *arguments])

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("strucin.cli", run_name="__main__")

    assert exc_info.value.code == exit_code
    captured = capsys.readouterr()
    if exit_code == 0:
        assert message in captured.out
        assert captured.err == ""
    else:
        assert message in captured.err
        assert captured.out == ""
