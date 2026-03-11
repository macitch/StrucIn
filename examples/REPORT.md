# StrucIn Architecture Report

## Summary
- Repository: `/path/to/strucin/src`
- Generated at: `2026-03-11T13:54:33.092692+00:00`
- StrucIn version: `0.1.0`
- Python files: **26**
- Modules: **26**
- Dependency edges: **49**
- Safe mode: **disabled**

## Top Hotspot Files (LOC x Fan-out)
- `strucin/cli/main.py`: score=8148 (loc=679, fan_out=12)
- `strucin/core/analyzer.py`: score=2004 (loc=334, fan_out=6)
- `strucin/core/explainer.py`: score=1266 (loc=422, fan_out=3)
- `strucin/core/reporter.py`: score=792 (loc=198, fan_out=4)
- `strucin/core/semantic.py`: score=732 (loc=366, fan_out=2)
- `strucin/cli/hooks.py`: score=618 (loc=206, fan_out=3)
- `strucin/core/diff.py`: score=437 (loc=437, fan_out=1)
- `strucin/web/dashboard.py`: score=396 (loc=132, fan_out=3)
- `strucin/core/import_resolver.py`: score=302 (loc=151, fan_out=2)
- `strucin/__init__.py`: score=294 (loc=49, fan_out=6)

## Largest Modules
- `strucin.cli.main`: 679 LOC
- `strucin.core.diff`: 437 LOC
- `strucin.core.explainer`: 422 LOC
- `strucin.core.semantic`: 366 LOC
- `strucin.core.analyzer`: 334 LOC
- `strucin.core.config`: 286 LOC
- `strucin.cli.hooks`: 206 LOC
- `strucin.core.reporter`: 198 LOC
- `strucin.core.import_resolver`: 151 LOC
- `strucin.web.dashboard`: 132 LOC

## Largest Packages
- `strucin`: 3942 LOC

## Most Imported Modules
- `strucin.core.analyzer`: fan_in=6
- `strucin.core.artifacts`: fan_in=6
- `strucin.core.config`: fan_in=5
- `strucin.core.indexer`: fan_in=5
- `strucin.core.models`: fan_in=4
- `strucin._version`: fan_in=3
- `strucin.core.explainer`: fan_in=3
- `strucin.exceptions`: fan_in=3
- `strucin.cli.ui`: fan_in=2
- `strucin.core.semantic`: fan_in=2

## Dependency Cycles
- None detected

## Refactor Suggestions
- `strucin`: High fan-out (6). Recommendation: Split orchestration from core logic and reduce direct dependencies.
- `strucin.cli.main`: High fan-out (12). Recommendation: Split orchestration from core logic and reduce direct dependencies.
- `strucin.cli.main`: High complexity (42). Recommendation: Extract branches into smaller pure functions with focused tests.
- `strucin.cli.main`: Large module (679 LOC). Recommendation: Split by responsibility into smaller modules within a package.
- `strucin.cli.main`: Missing module docstring. Recommendation: Add a top-level docstring to clarify module intent and boundaries.
- `strucin.cli.ui`: Missing module docstring. Recommendation: Add a top-level docstring to clarify module intent and boundaries.
- `strucin.core.analyzer`: High fan-out (6). Recommendation: Split orchestration from core logic and reduce direct dependencies.
- `strucin.core.analyzer`: High complexity (18). Recommendation: Extract branches into smaller pure functions with focused tests.
- `strucin.core.artifacts`: Missing module docstring. Recommendation: Add a top-level docstring to clarify module intent and boundaries.
- `strucin.core.config`: Missing module docstring. Recommendation: Add a top-level docstring to clarify module intent and boundaries.
- `strucin.core.diff`: High complexity (28). Recommendation: Extract branches into smaller pure functions with focused tests.
- `strucin.core.diff`: Large module (437 LOC). Recommendation: Split by responsibility into smaller modules within a package.
- `strucin.core.explainer`: High complexity (40). Recommendation: Extract branches into smaller pure functions with focused tests.
- `strucin.core.explainer`: Large module (422 LOC). Recommendation: Split by responsibility into smaller modules within a package.
- `strucin.core.explainer`: Missing module docstring. Recommendation: Add a top-level docstring to clarify module intent and boundaries.
- `strucin.core.import_resolver`: High complexity (24). Recommendation: Extract branches into smaller pure functions with focused tests.
- `strucin.core.indexer`: Missing module docstring. Recommendation: Add a top-level docstring to clarify module intent and boundaries.
- `strucin.core.lifecycle`: Missing module docstring. Recommendation: Add a top-level docstring to clarify module intent and boundaries.
- `strucin.core.metrics`: High complexity (17). Recommendation: Extract branches into smaller pure functions with focused tests.
- `strucin.core.reporter`: High complexity (26). Recommendation: Extract branches into smaller pure functions with focused tests.
