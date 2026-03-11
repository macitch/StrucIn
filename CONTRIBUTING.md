# Contributing to StrucIn

Thank you for your interest in contributing!

## Development Setup

```bash
git clone https://github.com/macitch/StrucIn.git
cd StrucIn
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev,llm,embeddings]"
```

## Running Tests

```bash
# Unit tests (no API keys required)
pytest

# Integration tests (requires ANTHROPIC_API_KEY or OPENAI_API_KEY)
pytest -m integration -v
```

## Lint & Typecheck

```bash
ruff check src/ tests/
mypy src/strucin
```

## Coverage

```bash
pytest --cov=src/strucin --cov-report=term-missing --cov-fail-under=85
```

## PR Guidelines

- One feature or fix per PR — keep scope focused
- All new code must include tests
- PRs must pass CI (lint, typecheck, test matrix on Python 3.11 and 3.12)
- Update `CHANGELOG.md` under `[Unreleased]` for user-visible changes
