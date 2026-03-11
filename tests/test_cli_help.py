from __future__ import annotations

import subprocess
import sys


def test_cli_help_shows_usage() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "strucin.cli", "--help"],
        capture_output=True,
        text=True,
        check=True,
    )

    assert "usage: strucin" in result.stdout
    assert "scan" in result.stdout
