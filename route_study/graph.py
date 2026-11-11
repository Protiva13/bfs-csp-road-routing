"""Strict SNAP edge-list loading. Node IDs are preserved; edges are undirected."""
from dataclasses import dataclass
import gzip
import hashlib
from pathlib import Path
import re


@dataclass(frozen=True)
class Graph:
    adjacency: dict[int, tuple[int, ...]]
    metadata: dict


def load_graph(path: str | Path) -> Graph:
    path = Path(path)
    digest = hashlib.sha256()
    with path.open('rb') as raw:
        for chunk in iter(lambda: raw.read(1024 * 1024), b''):
            digest.update(chunk)
    adjacency: dict[int, list[int]] = {}
    rows = loops = 0
    declared = None
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt', encoding='utf-8') as stream:
        for number, line in enumerate(stream, 1):
            line = line.strip()
            if not line:
                continue
            if line.startswith('#'):
                match = re.search(r'Nodes:\s*(\d+)\s+Edges:\s*(\d+)', line)
                if match:
                    declared = tuple(map(int, match.groups()))
                continue
            parts = line.split()
            if len(parts) != 2:
                raise ValueError(f'Line {number}: expected exactly two integer node IDs')
            try:
                u, v = map(int, parts)
            except ValueError as exc:
                raise ValueError(f'Line {number}: invalid integer node ID') from exc
            if min(u, v) < 0:
                raise ValueError(f'Line {number}: negative node ID')
            rows += 1
            adjacency.setdefault(u, [])
            adjacency.setdefault(v, [])
            if u == v:
                loops += 1
                continue
            adjacency[u].append(v)
            adjacency[v].append(u)
    if not adjacency:
        raise ValueError('Dataset contains no nodes')
    # Replace lists individually to limit peak memory; sort for deterministic BFS.
    for node in adjacency:
        adjacency[node] = tuple(sorted(set(adjacency[node])))
    edges = sum(map(len, adjacency.values())) // 2
    warnings = []
    if declared and declared != (len(adjacency), rows):
        warnings.append('Header node/edge counts differ from observed nodes/input rows')
    return Graph(adjacency, {
        'source_name': path.name, 'sha256': digest.hexdigest(),
        'nodes': len(adjacency), 'unique_undirected_edges': edges,
        'input_edge_rows': rows, 'self_loop_rows_removed': loops,
        'duplicate_or_reverse_rows_removed': rows - loops - edges,
        'declared_nodes': declared[0] if declared else None,
        'declared_edge_rows': declared[1] if declared else None,
        'directed': False, 'weighted': False, 'warnings': warnings,
    })


def connected_components(graph: Graph) -> list[list[int]]:
    unseen = set(graph.adjacency)
    components = []
    for root in sorted(graph.adjacency):
        if root not in unseen:
            continue
        unseen.remove(root)
        stack, component = [root], []
        while stack:
            node = stack.pop()
            component.append(node)
            for neighbor in graph.adjacency[node]:
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    stack.append(neighbor)
        components.append(sorted(component))
    return sorted(components, key=lambda c: (-len(c), c[0]))
