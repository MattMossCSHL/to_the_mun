"""
analysis.py — population analysis tools for GA runs.

Functions
---------
analyze_population : summarise top-N vs full population by score, stage count,
                     part count, and part-type frequency.
inspect_top_rockets : print top-N rocket compositions from a saved generation file.
"""

import json
import statistics
from collections import Counter
from pathlib import Path


def _extract_features(individual):
    """Pull score, stage count, part count, and typed part lists from one individual.

    Uses part ID prefixes to categorise parts (eng_, tank_, pod_0, decoupler_).
    Falls back to computing n_stages / n_parts from the rocket dict if the
    population was not run with detailed=True.

    Parameters
    ----------
    individual : tuple
        (rocket_dict, meta) tuple.

    Returns
    -------
    dict
        Keys: score, n_stages, n_parts, engines, tanks, pods.
    """
    rocket, meta = individual
    score = meta['score']

    if 'n_stages' in meta:
        n_stages = meta['n_stages']
    else:
        n_stages = len(set(rocket['stages'].values()))

    if 'n_parts' in meta:
        n_parts = meta['n_parts']
    else:
        n_parts = len(rocket['parts'])

    engines = [p['type'] for p in rocket['parts'] if p['id'].startswith('eng_')]
    tanks = [p['type'] for p in rocket['parts'] if p['id'].startswith('tank_')]
    pods = [p['type'] for p in rocket['parts'] if p['id'] == 'pod_0']

    return {
        'score': score,
        'n_stages': n_stages,
        'n_parts': n_parts,
        'engines': engines,
        'tanks': tanks,
        'pods': pods,
    }


def _group_stats(individuals):
    """Compute summary stats and part-type frequencies for a list of individuals.

    Parameters
    ----------
    individuals : list
        List of (rocket_dict, meta) tuples.

    Returns
    -------
    dict
        Keys: score (mean, median, max, pct_zeros), n_stages (mean, dist),
        n_parts (mean), engines (Counter), tanks (Counter), pods (Counter).
    """
    features = [_extract_features(ind) for ind in individuals]

    scores = [f['score'] for f in features]
    n_stages_list = [f['n_stages'] for f in features]
    n_parts_list = [f['n_parts'] for f in features]

    engine_counter = Counter()
    tank_counter = Counter()
    pod_counter = Counter()
    for f in features:
        engine_counter.update(f['engines'])
        tank_counter.update(f['tanks'])
        pod_counter.update(f['pods'])

    stage_dist = dict(sorted(Counter(n_stages_list).items()))

    return {
        'score': {
            'mean': statistics.mean(scores),
            'median': statistics.median(scores),
            'max': max(scores),
            'pct_zeros': sum(1 for s in scores if s == 0) / len(scores) * 100,
        },
        'n_stages': {
            'mean': statistics.mean(n_stages_list),
            'dist': stage_dist,
        },
        'n_parts': {
            'mean': statistics.mean(n_parts_list),
        },
        'engines': engine_counter,
        'tanks': tank_counter,
        'pods': pod_counter,
    }


def _make_summary(top_stats, pop_stats, top_n, n_total):
    """Generate a plain-English summary string from group stats.

    Parameters
    ----------
    top_stats : dict
        Stats dict for the top-N group.
    pop_stats : dict
        Stats dict for the full population.
    top_n : int
        Number of top rockets analysed.
    n_total : int
        Total population size.

    Returns
    -------
    str
        Multi-line summary.
    """
    lines = []

    top_mean = top_stats['score']['mean']
    pop_mean = pop_stats['score']['mean']
    ratio = top_mean / pop_mean if pop_mean > 0 else float('inf')

    lines.append(
        f"Top {top_n} mean score:  {top_mean:,.0f} m/s  "
        f"({ratio:.2f}x population mean of {pop_mean:,.0f} m/s)"
    )
    lines.append(
        f"Top {top_n} max score:   {top_stats['score']['max']:,.0f} m/s  |  "
        f"Pop max: {pop_stats['score']['max']:,.0f} m/s"
    )
    lines.append(
        f"Pop zeros: {pop_stats['score']['pct_zeros']:.1f}%  |  "
        f"Top zeros: {top_stats['score']['pct_zeros']:.1f}%"
    )

    top_stage_mean = top_stats['n_stages']['mean']
    pop_stage_mean = pop_stats['n_stages']['mean']
    lines.append(
        f"Avg stages — top: {top_stage_mean:.1f}  |  pop: {pop_stage_mean:.1f}"
    )

    top_dist = top_stats['n_stages']['dist']
    dist_str = '  '.join(f"{k}-stage: {v}" for k, v in top_dist.items())
    lines.append(f"Top stage dist: {dist_str}")

    top_parts_mean = top_stats['n_parts']['mean']
    pop_parts_mean = pop_stats['n_parts']['mean']
    lines.append(
        f"Avg parts  — top: {top_parts_mean:.1f}  |  pop: {pop_parts_mean:.1f}"
    )

    if top_stats['engines']:
        top_engine, top_engine_count = top_stats['engines'].most_common(1)[0]
        lines.append(f"Top engine (top {top_n}): {top_engine} ({top_engine_count} uses)")
    if top_stats['tanks']:
        top_tank, top_tank_count = top_stats['tanks'].most_common(1)[0]
        lines.append(f"Top tank   (top {top_n}): {top_tank} ({top_tank_count} uses)")
    if top_stats['pods']:
        top_pod, top_pod_count = top_stats['pods'].most_common(1)[0]
        lines.append(f"Top pod    (top {top_n}): {top_pod} ({top_pod_count} uses)")

    return '\n'.join(lines)


