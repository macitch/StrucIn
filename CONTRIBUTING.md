# Contributing to StrucIn

Thank you for your interest in contributing!

## Development Setup

```bash
git clone https://github.com/macitch/StrucIn.git
cd StrucIn
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"
```

## Running Tests

```bash
# Unit tests (no API keys required)
pytest -m "not integration"

# Integration tests (requires ANTHROPIC_API_KEY or OPENAI_API_KEY)
pip install -e ".[llm]"
pytest -m integration -v
```

## Lint & Typecheck

```bash
ruff check src/ tests/
mypy src/strucin
```

## Coverage

Coverage measures the full Python package, including CLI commands and the module
entry point. CI enforces the same 85% minimum on Python 3.11, 3.12, and 3.13.

```bash
pytest -m "not integration" --cov=src/strucin --cov-report=term-missing --cov-fail-under=85
```

## Dependency Audits

The dependency audit workflow resolves base, all-extra, and build dependencies
for Python 3.11–3.13 on Linux x86-64 and macOS 14+ Apple Silicon. It also checks
explicit direct minimum versions, so a clean latest resolution does not hide an
outdated lower bound. Inventories and JSON reports are uploaded even on failure.

Run the same checks from the repository root in a separate audit environment:

```bash
python3 -m venv /tmp/strucin-audit-tools
source /tmp/strucin-audit-tools/bin/activate
python -m pip install --upgrade "pip>=26.2" "uv==0.12.15" "pip-audit==2.10.1"
bash scripts/audit-dependencies.sh 3.11 x86_64-unknown-linux-gnu /tmp/strucin-audit-linux
MACOSX_DEPLOYMENT_TARGET=14.0 bash scripts/audit-dependencies.sh 3.13 aarch64-apple-darwin /tmp/strucin-audit-macos
```

Resolution downloads metadata without installing AI packages or model weights.
The scanner queries current PyPI advisories and fails on vulnerabilities or
collection errors. This checks the resolved versions and explicit direct minima;
it does not prove every version combination allowed by the dependency ranges is
safe, or test optional model/provider behavior.

To check an existing development environment, activate it and run
`python -m pip list --format=freeze --exclude-editable > /tmp/strucin-installed.txt`.
Then use the audit environment's Python to run
`python -m pip_audit --strict --no-deps --disable-pip -r /tmp/strucin-installed.txt`.

## PR Guidelines

- One feature or fix per PR — keep scope focused
- All new code must include tests
- PRs must pass CI (lint, typecheck, test matrix on Python 3.11, 3.12, and 3.13)
- Update `CHANGELOG.md` under `[Unreleased]` for user-visible changes
