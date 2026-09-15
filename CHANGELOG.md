# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Raise security minimums for Pygments, setuptools, PyTorch, and pytest; audit resolved base, optional AI, development, and build dependencies in CI, including explicit direct minimum versions. Neural embedding extras now require PyTorch 2.13+ (Apple Silicon/macOS 14+ for macOS wheels).
- Include CLI commands and the module entry point in coverage, with regression tests for startup, invalid inputs, empty search results, and dashboard server shutdown.
- Correct complexity scores for boolean operators, match cases/guards, comprehensions, assertions, and exception handlers; document the rules and invalidate analysis caches computed with the previous rules.
- Correct README quickstart paths for `explain` and `web`, and include the required development and narration dependencies in setup examples.
- Create dependency-graph and narration-metadata parent directories before writing either command's output artifacts, supporting independent nested output paths.
- Include added and removed modules in diff LOC totals and changed-file counts, counting each affected module once.
- Reject search queries whose embedding model differs from the index, even when vector dimensions match, with instructions to restore the model or rebuild with hashing.
- Recover from unreadable or invalid analysis/narration caches, validate cached entries, and replace cache files atomically; narration refresh bypasses old cache reads.
- Refresh semantic indexes when indexed files or embedding settings change, and add `search --refresh` for forced rebuilds.
- Keep `--json` stdout parseable by routing progress and timing summaries to stderr.
- Confine configured artifacts, automatic caches, and cleanup to the selected output directory.
- Apply safe mode across generated artifacts, search results, dashboards, LLM context, and caches.
- Resolve Python import names from source roots and packaging metadata so src layouts produce correct dependency graphs and cycle checks.
- Use fresh analysis for every GitHub Action command and cycle gate, honor configured output paths, and preserve reports when strict cycle checks fail.
- Skip external, broken, looping, and non-regular source/document links; revalidate reads and rebuild older search indexes under the new file policy.

## [0.1.0] - 2025-02-25

### Added
- Repository indexing with module mapping and file metadata
- Static AST analysis (imports, classes, functions, docstrings, cyclomatic complexity)
- Dependency graph and cycle detection
- Architecture report (`REPORT.md`) generation
- Semantic code/document search with hashing fallback and sentence-transformers support
- Architecture narration (`EXPLAIN.md`) via Anthropic/OpenAI or template fallback
- LLM output caching with SHA-256 cache keys and `--refresh` flag
- Secret redaction before sending any content to LLMs
- Interactive web dashboard for dependency exploration
- CLI with `scan`, `analyze`, `report`, `embed`, `search`, `explain`, `web` subcommands
- Config file support (`.strucin.toml`) for model selection and search tuning
- GitHub Actions CI: lint (ruff), typecheck (mypy), test matrix (Python 3.11, 3.12)
- 90%+ test coverage with mock-based tests for LLM and embedding code paths
