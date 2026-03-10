"""
genetic_algorithm.py — GA functions for generating and evolving rocket designs.

Functions
---------
generate_random_rocket  : build a random rocket dict (no validation)
score_rocket            : fitness function — returns delta-v or 0
"""

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
