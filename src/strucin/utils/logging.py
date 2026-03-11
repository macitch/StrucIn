from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class CommandTiming:
    stage: str
    duration_ms: float


def emit_structured_log(enabled: bool, event: str, **fields: object) -> None:
    if not enabled:
        return
    payload: dict[str, object] = {
        "ts": datetime.now(UTC).isoformat(),
        "event": event,
        **fields,
    }
    print(json.dumps(payload, sort_keys=True), file=sys.stderr)
