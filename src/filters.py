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


# def compute_delta_v(rocket_dict: dict,
#                     parts_list: list,
#                     parts_dict: dict,
#                     resource_lookup: dict,
#                     g_const: float = 9.80665,
#                     return_breakdown = False,
#                     verbose: bool = False):
#     """
#     Previous version: pure stage-by-stage Tsiolkovsky rocket equation using vacuum Isp.
#
#     This version treated every engine as if it could burn all staged propellant with its
#     vacuum performance, which over-credited air-breathing engines and let jet rockets
#     exploit the GA scoring function.
#     """
#
#     m_wet = get_total_mass(parts_list, parts_dict, resource_lookup)
#     total_dv = 0
#     stage_dvs = {}
#     id_to_type = {p['id']: p['type'] for p in rocket_dict['parts']}
#     id_to_parent = {p['id']: p['parent'] for p in rocket_dict['parts']}
#     id_to_children = {}
#
#     for part in rocket_dict['parts']:
#         if part['parent'] is not None:
#             if part['parent'] not in id_to_children:
#                 id_to_children[part['parent']] = []
#             id_to_children[part['parent']].append(part['id'])
#
#     for stage_num in sorted(set(rocket_dict['stages'].values()), reverse=True):
#         engine_id = None
#         decoupler_id = None
#
#         for part_id, stage in rocket_dict['stages'].items():
#             if stage == stage_num:
#                 part_type = id_to_type[part_id]
#                 if parts_dict[part_type]['engine'] is not None:
#                     engine_id = part_id
#                 if part_type.startswith('Decoupler'):
#                     decoupler_id = part_id
#
#         if engine_id is None:
#             continue
#
#         fuel_mass = 0
#         propellants = parts_dict[id_to_type[engine_id]]['engine']['propellants'].keys()
#         current = engine_id
#
#         while current is not None:
#             current_type = id_to_type[current]
#             if current_type.startswith('Decoupler'):
#                 break
#             part_resources = parts_dict[current_type]['resources']
#             if part_resources is not None:
#                 for resource, amount in part_resources.items():
#                     if resource in propellants:
#                         fuel_mass += amount * resource_lookup[resource]['density']
#             current = id_to_parent[current]
#
#         engine_type = id_to_type[engine_id]
#         isp = parts_dict[engine_type]['engine']['isp']['vacuum']
#         m_dry = m_wet - fuel_mass
#         if m_dry <= 0:
#             break
#         dv = isp * g_const * math.log(m_wet / m_dry)
#         stage_dvs[stage_num] = dv
#         total_dv += dv
#
#         if decoupler_id is not None:
#             to_visit = [decoupler_id]
#             jettisoned = []
#             while to_visit:
#                 current = to_visit.pop()
#                 jettisoned.append(current)
#                 to_visit.extend(id_to_children.get(current, []))
#
#             jettisoned_mass = sum(parts_dict[id_to_type[pid]]['mass_t'] for pid in jettisoned)
#             m_wet = m_dry - jettisoned_mass
#         else:
#             m_wet = m_dry
#
#     if return_breakdown:
#         return stage_dvs
#     return total_dv


def is_air_breathing_engine(part: dict,
                            parts_by_name: dict):
    """Return True if this part is an engine that consumes IntakeAir."""

    if not part['id'].startswith('eng_'):
        return False

    part_data = parts_by_name[part['type']]
    engine_data = part_data.get('engine')
    if engine_data is None:
        return False

    propellants = engine_data.get('propellants', {})
    return 'IntakeAir' in propellants


def stage_has_air_breathing_engine(stage_parts: list,
                                   parts_by_name: dict):
    """Return True if any part in this stage is an air-breathing engine."""

    return any(is_air_breathing_engine(part, parts_by_name) for part in stage_parts)


def compute_delta_v(rocket_dict: dict,
                    parts_list: list,
                    parts_dict: dict,
                    resource_lookup: dict,
                    g_const: float = 9.80665,
                    return_breakdown=False,
                    verbose: bool = False):
    """
    Return total delta-v in m/s, with special handling for air-breathing stages.

    The previous implementation used the Tsiolkovsky rocket equation with vacuum Isp for
    every stage, which badly overestimated jet engines because it assumed they could burn
    staged propellant all the way to space. This version keeps the same normal rocket-stage
    calculation, but air-breathing stages now use a rough ascent estimate with a 25 km jet
    ceiling and a conservative atmospheric-Isp fallback when sea-level Isp is missing.

    If return_breakdown=True, returns a dict of {stage_num: dv} instead of the total float.
    """

    altitude = 0
    velocity = 0
    m_wet = get_total_mass(parts_list, parts_dict, resource_lookup)
    total_dv = 0
    stage_dvs = {}

    burn_times = compute_burn_time(rocket_dict, parts_list, parts_dict, resource_lookup)

    id_to_type = {p['id']: p['type'] for p in rocket_dict['parts']}
    id_to_parent = {p['id']: p['parent'] for p in rocket_dict['parts']}
    id_to_children = {}

    for part in rocket_dict['parts']:
        if part['parent'] is not None:
            if part['parent'] not in id_to_children:
                id_to_children[part['parent']] = []
            id_to_children[part['parent']].append(part['id'])

    for stage_num in sorted(set(rocket_dict['stages'].values()), reverse=True):
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

        stage_parts = [
            part for part in rocket_dict['parts']
            if rocket_dict['stages'].get(part['id']) == stage_num
        ]

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

        engine_type = id_to_type[engine_id]
        thrust = parts_dict[engine_type]['engine']['max_thrust_kn']
        is_air_breathing = stage_has_air_breathing_engine(stage_parts, parts_dict)

        if is_air_breathing:
            isp_data = parts_dict[engine_type]['engine']['isp']
            sea_level_isp = isp_data.get('sea_level')
            if sea_level_isp is not None:
                isp = sea_level_isp
            else:
                isp = 0.2 * isp_data.get('vacuum')
        else:
            isp = parts_dict[engine_type]['engine']['isp']['vacuum']

        burn_time = burn_times[stage_num]
        m_dry = m_wet - fuel_mass
        if m_dry <= 0:
            break

        avg_mass = 0.5 * (m_wet + m_dry)

        if is_air_breathing:
            jet_ceiling = 25000
            accel = (thrust / avg_mass) - g_const

            if altitude >= jet_ceiling:
                dv = 0
            else:
                end_altitude = altitude + (velocity * burn_time) + (0.5 * accel * burn_time**2)

                if end_altitude <= jet_ceiling:
                    dv = isp * g_const * math.log(m_wet / m_dry)
                    velocity = velocity + (accel * burn_time)
                    altitude = end_altitude
                else:
                    a = 0.5 * accel
                    b = velocity
                    c = altitude - jet_ceiling

                    discriminant = b**2 - (4 * a * c)
                    t_to_ceiling = (-b + math.sqrt(discriminant)) / (2 * a)

                    burn_fraction = t_to_ceiling / burn_time
                    fuel_used = fuel_mass * burn_fraction
                    m_partial_dry = m_wet - fuel_used

                    dv = isp * g_const * math.log(m_wet / m_partial_dry)
                    velocity = velocity + (accel * t_to_ceiling)
                    altitude = jet_ceiling
                    m_dry = m_partial_dry
        else:
            dv = isp * g_const * math.log(m_wet / m_dry)
            accel = (thrust / avg_mass) - g_const
            altitude += (velocity * burn_time) + (0.5 * accel * burn_time**2)
            velocity += (accel * burn_time)

        stage_dvs[stage_num] = dv
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

    if return_breakdown:
        return stage_dvs
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
