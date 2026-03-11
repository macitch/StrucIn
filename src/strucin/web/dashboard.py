"""Web dashboard: generate static assets and optionally serve them locally.

Static assets (HTML, CSS, JavaScript) live in ``strucin/web/assets/`` and
are loaded at runtime via ``importlib.resources``.  This keeps them lintable,
diffable, and independently testable — no more multi-hundred-line string
literals in Python source.

The dashboard data (``data.json``) is validated against a required-key schema
before any file is written, so a schema violation raises ``ValueError`` early
rather than producing a broken dashboard that fails silently in the browser.
"""

from __future__ import annotations

import importlib.resources
import json
import logging
import socket
import threading
from dataclasses import asdict
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from strucin.core.analyzer import AnalysisResult, analyze_repository
from strucin.core.artifacts import build_artifact_metadata
from strucin.exceptions import DashboardSchemaError

_logger = logging.getLogger(__name__)

# Fields that app.js reads at the top level of data.json.
_REQUIRED_DATA_KEYS: frozenset[str] = frozenset(
    {"file_count", "module_count", "files", "nodes", "edges", "cycles"}
)


def _read_asset(name: str) -> str:
    """Return the text content of a dashboard asset file."""
    return (
        importlib.resources.files("strucin.web")
        .joinpath("assets")
        .joinpath(name)
        .read_text(encoding="utf-8")
    )


def _serialize_analysis(analysis: AnalysisResult) -> dict[str, object]:
    return {
        "artifact_metadata": build_artifact_metadata("web_dashboard_data"),
        "repo_root": analysis.repo_root,
        "generated_at": analysis.generated_at,
        "file_count": analysis.file_count,
        "module_count": analysis.module_count,
        "files": [asdict(f) for f in analysis.files],
        "nodes": analysis.dependency_graph_nodes,
        "edges": [asdict(e) for e in analysis.dependency_graph_edges],
        "cycles": analysis.cycles,
    }


def _validate_data(data: dict[str, object]) -> None:
    """Validate that *data* contains all fields required by ``app.js``.

    Raises ``ValueError`` with a descriptive message on any schema violation.
    This guard catches bugs during development before they produce a broken
    dashboard that fails silently in the browser.
    """
    missing = _REQUIRED_DATA_KEYS - data.keys()
    if missing:
        raise DashboardSchemaError(
            f"Dashboard data missing required fields: {sorted(missing)}"
        )
    for list_key in ("files", "nodes", "edges", "cycles"):
        if not isinstance(data[list_key], list):
            raise DashboardSchemaError(
                f"Dashboard data: '{list_key}' must be a list, "
                f"got {type(data[list_key]).__name__}"
            )


def build_dashboard(
    repo_path: Path,
    output_dir: Path,
    excluded_dirs: set[str] | None = None,
    max_workers: int | None = None,
    executor: str = "auto",
) -> Path:
    analysis = analyze_repository(
        repo_path,
        excluded_dirs=excluded_dirs,
        max_workers=max_workers,
        executor=executor,
    )
    data = _serialize_analysis(analysis)
    _validate_data(data)  # raises before any write if schema is violated

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "data.json").write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "index.html").write_text(_read_asset("index.html"), encoding="utf-8")
    (output_dir / "app.js").write_text(_read_asset("app.js"), encoding="utf-8")
    (output_dir / "styles.css").write_text(_read_asset("styles.css"), encoding="utf-8")
    return output_dir / "index.html"


def serve_dashboard(
    directory: Path, host: str = "127.0.0.1", port: int = 8765
) -> ThreadingHTTPServer:
    if host == "0.0.0.0":  # noqa: S104
        _logger.warning("Binding to 0.0.0.0 exposes the dashboard to your entire network.")
    class DashboardHandler(SimpleHTTPRequestHandler):
        def __init__(
            self,
            request: socket.socket,
            client_address: tuple[str, int],
            server: ThreadingHTTPServer,
        ) -> None:
            super().__init__(
                request=request,
                client_address=client_address,
                server=server,
                directory=str(directory),
            )

    return ThreadingHTTPServer((host, port), DashboardHandler)


def start_dashboard_server(directory: Path, host: str, port: int) -> ThreadingHTTPServer:
    server = serve_dashboard(directory, host, port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
