from __future__ import annotations

from strucin.core.metrics import build_adjacency, compute_fan_metrics, detect_cycles
from strucin.core.models import DependencyEdge

# ---------------------------------------------------------------------------
# detect_cycles
# ---------------------------------------------------------------------------


def test_detect_cycles_empty_graph() -> None:
    assert detect_cycles([], {}) == []


def test_detect_cycles_single_node_no_edges() -> None:
    assert detect_cycles(["a"], {}) == []


def test_detect_cycles_self_loop() -> None:
    """A module that imports itself is reported as a cycle."""
    edges = [DependencyEdge(source="a", target="a")]
    adjacency = build_adjacency(edges)
    cycles = detect_cycles(["a"], adjacency)
    assert cycles == [["a"]]


def test_detect_cycles_two_node_cycle() -> None:
    edges = [
        DependencyEdge(source="a", target="b"),
        DependencyEdge(source="b", target="a"),
    ]
    adjacency = build_adjacency(edges)
    cycles = detect_cycles(["a", "b"], adjacency)
    assert len(cycles) == 1
    assert set(cycles[0]) == {"a", "b"}


def test_detect_cycles_three_node_cycle() -> None:
    edges = [
        DependencyEdge(source="a", target="b"),
        DependencyEdge(source="b", target="c"),
        DependencyEdge(source="c", target="a"),
    ]
    adjacency = build_adjacency(edges)
    cycles = detect_cycles(["a", "b", "c"], adjacency)
    assert len(cycles) == 1
    assert set(cycles[0]) == {"a", "b", "c"}


def test_detect_cycles_two_independent_cycles() -> None:
    edges = [
        DependencyEdge(source="a", target="b"),
        DependencyEdge(source="b", target="a"),
        DependencyEdge(source="x", target="y"),
        DependencyEdge(source="y", target="x"),
    ]
    adjacency = build_adjacency(edges)
    cycles = detect_cycles(["a", "b", "x", "y"], adjacency)
    assert len(cycles) == 2
    cycle_sets = {frozenset(c) for c in cycles}
    assert frozenset({"a", "b"}) in cycle_sets
    assert frozenset({"x", "y"}) in cycle_sets


def test_detect_cycles_dag_has_no_cycles() -> None:
    """A directed acyclic graph must produce no cycles."""
    edges = [
        DependencyEdge(source="a", target="b"),
        DependencyEdge(source="b", target="c"),
    ]
    adjacency = build_adjacency(edges)
    assert detect_cycles(["a", "b", "c"], adjacency) == []


def test_detect_cycles_is_deterministic() -> None:
    """Calling detect_cycles twice on identical input returns the same result."""
    edges = [
        DependencyEdge(source="a", target="b"),
        DependencyEdge(source="b", target="a"),
    ]
    adjacency = build_adjacency(edges)
    nodes = ["a", "b"]
    assert detect_cycles(nodes, adjacency) == detect_cycles(nodes, adjacency)


def test_detect_cycles_disconnected_node_not_in_cycle() -> None:
    """A node with no edges is not reported as a cycle."""
    edges = [
        DependencyEdge(source="a", target="b"),
        DependencyEdge(source="b", target="a"),
    ]
    adjacency = build_adjacency(edges)
    cycles = detect_cycles(["a", "b", "isolated"], adjacency)
    for cycle in cycles:
        assert "isolated" not in cycle


def test_detect_cycles_deep_chain_does_not_raise() -> None:
    """Iterative Tarjan must not hit Python's recursion limit on a 2000-node chain."""
    n = 2000
    nodes = [f"m{i}" for i in range(n)]
    # Linear chain: m0 -> m1 -> ... -> m1999 (no cycle)
    edges = [DependencyEdge(source=f"m{i}", target=f"m{i + 1}") for i in range(n - 1)]
    adjacency = build_adjacency(edges)
    cycles = detect_cycles(nodes, adjacency)
    assert cycles == []


# ---------------------------------------------------------------------------
# compute_fan_metrics
# ---------------------------------------------------------------------------


def test_compute_fan_metrics_no_edges() -> None:
    fan_in, fan_out = compute_fan_metrics(["a", "b"], [], {})
    assert fan_in == {"a": 0, "b": 0}
    assert fan_out == {"a": 0, "b": 0}


def test_compute_fan_metrics_fan_in() -> None:
    """A node imported by 3 others has fan_in=3."""
    edges = [
        DependencyEdge(source="a", target="c"),
        DependencyEdge(source="b", target="c"),
        DependencyEdge(source="d", target="c"),
    ]
    adjacency = build_adjacency(edges)
    fan_in, _ = compute_fan_metrics(["a", "b", "c", "d"], edges, adjacency)
    assert fan_in["c"] == 3
    assert fan_in["a"] == 0


def test_compute_fan_metrics_fan_out() -> None:
    """A node that imports 2 others has fan_out=2."""
    edges = [
        DependencyEdge(source="a", target="b"),
        DependencyEdge(source="a", target="c"),
    ]
    adjacency = build_adjacency(edges)
    _, fan_out = compute_fan_metrics(["a", "b", "c"], edges, adjacency)
    assert fan_out["a"] == 2
    assert fan_out["b"] == 0
    assert fan_out["c"] == 0


def test_compute_fan_metrics_cycle_counts_both_directions() -> None:
    edges = [
        DependencyEdge(source="a", target="b"),
        DependencyEdge(source="b", target="a"),
    ]
    adjacency = build_adjacency(edges)
    fan_in, fan_out = compute_fan_metrics(["a", "b"], edges, adjacency)
    assert fan_in["a"] == 1
    assert fan_in["b"] == 1
    assert fan_out["a"] == 1
    assert fan_out["b"] == 1
