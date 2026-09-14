"""Read disposable JSON caches and replace them without exposing partial writes."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any, NoReturn

_logger = logging.getLogger(__name__)


def _invalid_constant(value: str) -> NoReturn:
    raise ValueError("Non-finite JSON constant")


def read_cache_json(cache_path: Path, *, kind: str) -> dict[str, Any] | None:
    """Treat missing, unreadable, malformed, or non-object JSON as a cache miss.

    Callers validate the destination and their cache schema. Diagnostics never
    echo cache contents or exception messages, which can contain private data.
    """
    try:
        payload = json.loads(
            cache_path.read_text(encoding="utf-8"), parse_constant=_invalid_constant
        )
    except FileNotFoundError:
        return None
    except (OSError, ValueError, RecursionError) as exc:
        _logger.warning("Ignoring %s (%s); rebuilding.", kind, type(exc).__name__)
        return None
    if not isinstance(payload, dict):
        _logger.warning("Ignoring %s with invalid JSON structure; rebuilding.", kind)
        return None
    return payload


def write_cache_json(cache_path: Path, payload: object) -> None:
    """Atomically replace a caller-validated destination using a sibling file.

    Exceptions leave the old destination intact. Temporary files are private and
    closed before replacement, including on platforms that forbid renaming an
    open file. This is atomic replacement, not coordination between writers.
    """
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=cache_path.parent,
            prefix=".strucin-cache-",
            suffix=".tmp",
            delete=False,
        ) as file:
            temporary_path = Path(file.name)
            json.dump(payload, file, indent=2, allow_nan=False)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        temporary_path.replace(cache_path)
    finally:
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)
