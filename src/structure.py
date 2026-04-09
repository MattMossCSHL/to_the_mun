"""
structure.py — structural validity checks for KSP rocket designs.

A rocket design is represented as a plain Python dict (or loaded from JSON):

    {
        "parts": [
            {"id": "pod_0",  "type": "mk1-3pod",      "parent": None},
            {"id": "tank_0", "type": "fuelTank",       "parent": "pod_0",  "attach_node": "bottom"},
            {"id": "eng_0",  "type": "liquidEngine",   "parent": "tank_0", "attach_node": "bottom"},
        ],
        "stages": {"eng_0": 0}
    }

Each part has:
    id          : str       — unique identifier within this rocket
    type        : str       — KSP internal part name (must exist in parts library)
    parent      : str|None  — id of the parent part, or None for the root
    attach_node : str       — name of the node on the PARENT part this attaches to
                              (omitted for the root part)

stages maps part ids to stage numbers (non-negative ints). Stage 0 fires last;
higher numbers fire first. Only parts that are activated via staging need an entry
(engines, decouplers). KSP-specific constraint: loops are not allowed in the part
tree, unlike real rockets which may have structural loops.

The parts library (parts_dict) is a dict keyed by internal part name, as produced
by src/scraper.py and saved to data/parts_library.json.

Intended usage:
    from src.structure import validate_rocket
    is_valid = validate_rocket(rocket_dict, parts_by_name, verbose=True)
"""

from src.config import load_resource_lookup

RESOURCE_LOOKUP = load_resource_lookup()


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_part_call(part: str,
                    parts_by_name_dict: dict):
    """
    Check that a single part type exists in the parts library.

    Parameters
    ----------
    part : str
        The internal KSP part name to look up (e.g. 'liquidEngine').
    parts_by_name_dict : dict
        Parts library keyed by internal part name, as produced by scraper.py.

    Returns
    -------
    bool
        True if the part type exists in the library, False otherwise.
    """
    if part not in parts_by_name_dict:
        return False
    else:
        return True


def check_single_root(rocket_dict: dict):
    """
    Check that exactly one part has no parent (the root of the part tree).

    A valid KSP rocket has exactly one root part — the topmost part of the
    stack (usually a command pod or probe core). Zero roots means no part
    anchors the tree; multiple roots means the design is disconnected.

    Parameters
    ----------
    rocket_dict : dict
        Rocket design dict with a 'parts' list.

    Returns
    -------
    bool
        True if exactly one part has parent=None, False otherwise.
    """
    num_no_parents = 0
    for part in rocket_dict['parts']:
        if part['parent'] is None:
            num_no_parents += 1

    if num_no_parents != 1:
        return False
    return True


def check_has_command(rocket_dict: dict,
                      parts_dict: dict):
    """
    Check that at least one part in the rocket has a command module.

    A controllable rocket requires at least one part with ModuleCommand
    (a crewed pod or a probe core). Without it the rocket cannot be steered.

    Parameters
    ----------
    rocket_dict : dict
        Rocket design dict with a 'parts' list.
    parts_dict : dict
        Parts library keyed by internal part name.

    Returns
    -------
    bool
        True if at least one part has is_command=True, False otherwise.
    """
    command_count = 0
    for part in rocket_dict['parts']:
        part_name = part['type']
        part_info = parts_dict[part_name]
        is_command = part_info['is_command']
        if is_command:
            command_count += 1
    if command_count > 0:
        return True
    return False


def check_has_engine(rocket_dict: dict,
                     parts_dict: dict):
    """
    Check that at least one part in the rocket is an engine.

    A rocket with no engine cannot produce thrust and cannot reach orbit.

    Parameters
    ----------
    rocket_dict : dict
        Rocket design dict with a 'parts' list.
    parts_dict : dict
        Parts library keyed by internal part name.

    Returns
    -------
    bool
        True if at least one part has engine data, False otherwise.
    """
    engine_count = 0
    for part in rocket_dict['parts']:
        part_name = part['type']
        part_info = parts_dict[part_name]
        is_engine = part_info['engine']
        if is_engine:
            engine_count += 1
    if engine_count > 0:
        return True
    return False


