"""
genetic_algorithm.py — GA functions for generating and evolving rocket designs.

Functions
---------
generate_random_rocket  : build a random rocket dict (no validation)
score_rocket            : fitness function — returns delta-v or 0
evaluate_population     : generate and score n rockets, returns list of (rocket, meta) tuples
tournament_select       : select survivors via tournament selection
mutate_swap_part        : replace a random non-pod part with another of the same type
mutate_add_stage        : append a new decoupler+tank+engine stage to the bottom
mutate_remove_stage     : drop the bottom stage entirely
"""

import copy
import random

from src.rocket import Rocket
from src.structure import validate_rocket
from src.filters import filter_rocket, compute_delta_v, DV_THRESHOLDS


def generate_random_rocket(parts_by_name: dict,
                           pods: list,
                           tanks: list,
                           engines: list,
                           decouplers: list,
                           max_stages: int = 2):
    """Build a random rocket dict with no validation or filtering.

    Constructs a vertical stack top-down: pod → (tank → engine → [decoupler]) × n_stages.
    All parts attach via attach_node='bottom'. Stage 0 fires last (top stage),
    highest stage number fires first (bottom booster).

    Parameters
    ----------
    parts_by_name : dict
        Full parts library keyed by part name.
    pods : list
        Part names with category 'Pods'.
    tanks : list
        Part names with resources and no engine.
    engines : list
        Part names with an engine field.
    decouplers : list
        Part names starting with 'Decoupler_'.
    max_stages : int, optional
        Maximum number of stages. Actual count is random in [1, max_stages].

    Returns
    -------
    dict
        Rocket dict with 'parts' and 'stages' fields.
    """
    r = Rocket(parts_by_name)

    pod = random.choice(pods)
    r.add_part('pod_0', pod, parent=None)

    tank_count = engine_count = decoupler_count = 0

    n_stages = random.randint(1, max_stages)
    current_parent = 'pod_0'
    for stage in range(n_stages):
        stage_num = stage
        tank = random.choice(tanks)
        r.add_part(f'tank_{tank_count}', tank, parent=current_parent, attach_node='bottom')
        current_parent = f'tank_{tank_count}'
        tank_count += 1

        engine = random.choice(engines)
        r.add_part(f'eng_{engine_count}', engine, parent=current_parent, attach_node='bottom')
        r.set_stage(f'eng_{engine_count}', stage_num)
        current_parent = f'eng_{engine_count}'
        engine_count += 1
        if stage != n_stages - 1:
            decup = random.choice(decouplers)
            r.add_part(f'decoupler_{decoupler_count}', decup, parent=current_parent, attach_node='bottom')
            r.set_stage(f'decoupler_{decoupler_count}', stage + 1)
            current_parent = f'decoupler_{decoupler_count}'
            decoupler_count += 1

    return r.to_dict()


def score_rocket(rocket_dict: dict,
                 parts_by_name: dict,
                 resource_lookup: dict):
    """Score a rocket by its total delta-v, or 0 if it fails any check.

    Runs validate_rocket then filter_rocket. If either fails, returns 0.
    Otherwise returns compute_delta_v as the fitness score.

    Parameters
    ----------
    rocket_dict : dict
        Rocket dict with 'parts' and 'stages' fields.
    parts_by_name : dict
        Full parts library keyed by part name.
    resource_lookup : dict
        Resource densities as returned by load_resource_lookup().

    Returns
    -------
    float
        Total delta-v in m/s, or 0 if the rocket fails validation or filters.
    """
    parts_list = [p['type'] for p in rocket_dict['parts']]
    is_valid = validate_rocket(rocket_dict, parts_by_name)
    is_filtered, errors = filter_rocket(rocket_dict, parts_list, parts_by_name, resource_lookup, DV_THRESHOLDS)
    if not is_valid or not is_filtered:
        return 0
    score = compute_delta_v(rocket_dict, parts_list, parts_by_name, resource_lookup)
    return score


