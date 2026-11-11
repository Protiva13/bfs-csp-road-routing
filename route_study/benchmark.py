"""Generate replayable queries and run paired constrained BFS/CSP pilots."""
import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
import csv
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import statistics
import time

from .constraints import RouteConstraints, edge_key, validate_route
from .csp import CspOptions, csp_route
from .graph import Graph, connected_components, load_graph
from .search import constrained_bfs


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def generate_suite(graph: Graph, count: int, seed: int, walk_hops: int,
                   max_hops: int) -> dict:
    if type(count) is not int or count < 1:
        raise ValueError('Query count must be positive')
    if not 1 <= walk_hops <= max_hops <= 128:
        raise ValueError('Require 1 <= walk_hops <= max_hops <= 128')
    nodes = connected_components(graph)[0]
    if len(nodes) < 2 or count > len(nodes):
        raise ValueError('Need enough distinct sources in a nontrivial largest component')
    rng = random.Random(seed)
    cases = []
    for index, source in enumerate(rng.sample(nodes, count)):
        walk = [source]
        for _ in range(walk_hops):
            neighbors = graph.adjacency[walk[-1]]
            forward = [v for v in neighbors if len(walk) < 2 or v != walk[-2]]
            walk.append(rng.choice(forward or neighbors))
        # A walk may close a cycle. Use its first neighbor as the documented fallback.
        target = walk[-1] if walk[-1] != source else walk[1]
        waypoint = walk[len(walk) // 2]
        blocked = [list(edge_key(*rng.choice(list(zip(walk, walk[1:])))))]
        families = {
            'hop_bound': RouteConstraints(max_hops=max_hops),
            'blocked_road': RouteConstraints(blocked, max_hops=max_hops),
            'waypoint': RouteConstraints(waypoint=waypoint, max_hops=max_hops),
            'combined': RouteConstraints(blocked, waypoint, max_hops),
            'zero_budget': RouteConstraints(max_hops=0),
        }
        for family, constraints in families.items():
            cases.append({'id': f'q{index:04d}-{family}', 'family': family,
                          'source': source, 'target': target,
                          'constraints': constraints.to_dict()})
    return {'schema_version': 1, 'dataset_sha256': graph.metadata['sha256'],
            'generation': {'seed': seed, 'base_queries': count, 'walk_hops': walk_hops,
                           'max_hops': max_hops,
                           'policy': 'distinct uniform sources in largest component; random-walk endpoints; '
                                     'avoid immediate backtracking when possible; closed-walk target falls '
                                     'back to first neighbor; midpoint waypoint; uniformly selected walk road blocked; '
                                     'no filtering based on planner outcomes'},
            'scenarios': cases}


def validate_suite(graph: Graph, suite: dict, options: CspOptions) -> None:
    if not isinstance(suite, dict) or suite.get('schema_version') != 1:
        raise ValueError('Expected scenario suite schema_version 1')
    if suite.get('dataset_sha256') != graph.metadata['sha256']:
        raise ValueError('Scenario suite dataset fingerprint does not match')
    cases = suite.get('scenarios')
    if not isinstance(cases, list) or not cases:
        raise ValueError('Scenario suite must contain a nonempty scenarios list')
    identifiers = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError('Each scenario must be an object')
        identifier = case.get('id')
        if not isinstance(identifier, str) or not identifier or identifier in identifiers:
            raise ValueError('Scenario IDs must be nonempty unique strings')
        identifiers.add(identifier)
        if not isinstance(case.get('family'), str) or not case['family']:
            raise ValueError('Each scenario needs a family label')
        for key in ('source', 'target'):
            if type(case.get(key)) is not int or case[key] not in graph.adjacency:
                raise ValueError(f'{identifier}: invalid {key}')
        constraints = RouteConstraints.from_dict(case.get('constraints', {}))
        constraints.validate_graph(graph)
        if constraints.max_hops is None or constraints.max_hops > options.max_hops:
            raise ValueError(f'{identifier}: require an explicit max_hops <= CSP solver hop bound')


def compare_pair(bfs: dict, csp: dict) -> str:
    completed = {'feasible', 'infeasible'}
    if bfs['status'] not in completed or csp['status'] not in completed:
        return 'unresolved'
    if bfs['status'] != csp['status']:
        return 'mismatch'
    if bfs['status'] == 'feasible' and bfs['hops'] != csp['hops']:
        return 'mismatch'
    return 'agree'


def summarize(records: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for row in records:
        if row['phase'] == 'measured':
            groups[(row['family'], row['planner'])].append(row)
    summary = []
    for (family, planner), rows in sorted(groups.items()):
        completed = [r['elapsed_seconds'] for r in rows if r['status'] in ('feasible', 'infeasible')]
        feasible = [r['elapsed_seconds'] for r in rows if r['status'] == 'feasible']
        summary.append({'family': family, 'planner': planner, 'runs': len(rows),
                        'status_counts': dict(sorted(Counter(r['status'] for r in rows).items())),
                        'median_completed_seconds': statistics.median(completed) if completed else None,
                        'median_feasible_seconds': statistics.median(feasible) if feasible else None})
    return summary


def run_suite(graph: Graph, suite: dict, *, repeats: int = 3, warmups: int = 1,
              seed: int = 42, options: CspOptions = CspOptions(),
              bfs_max_states: int = 100000, on_record=None) -> dict:
    if type(repeats) is not int or repeats < 1 or type(warmups) is not int or warmups < 0:
        raise ValueError('Require positive repeats and nonnegative warmups')
    if type(bfs_max_states) is not int or bfs_max_states < 1:
        raise ValueError('BFS state limit must be a positive integer')
    validate_suite(graph, suite, options)
    records, pairs = [], []
    cases = list(suite['scenarios'])
    random.Random(seed).shuffle(cases)
    for phase, iterations in (('warmup', warmups), ('measured', repeats)):
        for repeat in range(iterations):
            for index, case in enumerate(cases):
                rules = RouteConstraints.from_dict(case['constraints'])
                order = ['constrained_bfs', 'csp']
                if (repeat + index) % 2:
                    order.reverse()
                paired = {}
                for planner in order:
                    row = {'scenario_id': case['id'], 'family': case['family'],
                           'source': case['source'], 'target': case['target'],
                           'constraints': rules.to_dict(), 'planner': planner,
                           'phase': phase, 'repeat': repeat, 'execution_index': len(records),
                           'status': 'error', 'path': None, 'hops': None,
                           'route_validated': False, 'error': None, 'metrics': {}}
                    started = time.perf_counter()
                    try:
                        if planner == 'constrained_bfs':
                            found = constrained_bfs(graph, case['source'], case['target'], rules,
                                                    timeout_seconds=options.timeout_seconds,
                                                    max_expanded_states=bfs_max_states)
                            status = found.status or ('feasible' if found.path is not None else 'infeasible')
                        else:
                            found = csp_route(graph, case['source'], case['target'], rules, options)
                            status = found.status
                        row['elapsed_seconds'] = time.perf_counter() - started
                        details = asdict(found)
                        row.update(status=status, path=found.path, hops=found.hops,
                                   metrics={k: v for k, v in details.items() if k not in ('path', 'status')})
                        if found.path is not None:
                            try:
                                validate_route(graph, found.path, case['source'], case['target'], rules)
                                row['route_validated'] = True
                            except ValueError as exc:
                                row.update(status='invalid_route', error=str(exc))
                    except Exception as exc:
                        row['elapsed_seconds'] = time.perf_counter() - started
                        row.update(status='error', error=f'{type(exc).__name__}: {exc}')
                    records.append(row)
                    paired[planner] = row
                    if on_record is not None:
                        on_record(row)
                pairs.append({'scenario_id': case['id'], 'phase': phase, 'repeat': repeat,
                              'agreement': compare_pair(paired['constrained_bfs'], paired['csp'])})
    source_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in sorted(Path(__file__).parent.glob('*.py'))}
    completed_answers = defaultdict(set)
    for row in records:
        if row['phase'] == 'measured' and row['status'] in ('feasible', 'infeasible'):
            completed_answers[(row['scenario_id'], row['planner'])].add((row['status'], row['hops']))
    inconsistencies = [{'scenario_id': key[0], 'planner': key[1]}
                       for key, answers in sorted(completed_answers.items()) if len(answers) > 1]
    return {'schema_version': 1, 'purpose': 'pilot comparison; not a publication conclusion',
            'created_at_utc': datetime.now(timezone.utc).isoformat(),
            'dataset': graph.metadata, 'suite_sha256': fingerprint(suite), 'suite': suite,
            'source_sha256': source_hashes,
            'environment': {'python': platform.python_version(), 'platform': platform.platform(),
                            'processor': platform.processor() or 'unavailable',
                            'logical_cpus': os.cpu_count(), 'architecture': platform.machine()},
            'settings': {'repeats': repeats, 'warmups': warmups, 'order_seed': seed,
                         'csp_options': asdict(options), 'bfs_max_expanded_states': bfs_max_states,
                         'order_policy': 'seeded case shuffle; alternate planner order by case and repetition',
                         'timing_scope': 'planner call, including CSP preprocessing and resource checks; '
                                         'excludes dataset loading, generation, route validation, serialization'},
            'records': records, 'pairs': pairs, 'summary': summarize(records),
            'inconsistent_completed_answers': inconsistencies,
            'measured_agreement_counts': dict(Counter(p['agreement'] for p in pairs if p['phase'] == 'measured'))}


def save_report(report: dict, directory: Path) -> None:
    (directory / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    fields = ['scenario_id', 'family', 'planner', 'phase', 'repeat', 'execution_index',
              'source', 'target', 'status', 'hops', 'elapsed_seconds', 'route_validated', 'error']
    with (directory / 'runs.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(report['records'])
    with (directory / 'summary.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=['family', 'planner', 'runs', 'status_counts',
                                'median_completed_seconds', 'median_feasible_seconds'])
        writer.writeheader()
        writer.writerows({**r, 'status_counts': json.dumps(r['status_counts'], sort_keys=True)}
                         for r in report['summary'])
    lines = ['# Paired route-planning pilot', '',
             'These measurements describe this pilot only; they are not conference conclusions.', '',
             f"Measured pair outcomes: `{report['measured_agreement_counts']}`.", '',
             f"Inconsistent completed answers across measured repetitions: {len(report['inconsistent_completed_answers'])}.", '',
             '| Family | Planner | Runs | Status counts | Median completed seconds |',
             '|---|---|---:|---|---:|']
    for row in report['summary']:
        median = row['median_completed_seconds']
        lines.append(f"| {row['family']} | {row['planner']} | {row['runs']} | "
                     f"{json.dumps(row['status_counts'], sort_keys=True)} | "
                     f"{format(median, '.9f') if median is not None else 'n/a'} |")
    lines.extend(['', 'Warmups are excluded. Infeasible completed queries are included in the '
                  'completed-time median; interrupted/error runs remain in status counts but '
                  'are excluded from that median. See runs.csv and report.json for every invocation.', '',
                  'Local random-walk endpoint sampling favors short routes. Repetitions reuse '
                  'the loaded graph and are not independent dataset samples. CSP includes its '
                  'distance preprocessing. No memory measurements or significance tests are claimed.', ''])
    (directory / 'summary.md').write_text('\n'.join(lines), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    generate = commands.add_parser('generate')
    generate.add_argument('--queries', type=int, default=3)
    generate.add_argument('--seed', type=int, default=42)
    generate.add_argument('--walk-hops', type=int, default=6)
    generate.add_argument('--max-hops', type=int, default=12)
    generate.add_argument('--output', type=Path, required=True)
    run = commands.add_parser('run')
    run.add_argument('--suite', type=Path, required=True)
    run.add_argument('--output-dir', type=Path, required=True)
    run.add_argument('--repeats', type=int, default=3)
    run.add_argument('--warmups', type=int, default=1)
    run.add_argument('--seed', type=int, default=42)
    run.add_argument('--max-hops', type=int, default=20)
    run.add_argument('--max-nodes', type=int, default=5000)
    run.add_argument('--max-assignments', type=int, default=100000)
    run.add_argument('--timeout', type=float, default=10.0)
    run.add_argument('--bfs-max-states', type=int, default=100000)
    for command in (generate, run):
        command.add_argument('--data', type=Path, default=Path('data/roadNet-TX.txt.gz'))
    args = parser.parse_args()
    try:
        if args.command == 'generate' and args.output.exists():
            raise ValueError('Suite output already exists; choose a new output filename')
        if args.command == 'run' and args.output_dir.exists():
            raise ValueError('Output directory already exists; choose a new directory')
        graph = load_graph(args.data)
        if args.command == 'generate':
            suite = generate_suite(graph, args.queries, args.seed, args.walk_hops, args.max_hops)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(suite, indent=2) + '\n', encoding='utf-8')
            print(f"Saved {len(suite['scenarios'])} scenarios to {args.output}")
        else:
            suite = json.loads(args.suite.read_text(encoding='utf-8'))
            options = CspOptions(args.max_hops, args.max_nodes, args.max_assignments, args.timeout)
            validate_suite(graph, suite, options)
            args.output_dir.mkdir(parents=True)
            # Persist the inputs first and flush each completed invocation for partial-run recovery.
            (args.output_dir / 'suite.json').write_text(json.dumps(suite, indent=2) + '\n', encoding='utf-8')
            invocation = {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()}
            (args.output_dir / 'invocation.json').write_text(json.dumps(invocation, indent=2) + '\n', encoding='utf-8')
            with (args.output_dir / 'raw.jsonl').open('w', encoding='utf-8') as raw:
                def record(row):
                    raw.write(json.dumps(row) + '\n')
                    raw.flush()
                report = run_suite(graph, suite, repeats=args.repeats, warmups=args.warmups,
                                   seed=args.seed, options=options, bfs_max_states=args.bfs_max_states,
                                   on_record=record)
            save_report(report, args.output_dir)
            print(f"Measured comparisons: {report['measured_agreement_counts']}")
            print(f'Reports saved to {args.output_dir.resolve()}')
            if any(p['agreement'] == 'mismatch' for p in report['pairs']) or report['inconsistent_completed_answers'] or any(
                    r['status'] in ('invalid_route', 'error') for r in report['records']):
                return 1
    except (OSError, ValueError, EOFError) as exc:
        parser.exit(2, f'Error: {exc}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
