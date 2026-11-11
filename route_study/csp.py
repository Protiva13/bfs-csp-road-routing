"""Finite-domain route CSP: position variables, AC-3, and MRV backtracking.

Try exact lengths in increasing order. Domains contain graph node IDs;
binary constraints require adjacent unblocked roads, and a global occurrence
constraint requires the waypoint in at least one position. No AllDifferent
constraint is used: repeated junctions are allowed.
"""
from collections import deque
from dataclasses import dataclass
import time
from .constraints import RouteConstraints, edge_key
from .graph import Graph


@dataclass(frozen=True)
class CspOptions:
    max_hops: int = 20
    max_nodes: int = 5000
    max_assignments: int = 100000
    timeout_seconds: float = 10.0

    def __post_init__(self):
        if type(self.max_hops) is not int or not 0 <= self.max_hops <= 128:
            raise ValueError('CSP max_hops must be an integer from 0 through 128')
        for name in ('max_nodes', 'max_assignments'):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f'CSP {name} must be a positive integer')
        if not 0 < self.timeout_seconds < float('inf'):
            raise ValueError('CSP timeout_seconds must be positive and finite')


@dataclass(frozen=True)
class CspResult:
    path: list[int] | None
    status: str
    effective_max_hops: int
    complete_for_constraints: bool
    candidate_nodes: int
    lengths_attempted: int
    assignments_tried: int
    arc_revisions: int
    values_pruned: int

    @property
    def hops(self):
        return None if self.path is None else len(self.path) - 1


class _LimitReached(Exception):
    pass


def csp_route(graph: Graph, source: int, target: int, constraints: RouteConstraints,
              options: CspOptions = CspOptions()) -> CspResult:
    if source not in graph.adjacency or target not in graph.adjacency:
        raise ValueError('Source and target must exist in the graph')
    constraints.validate_graph(graph)
    bound = min(options.max_hops, constraints.max_hops) if constraints.max_hops is not None else options.max_hops
    # A shortest feasible walk has no repeated (node, waypoint-seen) state.
    universal_bound = len(graph.adjacency) * (2 if constraints.waypoint is not None else 1) - 1
    complete = bound >= (constraints.max_hops if constraints.max_hops is not None else universal_bound)
    deadline = time.perf_counter() + options.timeout_seconds
    stats = {'candidate_nodes': 1, 'lengths_attempted': 0, 'assignments_tried': 0,
             'arc_revisions': 0, 'values_pruned': 0}

    def check_time():
        if time.perf_counter() >= deadline:
            raise _LimitReached('timeout')

    def result(path, status):
        return CspResult(path, status, bound, complete, **stats)

    def allowed(u, v):
        return edge_key(u, v) not in constraints.blocked_edges

    try:
        # Include EVERY node reachable within the bound, not an arbitrary sample.
        # Thus every feasible walk within the bound lies in this candidate set.
        distances = {source: 0}
        queue = deque([source])
        while queue:
            check_time()
            u = queue.popleft()
            if distances[u] >= bound:
                continue
            for v in graph.adjacency[u]:
                check_time()
                if allowed(u, v) and v not in distances:
                    if len(distances) >= options.max_nodes:
                        raise _LimitReached('node_limit')
                    distances[v] = distances[u] + 1
                    stats['candidate_nodes'] = len(distances)
                    queue.append(v)
        nodes = set(distances)
        # Distances serve only as safe domain filters; CSP decides the route.
        to_target = {}
        if target in nodes:
            to_target[target] = 0
            queue = deque([target])
        while queue:
            check_time()
            u = queue.popleft()
            for v in graph.adjacency[u]:
                check_time()
                if v in nodes and v not in to_target and allowed(u, v):
                    to_target[v] = to_target[u] + 1
                    queue.append(v)
        neighbors = {}
        for u in sorted(nodes):
            check_time()
            neighbors[u] = {v for v in graph.adjacency[u] if v in nodes and allowed(u, v)}

        def propagate(domains):
            arcs = deque((i, j) for i in range(len(domains)) for j in (i - 1, i + 1)
                         if 0 <= j < len(domains))
            while True:
                while arcs:
                    check_time()
                    i, j = arcs.popleft()
                    stats['arc_revisions'] += 1
                    remove = set()
                    for value in sorted(domains[i]):
                        check_time()
                        if not neighbors[value].intersection(domains[j]):
                            remove.add(value)
                    if remove:
                        domains[i] -= remove
                        stats['values_pruned'] += len(remove)
                        if not domains[i]:
                            return False
                        for k in (i - 1, i + 1):
                            if 0 <= k < len(domains) and k != j:
                                arcs.append((k, i))
                waypoint = constraints.waypoint
                if waypoint is None:
                    return True
                positions = [i for i, domain in enumerate(domains) if waypoint in domain]
                if not positions:
                    return False
                if len(positions) != 1 or len(domains[positions[0]]) == 1:
                    return True
                i = positions[0]
                stats['values_pruned'] += len(domains[i]) - 1
                domains[i] = {waypoint}
                arcs.extend((j, i) for j in (i - 1, i + 1) if 0 <= j < len(domains))

        def solve(domains):
            check_time()
            if not propagate(domains):
                return None
            undecided = [i for i, domain in enumerate(domains) if len(domain) > 1]
            if not undecided:
                return [next(iter(domain)) for domain in domains]
            variable = min(undecided, key=lambda i: (len(domains[i]), i))
            for value in sorted(domains[variable]):
                check_time()
                if stats['assignments_tried'] >= options.max_assignments:
                    raise _LimitReached('assignment_limit')
                stats['assignments_tried'] += 1
                branch = [domain.copy() for domain in domains]
                branch[variable] = {value}
                path = solve(branch)
                if path is not None:
                    return path
            return None

        for length in range(bound + 1):
            check_time()
            stats['lengths_attempted'] += 1
            domains = []
            for i in range(length + 1):
                check_time()
                domains.append({u for u in nodes if distances[u] <= i and
                                to_target.get(u, bound + 1) <= length - i})
            domains[0].intersection_update({source})
            domains[-1].intersection_update({target})
            if any(not domain for domain in domains):
                continue
            path = solve(domains)
            if path is not None:
                return result(path, 'feasible')
        return result(None, 'infeasible' if complete else 'infeasible_within_bound')
    except _LimitReached as exc:
        return result(None, str(exc))