def evaluate_population(n_rockets: int,
                        parts_by_name: dict,
                        resource_lookup: dict,
                        pods: list,
                        tanks: list,
                        engines: list,
                        decouplers: list,
                        max_stages: int = 2,
                        generation: int = 0,
                        detailed: bool = False):
    """Generate and score a population of random rockets.

    Returns a list of (rocket_dict, meta) tuples. meta always contains 'score'.
    When detailed=True, meta also contains 'valid', 'filtered', 'n_stages',
    'n_parts', 'stage_dv', and 'generation'.

    Parameters
    ----------
    n_rockets : int
        Number of rockets to generate.
    parts_by_name : dict
        Full parts library keyed by part name.
    resource_lookup : dict
        Resource densities as returned by load_resource_lookup().
    pods : list
        Part names with category 'Pods'.
    tanks : list
        Part names with resources and no engine.
    engines : list
        Part names with an engine field.
    decouplers : list
        Part names starting with 'Decoupler_'.
    max_stages : int, optional
        Maximum number of stages per rocket.
    generation : int, optional
        Generation number, stored in detailed metadata.
    detailed : bool, optional
        If True, include full metadata breakdown in each tuple.

    Returns
    -------
    list
        List of (rocket_dict, meta) tuples.
    """
    population = []
    for r in range(n_rockets):
        rocket = generate_random_rocket(parts_by_name, pods, tanks, engines, decouplers, max_stages=max_stages)
        valid = validate_rocket(rocket, parts_by_name)
        parts_list = [p['type'] for p in rocket['parts']]
        filtered, reasons = filter_rocket(rocket, parts_list, parts_by_name, resource_lookup, DV_THRESHOLDS)

        if valid and filtered:
            stage_dvs = compute_delta_v(rocket, parts_list, parts_by_name, resource_lookup, return_breakdown=True)
            score = sum(stage_dvs.values())
        else:
            score = 0
            stage_dvs = {}

        if not detailed:
            meta = {'score': score}
        else:
            meta = {'score': score,
                    'valid': valid,
                    'filtered': filtered,
                    'n_stages': len(set(rocket['stages'].values())),
                    'n_parts': len(parts_list),
                    'stage_dv': stage_dvs,
                    'generation': generation
                    }
        population.append((rocket, meta))
    return population


def tournament_select(population: list,
                      pct_survivors: float = 0.5,
                      tournament_size: int = 3):
    """Select survivors from a population using tournament selection.

    Repeats n_survivors times: draws tournament_size random candidates,
    appends the one with the highest meta['score'] to survivors.
    Selection is with replacement — the same rocket can win multiple rounds.

    Parameters
    ----------
    population : list
        List of (rocket_dict, meta) tuples.
    pct_survivors : float, optional
        Fraction of population to select. Default 0.5.
    tournament_size : int, optional
        Number of candidates per tournament round. Default 3.

    Returns
    -------
    list
        List of (rocket_dict, meta) tuples, length int(len(population) * pct_survivors).
    """
    n_survivors = int(len(population) * pct_survivors)
    survivors = []
    while len(survivors) < n_survivors:
        competitors = random.choices(population, k=tournament_size)
        winner = max(competitors, key=lambda x: x[1]['score'])
        survivors.append(winner)
    return survivors


def mutate_swap_part(rocket_dict: dict,
                     pods: list,
                     tanks: list,
                     engines: list,
                     decouplers: list):
    """Replace a random non-pod part with a different part of the same category.

    Deepcopies the rocket before modifying. Excludes pod_0 from candidates.
    Category is determined by membership in pods/tanks/engines/decouplers lists.

    Parameters
    ----------
    rocket_dict : dict
        Rocket dict with 'parts' and 'stages' fields.
    pods : list
        Part names with category 'Pods'.
    tanks : list
        Part names with resources and no engine.
    engines : list
        Part names with an engine field.
    decouplers : list
        Part names starting with 'Decoupler_'.

    Returns
    -------
    dict
        New rocket dict with one part type swapped.
    """
    new_rocket = copy.deepcopy(rocket_dict)
    parts_list = [p for p in rocket_dict['parts'] if p['id'] != 'pod_0']
    rand_part = random.choice(parts_list)
    rand_part_type = rand_part['type']
    rand_part_id = rand_part['id']
    if rand_part_type in pods:
        swap = random.choice(pods)
    if rand_part_type in engines:
        swap = random.choice(engines)
    if rand_part_type in tanks:
        swap = random.choice(tanks)
    if rand_part_type in decouplers:
        swap = random.choice(decouplers)

    for i, p in enumerate(new_rocket['parts']):
        if p['id'] == rand_part_id:
            new_rocket['parts'][i]['type'] = swap
            break
    return new_rocket


