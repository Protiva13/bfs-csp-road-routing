import itertools
import random
import unittest
from unittest.mock import patch
from route_study.constraints import RouteConstraints, validate_route
from route_study.csp import CspOptions, csp_route
from route_study.graph import Graph
from route_study.search import constrained_bfs


def make_graph(edges, n=5):
    adjacency = {i: set() for i in range(n)}
    for u, v in edges:
        adjacency[u].add(v)
        adjacency[v].add(u)
    return Graph({u: tuple(sorted(v)) for u, v in adjacency.items()}, {})


class CspTests(unittest.TestCase):
    def setUp(self):
        self.graph = make_graph([(0, 1), (1, 3), (0, 2), (2, 3), (1, 2), (2, 4)])

    def test_waypoint_revisit_and_combined_rules(self):
        rules = RouteConstraints([(0, 1)], 4, 4)
        result = csp_route(self.graph, 0, 3, rules)
        self.assertEqual(result.path, [0, 2, 4, 2, 3])
        self.assertEqual(result.status, 'feasible')
        self.assertEqual(result.hops, 4)
        validate_route(self.graph, result.path, 0, 3, rules)

    def test_infeasible_and_bounded_unknown_are_distinct(self):
        rules = RouteConstraints(waypoint=4, max_hops=3)
        self.assertEqual(csp_route(self.graph, 0, 3, rules).status, 'infeasible')
        short = csp_route(self.graph, 0, 3, RouteConstraints(waypoint=4), CspOptions(max_hops=3))
        self.assertEqual(short.status, 'infeasible_within_bound')
        self.assertFalse(short.complete_for_constraints)
        self.assertIsNone(short.path)
        self.assertEqual(csp_route(self.graph, 0, 3,
            RouteConstraints(waypoint=4, max_hops=4), CspOptions(max_hops=3)).status,
            'infeasible_within_bound')

    def test_zero_hops_identical_endpoints_and_endpoint_waypoints(self):
        for waypoint in (None, 0):
            self.assertEqual(csp_route(self.graph, 0, 0,
                RouteConstraints(waypoint=waypoint, max_hops=0)).path, [0])
        self.assertEqual(csp_route(self.graph, 0, 3,
            RouteConstraints(max_hops=0)).status, 'infeasible')
        self.assertEqual(csp_route(self.graph, 0, 0,
            RouteConstraints(waypoint=4, max_hops=4)).hops, 4)
        for waypoint in (0, 3):
            self.assertEqual(csp_route(self.graph, 0, 3,
                RouteConstraints(waypoint=waypoint)).hops, 2)

    def test_disconnected_and_blocked_roads(self):
        graph = make_graph([(0, 1)], 3)
        self.assertEqual(csp_route(graph, 0, 2, RouteConstraints()).status, 'infeasible')
        for source, target in ((0, 1), (1, 0)):
            result = csp_route(graph, source, target, RouteConstraints([(1, 0)], max_hops=2))
            self.assertEqual(result.status, 'infeasible')

    def test_limits_never_claim_infeasibility(self):
        result = csp_route(self.graph, 0, 3, RouteConstraints(), CspOptions(max_nodes=1))
        self.assertEqual(result.status, 'node_limit')
        self.assertIsNone(result.path)
        with patch('route_study.csp.time.perf_counter', side_effect=[0, 100]):
            result = csp_route(self.graph, 0, 3, RouteConstraints())
        self.assertEqual(result.status, 'timeout')
        graph = make_graph([(0, 1), (0, 2), (1, 3), (1, 4), (2, 3), (2, 4),
                            (3, 5), (4, 5)], 6)
        result = csp_route(graph, 0, 5, RouteConstraints(max_hops=3),
                           CspOptions(max_assignments=1))
        self.assertEqual(result.status, 'assignment_limit')

    def test_invalid_inputs(self):
        for kw in ({'max_hops': -1}, {'max_hops': 129}, {'max_hops': True},
                   {'max_nodes': 0}, {'max_assignments': 0}, {'timeout_seconds': 0},
                   {'timeout_seconds': float('nan')}):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                CspOptions(**kw)
        for source, rules in ((99, RouteConstraints()), (0, RouteConstraints(waypoint=99)),
                              (0, RouteConstraints([(0, 4)]))):
            with self.assertRaises(ValueError):
                csp_route(self.graph, source, 3, rules)

    def test_seeded_small_graphs_match_constrained_bfs(self):
        rng = random.Random(123)
        possible = list(itertools.combinations(range(5), 2))
        for trial in range(100):
            edges = [edge for edge in possible if rng.random() < .4]
            graph = make_graph(edges)
            source, target = rng.randrange(5), rng.randrange(5)
            rules = RouteConstraints(edges[:1] if trial % 2 else [],
                                     rng.choice([None, 0, 1, 2, 3, 4]), rng.randrange(7))
            expected = constrained_bfs(graph, source, target, rules)
            result = csp_route(graph, source, target, rules)
            with self.subTest(trial=trial):
                self.assertEqual(result.hops, expected.hops)
                self.assertEqual(result.status, 'feasible' if expected.path is not None else 'infeasible')
                if result.path is not None:
                    validate_route(graph, result.path, source, target, rules)

    def test_deterministic_paths_and_counters(self):
        rules = RouteConstraints(waypoint=4)
        self.assertEqual(csp_route(self.graph, 0, 3, rules), csp_route(self.graph, 0, 3, rules))


if __name__ == '__main__':
    unittest.main()
