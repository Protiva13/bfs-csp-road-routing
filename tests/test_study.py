import gzip
from pathlib import Path
import tempfile
import unittest
from route_study.graph import load_graph, connected_components
from route_study.search import bfs
from route_study.scenarios import generate_scenarios


class StudyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'graph.txt'
        self.path.write_text('# Nodes: 6 Edges: 8\n10 20\n20 10\n20 30\n10 40\n40 30\n30 50\n50 50\n99 99\n')
        self.graph = load_graph(self.path)

    def test_validation_and_normalization(self):
        m = self.graph.metadata
        self.assertEqual(m['nodes'], 6)
        self.assertEqual(m['unique_undirected_edges'], 5)
        self.assertEqual(m['duplicate_or_reverse_rows_removed'], 1)
        self.assertEqual(m['self_loop_rows_removed'], 2)
        self.assertEqual(m['warnings'], [])
        self.assertEqual(self.graph.adjacency[99], ())
        for u, neighbors in self.graph.adjacency.items():
            for v in neighbors:
                self.assertIn(u, self.graph.adjacency[v])

    def test_gzip_equivalence(self):
        compressed = self.path.with_suffix('.txt.gz')
        with gzip.open(compressed, 'wt') as stream:
            stream.write(self.path.read_text())
        self.assertEqual(load_graph(compressed).adjacency, self.graph.adjacency)

    def test_components(self):
        self.assertEqual(connected_components(self.graph), [[10, 20, 30, 40, 50], [99]])

    def test_shortest_path_and_metrics(self):
        result = bfs(self.graph, 10, 50)
        self.assertEqual(result.path, [10, 20, 30, 50])
        self.assertEqual(result.hops, 3)
        self.assertLessEqual(result.expanded_nodes, result.discovered_nodes)
        self.assertGreaterEqual(result.frontier_peak, 1)
        for u, v in zip(result.path, result.path[1:]):
            self.assertIn(v, self.graph.adjacency[u])

    def test_same_unreachable_and_missing(self):
        self.assertEqual(bfs(self.graph, 10, 10).hops, 0)
        self.assertIsNone(bfs(self.graph, 10, 99).path)
        with self.assertRaises(ValueError):
            bfs(self.graph, 10, 123)

    def test_scenarios(self):
        components = connected_components(self.graph)
        first = generate_scenarios(components, 20, 42)
        self.assertEqual(first, generate_scenarios(components, 20, 42))
        pairs = {(s['source'], s['target']) for s in first}
        self.assertEqual(len(pairs), 20)
        self.assertTrue(all(u != v and u != 99 and v != 99 for u, v in pairs))
        self.assertNotEqual(first, generate_scenarios(components, 20, 43))
        for count in (-1, 21):
            with self.assertRaises(ValueError):
                generate_scenarios(components, count, 42)
        self.assertEqual(generate_scenarios([[1]], 0, 42), [])

    def test_bad_input(self):
        for contents in ('', '# comment\n', '1 x', '1 2 3', '-1 2'):
            with self.subTest(contents=contents):
                self.path.write_text(contents)
                with self.assertRaises(ValueError):
                    load_graph(self.path)

    def test_header_mismatch(self):
        self.path.write_text('# Nodes: 99 Edges: 99\n1 2\n')
        self.assertTrue(load_graph(self.path).metadata['warnings'])


if __name__ == '__main__':
    unittest.main()
