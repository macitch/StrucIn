#!/usr/bin/env bash
# Run from the repository root using Python 3.11+ with uv and pip-audit installed.
set -euo pipefail

if [ "$#" -ne 3 ]; then
  echo "Usage: bash scripts/audit-dependencies.sh PYTHON_VERSION PLATFORM OUTPUT_DIR" >&2
  exit 2
fi

python_version="$1"
platform="$2"
output_dir="$3"
mkdir -p "$output_dir"

python - "$output_dir" <<'PY'
import sys
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version

config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
project = config["project"]
base = project["dependencies"]
extras = [item for group in project.get("optional-dependencies", {}).values() for item in group]
build = config["build-system"]["requires"]
output = Path(sys.argv[1])
for name, requirements in {"base": base, "all-extras": base + extras, "build": build}.items():
    (output / f"{name}.in").write_text("\n".join(sorted(set(requirements))) + "\n")

# Audit explicit lower bounds separately; fresh resolution normally selects newer versions.
minimums = set()
for text in set(base + extras + build):
    requirement = Requirement(text)
    if requirement.url or requirement.marker or requirement.extras:
        raise ValueError(f"Extend minimum-version auditing before using this requirement: {text}")
    if not requirement.specifier:
        continue  # Unbounded requirements are covered by the resolved build/runtime scans.
    candidates = [Version(s.version) for s in requirement.specifier if s.operator in {">=", "=="}]
    if not candidates or max(candidates) not in requirement.specifier:
        raise ValueError(f"Cannot determine an inclusive minimum version: {text}")
    minimums.add(f"{requirement.name}=={max(candidates)}")
(output / "minimum-direct.txt").write_text("\n".join(sorted(minimums)) + "\n")
PY

for profile in base all-extras build; do
  uv pip compile "$output_dir/$profile.in" \
    --python-version "$python_version" --python-platform "$platform" \
    --no-build --upgrade --generate-hashes --no-header --no-annotate --quiet \
    --output-file "$output_dir/$profile.txt"
done

status=0
for profile in base all-extras build minimum-direct; do
  echo "Auditing $profile ($platform, Python $python_version)"
  python -m pip_audit --requirement "$output_dir/$profile.txt" \
    --no-deps --disable-pip --strict --progress-spinner off \
    --format json --output "$output_dir/$profile.json" || status=1
done
exit "$status"