def analyze_population(population, top_n=10, verbose=False):
    """Summarise top-N vs full population: scores, stage counts, part frequencies.

    Sorts the population by score descending, then computes stats for the top-N
    group and the full population independently. Always returns a result dict.
    Prints a human-readable summary when verbose=True.

    Parameters
    ----------
    population : list
        List of (rocket_dict, meta) tuples. meta must have 'score'.
        If meta also has 'n_stages' and 'n_parts' (detailed=True run), those
        are used directly; otherwise they are computed from the rocket dict.
    top_n : int, optional
        Number of top-scoring rockets to analyse. Default 10.
    verbose : bool, optional
        If True, print a human-readable summary. Default False.

    Returns
    -------
    dict
        Keys:
        - 'top': stats dict for top-N rockets
        - 'full': stats dict for full population
        - 'summary': plain-English summary string
        Each stats dict has: score (mean/median/max/pct_zeros),
        n_stages (mean/dist), n_parts (mean), engines/tanks/pods (Counters).
    """
    sorted_pop = sorted(population, key=lambda x: x[1]['score'], reverse=True)
    top = sorted_pop[:top_n]

    top_stats = _group_stats(top)
    pop_stats = _group_stats(sorted_pop)

    summary = _make_summary(top_stats, pop_stats, top_n, len(population))

    if verbose:
        print(summary)

    return {
        'top': top_stats,
        'full': pop_stats,
        'summary': summary,
    }


def inspect_top_rockets(run_dir, generation=None, top_n=5):
    """Print top-N rocket compositions from a saved GA run generation file.

    Parameters
    ----------
    run_dir : str or Path
        Directory containing gen_NNN.json files.
    generation : int, optional
        Specific generation number to inspect. If None, uses the latest file.
    top_n : int, optional
        Number of top-scoring rockets to print. Default 5.
    """
    run_dir = Path(run_dir)
    gen_files = sorted(run_dir.glob('gen_*.json'))
    if not gen_files:
        print('no generation files found')
        return

    target = gen_files[-1] if generation is None else run_dir / f'gen_{generation:03d}.json'
    data = json.loads(target.read_text())
    rockets = sorted(data['rockets'], key=lambda r: r['meta']['score'], reverse=True)

    print(f'file: {target}')
    print(f'generation: {data["generation"]}')
    print()

    for i, rec in enumerate(rockets[:top_n], start=1):
        rocket = rec['rocket']
        meta = rec['meta']

        engines = [p['type'] for p in rocket['parts'] if p['id'].startswith('eng_')]
        tanks = [p['type'] for p in rocket['parts'] if p['id'].startswith('tank_')]

        print(f'=== TOP {i} ===')
        print(f'score:    {meta["score"]:.1f}')
        print(f'engines:  {engines}')
        print(f'tanks:    {tanks}')
        print(f'stages:   {sorted(set(rocket["stages"].values()))}')
        print(f'stage_dv: {meta.get("stage_dv")}')
        print('parts:')
        for part in rocket['parts']:
            stage = rocket['stages'].get(part['id'])
            parent = str(part['parent'])
            print(f'  {part["id"]:12s} {part["type"]:20s} parent={parent:12s} stage={stage}')
        print()