def has_minimal_structure(rocket_dict: dict,
                          parts_dict: dict):
    """
    Check the three minimum structural requirements: root, command, engine.

    Convenience wrapper combining check_single_root, check_has_command,
    and check_has_engine. All three must pass.

    Parameters
    ----------
    rocket_dict : dict
        Rocket design dict with a 'parts' list.
    parts_dict : dict
        Parts library keyed by internal part name.

    Returns
    -------
    bool
        True if all three checks pass, False if any fail.
    """
    root_check = check_single_root(rocket_dict)
    command_check = check_has_command(rocket_dict, parts_dict)
    engine_check = check_has_engine(rocket_dict, parts_dict)
    valid_struct = all([root_check, command_check, engine_check])

    return valid_struct


def check_graph_connections(rocket_dict: dict,
                            parts_dict: dict,
                            verbose: bool = False):
    """
    Check that the part tree is fully connected and contains no cycles.

    Performs a breadth-first traversal starting from the root part, walking
    downward through parent->child relationships. Two properties are verified:

    - No cycles: KSP enforces a strict tree structure. Unlike real rockets
      which may have structural loops (crossbeams, trusses), KSP parts each
      have exactly one parent. A cycle would cause infinite traversal.

    - Full connectivity: every part must be reachable from the root. Any
      part not visited after traversal is an orphan disconnected from the tree.

    Parameters
    ----------
    rocket_dict : dict
        Rocket design dict with a 'parts' list.
    parts_dict : dict
        Parts library keyed by internal part name (unused, kept for consistent
        function signature across all checks).
    verbose : bool
        If True, prints the set of visited part ids on success.

    Returns
    -------
    bool
        True if the part tree is connected and cycle-free, False otherwise.
    """
    all_parts = {part['id'] for part in rocket_dict['parts']}
    root_id = next(part['id'] for part in rocket_dict['parts'] if part['parent'] is None)
    children = {part['id']: [] for part in rocket_dict['parts']}
    for part in rocket_dict['parts']:
        if part['parent'] is not None:
            children[part['parent']].append(part['id'])

    queue = [root_id]
    visited = set()

    while queue:
        current = queue.pop(0)
        visited.add(current)
        for child in children[current]:  ##### Note: this is a check of circularity because KSP enforces a linear graph structure on its rockets. This would not exist on a real rocket that has various circular systems
            if child in visited:
                return False
            else:
                queue.append(child)

    if visited != all_parts:
        return False
    if verbose:
        print(visited)
        return True
    return True


def check_propellant(rocket_dict: dict,
                     parts_dict: dict):
    """
    Check that every engine's propellants are available somewhere in the rocket.

    Collects all resources stored across all parts (fuel tanks, SRBs, etc.)
    and checks that the union of required propellants is a subset of available
    resources. Note: SRBs carry SolidFuel internally in their resources field,
    so they pass this check automatically without a separate tank.

    Parameters
    ----------
    rocket_dict : dict
        Rocket design dict with a 'parts' list.
    parts_dict : dict
        Parts library keyed by internal part name.

    Returns
    -------
    bool
        True if all engine propellants are available in the rocket's resources,
        False if any engine needs a resource not present in any part.
    """
    available_resources = set()
    for part in rocket_dict['parts']:
        part_info = parts_dict[part['type']]
        if part_info['resources']:
            available_resources.update(part_info['resources'].keys())

    needed_propellants = set()
    for part in rocket_dict['parts']:
        if parts_dict[part['type']]['engine'] is not None:
            needed_propellants.update(parts_dict[part['type']]['engine']['propellants'].keys())
    if needed_propellants.issubset(available_resources):
        return True
    return False


def check_staging(rocket_dict: dict):
    """
    Check that all stage references are valid.

    Verifies two things:
    - Every part id referenced in 'stages' exists in the rocket's parts list.
    - Every stage number is a non-negative integer (stage 0 fires last,
      higher numbers fire first — KSP convention).

    Parameters
    ----------
    rocket_dict : dict
        Rocket design dict with a 'parts' list and a 'stages' dict.

    Returns
    -------
    bool
        True if all stage entries are valid, False otherwise.
    """
    all_parts = {part['id'] for part in rocket_dict['parts']}

    stages = set()
    for name, stage in rocket_dict['stages'].items():
        if not isinstance(stage, int) or stage < 0:
            return False
        stages.add(name)

    if stages.issubset(all_parts):
        return True
    return False


