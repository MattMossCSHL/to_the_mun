import math


DV_THRESHOLDS = {
    'atmosphere': 1800,
    'orbit': 3400,
    'mun_orbit': 4300,
    'mun_landing': 5700
}


def get_total_mass(parts_list: list,
                   parts_dict: dict,
                   fuel_lookup: dict):
    """Return total wet mass (dry + fuel) in tonnes for a list of part type strings."""

    total_dry_mass = 0
    for part in parts_list:
        mass = parts_dict[part]['mass_t']
        total_dry_mass += mass

    total_fuel_mass = 0
    for part in parts_list:
        part_entry = parts_dict[part]
        if part_entry['resources'] is not None:
            for resource in part_entry['resources'].keys():
                units = part_entry['resources'][resource]
                conversion = fuel_lookup[resource]['density']
                mass = units * conversion
                total_fuel_mass += mass

    total_mass = total_dry_mass + total_fuel_mass
    return total_mass


def calculate_thrust(parts_list: list,
                   parts_dict: dict):
    """Return total max thrust in kN across all engines in parts_list."""

    total_thrust = 0
    for part in parts_list:
        part_entry = parts_dict[part]
        if part_entry['engine'] is not None:
            thrust = part_entry['engine']['max_thrust_kn']
            total_thrust += thrust

    return total_thrust


def calculate_twr(parts_list: list,
                  parts_dict: dict,
                  fuel_lookup: dict,
                  g_const: float = 9.80665):
    """Return thrust-to-weight ratio at launch (sea level, full propellant load)."""

    mass = get_total_mass(parts_list, parts_dict, fuel_lookup)
    thrust = calculate_thrust(parts_list, parts_dict)
    twr = thrust / (mass * g_const)

    return twr


def compute_delta_v(rocket_dict: dict,
                    parts_list: list,
                    parts_dict: dict,
                    resource_lookup: dict,
                    g_const: float = 9.80665,
                    verbose: bool = False):
    """
    Return total delta-v in m/s using the Tsiolkovsky rocket equation, summed across all stages.

    Stages are processed from highest stage number to lowest (first to fire → last to fire).
    For each stage: fuel mass is computed by walking the part tree from the engine toward the root,
    accumulating propellant mass until a Decoupler is encountered. After each stage, jettisoned
    parts (decoupler + all descendants) are subtracted from the running wet mass.
    """

    m_wet = get_total_mass(parts_list, parts_dict, resource_lookup)
    total_dv = 0

    # parts lookup by id
    id_to_type = {p['id']: p['type'] for p in rocket_dict['parts']}
    #parent lookup by id for trace
    id_to_parent = {p['id']: p['parent'] for p in rocket_dict['parts']}
    #child lookup by id for reverse order trace
    id_to_children = {}
    for part in rocket_dict['parts']:
        if part['parent'] is not None:
            if part['parent'] not in id_to_children:
                id_to_children[part['parent']] = []
            id_to_children[part['parent']].append(part['id']) # the above 3 lines could be id_to_children.setdefault(p['parent'], []).append(p['id']), but i did not know this

    for stage_num in sorted(set(rocket_dict['stages'].values()), reverse = True):
        engine_id = None
        decoupler_id = None

        for part_id, stage in rocket_dict['stages'].items():
            if stage == stage_num:
                part_type = id_to_type[part_id]
                if parts_dict[part_type]['engine'] is not None:
                    engine_id = part_id
                if part_type.startswith('Decoupler'):
                    decoupler_id = part_id
        if verbose:
            print(engine_id, decoupler_id)

        if engine_id is None:
            continue

        fuel_mass = 0

        propellants = parts_dict[id_to_type[engine_id]]['engine']['propellants'].keys()
        current = engine_id
        while current is not None:
            current_type = id_to_type[current]
            if current_type.startswith('Decoupler'):
                break
            part_resources = parts_dict[current_type]['resources']
            if part_resources is not None:
                for resource, amount in part_resources.items():
                    if resource in propellants:
                        fuel_mass += amount * resource_lookup[resource]['density']
                        if verbose:
                            print(f'current fuel mass is {fuel_mass}')
            current = id_to_parent[current]

        ### delta_v calculation
        engine_type = id_to_type[engine_id]
        isp = parts_dict[engine_type]['engine']['isp']['vacuum']
        m_dry = m_wet - fuel_mass
        dv = isp * g_const * math.log(m_wet / m_dry)
        total_dv += dv
        if verbose:
            print(f"stage {stage_num}: isp={isp}, m_wet={m_wet:.3f}, m_dry={m_dry:.3f}, dv={dv:.1f}")

        if decoupler_id is not None:
            to_visit = [decoupler_id]
            jettisoned = []
            while to_visit:
                current = to_visit.pop()
                jettisoned.append(current)
                to_visit.extend(id_to_children.get(current, []))

            jettisoned_mass = sum(parts_dict[id_to_type[pid]]['mass_t'] for pid in jettisoned)
            m_wet = m_dry - jettisoned_mass
            if verbose:
                print(f"  jettisoned {jettisoned}, dry mass={jettisoned_mass:.3f}t, new m_wet={m_wet:.3f}")
        else:
            m_wet = m_dry

    return total_dv


