# Road-network route-planning study

A Python standard-library project for a conference-style comparison of BFS and CSP route planning. It implements dataset validation, connected components, standard BFS, reproducible endpoint sampling, constraint-aware BFS, and a bounded finite-domain CSP solver. No comparative research findings are claimed.

## Run in VS Code (Windows)

Open this folder in VS Code. Install Microsoft's Python and Python Debugger extensions, then open a terminal in this folder. Python 3.10 or newer is required.

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m route_study --analyze-only --output outputs/analysis.json
.\.venv\Scripts\python.exe -m route_study --scenarios 10 --seed 42 --output outputs/baseline.json
```

No third-party Python packages or installation of this project are needed. Select `.venv\Scripts\python.exe` using **Python: Select Interpreter**. F5 offers analysis and baseline configurations. On macOS/Linux use `python3 -m venv .venv` and `.venv/bin/python` in place of the Windows commands.

Download the Texas road-network dataset from [SNAP](https://snap.stanford.edu/data/roadNet-TX.html) and save `roadNet-TX.txt.gz` in `data/`. The raw dataset is not included in this repository. See [dataset instructions](data/README.md) for the direct download and checksum. To use another location or another edge list:

```powershell
.\.venv\Scripts\python.exe -m route_study --data "C:\path\roadNet-TX.txt.gz" --scenarios 3 --seed 42
```

The full network requires substantial memory (allow several GB of free RAM). Start with analysis or a small scenario count. Each command reloads the graph; loading and component analysis are intentionally outside search timings.

## Dataset and validation

Reads UTF-8 plain text or `.gz` edge lists with two nonnegative integer IDs per data row; blank lines and `#` comments are supported. Original IDs are retained, including gaps. The loader treats roads as undirected and unweighted, removes self-loops, and collapses duplicate/reverse rows. Nodes occurring only in self-loops remain isolated nodes. Nodes never mentioned in an edge row cannot be reconstructed from a header count.

Metadata records a SHA-256 hash of the original file bytes, observed node/row/edge counts, removed rows, header counts, and mismatch warnings. A SNAP header's edge count is compared with input rows, not normalized undirected edges. Malformed data and empty inputs fail with a line-specific error where applicable. Header mismatches produce warnings in JSON rather than silently changing the graph. The file is not fetched from the internet or modified.

## Reproducibility and interpretation

Components are ordered by descending size, breaking ties by minimum node ID. Scenarios sample unique **ordered** source/target pairs uniformly from the largest component; source differs from target, and every pair is reachable. This policy does not stratify by distance or represent unreachable cases. Tests cover disconnected queries separately. Fixed seed, dataset, code, and Python version reproduce endpoint pairs and paths. Reports save the explicit pairs, Python version, seed, and dataset hash. Timing naturally varies.

BFS minimizes **hop count**, not physical distance or travel time. Sorted neighbor IDs make ties deterministic. Search results include the full path, hops, expanded nodes (dequeued, including the goal), discovered nodes (enqueued), and peak frontier size (including the initial source). A missing route has `path: null` and `hops: null`; unknown endpoints raise an error. Search time uses a monotonic performance clock and includes path reconstruction, but excludes graph loading, component analysis, scenario generation, and JSON serialization.

Output JSON includes component sizes and individual scenario results. Existing output files are overwritten; use distinct `--output` names for preserved runs. Smoke runs are implementation checks, not publishable benchmarks. For a paper, establish scenario families, repeat measurements, record hardware/software and resource limits, and report failures/timeouts as well as successful searches.

## Step 4: constraint-aware BFS

Run this small synthetic example first (it is separate from the real Texas dataset):

```powershell
.\.venv\Scripts\python.exe -m route_study --data examples/tiny-roads.txt --planner constrained-bfs --constraints examples/constraints.json --source 0 --target 3 --output outputs/constrained-example.json
```

The example blocks road 0--1, requires visiting node 4, and allows at most 4 hops. The expected route is `0 -> 2 -> 4 -> 2 -> 3`. Junction 2 is visited twice. This is a known synthetic example, not an experimental result.

Constraint JSON accepts these fields only:

```json
{
  "blocked_edges": [[0, 1]],
  "waypoint": 4,
  "max_hops": 4
}
```