def check_valid_nodes(rocket_dict: dict,
                      parts_dict: dict):
    """
    Check that each part's attach_node exists on its parent part.

    For every non-root part, verifies that the node name given in
    'attach_node' is present in the parent part's nodes dict in the
    parts library. This ensures the physical attachment point exists
    on the parent and the connection is geometrically valid.

    Parameters
    ----------
    rocket_dict : dict
        Rocket design dict with a 'parts' list. Each non-root part must
        have an 'attach_node' field naming a node on the parent part.
    parts_dict : dict
        Parts library keyed by internal part name.

    Returns
    -------
    bool
        True if all attachment nodes are valid, False if any part references
        a node that doesn't exist on its parent.
    """
    id_to_type = {p['id']: p['type'] for p in rocket_dict['parts']}

    for part in rocket_dict['parts']:
        if part['parent'] == None:
            continue
        parent_type = id_to_type[part['parent']]
        if not isinstance(part['attach_node'], str):
            return False
        if part['attach_node'] not in parts_dict[parent_type]['nodes'].keys():
            return False
    return True


# ---------------------------------------------------------------------------
# Geometry helpers and filter
# ---------------------------------------------------------------------------

def build_part_lookup(rocket_dict: dict):
    """
    Map each placed part id to its full placed-part dict.

    Parameters
    ----------
    rocket_dict : dict
        Rocket design dict with a 'parts' list.

    Returns
    -------
    dict
        Mapping of placed part id to the corresponding placed-part dict.
    """
    part_lookup = {}

    for part in rocket_dict['parts']:
        part_id = part['id']
        part_lookup[part_id] = part

    return part_lookup


def build_children_lookup(rocket_dict: dict):
    """
    Map each placed part id to the ids of its direct children.

    Parameters
    ----------
    rocket_dict : dict
        Rocket design dict with a 'parts' list.

    Returns
    -------
    dict
        Mapping of placed part id to a list of direct child ids.
    """
    children_lookup = {}

    for part in rocket_dict['parts']:
        part_id = part['id']
        children_lookup[part_id] = []

    for part in rocket_dict['parts']:
        if part['parent'] is not None:
            parent_id = part['parent']
            child_id = part['id']

            children_lookup[parent_id].append(child_id)

    return children_lookup


def get_root_part_id(rocket_dict: dict):
    """
    Return the single root part id if exactly one root exists.

    Parameters
    ----------
    rocket_dict : dict
        Rocket design dict with a 'parts' list.

    Returns
    -------
    str or None
        The single root part id, or None if the rocket has zero or multiple roots.
    """
    root_ids = []
    for part in rocket_dict['parts']:
        if part['parent'] is None:
            root_ids.append(part['id'])

    if len(root_ids) != 1:
        return None
    return root_ids[0]


def get_inline_stack_ids(rocket_dict: dict):
    """
    Return the ordered top-to-bottom inline stack ids for a non-branching rocket.

    Parameters
    ----------
    rocket_dict : dict
        Rocket design dict with a 'parts' list.

    Returns
    -------
    list[str] or None
        Ordered part ids from root to tail for a clean inline chain, or None if
        the rocket has no single root or branches.
    """
    children_lookup = build_children_lookup(rocket_dict)
    root_id = get_root_part_id(rocket_dict)

    if root_id is None:
        return None

    stack_ids = []
    current_id = root_id

    while current_id is not None:
        stack_ids.append(current_id)

        children = children_lookup[current_id]

        if len(children) > 1:
            return None

        if len(children) == 0:
            current_id = None
        else:
            current_id = children[0]

    return stack_ids


def get_part_height(part_info: dict):
    """
    Estimate part height from the vertical distance between top and bottom nodes.

    Parameters
    ----------
    part_info : dict
        Parts-library entry for a single part type.

    Returns
    -------
    float or None
        Estimated inline height, or None if either top or bottom node is missing.
    """
    nodes = part_info['nodes']

    if 'top' not in nodes or 'bottom' not in nodes:
        return None

    top_position = nodes['top']['pos']
    bottom_position = nodes['bottom']['pos']

    top_y = top_position[1]
    bottom_y = bottom_position[1]

    return abs(top_y - bottom_y)


