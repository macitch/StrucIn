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
pip install -e ".[dev]"
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
strucin explain --path /path/to/myrepo  # writes docs/EXPLAIN.md (template, no key needed)

# Enable LLM-powered narration
pip install -e ".[llm]"
export ANTHROPIC_API_KEY="sk-ant-..."
strucin explain --path /path/to/myrepo  # writes docs/EXPLAIN.md

# Semantic search
strucin search "authentication middleware" --path /path/to/myrepo

# Compare two analysis snapshots
strucin diff before.json after.json

# Machine-readable output
strucin analyze /path/to/myrepo --json

# Launch web dashboard
strucin web --path /path/to/myrepo
```

With `--json`, `scan`, `analyze`, `search`, and `diff` write one JSON document to
stdout on success. Progress, timing summaries, warnings, and errors go to stderr.
Check the exit status before consuming the result; failed commands return a
nonzero status. For example:

```bash
strucin analyze /path/to/myrepo --json > analysis-summary.json
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

Builds or reuses a current semantic index and returns top semantic matches.

```bash
python -m strucin.cli search "retry failed payment" --path /path/to/repo --top-k 5
python -m strucin.cli search "retry failed payment" --path /path/to/repo --refresh
```

Search checks the contents and paths of eligible Python and documentation files
on every run. Edits, additions, deletions, renames, source-root mappings, excluded
directories, and embedding model/dimension settings invalidate the saved index.
Unchanged inputs reuse their existing embeddings; changing the query, result
limit, worker count, or timing settings does not require rebuilding them. Older
indexes without a content fingerprint are rebuilt automatically.

Use `--refresh` to bypass the saved index and regenerate embeddings, including
after installing a previously unavailable neural model. The fingerprint tracks
the requested model settings separately from the actual model used, so a hashing
fallback or a neural model's fixed vector width does not cause repeated rebuilds.
Safe mode continues to build in memory without reading or writing the saved index.

Queries must use the same embedding model and vector width as the index. If a
saved neural index's model becomes unavailable, search stops with an error
before scoring. Restore that model and its dependencies, or set
`embedding_model = "hashing-v1"` under `[search]` in `.strucin.toml` and rerun
with `--refresh` to rebuild all vectors. Building a new index can still fall
back to hashing when a neural model cannot load; the index records the actual
model used so subsequent queries use that same model.

Library callers can pass `cached_index=` to `build_semantic_index` to request the
same freshness check; omitting it always builds a new index.

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

Analysis and narration caches are disposable. Unreadable or malformed cache
files and invalid entries are skipped with a warning, then recomputed. Valid
entries can still be reused. `explain --refresh` bypasses the narration cache
read and replaces it with the newly generated entry.

Cache updates use a temporary file in the same directory and atomic replacement,
so readers see a complete old or new file. If cache persistence fails, the
computed analysis or narration is still returned with a warning. Required output
artifacts and path-containment errors continue to fail the command. These rules
also apply to the separate safe-mode narration cache; safe mode still skips raw
analysis caches.

### `diff`

Compares two analysis snapshots and shows what changed: new/resolved cycles,
complexity delta, coupling shifts, and LOC changes.

```bash
strucin diff before.json after.json
strucin diff before.json after.json --json
```

The summary's total LOC delta includes added modules, removed modules, and LOC
changes in retained modules. For example, adding 100 lines, removing 40, and
adding 10 to an existing module reports a net change of +70 lines.

`files_changed` counts added and removed modules plus retained modules with a
reported LOC, complexity, or coupling change, counting each module once. Coupling
changes are reported when fan-in or fan-out changes by at least 2. A module rename
counts as one removal and one addition. Detailed metric-change lists compare
modules present in both snapshots; additions and removals have their own lists.

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
- By default, JSON artifacts are written to the target repo root; Markdown reports go to `docs/`

Each output can use an independent nested path within the repository, such as
`dependency_graph = "graphs/nested/dependencies.json"` or
`explain_metadata = "metadata/narration/details.json"`. Commands validate output
paths before creating their parent directories. `analyze` and `explain` prepare
both output parents before writing either result, so a directory-creation error
does not overwrite one result while leaving the other unwritten.

## Source Roots

StrucIn keeps repository-relative file paths separate from Python import names:
`src/pkg/service.py` is recorded at that path with module name `pkg.service`.
Flat layouts and namespace packages are supported. Source roots are selected in
this order:

1. Repeated `--source-root DIR` options for the current command.
2. `[scan] source_roots` in `.strucin.toml`.
3. Static packaging metadata: setuptools `package-dir` / `packages.find.where`
   in `pyproject.toml`, Poetry `packages[].from`, or setuptools `package_dir` /
   `options.packages.find.where` in `setup.cfg`.
4. A top-level `src/` directory without `src/__init__.py`, then the repository root.

```toml
[scan]
source_roots = ["src", "components/shared/python"]
```

```bash
strucin analyze /path/to/repo --source-root src --source-root components/shared/python
strucin-check-cycles /path/to/repo --source-root src
```