def mutate_add_stage(rocket_dict: dict,
                     tanks: list,
                     engines: list,
                     decouplers: list,
                     max_stages: int = 4):
    """Append a new decoupler+tank+engine stage to the bottom of the rocket.

    Returns an unchanged copy if the rocket is already at max_stages.
    New part IDs are derived from counts of existing parts to avoid collisions.

    Parameters
    ----------
    rocket_dict : dict
        Rocket dict with 'parts' and 'stages' fields.
    tanks : list
        Part names with resources and no engine.
    engines : list
        Part names with an engine field.
    decouplers : list
        Part names starting with 'Decoupler_'.
    max_stages : int, optional
        Maximum number of stages allowed. Default 4.

    Returns
    -------
    dict
        New rocket dict with one stage added, or unchanged copy if at max_stages.
    """
    new_rocket = copy.deepcopy(rocket_dict)
    n_stages = max(new_rocket['stages'].values())
    if len(set(new_rocket['stages'].values())) == max_stages:
        return new_rocket

    all_ids = {p['id'] for p in new_rocket['parts']}
    parent_ids = {p['parent'] for p in new_rocket['parts'] if p['parent'] is not None}
    bottom_id = (all_ids - parent_ids).pop()

    new_tank = random.choice(tanks)
    new_engine = random.choice(engines)
    new_decoupler = random.choice(decouplers)

    next_stage = n_stages + 1

    n_decouplers = sum(1 for p in new_rocket['parts'] if p['id'].startswith('decoupler_'))
    n_tanks = sum(1 for p in new_rocket['parts'] if p['id'].startswith('tank_'))
    n_engines = sum(1 for p in new_rocket['parts'] if p['id'].startswith('eng_'))

    new_rocket['parts'].append({'id': f"decoupler_{n_decouplers}", 'type': new_decoupler, 'parent': bottom_id, 'attach_node': 'bottom'})
    new_rocket['parts'].append({'id': f"tank_{n_tanks}", 'type': new_tank, 'parent': f"decoupler_{n_decouplers}", 'attach_node': 'bottom'})
    new_rocket['parts'].append({'id': f"eng_{n_engines}", 'type': new_engine, 'parent': f"tank_{n_tanks}", 'attach_node': 'bottom'})

    new_rocket['stages'][f"decoupler_{n_decouplers}"] = next_stage
    new_rocket['stages'][f"eng_{n_engines}"] = next_stage

    return new_rocket


def mutate_remove_stage(rocket_dict: dict):
    """Drop the bottom stage from a rocket.

    Returns an unchanged copy if the rocket has only one stage.
    Removes the bottom engine, its parent tank, and the decoupler above the tank.

    Parameters
    ----------
    rocket_dict : dict
        Rocket dict with 'parts' and 'stages' fields.

    Returns
    -------
    dict
        New rocket dict with the bottom stage removed, or unchanged copy if single-stage.
    """
    new_rocket = copy.deepcopy(rocket_dict)
    id_to_parent = {p['id']: p['parent'] for p in new_rocket['parts']}
    n_stages = max(new_rocket['stages'].values())
    if n_stages == 0:
        return new_rocket

    all_ids = {p['id'] for p in new_rocket['parts']}
    parent_ids = {p['parent'] for p in new_rocket['parts'] if p['parent'] is not None}
    bottom_id = (all_ids - parent_ids).pop()

    bottom_tank = id_to_parent[bottom_id]
    bottom_decoupler = id_to_parent[bottom_tank]
    to_remove = {bottom_id, bottom_tank, bottom_decoupler}

    new_rocket['parts'] = [p for p in new_rocket['parts'] if p['id'] not in to_remove]
    for pid in to_remove:
        new_rocket['stages'].pop(pid, None)

    return new_rocket