def get_part_diameter_proxy(part_info: dict):
    """
    Estimate part diameter from bulkhead profile classes or inline node sizes.

    Parameters
    ----------
    part_info : dict
        Parts-library entry for a single part type.

    Returns
    -------
    float or None
        Approximate stack diameter proxy in meters when bulkhead profiles are
        available, otherwise a positive inline node size proxy, or None if no
        usable diameter signal is present.
    """
    profile_sizes = {
        'size0': 0.625,
        'size1': 1.25,
        'size1p5': 1.875,
        'size2': 2.5,
        'size3': 3.75,
    }

    bulkhead_profiles = part_info['bulkhead_profiles']
    if bulkhead_profiles is not None:
        profile_diameters = []
        for profile in bulkhead_profiles:
            if profile in profile_sizes:
                profile_diameters.append(profile_sizes[profile])
        if len(profile_diameters) > 0:
            return max(profile_diameters)

    nodes = part_info['nodes']
    sizes = []

    if 'top' in nodes and nodes['top']['size'] > 0:
        sizes.append(nodes['top']['size'])

    if 'bottom' in nodes and nodes['bottom']['size'] > 0:
        sizes.append(nodes['bottom']['size'])

    if len(sizes) == 0:
        return None

    return max(sizes)


def get_part_mass_proxy(part_info: dict,
                        resource_lookup: dict):
    """
    Estimate wet part mass as dry mass plus stored resource mass.

    Parameters
    ----------
    part_info : dict
        Parts-library entry for a single part type.
    resource_lookup : dict
        Resource density lookup keyed by resource name.

    Returns
    -------
    float
        Approximate wet mass in tonnes.
    """
    total_mass = part_info['mass_t']

    if part_info['resources'] is not None:
        for resource_name, amount in part_info['resources'].items():
            density = resource_lookup[resource_name]['density']
            total_mass += amount * density
    return total_mass


def get_part_axial_com(part_info: dict):
    """
    Estimate the part center of mass along the part's own vertical axis.

    Parameters
    ----------
    part_info : dict
        Parts-library entry for a single part type.

    Returns
    -------
    float or None
        Local axial center-of-mass position, or None if the part lacks top or
        bottom nodes needed to define its inline axis.
    """
    nodes = part_info['nodes']

    if 'top' not in nodes or 'bottom' not in nodes:
        return None

    top_position = nodes['top']['pos']
    bottom_position = nodes['bottom']['pos']

    top_y = top_position[1]
    bottom_y = bottom_position[1]

    midpoint = (top_y + bottom_y) / 2

    if part_info['com_offset'] is not None:
        midpoint += part_info['com_offset'][1]

    return midpoint


def compute_geometry_metrics(rocket_dict: dict,
                             parts_dict: dict,
                             resource_lookup: dict):
    """
    Assemble first-pass inline geometry metrics for a rocket.

    Parameters
    ----------
    rocket_dict : dict
        Rocket design dict with a 'parts' list.
    parts_dict : dict
        Parts library keyed by internal part name.
    resource_lookup : dict
        Resource density lookup keyed by resource name.

    Returns
    -------
    dict or None
        Geometry metrics for a clean inline rocket, or None if the geometry
        cannot be reconstructed from the available data.
    """
    part_lookup = build_part_lookup(rocket_dict)
    stack_ids = get_inline_stack_ids(rocket_dict)

    if stack_ids is None:
        return None

    part_heights = []
    part_diameters = []
    part_masses = []
    part_axial_coms = []

    for part_id in stack_ids:
        placed_part = part_lookup[part_id]
        part_type = placed_part['type']
        part_info = parts_dict[part_type]

        height = get_part_height(part_info)
        diameter = get_part_diameter_proxy(part_info)
        mass = get_part_mass_proxy(part_info, resource_lookup)
        axial_com = get_part_axial_com(part_info)

        if height is None or diameter is None or axial_com is None:
            return None

        part_heights.append(height)
        part_diameters.append(diameter)
        part_masses.append(mass)
        part_axial_coms.append(axial_com)

    total_height = sum(part_heights)

    if total_height <= 0:
        return None

    diameter_transitions = []

    for item in range(len(part_diameters) - 1):
        current_diameter = part_diameters[item]
        next_diameter = part_diameters[item + 1]

        if current_diameter != next_diameter:
            transition_size = abs(next_diameter - current_diameter)
            diameter_transitions.append(transition_size)

    diameter_transition_count = len(diameter_transitions)
    diameter_transition_severity = sum(diameter_transitions)

    max_diameter = max(part_diameters)
    if max_diameter <= 0:
        return None

    slenderness_ratio = total_height / max_diameter

    global_part_coms = []
    current_top = 0

    for i in range(len(stack_ids)):
        part_height = part_heights[i]
        part_local_com = part_axial_coms[i]

        local_top_y = part_height / 2
        global_part_com = current_top + (local_top_y - part_local_com)

        global_part_coms.append(global_part_com)
        current_top += part_height

    total_mass = sum(part_masses)
    if total_mass <= 0:
        return None

    axial_center_of_mass = sum(
        part_mass * global_com for part_mass, global_com in zip(part_masses, global_part_coms)
    ) / total_mass

    center_of_mass_height_fraction = axial_center_of_mass / total_height

    return {
      "stack_ids": stack_ids,
      "part_heights": part_heights,
      "part_diameters": part_diameters,
      "part_masses": part_masses,
      "part_axial_coms": part_axial_coms,
      "total_height": total_height,
      "diameter_transitions": diameter_transitions,
      "diameter_transition_count": diameter_transition_count,
      "diameter_transition_severity": diameter_transition_severity,
      "axial_center_of_mass": axial_center_of_mass,
      "center_of_mass_height_fraction": center_of_mass_height_fraction,
      "slenderness_ratio": slenderness_ratio
    }


