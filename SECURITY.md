# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 0.1.x   | Yes                |

## How StrucIn Handles Your Code

StrucIn performs **read-only static analysis** on your repository:

- It reads Python files and parses their AST — it never executes your code.
- Analysis artifacts (JSON, Markdown) are written to the target repository directory.
- Cache files are stored in `.strucin_cache/` within the target repository.

### Source and Documentation Links

Python and documentation discovery skips file links that resolve outside the
selected repository, dangling links, symlink loops, and non-regular files.
Links to regular files inside the repository remain supported, with their
repository-relative link paths preserved in analysis and search results.
Directory links are not traversed during discovery.

Containment is rechecked whenever source or documentation bytes are read. On
platforms supporting descriptor-relative opens and `O_NOFOLLOW`, path components
are opened without following links to reject replacements between validation and
reading. Other platforms use the validated canonical path. A file that becomes
unsafe after discovery aborts that run instead of contributing outside content.

Search indexes produced before this policy are rebuilt by the CLI. Existing
exports are not retroactively scrubbed; regenerate any previously shared analysis,
reports, or indexes that may have included outside links.

### Artifact Destinations

Configured outputs and automatic caches must stay within the target repository.
Parent-directory segments (`..`) and symlinks that resolve outside that directory
are rejected before writing or cleaning up artifacts. All configured destinations
are checked before cleanup deletes any stale files.

The explicit `web --out /path/to/export` option selects a separate dashboard output
directory. Generated dashboard files are confined to that selected directory.

### LLM Integration (Optional)

When using the `explain` command with an API key:

- A **limited context** (max 12,000 characters) of structural metadata is sent to the configured LLM provider (Anthropic or OpenAI).
- **Secret redaction** is applied before any LLM call — 9 regex patterns strip passwords, API keys, tokens, private keys, and credential URLs from the payload.
- No source code is sent — only module names, metrics, and docstrings.
- LLM calls are opt-in and require explicit API key configuration.

### Safe Mode

Enable safe mode for a repository with:

```toml
[security]
safe_mode = true
```

`scan`, `analyze`, `report`, `explain`, `search`, and `web` honor this setting.
Each also accepts `--safe-mode` or `--no-safe-mode` to override it for one run.
Pre-commit hooks honor the repository setting. `diff` operates on snapshots
without loading repository configuration; use `diff --safe-mode` explicitly.

In safe mode:

- Generated index, analysis, graph, report, narration metadata, and dashboard
  contents hide repository paths, file paths, module/package names, import names,
  and class/function names. Graph relationships and numeric metrics remain.
- All docstrings and source snippets are omitted from shareable data. LLM context
  is anonymized **before** the provider call, including the repository root.
  Known identifiers and recognized secret patterns are filtered again from
  provider responses and cached narration before writing or returning them.
- Raw analysis caches are neither read nor written. Narration uses a separate
  `.strucin_cache/explain_safe_cache.json` containing filtered content. Normal
  explanation caches are never reused by safe mode.
- Search rebuilds its index in memory on every run, without reading or writing
  `semantic_index.json`. Results retain scores and line numbers with anonymous
  labels; source text and the query are omitted from displayed output.

Anonymous labels are scoped to an export and can change when the file set changes.
For accurate comparisons, run `diff --safe-mode` on the original snapshots so
matching happens before anonymization.

Safe mode governs newly generated content; it does not retroactively scrub older
artifacts or caches. Existing retention cleanup still applies. Output filenames,
configuration files, and diagnostic errors are not anonymized, so share the
intended generated artifacts rather than the entire working directory or logs.
Structural metrics and graph topology remain visible.

Library callers must pass `safe_mode=True` to the relevant output writer,
report generator, explainer, or dashboard builder. Raw `analyze_repository` results
remain in memory with original names; use `use_cache=False` to prevent raw cache
reads and writes. The low-level semantic index writer persists source text and
should not be used for a safe export.

## Reporting a Vulnerability

If you discover a security vulnerability in StrucIn, please report it responsibly:

1. **Do not** open a public GitHub issue.
2. Email **contact@macitch.dev** with:
   - A description of the vulnerability
   - Steps to reproduce
   - Affected version(s)
3. You will receive an acknowledgment within 48 hours.
4. A fix will be prioritized and released as a patch version.

## Scope

The following are in scope for security reports:

- Secret leakage through LLM calls or output artifacts
- Path traversal in file scanning or artifact writing
- Code execution through crafted Python files (AST parsing should never execute code)
- Dependency vulnerabilities in core dependencies

The following are out of scope:

- Denial of service through extremely large repositories (expected behavior)
- Issues requiring physical access to the machine running StrucIn
