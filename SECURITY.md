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

### LLM Integration (Optional)

When using the `explain` command with an API key:

- A **limited context** (max 12,000 characters) of structural metadata is sent to the configured LLM provider (Anthropic or OpenAI).
- **Secret redaction** is applied before any LLM call — 9 regex patterns strip passwords, API keys, tokens, private keys, and credential URLs from the payload.
- No source code is sent — only module names, metrics, and docstrings.
- LLM calls are opt-in and require explicit API key configuration.

### Safe Mode

Enable `safe_mode = true` in `.strucin.toml` or pass `--safe-mode` to redact module and package names from all output artifacts.

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
