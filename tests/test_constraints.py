import itertools
import random
import unittest
from route_study.constraints import RouteConstraints, validate_route
from route_study.graph import Graph
from route_study.search import bfs, constrained_bfs


def make_graph(edges, nodes=range(5)):
    adjacency = {node: set() for node in nodes}
    for u, v in edges:
        adjacency[u].add(v)
        adjacency[v].add(u)
    return Graph({u: tuple(sorted(v)) for u, v in adjacency.items()}, {})


class ConstraintTests(unittest.TestCase):
    def setUp(self):
        self.graph = make_graph([(0, 1), (1, 3), (0, 2), (2, 3), (1, 2), (2, 4)])

    def test_empty_constraints_match_baseline(self):
        for source, target in itertools.product(range(5), repeat=2):
            self.assertEqual(bfs(self.graph, source, target),
                             constrained_bfs(self.graph, source, target, RouteConstraints()))

    def test_blocked_edge_is_bidirectional(self):
        constraints = RouteConstraints.from_dict({'blocked_edges': [[1, 0], [0, 1]]})
        self.assertEqual(len(constraints.blocked_edges), 1)
        self.assertEqual(constrained_bfs(self.graph, 0, 1, constraints).path, [0, 2, 1])
        self.assertEqual(constrained_bfs(self.graph, 1, 0, constraints).path, [1, 2, 0])

    def test_waypoint_requires_revisiting_junction(self):
        constraints = RouteConstraints(waypoint=4, max_hops=4)
        result = constrained_bfs(self.graph, 0, 3, constraints)
        self.assertEqual(result.path, [0, 2, 4, 2, 3])
        validate_route(self.graph, result.path, 0, 3, constraints)
        self.assertIsNone(constrained_bfs(self.graph, 0, 3,
                                         RouteConstraints(waypoint=4, max_hops=3)).path)

    def test_combined_constraints(self):
        constraints = RouteConstraints.from_dict(
            {'blocked_edges': [[0, 1]], 'waypoint': 4, 'max_hops': 4})
        result = constrained_bfs(self.graph, 0, 3, constraints)
        self.assertEqual(result.hops, 4)
        validate_route(self.graph, result.path, 0, 3, constraints)
        self.assertIsNone(constrained_bfs(self.graph, 0, 3,
            RouteConstraints([(0, 1), (0, 2)], waypoint=4)).path)

    def test_zero_hops_and_endpoint_waypoint(self):
        self.assertEqual(constrained_bfs(self.graph, 0, 0,
            RouteConstraints(waypoint=0, max_hops=0)).path, [0])
        self.assertIsNone(constrained_bfs(self.graph, 0, 1, RouteConstraints(max_hops=0)).path)
        self.assertEqual(constrained_bfs(self.graph, 0, 0,
            RouteConstraints(waypoint=4)).path, [0, 2, 4, 2, 0])
        for waypoint in (0, 3):
            self.assertEqual(constrained_bfs(self.graph, 0, 3,
                RouteConstraints(waypoint=waypoint)).hops, 2)

    def test_invalid_constraints(self):
        invalid = [[], {'unknown': 1}, {'max_hops': -1}, {'max_hops': True},
                   {'max_hops': 1.5}, {'waypoint': '4'}, {'blocked_edges': None},
                   {'blocked_edges': [[0]]}, {'blocked_edges': [[0, -1]]},
                   {'blocked_edges': [[True, 1]]}]
        for data in invalid:
            with self.subTest(data=data), self.assertRaises(ValueError):
                RouteConstraints.from_dict(data)
        for constraints in (RouteConstraints(waypoint=99), RouteConstraints([(0, 4)])):
            with self.assertRaises(ValueError):
                constrained_bfs(self.graph, 0, 3, constraints)
        with self.assertRaises(ValueError):
            constrained_bfs(self.graph, 99, 3, RouteConstraints())

    def test_independent_validator_rejects_invalid_routes(self):
        for path, constraints in [([], RouteConstraints()),
            ([1, 3], RouteConstraints()), ([0, 99, 3], RouteConstraints()),
            ([0, 4, 3], RouteConstraints()),
            ([0, 1, 3], RouteConstraints([(1, 0)])),
            ([0, 1, 3], RouteConstraints(waypoint=4)),
            ([0, 1, 3], RouteConstraints(max_hops=1))]:
            with self.subTest(path=path, constraints=constraints), self.assertRaises(ValueError):
                validate_route(self.graph, path, 0, 3, constraints)

    def test_shortest_hops_against_bounded_walk_enumeration(self):
        # Independent oracle enumerates all walks by length, without BFS state pruning.
        rng = random.Random(71)
        possible = list(itertools.combinations(range(4), 2))
        for trial in range(40):
            edges = [edge for edge in possible if rng.random() < .5]
            graph = make_graph(edges, range(4))
            blocked = edges[:1] if trial % 2 else []
            waypoint = rng.choice([None, 0, 1, 2, 3])
            source, target = rng.randrange(4), rng.randrange(4)
            budget = rng.randrange(6)
            constraints = RouteConstraints(blocked, waypoint, budget)
            walks, expected = [[source]], None
            for depth in range(budget + 1):
                if any(p[-1] == target and (waypoint is None or waypoint in p) for p in walks):
                    expected = depth
                    break
                walks = [p + [v] for p in walks for v in graph.adjacency[p[-1]]
                         if (min(p[-1], v), max(p[-1], v)) not in constraints.blocked_edges]
            result = constrained_bfs(graph, source, target, constraints)
            with self.subTest(trial=trial):
                self.assertEqual(result.hops, expected)
                self.assertLessEqual(result.discovered_nodes, 2 * len(graph.adjacency))
                if result.path is not None:
                    validate_route(graph, result.path, source, target, constraints)


if __name__ == '__main__':
    unittest.main()
