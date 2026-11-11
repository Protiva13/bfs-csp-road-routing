import contextlib
import io
import json
import unittest
from unittest.mock import patch
from route_study.__main__ import main
from route_study.graph import Graph


class CliTests(unittest.TestCase):
    def run_report(self, constraints, planner='constrained-bfs', extra=()):
        graph = Graph({0: (1,), 1: (0, 2), 2: (1,)}, {'sha256': 'synthetic', 'nodes': 3})
        args = ['route_study', '--planner', planner, '--constraints', 'rules.json',
                '--source', '0', '--target', '2', *extra]
        with patch('sys.argv', args), patch('route_study.__main__.load_graph', return_value=graph), \
             patch('pathlib.Path.read_text', return_value=json.dumps(constraints)), \
             patch('pathlib.Path.mkdir'), patch('pathlib.Path.write_text') as write, \
             contextlib.redirect_stdout(io.StringIO()):
            main()
        return json.loads(write.call_args.args[0])

    def test_successful_report(self):
        report = self.run_report({'waypoint': 1, 'max_hops': 2})
        self.assertEqual(report['planner'], 'constrained_bfs')
        self.assertEqual(report['constraints']['waypoint'], 1)
        self.assertEqual(report['metric_unit'], 'states')
        self.assertEqual(report['scenarios'][0]['path'], [0, 1, 2])
        self.assertTrue(report['scenarios'][0]['route_validated'])

    def test_infeasible_report(self):
        report = self.run_report({'max_hops': 1})
        result = report['scenarios'][0]
        self.assertEqual(result['status'], 'infeasible')
        self.assertIsNone(result['hops'])
        self.assertFalse(result['route_validated'])

    def test_csp_report(self):
        report = self.run_report({'waypoint': 1, 'max_hops': 2}, 'csp')
        self.assertEqual(report['planner'], 'finite_domain_csp')
        self.assertEqual(report['scenarios'][0]['path'], [0, 1, 2])
        self.assertEqual(report['scenarios'][0]['status'], 'feasible')
        self.assertTrue(report['scenarios'][0]['route_validated'])
        self.assertIn('arc_revisions', report['scenarios'][0])
        self.assertNotIn('expanded_nodes', report['scenarios'][0])

    def test_csp_bound_status_preserved_in_report(self):
        report = self.run_report({}, 'csp', ['--csp-max-hops', '1'])
        self.assertEqual(report['scenarios'][0]['status'], 'infeasible_within_bound')
        self.assertFalse(report['scenarios'][0]['route_validated'])

    def test_invalid_arguments_fail_before_loading(self):
        for args in (['--source', '0'], ['--target', '2'], ['--constraints', 'rules.json']):
            with self.subTest(args=args), patch('sys.argv', ['route_study', *args]), \
                 patch('route_study.__main__.load_graph') as load, \
                 contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main()
            self.assertEqual(error.exception.code, 2)
            load.assert_not_called()


if __name__ == '__main__':
    unittest.main()