Blocked roads apply in both directions. Each must exist in the loaded graph; a nonexistent road is treated as a configuration error. The optional waypoint must exist, and it counts as visited if it is the source or destination. The optional maximum hop count is inclusive and can be zero. Omit a field (or use `null` for waypoint/max_hops) to leave that constraint unrestricted. An empty object means no constraints.

Routes are **walks: repeated nodes and edges are allowed**. This permits visiting a dead-end waypoint and returning through the same junction. Both CSP and constrained BFS follow this same rule for a fair comparison. If the study later requires simple paths with no repeats, that is a different search problem and must be implemented explicitly.

Constrained BFS tracks `(node, waypoint_visited)` states. Reaching the same node before and after visiting the waypoint are different states. Each state is discovered at its shortest depth; later arrivals cannot help meet an upper hop limit. The search is finite even without a hop bound, with at most two states per node. Sorted neighbors provide deterministic tie breaking. It finds the fewest-hop feasible walk or returns an infeasible status after exhaustion. Standalone calls are unrestricted by default; the Step 6 runner supplies optional time and expanded-state limits, with separate interruption statuses.

Use your own constraint JSON with the Texas file. The synthetic example's node IDs and blocked road must not be assumed valid on Texas. With no explicit endpoints, seeded scenarios work as before. Their endpoints are connected in the original graph, but constraints can make a query infeasible. Explicit `--source` and `--target` override random sampling and allow testing disconnected pairs or identical endpoints.

Reports use schema version 3 and save the normalized constraints, route semantics, planner, and scenario endpoints. Successful routes are independently validated against endpoints, graph connections, blocked roads, waypoint, and hop budget; validation is outside the search timer. An infeasible result has `path: null`, `hops: null`, and `route_validated: false` (there is no returned route to validate). This validator checks feasibility, not optimality; small-graph tests compare optimal hop counts against independent bounded walk enumeration.

For constrained BFS, the existing `expanded_nodes` and `discovered_nodes` JSON keys count **states**, as indicated by `metric_unit: "states"`; `frontier_peak` also counts states. Standard BFS retains node counts. Do not present these as identical work units without that distinction. Constrained search time includes constraint validation at search entry and path reconstruction; it excludes the independent returned-route validator. Constraint files are rejected for the standard BFS planner to avoid silently ignoring rules.

### Verified smoke runs

Step 4 verification passed 19 tests, the synthetic command above, and one constrained query against the complete uploaded Texas graph. These are correctness checks, not comparative experiments. The Texas smoke query was deliberately selected from a previously validated route so that all constraints could be satisfied; it is not a random benchmark sample.

Reproduce that Texas smoke query using the saved constraint file:

```powershell
.\.venv\Scripts\python.exe -m route_study --planner constrained-bfs --constraints outputs/texas-constraints.json --source 184720 --target 184511 --output outputs/constrained-texas-smoke.json
```

The smoke reports and Texas constraint file are local generated artifacts under `outputs/` and are ignored by Git. The synthetic files under `examples/` are the portable example for a new checkout.

## Step 5: bounded CSP route planner

Run the same synthetic query with CSP:

```powershell
.\.venv\Scripts\python.exe -m route_study --data examples/tiny-roads.txt --planner csp --constraints examples/constraints.json --source 0 --target 3 --output outputs/csp-example.json
```

Or select **Step 5: CSP example** in VS Code's Run and Debug menu. The result should have 4 hops and pass the shared route validator. Repeating junctions is allowed, just as in constrained BFS. To check a known impossible query, substitute `examples/constraints-infeasible.json`, which gives the same waypoint query only 3 hops.

For each length L from zero to the effective hop bound, the CSP creates node-position variables `X_0, ..., X_L`. Endpoint domains fix `X_0` to the source and `X_L` to the target. Binary constraints require neighboring variables to use an existing, unblocked road. A global occurrence constraint requires the waypoint in at least one position. No AllDifferent constraint is imposed. AC-3 removes domain values lacking support in adjacent domains; if the waypoint has only one remaining possible position, that position is forced. Remaining variables are assigned by minimum remaining domain size (MRV), breaking ties by position, and trying node IDs in sorted order. Backtracking copies domains to restore branches. The first satisfiable length gives a shortest feasible walk. CSP can return a different equally short route from BFS.