The override is available on `scan`, `analyze`, `report`, `explain`, `search`,
`web`, and both pre-commit hooks. Library entry points accept `source_roots=`;
pass repository configuration explicitly, as with other library options.
Use `["."]` (or `--source-root .`) to retain repository-relative import names
and disable automatic discovery. Paths must name existing directories inside
the repository; absolute paths and `..` are rejected.

Nested roots take precedence over their parents. Named setuptools package
mappings preserve the configured package prefix. Files outside configured roots,
such as tests and scripts, retain repository-relative module names. Conflicting
files with the same import name cause a clear error; adjust the roots or exclude
the duplicate directory. StrucIn reads metadata without running `setup.py` or
importing the project. For dynamic build configuration or other packaging tools,
set the roots explicitly.

Analysis caches recheck module identities, and search rebuilds older indexes or
indexes created with different source-root mappings. Existing snapshots keep
their original module names; regenerate them before comparing layouts across
this change.

Packaging conventions: [setuptools package discovery](https://setuptools.pypa.io/en/latest/userguide/package_discovery.html)
and [Poetry packages](https://python-poetry.org/docs/pyproject/#packages).

## Safe Mode

For shareable output, set `[security] safe_mode = true` in `.strucin.toml`, or
pass `--safe-mode` to `scan`, `analyze`, `report`, `explain`, `search`, or `web`:

```bash
strucin analyze /path/to/repo --safe-mode
strucin explain --path /path/to/repo --safe-mode
strucin web --path /path/to/repo --safe-mode
strucin diff before.json after.json --safe-mode
```

Safe mode anonymizes names and paths in generated content and LLM context,
omits docstrings/source snippets, skips raw analysis caches, and keeps a separate
safe narration cache. Search uses an in-memory index and anonymous results.
`--no-safe-mode` overrides the repository setting for one run.

Existing artifacts are not retroactively scrubbed. Anonymous labels are local to
an export; compare original snapshots with `diff --safe-mode`. See
[SECURITY.md](SECURITY.md#safe-mode) for the full contract and library usage.

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

Every Action command (`scan`, `analyze`, or `report`) produces fresh analysis
and dependency graph JSON at the locations configured in `.strucin.toml`.
The cycle decision uses that run's in-memory analysis. `report` renders the same
result; stale or malformed snapshots from earlier runs cannot change the gate.
Analysis or artifact-writing errors fail the Action even in advisory mode.

Set `fail-on-cycles: 'true'` to fail when the current analysis contains cycles.
`safe-mode: 'true'` anonymizes artifacts and preserves cycle enforcement; it does
not suppress errors. With the input left false, the repository's safe-mode
configuration still applies.

The Action exposes `analysis-path`, `cycles-found`, `cycle-count`, and
`report-path`. Outputs are set after artifact generation succeeds, including when
the cycle gate subsequently fails. A failure before completion leaves the cycle
result unset, rather than reporting false. `report-path` is empty for `scan` and
`analyze`; old reports are never reused for comments or uploads. Reports from
strict cycle failures are still uploaded and can be posted to the PR when enabled.

See `.github/workflows/example-usage.yml` for a full example with strict mode
and workflow dispatch support. `.github/workflows/action-test.yml` checks the
composite Action against cyclic and acyclic fixtures for all three commands.

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

## Complexity Scoring

StrucIn calculates an AST-based complexity score as **1 plus decision points**:

| Construct | Added points |
|-----------|--------------|
| `if`, `elif`, conditional expression (`x if condition else y`) | 1 each |
| `for`, `async for`, `while` | 1 each |
| `except` or `except*` handler | 1 per handler |
| `assert` | 1 each |
| Boolean `and` / `or` | 1 per operator; six operands add 5 |
| Comprehension | 1 per `for` generator plus 1 per `if` filter |
| Refutable `match` case | 1 per case |
| `match` guard (`case ... if condition`) | 1 per guard, plus boolean operators in it |

An unconditional wildcard or capture case adds no point; a guarded one adds its
guard's points. Aliases preserve the underlying pattern's behavior. An OR pattern
counts as a single case, and is unconditional if an alternative is unconditional.
`try`, `else`, `finally`, context managers, and ordinary expressions add no points
of their own; decisions inside them still count.

For example, `return a and b and c and d and e and f` scores **6**. A `match`
with three literal cases and one unconditional wildcard scores **4**.

File and function scores aggregate decisions across their entire AST, including
nested definitions. Each score starts with one base point; the file score is
not the sum of function scores. The complexity hook applies its threshold to
**file/module scores**, and fails only when a score exceeds the threshold.

The corrected rules invalidate older analysis caches automatically. Regenerate
saved analysis snapshots before comparing complexity across this change; the
new rules can raise or lower scores without source edits.

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

Source and documentation file links must resolve to regular files inside the
repository. External, dangling, and looping links are skipped; directory links
are not traversed. Older search indexes are rebuilt to apply these read rules.

See [SECURITY.md](SECURITY.md) for the security policy, how StrucIn handles
your code, and how to report vulnerabilities.
