"""Shared route semantics for constrained BFS and CSP."""
from dataclasses import dataclass
from .graph import Graph


def edge_key(u: int, v: int) -> tuple[int, int]:
    return (min(u, v), max(u, v))


@dataclass(frozen=True)
class RouteConstraints:
    blocked_edges: frozenset[tuple[int, int]] = frozenset()
    waypoint: int | None = None
    max_hops: int | None = None

    def __post_init__(self):
        if self.max_hops is not None and (type(self.max_hops) is not int or self.max_hops < 0):
            raise ValueError('max_hops must be a nonnegative integer or null')
        if self.waypoint is not None and (type(self.waypoint) is not int or self.waypoint < 0):
            raise ValueError('waypoint must be a nonnegative integer or null')
        normalized = set()
        for edge in self.blocked_edges:
            if not isinstance(edge, (list, tuple)) or len(edge) != 2:
                raise ValueError('Each blocked edge must contain two node IDs')
            if any(type(node) is not int or node < 0 for node in edge):
                raise ValueError('Blocked edge IDs must be nonnegative integers')
            normalized.add(edge_key(*edge))
        object.__setattr__(self, 'blocked_edges', frozenset(normalized))

    @classmethod
    def from_dict(cls, data: dict) -> 'RouteConstraints':
        if not isinstance(data, dict):
            raise ValueError('Constraints must be a JSON object')
        unknown = set(data) - {'blocked_edges', 'waypoint', 'max_hops'}
        if unknown:
            raise ValueError(f'Unknown constraint fields: {sorted(unknown)}')
        edges = data.get('blocked_edges', [])
        if not isinstance(edges, list):
            raise ValueError('blocked_edges must be a list of node pairs')
        return cls(edges, data.get('waypoint'), data.get('max_hops'))

    def to_dict(self) -> dict:
        return {'blocked_edges': [list(edge) for edge in sorted(self.blocked_edges)],
                'waypoint': self.waypoint, 'max_hops': self.max_hops}

    def validate_graph(self, graph: Graph) -> None:
        if self.waypoint is not None and self.waypoint not in graph.adjacency:
            raise ValueError(f'Unknown waypoint: {self.waypoint}')
        for u, v in self.blocked_edges:
            if u not in graph.adjacency or v not in graph.adjacency[u]:
                raise ValueError(f'Blocked road does not exist: {u}, {v}')


def validate_route(graph: Graph, path: list[int], source: int, target: int,
                   constraints: RouteConstraints) -> None:
    """Independently check a returned walk; raise ValueError on any violation."""
    constraints.validate_graph(graph)
    if not path or path[0] != source or path[-1] != target:
        raise ValueError('Route endpoints do not match the query')
    if any(node not in graph.adjacency for node in path):
        raise ValueError('Route contains an unknown node')
    for u, v in zip(path, path[1:]):
        if v not in graph.adjacency[u]:
            raise ValueError('Route contains a nonexistent road')
        if edge_key(u, v) in constraints.blocked_edges:
            raise ValueError('Route uses a blocked road')
    if constraints.waypoint is not None and constraints.waypoint not in path:
        raise ValueError('Route does not visit the waypoint')
    if constraints.max_hops is not None and len(path) - 1 > constraints.max_hops:
        raise ValueError('Route exceeds the hop budget')
