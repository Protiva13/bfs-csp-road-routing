"""Baseline search contract, reusable by future constraint-aware planners."""
from collections import deque
from dataclasses import dataclass
from typing import Protocol
import math
import time
from .graph import Graph
from .constraints import RouteConstraints, edge_key


@dataclass(frozen=True)
class SearchResult:
    path: list[int] | None
    expanded_nodes: int
    discovered_nodes: int
    frontier_peak: int
    status: str | None = None

    @property
    def hops(self) -> int | None:
        return len(self.path) - 1 if self.path is not None else None


class Planner(Protocol):
    def __call__(self, graph: Graph, source: int, target: int) -> SearchResult: ...


def bfs(graph: Graph, source: int, target: int) -> SearchResult:
    if source not in graph.adjacency or target not in graph.adjacency:
        raise ValueError('Source and target must exist in the graph')
    frontier = deque([source])
    parent = {source: None}
    expanded, peak = 0, 1
    while frontier:
        node = frontier.popleft()
        expanded += 1
        if node == target:
            path = []
            while node is not None:
                path.append(node)
                node = parent[node]
            return SearchResult(path[::-1], expanded, len(parent), peak)
        for neighbor in graph.adjacency[node]:
            if neighbor not in parent:
                parent[neighbor] = node
                frontier.append(neighbor)
        peak = max(peak, len(frontier))
    return SearchResult(None, expanded, len(parent), peak)


def constrained_bfs(graph: Graph, source: int, target: int,
                    constraints: RouteConstraints, *, timeout_seconds: float | None = None,
                    max_expanded_states: int | None = None) -> SearchResult:
    """Shortest feasible walk over (node, waypoint-visited) states.

    Node revisits are allowed. First discovery of a state has minimum depth,
    so later arrivals at that same state cannot improve a maximum-hop budget.
    Metrics count states; at most two states per graph node are possible.
    """
    if timeout_seconds is not None and (not math.isfinite(timeout_seconds) or timeout_seconds <= 0):
        raise ValueError('timeout_seconds must be positive and finite')
    if max_expanded_states is not None and (type(max_expanded_states) is not int or max_expanded_states < 1):
        raise ValueError('max_expanded_states must be a positive integer')
    deadline = time.perf_counter() + timeout_seconds if timeout_seconds is not None else None
    if source not in graph.adjacency or target not in graph.adjacency:
        raise ValueError('Source and target must exist in the graph')
    constraints.validate_graph(graph)
    initial = (source, constraints.waypoint is None or source == constraints.waypoint)
    frontier = deque([(initial, 0)])
    parent = {initial: None}
    expanded, peak = 0, 1
    while frontier:
        if deadline is not None and time.perf_counter() >= deadline:
            return SearchResult(None, expanded, len(parent), peak, 'timeout')
        if max_expanded_states is not None and expanded >= max_expanded_states:
            return SearchResult(None, expanded, len(parent), peak, 'state_limit')
        state, depth = frontier.popleft()
        node, visited = state
        expanded += 1
        if node == target and visited:
            path = []
            while state is not None:
                path.append(state[0])
                state = parent[state]
            return SearchResult(path[::-1], expanded, len(parent), peak)
        if constraints.max_hops is not None and depth >= constraints.max_hops:
            continue
        for neighbor in graph.adjacency[node]:
            if deadline is not None and time.perf_counter() >= deadline:
                return SearchResult(None, expanded, len(parent), max(peak, len(frontier)), 'timeout')
            if edge_key(node, neighbor) in constraints.blocked_edges:
                continue
            next_state = (neighbor, visited or neighbor == constraints.waypoint)
            if next_state not in parent:
                parent[next_state] = state
                frontier.append((next_state, depth + 1))
        peak = max(peak, len(frontier))
    return SearchResult(None, expanded, len(parent), peak)
