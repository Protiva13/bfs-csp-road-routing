import argparse
from dataclasses import asdict
import json
from pathlib import Path
import platform
import time
from .graph import load_graph, connected_components
from .scenarios import generate_scenarios
from .search import bfs, constrained_bfs
from .constraints import RouteConstraints, validate_route
from .csp import CspOptions, csp_route


def main():
    parser = argparse.ArgumentParser(description='Road-network BFS study baseline')
    parser.add_argument('--data', type=Path, default=Path('data/roadNet-TX.txt.gz'))
    parser.add_argument('--output', type=Path, default=Path('outputs/baseline.json'))
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--scenarios', type=int, default=10)
    parser.add_argument('--analyze-only', action='store_true')
    parser.add_argument('--planner', choices=['bfs', 'constrained-bfs', 'csp'], default='bfs')
    parser.add_argument('--constraints', type=Path, help='JSON constraints shared by all queries')
    parser.add_argument('--source', type=int, help='Explicit query instead of sampled pairs')
    parser.add_argument('--target', type=int)
    parser.add_argument('--csp-max-hops', type=int, default=20)
    parser.add_argument('--csp-max-nodes', type=int, default=5000)
    parser.add_argument('--csp-max-assignments', type=int, default=100000)
    parser.add_argument('--csp-timeout', type=float, default=10.0)
    args = parser.parse_args()
    try:
        if (args.source is None) != (args.target is None):
            raise ValueError('--source and --target must be supplied together')
        if args.constraints and args.planner == 'bfs':
            raise ValueError('--constraints requires --planner constrained-bfs or csp')
        csp_options = CspOptions(args.csp_max_hops, args.csp_max_nodes,
                                 args.csp_max_assignments, args.csp_timeout)
        constraints = RouteConstraints.from_dict(
            json.loads(args.constraints.read_text(encoding='utf-8')) if args.constraints else {})
        graph = load_graph(args.data)
        constraints.validate_graph(graph)
        components = connected_components(graph)
        report = {
            'schema_version': 3,
            'planner': {'bfs': 'standard_bfs', 'constrained-bfs': 'constrained_bfs',
                        'csp': 'finite_domain_csp'}[args.planner],
            'csp_options': asdict(csp_options) if args.planner == 'csp' else None,
            'constraints': constraints.to_dict(),
            'route_semantics': 'walks; repeated nodes allowed; minimize hops',
            'metric_unit': {'bfs': 'nodes', 'constrained-bfs': 'states',
                            'csp': 'CSP assignments and propagation operations'}[args.planner],
            'python_version': platform.python_version(), 'dataset': graph.metadata,
            'components': {'count': len(components),
                           'sizes_descending': [len(c) for c in components]},
            'scenario_policy': ('explicit endpoints' if args.source is not None else
                                'unique ordered pairs uniformly sampled from largest component'),
            'seed': args.seed, 'scenarios': [],
        }
        if not args.analyze_only:
            scenarios = ([{'id': 'explicit', 'source': args.source, 'target': args.target}]
                         if args.source is not None else
                         generate_scenarios(components, args.scenarios, args.seed))
            for scenario in scenarios:
                start = time.perf_counter()
                if args.planner == 'bfs':
                    result = bfs(graph, scenario['source'], scenario['target'])
                elif args.planner == 'constrained-bfs':
                    result = constrained_bfs(graph, scenario['source'], scenario['target'], constraints)
                else:
                    result = csp_route(graph, scenario['source'], scenario['target'], constraints, csp_options)
                elapsed = time.perf_counter() - start
                if result.path is not None:
                    validate_route(graph, result.path, scenario['source'], scenario['target'], constraints)
                report['scenarios'].append({**scenario, **asdict(result),
                                            'status': (result.status if args.planner == 'csp' else
                                                       'feasible' if result.path is not None else 'infeasible'),
                                            'route_validated': result.path is not None,
                                            'hops': result.hops, 'elapsed_seconds': elapsed})
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    except (OSError, ValueError, EOFError) as exc:
        parser.exit(2, f'Error: {exc}\n')
    print(f"Loaded {graph.metadata['nodes']:,} nodes; {len(components):,} components.")
    print(f'Report saved to {args.output.resolve()}')


if __name__ == '__main__':
    main()