The solver loads the original graph but builds domains from **all nodes reachable from the source within the effective hop bound**, respecting blocked roads. BFS distance preprocessing filters domains by distances from the source and target; it does not return the CSP solution. Every walk within the bound is contained in that candidate set, so this extraction preserves completeness within the bound. The candidate set is not an arbitrary sampled subgraph. If its node cap is exceeded, extraction stops with `node_limit`; no truncated-graph infeasibility claim is made.

Default resource settings:

| Option | Default | Meaning |
|---|---:|---|
| `--csp-max-hops` | 20 | Solver hop bound, supported range 0â€“128 |
| `--csp-max-nodes` | 5000 | Maximum candidate nodes |
| `--csp-max-assignments` | 100000 | Maximum backtracking value assignments |
| `--csp-timeout` | 10 | Cooperative time limit in seconds per query |

The effective hop bound is the smaller of the solver hop bound and the constraint's `max_hops`, when supplied. The timeout includes extraction, domain construction, propagation, and backtracking; dataset loading and returned-route validation remain outside it. Time checks occur between operations, so this is not a hard process-level deadline. Candidate-node and assignment caps are not a memory-byte limit; large domains and deep searches can still be expensive.

Reports now use schema version 3. CSP results distinguish:

- `feasible`: validated minimum-hop route; all shorter lengths were exhausted.
- `infeasible`: all permitted lengths exhausted, covering the constraint's hop budget (or a complete finite-state bound when no budget exists).
- `infeasible_within_bound`: no route up to the solver bound; a longer permitted route may exist.
- `node_limit`, `assignment_limit`, `timeout`: interrupted without proving infeasibility.

`complete_for_constraints` describes whether the effective hop bound covers the constraint budget, independently of resource limits. It does not itself certify a completed search; always inspect `status`. CSP metrics are `candidate_nodes`, `lengths_attempted`, `assignments_tried`, `arc_revisions` (AC-3 arc processing operations), and `values_pruned` (propagation removals across all branches). These are different work units from BFS expanded/discovered nodes or states; they must not be directly equated. Assignment counts omit forced singleton assignments. Domain initialization and branch restriction are not included in propagation-removal counts.

Reproduce the earlier short Texas query using CSP on the full loaded dataset:

```powershell
.\.venv\Scripts\python.exe -m route_study --planner csp --constraints outputs/texas-constraints.json --source 184720 --target 184511 --output outputs/csp-texas-smoke.json
```

That generated constraint file is available in this workspace; it is ignored by Git. This is a local smoke test with a small bounded candidate set, not a full-network CSP benchmark. For controlled comparisons, set the same hop budget in the shared constraint JSON, choose a CSP solver bound at least that large, use identical endpoints, and report limits rather than dropping interrupted queries.

## Step 6: paired experiments and replayable scenario suites

Start with the checked-in synthetic suite:

```powershell
.\.venv\Scripts\python.exe -m route_study.benchmark run --data examples/tiny-roads.txt --suite examples/tiny-suite.json --output-dir outputs/my-synthetic-comparison --repeats 3 --warmups 1 --timeout 2
```

Or select **Step 6: paired synthetic experiment** in VS Code. Output directories must be new; choose a different directory name for each run, including repeated F5 launches. The runner refuses to overwrite saved suites or experiment directories.

Generate and run a modest Texas pilot:

```powershell
.\.venv\Scripts\python.exe -m route_study.benchmark generate --queries 3 --seed 42 --walk-hops 6 --max-hops 12 --output outputs/my-texas-suite.json
.\.venv\Scripts\python.exe -m route_study.benchmark run --suite outputs/my-texas-suite.json --output-dir outputs/my-texas-pilot --repeats 3 --warmups 1 --timeout 2
```

Generation loads the full graph and chooses distinct uniform sources in the largest component. Each source gets a short random walk, avoiding immediate backtracking when alternatives exist. The target is the final node (or the first neighbor if the walk closes at its source); the waypoint is the walk midpoint; the blocked road is sampled uniformly from walk steps. There are five scenario families per base query: a shared hop bound alone, a blocked road, a waypoint, combined constraints, and a zero-hop budget for deliberately infeasible distinct endpoints. Blocked and combined scenarios may be feasible or infeasible; none are discarded based on solver outcomes. This is a **local-route sampling policy**, not uniform random endpoint pairs or a representative long-distance benchmark. The Step 1–3 random-pair generator remains separate.

