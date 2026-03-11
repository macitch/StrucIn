from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_cli_emits_structured_command_log_when_enabled(tmp_path: Path) -> None:
    (tmp_path / ".strucin.toml").write_text(
        "\n".join(
            [
                "[observability]",
                "structured_logging = true",
                "timing_enabled = true",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "mod.py").write_text("def run() -> int:\n    return 1\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "strucin.cli", "analyze", str(tmp_path)],
        capture_output=True,
        text=True,
        check=True,
    )

    structured_line = result.stderr.strip().splitlines()[-1]
    payload = json.loads(structured_line)
    assert payload["event"] == "command_completed"
    assert payload["command"] == "analyze"
    assert "total_ms" in payload
    assert "bottleneck_stage" in payload
