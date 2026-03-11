from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from strucin.core.indexer import scan_repository


def test_scan_repository_excludes_known_directories(tmp_path: Path) -> None:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "services.py").write_text(
        "def run() -> None:\n    pass\n",
        encoding="utf-8",
    )
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "ignored.py").write_text("print('ignore')\n", encoding="utf-8")
    (tmp_path / "venv").mkdir()
    (tmp_path / "venv" / "ignored.py").write_text("print('ignore')\n", encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "ignored.py").write_text("print('ignore')\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "ignored.py").write_text("print('ignore')\n", encoding="utf-8")

    result = scan_repository(tmp_path)

    assert result.file_count == 2
    assert [file.path for file in result.files] == ["app/__init__.py", "app/services.py"]
    assert [file.module_path for file in result.files] == ["app", "app.services"]
    assert result.files[1].loc == 2


def test_cli_scan_generates_repo_index_json(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "core.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "ignored.py").write_text("print('ignore')\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "strucin.cli", "scan", str(tmp_path)],
        capture_output=True,
        text=True,
        check=True,
    )

    assert "Scanned 2 Python files." in result.stdout

    index_path = tmp_path / "repo_index.json"
    assert index_path.exists()

    payload = json.loads(index_path.read_text(encoding="utf-8"))
    assert payload["file_count"] == 2
    assert payload["files"][0]["path"] == "pkg/__init__.py"
    assert payload["files"][1]["module_path"] == "pkg.core"
