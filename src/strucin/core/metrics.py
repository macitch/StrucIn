"""Graph metrics and cycle detection for the dependency graph.

Cycle detection uses Tarjan's strongly connected components (SCC) algorithm,
which runs in O(V + E) time.  A component is reported as a cycle when it
contains more than one node, or when it is a single node with a self-loop
(a module that imports itself).

The implementation is **iterative** (uses an explicit work-stack) rather than
recursive, so it never hits Python's default recursion limit even on
repositories with thousands of mutually-importing modules.

Reference: Tarjan, R. E. (1972). Depth-first search and linear graph
algorithms. SIAM Journal on Computing, 1(2), 146–160.
"""

from __future__ import annotations

from collections import defaultdict

from strucin.core.models import DependencyEdge


def build_adjacency(edges: list[DependencyEdge]) -> dict[str, set[str]]:
    """Return a source → {targets} adjacency mapping from a list of edges."""
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        adjacency[edge.source].add(edge.target)
    return adjacency


def detect_cycles(nodes: list[str], adjacency: dict[str, set[str]]) -> list[list[str]]:  # noqa: C901
    """Return all dependency cycles using Tarjan's SCC algorithm (iterative).

    The algorithm is implemented iteratively using an explicit work-stack to
    avoid Python's default recursion limit, which would cause ``RecursionError``
    on repositories with dependency chains longer than ~1 000 modules.

    Algorithm phases per node:
    1. Assign a discovery index and lowlink value; push onto the SCC stack.
    2. Advance through sorted neighbours via a persistent iterator, updating
       lowlink for unvisited neighbours (recurse) and stack-resident ones.
    3. When all neighbours are exhausted (``StopIteration``), propagate lowlink
       to the parent and, if this node is an SCC root, pop the component.

    Results are sorted by (length, members) for deterministic output.
    """
    index_counter = [0]
    index_map: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    scc_stack: list[str] = []
    on_scc_stack: set[str] = set()
    all_sccs: list[list[str]] = []

    for start in nodes:
        if start in index_map:
            continue

        # work_stack entries: (node, neighbour_iterator)
        work_stack: list[tuple[str, object]] = []

        def _push(node: str, _ws: list[tuple[str, object]] = work_stack) -> None:
            index_map[node] = index_counter[0]
            lowlink[node] = index_counter[0]
            index_counter[0] += 1
            scc_stack.append(node)
            on_scc_stack.add(node)
            _ws.append((node, iter(sorted(adjacency.get(node, set())))))

        _push(start)

        while work_stack:
            node, neighbours = work_stack[-1]
            try:
                neighbour = next(neighbours)  # type: ignore[call-overload]
                if neighbour not in index_map:
                    _push(neighbour)
                elif neighbour in on_scc_stack:
                    lowlink[node] = min(lowlink[node], index_map[neighbour])
            except StopIteration:
                work_stack.pop()
                if work_stack:
                    parent = work_stack[-1][0]
                    lowlink[parent] = min(lowlink[parent], lowlink[node])
                if lowlink[node] == index_map[node]:
                    component: list[str] = []
                    while scc_stack:
                        member = scc_stack.pop()
                        on_scc_stack.remove(member)
                        component.append(member)
                        if member == node:
                            break
                    component.sort()
                    all_sccs.append(component)

    cycles: list[list[str]] = []
    for component in all_sccs:
        if len(component) > 1:
            cycles.append(component)
            continue
        single = component[0]
        if single in adjacency.get(single, set()):
            cycles.append(component)
    return sorted(cycles, key=lambda cycle: (len(cycle), cycle))


def compute_fan_metrics(
    nodes: list[str],
    edges: list[DependencyEdge],
    adjacency: dict[str, set[str]],
) -> tuple[dict[str, int], dict[str, int]]:
    """Return ``(fan_in, fan_out)`` dicts keyed by module path.

    fan_out[m] = number of distinct internal modules *m* imports.
    fan_in[m]  = number of distinct internal modules that import *m*.
    """
    fan_out: dict[str, int] = {node: len(adjacency.get(node, set())) for node in nodes}
    fan_in: dict[str, int] = {node: 0 for node in nodes}
    for edge in edges:
        fan_in[edge.target] += 1
    return fan_in, fan_out
