import copy
import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from route_study.benchmark import (compare_pair, fingerprint, generate_suite, run_suite,
                                   save_report, validate_suite)
from route_study.constraints import RouteConstraints
from route_study.csp import CspOptions
from route_study.graph import Graph
from route_study.search import constrained_bfs


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.graph = Graph({0: (1, 2), 1: (0, 2), 2: (0, 1, 3), 3: (2,)},
                           {'sha256': 'synthetic-graph', 'nodes': 4})
        self.suite = generate_suite(self.graph, 2, 42, 3, 6)

    def test_generation_is_seeded_and_has_all_families(self):
        self.assertEqual(self.suite, generate_suite(self.graph, 2, 42, 3, 6))
        self.assertNotEqual(self.suite, generate_suite(self.graph, 2, 43, 3, 6))
        self.assertEqual(len(self.suite['scenarios']), 10)
        self.assertEqual({c['family'] for c in self.suite['scenarios']},
                         {'hop_bound', 'blocked_road', 'waypoint', 'combined', 'zero_budget'})
        validate_suite(self.graph, self.suite, CspOptions())
        self.assertTrue(all(c['source'] != c['target'] for c in self.suite['scenarios']))
        self.assertEqual(fingerprint({'a': 1, 'b': 2}), fingerprint({'b': 2, 'a': 1}))

    def test_suite_rejects_wrong_graph_duplicate_ids_and_unfair_bound(self):
        for change in ('hash', 'duplicate', 'budget', 'endpoint'):
            suite = copy.deepcopy(self.suite)
            if change == 'hash':
                suite['dataset_sha256'] = 'different'
            elif change == 'duplicate':
                suite['scenarios'][1]['id'] = suite['scenarios'][0]['id']
            elif change == 'budget':
                suite['scenarios'][0]['constraints']['max_hops'] = 21
            else:
                suite['scenarios'][0]['source'] = 999
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_suite(self.graph, suite, CspOptions())

    def test_paired_runs_warmups_summary_and_balanced_order(self):
        report = run_suite(self.graph, self.suite, repeats=2, warmups=1)
        self.assertEqual(len(report['records']), 60)
        self.assertEqual(report['measured_agreement_counts'], {'agree': 20})
        self.assertEqual(report['inconsistent_completed_answers'], [])
        self.assertEqual(sum(row['runs'] for row in report['summary']), 40)
        self.assertTrue(all(r['route_validated'] for r in report['records'] if r['status'] == 'feasible'))
        first_id = self.suite['scenarios'][0]['id']
        first = [r for r in report['records'] if r['scenario_id'] == first_id and r['phase'] == 'measured']
        self.assertEqual(first[0]['planner'], first[3]['planner'])
        self.assertNotEqual(first[0]['planner'], first[2]['planner'])
        for pair in report['pairs']:
            rows = [r for r in report['records'] if r['scenario_id'] == pair['scenario_id'] and
                    r['repeat'] == pair['repeat'] and r['phase'] == pair['phase']]
            self.assertEqual(rows[0]['constraints'], rows[1]['constraints'])
            self.assertEqual((rows[0]['source'], rows[0]['target']), (rows[1]['source'], rows[1]['target']))

    def test_resource_limits_are_retained_and_unresolved(self):
        suite = copy.deepcopy(self.suite)
        suite['scenarios'] = [suite['scenarios'][0]]
        report = run_suite(self.graph, suite, repeats=1, warmups=0,
                           options=CspOptions(max_nodes=1), bfs_max_states=1)
        self.assertEqual({r['status'] for r in report['records']}, {'node_limit', 'state_limit'})
        self.assertEqual(report['measured_agreement_counts'], {'unresolved': 1})
        self.assertTrue(all(row['median_completed_seconds'] is None for row in report['summary']))

    def test_error_and_invalid_routes_are_retained(self):
        suite = copy.deepcopy(self.suite)
        suite['scenarios'] = [suite['scenarios'][0]]
        with patch('route_study.benchmark.csp_route', side_effect=RuntimeError('test failure')):
            report = run_suite(self.graph, suite, repeats=1, warmups=0)
        row = next(r for r in report['records'] if r['planner'] == 'csp')
        self.assertEqual(row['status'], 'error')
        self.assertIn('test failure', row['error'])
        with patch('route_study.benchmark.validate_route', side_effect=ValueError('invalid test route')):
            report = run_suite(self.graph, suite, repeats=1, warmups=0)
        self.assertTrue(all(r['status'] == 'invalid_route' for r in report['records']))

    def test_comparison_requires_completed_equal_answers(self):
        self.assertEqual(compare_pair({'status': 'feasible', 'hops': 2},
                                      {'status': 'feasible', 'hops': 3}), 'mismatch')
        self.assertEqual(compare_pair({'status': 'feasible', 'hops': 2},
                                      {'status': 'infeasible', 'hops': None}), 'mismatch')
        self.assertEqual(compare_pair({'status': 'infeasible', 'hops': None},
                                      {'status': 'timeout', 'hops': None}), 'unresolved')

    def test_bfs_timeout_and_state_limits_are_not_infeasible(self):
        with patch('route_study.search.time.perf_counter', side_effect=[0, 100]):
            result = constrained_bfs(self.graph, 0, 3, RouteConstraints(), timeout_seconds=1)
        self.assertEqual(result.status, 'timeout')
        self.assertEqual(constrained_bfs(self.graph, 0, 3, RouteConstraints(),
            max_expanded_states=1).status, 'state_limit')
        for kwargs in ({'timeout_seconds': 0}, {'timeout_seconds': float('nan')},
                       {'max_expanded_states': 0}):
            with self.assertRaises(ValueError):
                constrained_bfs(self.graph, 0, 3, RouteConstraints(), **kwargs)

    def test_bad_generation_and_repeat_options(self):
        for args in ((0, 42, 3, 6), (2, 42, 7, 6), (5, 42, 3, 6)):
            with self.assertRaises(ValueError):
                generate_suite(self.graph, *args)
        for kwargs in ({'repeats': 0}, {'warmups': -1}, {'bfs_max_states': 0}):
            with self.assertRaises(ValueError):
                run_suite(self.graph, self.suite, **kwargs)

    def test_saved_artifacts_retain_all_runs(self):
        report = run_suite(self.graph, self.suite, repeats=1, warmups=0)
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            save_report(report, directory)
            loaded = json.loads((directory / 'report.json').read_text(encoding='utf-8'))
            self.assertEqual(loaded['suite_sha256'], fingerprint(self.suite))
            with (directory / 'runs.csv').open(newline='', encoding='utf-8') as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), 20)
            self.assertIn('pilot only', (directory / 'summary.md').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