def compute_burn_time(rocket_dict: dict,
                    parts_list: list,
                    parts_dict: dict,
                    resource_lookup: dict,
                    g_const: float = 9.80665,
                    verbose: bool = False):
    """
    Return a dict of {stage_num: burn_time_seconds} for each staged engine.

    Burn time per stage = fuel_mass * isp * g0 / thrust.
    Stages are processed from highest stage number to lowest.
    """

    burn_times = {}

    # parts lookup by id
    id_to_type = {p['id']: p['type'] for p in rocket_dict['parts']}
    #parent lookup by id for trace
    id_to_parent = {p['id']: p['parent'] for p in rocket_dict['parts']}

    for stage_num in sorted(set(rocket_dict['stages'].values()), reverse = True):
        engine_id = None

        for part_id, stage in rocket_dict['stages'].items():
            if stage == stage_num:
                part_type = id_to_type[part_id]
                if parts_dict[part_type]['engine'] is not None:
                    engine_id = part_id
        if verbose:
            print(engine_id)

        if engine_id is None:
            continue

        fuel_mass = 0

        propellants = parts_dict[id_to_type[engine_id]]['engine']['propellants'].keys()
        current = engine_id
        while current is not None:
            current_type = id_to_type[current]
            if current_type.startswith('Decoupler'):
                break
            part_resources = parts_dict[current_type]['resources']
            if part_resources is not None:
                for resource, amount in part_resources.items():
                    if resource in propellants:
                        fuel_mass += amount * resource_lookup[resource]['density']
                        if verbose:
                            print(f'current fuel mass is {fuel_mass}')
            current = id_to_parent[current]

        ### burn time calculation
        engine_type = id_to_type[engine_id]
        isp = parts_dict[engine_type]['engine']['isp']['vacuum']

        thrust = parts_dict[id_to_type[engine_id]]['engine']['max_thrust_kn']
        burn_time = fuel_mass * isp * g_const / thrust
        burn_times[stage_num] = burn_time
        if verbose:
            print(f"  stage {stage_num}, fuel ={fuel_mass:.3f}, thrust ={thrust:.3f}, burn_time = {burn_time:.1f}s")

    return burn_times


def filter_rocket(rocket_dict: dict,
                    parts_list: list,
                    parts_dict: dict,
                    resource_lookup: dict,
                    dv_thresholds: dict,
                    goal: str =  'orbit',
                    g_const: float = 9.80665,
                    verbose: bool = False):
    """
    Run all three analytic filters and return (passed, reasons).

    passed: True if all checks pass, False otherwise.
    reasons: list of failure reason strings (empty if passed).

    Checks:
      - TWR >= 1.2 at launch
      - total delta-v >= dv_thresholds[goal]
      - per-stage burn time >= 5.0 seconds
    """

    dv_goal = dv_thresholds[goal]

    twr = calculate_twr(parts_list, parts_dict, resource_lookup)
    dv = compute_delta_v(rocket_dict, parts_list, parts_dict, resource_lookup, g_const = g_const)
    burn_time = compute_burn_time(rocket_dict, parts_list, parts_dict, resource_lookup, g_const = g_const)

    checks = [
          (twr < 1.2,  f"TWR too low: {twr:.2f}"),
          (dv < dv_goal, f"insufficient delta-v: {dv:.0f} m/s")
    ]

    reasons = []
    for condition, message in checks:
          if condition:
              reasons.append(message)
              if verbose:
                  print(f"FAIL: {message}")
    for stage_num, t in burn_time.items():
        if t < 5.0:
            reasons.append(f"stage {stage_num} burn time too short: {t:.1f}s")
    return (len(reasons) == 0, reasons)
