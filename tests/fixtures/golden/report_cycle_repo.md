# StrucIn Architecture Report

## Summary
- Repository: `/repo`
- Generated at: `2026-01-01T00:00:00+00:00`
- StrucIn version: `0.1.0`
- Python files: **3**
- Modules: **3**
- Dependency edges: **2**
- Safe mode: **disabled**

## Top Hotspot Files (LOC x Fan-out)
- `pkg/a.py`: score=7 (loc=7, fan_out=1)
- `pkg/b.py`: score=6 (loc=6, fan_out=1)
- `pkg/__init__.py`: score=0 (loc=0, fan_out=0)

## Largest Modules
- `pkg.a`: 7 LOC
- `pkg.b`: 6 LOC
- `pkg`: 0 LOC

## Largest Packages
- `pkg`: 13 LOC

## Most Imported Modules
- `pkg.a`: fan_in=1
- `pkg.b`: fan_in=1
- `pkg`: fan_in=0

## Dependency Cycles
- `pkg.a` -> `pkg.b`

## Refactor Suggestions
- `dependency graph`: Detected 1 dependency cycle(s). Recommendation: Break cycle edges with interfaces or inversion of control (example: pkg.a -> pkg.b).
