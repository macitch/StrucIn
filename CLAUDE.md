# CLAUDE.md

Context for AI coding agents (Claude Code, Codex and others) working in this repository.
Human contributors: see CONTRIBUTING.md, which stays the source of truth.

## What this project is

StrucIn analyzes local Python repositories and generates architecture artifacts:
module index, AST analysis, dependency graph with cycle detection, Markdown report,
semantic search, LLM-assisted narration, and a static web dashboard.
Python 3.11+. Runtime dependencies are deliberately small (`rich`, `pygments`).
AI features (`anthropic`, `openai`, `sentence-transformers`) are optional extras.

## Layout

- `src/strucin/core/`: analysis, indexing, reporting, semantic search, explanations, caching, privacy
- `src/strucin/cli/`: argument parsing, UX, command orchestration, pre-commit hooks
- `src/strucin/web/`: dashboard generation and local serving
- `src/strucin/utils/`: shared helpers (logging)
- `src/strucin/exceptions.py`: project exceptions
- `tests/`: unit and regression tests, fixtures in `tests/fixtures`
- `.github/workflows/`: CI, action test, example usage, publish

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Checks (run all of them before saying a task is done)

```bash
ruff check src/ tests/
ruff format --check src/ tests/
mypy src/strucin
pytest -m "not integration" --cov=src/strucin --cov-report=term-missing --cov-fail-under=85
```

CI runs the same checks on Python 3.11, 3.12 and 3.13. A change is not done until
lint, format, type check and tests all pass locally.

## Conventions

- Type everything. `mypy --strict` is enforced on `src/strucin`.
- Ruff rules include security (`S`), complexity (max McCabe 12), and no `print` (`T20`).
  `print` is allowed only in the CLI output modules already listed in `pyproject.toml`.
- Line length 100. Use `pathlib` (`PTH` rules), not `os.path`.
- Every new behavior gets a test. Fix bugs with a failing test first.
- Do not lower the 85% coverage gate or add `# noqa` / `# type: ignore` without a reason in a comment.
- Keep `--json` output clean: JSON on stdout, progress and errors on stderr, nonzero exit on failure.
- Artifact paths are validated for safety (symlink loops, traversal). Do not bypass those checks.
- Respect privacy and redaction behavior in `core/privacy.py` when touching LLM or explain code.

## Tests

- Unit tests need no API keys: `pytest -m "not integration"`.
- Integration tests call real LLM APIs and need `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`.
  Never run them unless asked, and never commit keys.

## Pull requests

- One feature or fix per PR, from a branch (`fix/...`, `feat/...`), never directly on `main`.
- PRs must pass CI before merge.
- Update `CHANGELOG.md` under `[Unreleased]` for user-visible changes.
- Summarize what changed, why, and how it was verified.

## Working agreements for agents

- Read the relevant module and its tests before editing.
- Prefer small, reviewable diffs. Do not refactor unrelated code.
- Do not add dependencies without asking; the runtime dependency list is intentionally minimal.
- Report what you ran and the result. If a check fails or was skipped, say so.
- A human reviews and merges every PR.
