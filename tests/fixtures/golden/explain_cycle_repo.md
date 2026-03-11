# StrucIn Architecture Narration

## System Overview
This repository contains **3 Python files** and **3 modules** connected by **2 internal dependencies**.
Safe mode is **disabled**.
There are **1 dependency cycle(s)** that should be prioritized.

## Module Summaries
### Top Hotspots
- `pkg.a` (pkg/a.py): hotspot=7, loc=7, fan_out=1, complexity=2
  docstring: Module A.
- `pkg.b` (pkg/b.py): hotspot=6, loc=6, fan_out=1, complexity=1
  docstring: Module B.
- `pkg` (pkg/__init__.py): hotspot=0, loc=0, fan_out=0, complexity=1

### Largest Modules
- `pkg.a`: loc=7, fan_in=1, fan_out=1
- `pkg.b`: loc=6, fan_in=1, fan_out=1
- `pkg`: loc=0, fan_in=0, fan_out=0

### Most Imported Modules
- `pkg.a`: fan_in=1
- `pkg.b`: fan_in=1
- `pkg`: fan_in=0

## Cycle Explanations
- Cycle: `pkg.a` -> `pkg.b`
  Impact: increases coupling and test setup overhead; changes ripple across modules.
  Suggested break: extract shared interfaces or move shared logic to a lower-level module.

## Onboarding Guide
1. Run `strucin scan <repo>` to baseline repository structure.
2. Run `strucin analyze <repo>` to inspect dependencies and metrics.
3. Review hotspot `pkg.a` first (loc=7, fan_out=1).
4. Review hotspot `pkg.b` first (loc=6, fan_out=1).
5. Review hotspot `pkg` first (loc=0, fan_out=0).
6. Map inbound dependents around central modules: `pkg.a`, `pkg.b`, `pkg`.
7. Resolve 1 dependency cycle(s) early.