Both planners read the exact same saved endpoints and constraints. The suite's dataset fingerprint must match the loaded file. Every scenario must have an explicit hop budget no greater than the CSP solver bound (`--max-hops`, default 20); otherwise the runner refuses the comparison. Use `--max-hops` up to 128 for a suite with larger budgets. Sources, targets, waypoint IDs, blocked roads, and scenario IDs are validated before runs.

The graph is loaded once. Each warmup and measured repetition runs every scenario with both planners. A seeded shuffle fixes case order; planner order alternates by case and repetition. Identical constraints and the same `--timeout` apply to both. BFS also has `--bfs-max-states` (default 100000 expanded states); CSP has `--max-nodes` (5000 candidates) and `--max-assignments` (100000 backtracking assignments). These caps count different work units and are not equivalent memory limits. Both deadlines are cooperative. Planner calls include resource-check overhead; CSP preprocessing is included in its timing. Loading, generation, route validation, and output writing are excluded.

Every returned route is independently validated. A measured pair agrees only if both completed with the same feasibility and, when feasible, the same minimum hop count. Equal paths are not required. Timeouts, limits, exceptions, and invalid routes remain in the data; they are never treated as infeasibility or silently dropped. Pairs without two completed valid answers are unresolved. Contradictory completed answers across repetitions are flagged. Exit code 1 indicates a mismatch, invalid route, exception, or inconsistent completed answer; 2 indicates invalid inputs. Resource-limited unresolved pairs alone do not produce exit code 1, so always inspect counts.

Each output directory contains:

- `suite.json` and `invocation.json`: exact replay inputs and command options.
- `raw.jsonl`: flushed record after each invocation, including warmups, for partial-run inspection if interrupted. It is not an automatic resume mechanism.
- `report.json`: inputs, dataset hash, source-file hashes, Python/OS/CPU information, settings, individual results, agreement checks, and summaries.
- `runs.csv`: every invocation, including failures and warmups; paths and algorithm-specific metrics remain in JSON.
- `summary.csv` and `summary.md`: per-family/per-planner counts and descriptive timing medians.

Warmups are excluded from summary medians. Completed-time medians include both feasible and proven infeasible cases; feasible-only medians are separate. Interrupted/error runs are excluded from timing medians but retained in status counts. Do not compare medians alone if completion rates differ. Repeated timings reuse the same graph and queries; they are not independent scenario samples. Reports do not measure memory, run statistical significance tests, or claim an algorithm is superior. Before a paper, broaden the scenario and hop-budget families, include difficult/unreachable routes, document the dataset's direction semantics, measure memory if needed, and choose a justified statistical protocol.

## Code and next steps

- `route_study/graph.py`: graph contract, strict loading, validation, components.
- `route_study/search.py`: standard BFS, `SearchResult`, and a planner protocol.
- `route_study/constraints.py`: shared constraint contract and independent route validator.
- `route_study/csp.py`: bounded position-variable CSP, AC-3, MRV backtracking, resource limits.
- `route_study/scenarios.py`: seeded scenario generation without search-dependent sampling.
- `route_study/__main__.py`: command-line orchestration and JSON reporting.
- `route_study/benchmark.py`: suite generation/replay, paired repetitions, resource reporting, CSV/JSON/Markdown artifacts.
- `tests/test_study.py`: small known graphs, gzip, malformed data, components, BFS, and sampling.
- `tests/test_constraints.py`: combined constraints, revisits, infeasibility, input validation, and shortest-hop oracle checks.
- `tests/test_cli.py`: successful/infeasible reports and invalid command-line combinations.
- `tests/test_csp.py`: CSP/BFS agreement, waypoint revisits, deterministic results, and limit statuses.
- `tests/test_benchmark.py`: replay validation, pairing, warmups, resource limits, failures, and artifact export.

The Step 6 infrastructure and small pilots are implemented. Next is a broader, justified experimental design and research analysis. Multiple required waypoints and blocked nodes are not implemented yet. The tested cases and pilot results do not establish which algorithm is faster or more suitable for a paper.