def check_geometry_filter(rocket_dict: dict,
                          parts_dict: dict,
                          resource_lookup: dict,
                          verbose: bool = False):
    """
    Apply the first-pass inline geometry filter to a rocket.

    Parameters
    ----------
    rocket_dict : dict
        Rocket design dict with a 'parts' list.
    parts_dict : dict
        Parts library keyed by internal part name.
    resource_lookup : dict
        Resource density lookup keyed by resource name.
    verbose : bool, optional
        If True, print the geometry metrics and any failed soft rules.

    Returns
    -------
    bool
        False on geometry reconstruction failure, or when two or more soft
        geometry rules fail. True otherwise.
    """
    metrics = compute_geometry_metrics(rocket_dict, parts_dict, resource_lookup)

    if metrics is None:
        if verbose:
            print("FAIL: could not reconstruct inline geometry")
        return False

    failed_rules = []

    if metrics["diameter_transition_count"] > 2:
        failed_rules.append("too many diameter transitions")

    if metrics["diameter_transition_severity"] > 2.5:
        failed_rules.append("severe diameter transitions")

    if metrics["slenderness_ratio"] > 9.0:
        failed_rules.append("extreme slenderness")

    if metrics["center_of_mass_height_fraction"] < 0.2:
        failed_rules.append("top-heavy mass distribution")

    if verbose:
        print("geometry metrics:", metrics)
        print("failed geometry rules:", failed_rules)

    if len(failed_rules) >= 2:
        if verbose:
            print("FAIL: geometry filter")
        return False

    return True


# ---------------------------------------------------------------------------
# Final validator
# ---------------------------------------------------------------------------

def validate_rocket(rocket_dict: dict,
                    parts_dict: dict,
                    verbose: bool = False):
    """
    Run all structural validity checks on a rocket design.

    Checks are run in order. The first check (valid part references) is a
    gate — if any part type is unknown, all subsequent checks are skipped
    since they depend on part library lookups.

    Checks performed (in order):
        1. All part types exist in the parts library (gate)
        2. Exactly one root, at least one command source, at least one engine
        3. Part tree is connected and cycle-free
        4. All engine propellants are available in the rocket's resources
        5. Stage references are valid non-negative integers for known parts
        6. Attachment nodes exist on the referenced parent parts

    Parameters
    ----------
    rocket_dict : dict
        Rocket design dict with 'parts' and 'stages' fields.
    parts_dict : dict
        Parts library keyed by internal part name.
    verbose : bool
        If True, prints which check failed and why before returning False.

    Returns
    -------
    bool
        True if the rocket passes all checks, False otherwise.
    """
    for part in rocket_dict['parts']:
        if not check_part_call(part['type'], parts_dict):
            if verbose:
                print(f"FAIL: unknown part type '{part['type']}'")
            return False
    geometry_check = check_geometry_filter(
        rocket_dict,
        parts_dict,
        RESOURCE_LOOKUP,
        verbose=verbose
    )
    if not geometry_check:
        if verbose:
            print('Failed geometry check')
        return False
    checks = [
          (has_minimal_structure(rocket_dict, parts_dict),  "missing root, command, or engine"),
          (check_graph_connections(rocket_dict, parts_dict), "part tree disconnected or has cycles"),
          (check_propellant(rocket_dict, parts_dict),        "propellant incompatibility"),
          (check_staging(rocket_dict),                       "invalid stage references"),
          (check_valid_nodes(rocket_dict, parts_dict),       "invalid attachment nodes"),
      ]
    for result, message in checks:
          if not result:
              if verbose:
                  print(f"FAIL: {message}")
              return False
    return True
