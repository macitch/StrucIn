from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from strucin._version import __version__

ARTIFACT_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class ArtifactMetadata:
    artifact_type: str
    generated_at: str
    schema_version: str
    strucin_version: str


def build_artifact_metadata(artifact_type: str, generated_at: str | None = None) -> dict[str, str]:
    timestamp = generated_at or datetime.now(UTC).isoformat()
    return asdict(
        ArtifactMetadata(
            artifact_type=artifact_type,
            generated_at=timestamp,
            schema_version=ARTIFACT_SCHEMA_VERSION,
            strucin_version=__version__,
        )
    )
