[![CI](https://github.com/macitch/StrucIn/actions/workflows/ci.yml/badge.svg)](https://github.com/macitch/StrucIn/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/strucin)](https://pypi.org/project/strucin/)
[![Python versions](https://img.shields.io/pypi/pyversions/strucin)](https://pypi.org/project/strucin/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)

# StrucIn

StrucIn analyzes local Python repositories and generates architecture
artifacts you can use for technical discovery, refactoring planning, onboarding,
and dependency risk review.

## What StrucIn Provides

- Repository indexing with module mapping and file metadata
- Static AST analysis for imports, classes, functions, docstrings, and complexity
- Dependency graph and cycle detection
- Architecture report (`docs/REPORT.md`)
- Semantic code/document search (`semantic_index.json` at repo root)
- Architecture narration (`docs/EXPLAIN.md`) with caching and redaction
- Interactive web dashboard for dependency exploration

## Current Scope

- Language: Python repositories
- Input: local filesystem paths
- Output: JSON and Markdown artifacts written to the target repository

## Architecture Overview

- `src/strucin/core/`: analysis, reporting, semantic indexing, explanations
- `src/strucin/cli/`: command parsing, UX, orchestration
- `src/strucin/web/`: dashboard generation and local serving
- `src/strucin/core/config.py`: configuration loading and defaults
- `src/strucin/utils/`: shared utility helpers
- `tests/`: unit and regression test suite with fixtures

## Installation

### 1. Create and activate a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install development tooling

```bash
pip install --upgrade pip
pip install ruff mypy pytest
pip install -e .
```

### 3. Run the CLI

```bash
strucin --help
```

## Quickstart

```bash
# Scaffold configuration
strucin init --path /path/to/myrepo

# Analyze a local Python repo
strucin scan /path/to/myrepo
strucin analyze /path/to/myrepo
strucin report /path/to/myrepo     # writes docs/REPORT.md
strucin explain /path/to/myrepo    # writes docs/EXPLAIN.md (template, no key needed)

# Enable LLM-powered narration
export ANTHROPIC_API_KEY="sk-ant-..."
strucin explain /path/to/myrepo    # writes docs/EXPLAIN.md 

# Semantic search
strucin search "authentication middleware" --path /path/to/myrepo

# Compare two analysis snapshots
strucin diff before.json after.json

# Machine-readable output
strucin analyze /path/to/myrepo --json

# Launch web dashboard
strucin web /path/to/myrepo
```

## Optional Dependencies

| Extra | Installs | Enables |
|-------|----------|---------|
| `pip install strucin[llm]` | anthropic, openai | LLM-powered narration |
| `pip install strucin[embeddings]` | sentence-transformers | Neural semantic search |
| `pip install strucin[ai]` | all of the above | Full AI feature set |
| `pip install strucin[dev]` | pytest, ruff, mypy, coverage | Development tooling |

## Command Reference

### `init`

Scaffolds a `.strucin.toml` configuration file with commented defaults.

```bash
strucin init --path /path/to/repo
strucin init --path /path/to/repo --force  # overwrite existing
```

### `scan`

Recursively discovers Python files and writes repository index metadata.

```bash
python -m strucin.cli scan /path/to/repo
```

Primary output:
- `repo_index.json`

### `analyze`

Runs AST analysis, builds dependency graph, computes metrics, and detects cycles.

```bash
python -m strucin.cli analyze /path/to/repo
```

Primary outputs:
- `analysis.json`
- `dependency_graph.json`

### `report`

Generates Markdown architecture report from analysis results.

```bash
python -m strucin.cli report /path/to/repo
```

Primary output:
- `docs/REPORT.md`

### `search`

Builds or loads semantic index and returns top semantic matches.

```bash
python -m strucin.cli search "retry failed payment" --path /path/to/repo --top-k 5
```

Primary output:
- `semantic_index.json`

### `explain`

Generates architecture narration with cache support and metadata output.

```bash
python -m strucin.cli explain --path /path/to/repo
python -m strucin.cli explain --path /path/to/repo --refresh
```

Primary outputs:
- `docs/EXPLAIN.md`
- `explain.json`
- `.strucin_cache/explain_cache.json`

### `diff`

Compares two analysis snapshots and shows what changed: new/resolved cycles,
complexity delta, coupling shifts, and LOC changes.

```bash
strucin diff before.json after.json
strucin diff before.json after.json --json
```

### `web`

Generates interactive web dashboard assets and optionally serves locally.

```bash
python -m strucin.cli web --path /path/to/repo --out /path/to/repo/.strucin_web
python -m strucin.cli web --path /path/to/repo --serve --host 127.0.0.1 --port 8765
```

Primary outputs:
- `.strucin_web/index.html`
- `.strucin_web/app.js`
- `.strucin_web/styles.css`
- `.strucin_web/data.json`

## Configuration (`.strucin.toml`)

StrucIn reads `.strucin.toml` from the target repository root.

```toml
[scan]
exclude_dirs = [".git", "__pycache__", "node_modules", "venv", ".venv"]

[search]
top_k = 5
dimensions = 256

[performance]
max_workers = 8

[output]
repo_index = "repo_index.json"
analysis = "analysis.json"
dependency_graph = "dependency_graph.json"
report = "docs/REPORT.md"
semantic_index = "semantic_index.json"
explain_markdown = "docs/EXPLAIN.md"
explain_metadata = "explain.json"
```

Notes:
- `max_workers` controls parallel scanning/analysis/semantic indexing
- JSON artifacts are written to the target repo root; Markdown reports go to `docs/`

## Output Artifacts

| Artifact | Location | Description |
|----------|----------|-------------|
| `repo_index.json` | repo root | File/module map with LOC and size |
| `analysis.json` | repo root | Static analysis details and dependency graph |
| `dependency_graph.json` | repo root | Graph nodes/edges for integrations |
| `semantic_index.json` | repo root | Chunk embeddings and metadata |
| `explain.json` | repo root | Narration metadata (timestamp/cache key) |
| `REPORT.md` | `docs/` | Architecture summary and hotspots |
| `EXPLAIN.md` | `docs/` | Architecture narrative and onboarding guide |
| `.strucin_web/*` | repo root | Static dashboard files |

## GitHub Action

Run StrucIn in CI and post architecture reports as PR comments:

```yaml
- uses: macitch/StrucIn@main
  with:
    command: report
    post-comment: true
    fail-on-cycles: false
```

See `.github/workflows/example-usage.yml` for a full example with strict mode
and workflow dispatch support.

## Pre-commit Hooks

Add StrucIn checks to your `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/macitch/StrucIn
    rev: main
    hooks:
      - id: strucin-cycles        # fail on dependency cycles
      - id: strucin-complexity     # fail on high complexity
        args: ['--threshold', '15']
```

## Quality and Validation

Run project checks:

```bash
ruff check .
mypy src/strucin
pytest -q
```

## Web Dashboard Usage

Generate and serve:

```bash
python -m strucin.cli web --path . --serve --host 127.0.0.1 --port 8765
```

Open:

`http://127.0.0.1:8765/index.html`

## Examples

The `examples/` directory contains sample output artifacts generated by running
StrucIn on its own codebase, so you can see what you get before installing.

## Security

See [SECURITY.md](SECURITY.md) for the security policy, how StrucIn handles
your code, and how to report vulnerabilities.
