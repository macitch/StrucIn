# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
