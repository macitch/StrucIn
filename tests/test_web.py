from __future__ import annotations

import importlib.resources
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

import strucin.web
import strucin.web.dashboard
from strucin.exceptions import DashboardSchemaError
from strucin.web.dashboard import _validate_data, build_dashboard, serve_dashboard


def test_build_dashboard_generates_files_and_data(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "service.py").write_text(
        "def ping() -> str:\n"
        '    return "pong"\n',
        encoding="utf-8",
    )

    output_dir = tmp_path / ".dashboard"
    html_path = build_dashboard(tmp_path, output_dir)

    assert html_path.exists()
    assert (output_dir / "app.js").exists()
    assert (output_dir / "styles.css").exists()

    data_payload = json.loads((output_dir / "data.json").read_text(encoding="utf-8"))
    assert data_payload["file_count"] == 2
    assert "nodes" in data_payload
    assert "edges" in data_payload


# ---------------------------------------------------------------------------
# _validate_data unit tests
# ---------------------------------------------------------------------------


def test_validate_data_passes_on_valid_data() -> None:
    """Valid data dict with all required keys does not raise."""
    _validate_data(
        {"file_count": 1, "module_count": 1, "files": [], "nodes": [], "edges": [], "cycles": []}
    )


def test_validate_data_raises_on_missing_key() -> None:
    """Missing a required key raises DashboardSchemaError naming the absent fields."""
    with pytest.raises(DashboardSchemaError, match="missing required fields"):
        _validate_data({"file_count": 1})


def test_validate_data_raises_on_wrong_type() -> None:
    """A non-list value for 'files' raises DashboardSchemaError with a descriptive message."""
    bad: dict[str, object] = {
        "file_count": 1,
        "module_count": 1,
        "files": "not-a-list",
        "nodes": [],
        "edges": [],
        "cycles": [],
    }
    with pytest.raises(DashboardSchemaError, match="'files' must be a list"):
        _validate_data(bad)


# ---------------------------------------------------------------------------
# build_dashboard raises before writing on schema violation
# ---------------------------------------------------------------------------


def test_build_dashboard_raises_before_writing_on_schema_violation(tmp_path: Path) -> None:
    """_validate_data fires before any file is written; output_dir is not created."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")

    output_dir = tmp_path / ".dashboard"

    # Patch _serialize_analysis to return data missing all required list keys.
    bad_data: dict[str, object] = {"file_count": 1}
    with patch("strucin.web.dashboard._serialize_analysis", return_value=bad_data):
        with pytest.raises(DashboardSchemaError, match="missing required fields"):
            build_dashboard(tmp_path, output_dir)

    assert not output_dir.exists(), "output_dir should not be created when validation fails"


# ---------------------------------------------------------------------------
# Asset files readable via importlib.resources
# ---------------------------------------------------------------------------


def test_dashboard_assets_readable_via_importlib_resources() -> None:
    """HTML, CSS, and JS assets are accessible as package resources."""
    web_pkg = importlib.resources.files("strucin.web")
    for filename in ("index.html", "app.js", "styles.css"):
        content = (web_pkg / "assets" / filename).read_text(encoding="utf-8")
        assert len(content) > 0, f"assets/{filename} must not be empty"

    html = (web_pkg / "assets" / "index.html").read_text(encoding="utf-8")
    assert "StrucIn" in html
    assert "app.js" in html

    js = (web_pkg / "assets" / "app.js").read_text(encoding="utf-8")
    assert "bootstrap" in js
    assert "data.json" in js
    assert '"use strict"' in js
    assert "escapeHtml" in js

    css = (web_pkg / "assets" / "styles.css").read_text(encoding="utf-8")
    assert "--bg" in css


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


def test_cli_web_generates_dashboard_assets(tmp_path: Path) -> None:
    (tmp_path / "mod").mkdir()
    (tmp_path / "mod" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "mod" / "core.py").write_text("value = 1\n", encoding="utf-8")

    output_dir = tmp_path / "ui"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "strucin.cli",
            "web",
            "--path",
            str(tmp_path),
            "--out",
            str(output_dir),
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    assert "Dashboard generated at" in result.stdout
    assert "Tip: run with --serve to start a local server." in result.stdout
    assert (output_dir / "index.html").exists()
    assert (output_dir / "data.json").exists()


# ---------------------------------------------------------------------------
# Import smoke tests
# ---------------------------------------------------------------------------


def test_strucin_web_package_importable() -> None:
    """strucin.web is importable as a package with no side effects."""
    assert strucin.web is not None


def test_strucin_web_dashboard_importable() -> None:
    """strucin.web.dashboard exposes the expected public API."""
    assert callable(build_dashboard)
    assert callable(serve_dashboard)
    assert callable(_validate_data)


def test_build_dashboard_is_callable_with_correct_signature() -> None:
    """build_dashboard accepts executor kwarg introduced in Phase 14 Fix 6."""
    import inspect

    sig = inspect.signature(build_dashboard)
    params = sig.parameters
    assert "repo_path" in params
    assert "output_dir" in params
    assert "executor" in params
    assert params["executor"].default == "auto"
