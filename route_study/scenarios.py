"""Sample unique ordered endpoint pairs from the largest component."""
import random


def generate_scenarios(components: list[list[int]], count: int, seed: int) -> list[dict]:
    if count < 0:
        raise ValueError('Scenario count must be nonnegative')
    nodes = sorted(components[0]) if components else []
    n = len(nodes)
    if count > n * (n - 1):
        raise ValueError('Too many distinct endpoint pairs for the largest component')
    rng = random.Random(seed)
    # Sample ranks without rejection, including when nearly all pairs are requested.
    ranks = rng.sample(range(n * (n - 1)), count)
    scenarios = []
    for index, rank in enumerate(ranks):
        i, j = divmod(rank, n - 1)
        if j >= i:
            j += 1
        scenarios.append({'id': f's{index:05d}', 'source': nodes[i], 'target': nodes[j]})
    return scenarios
