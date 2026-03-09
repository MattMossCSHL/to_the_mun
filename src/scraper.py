"""
scraper.py — functions for scraping structured data from KSP game files.

Currently supports KSP1 stock part .cfg files. The KSP .cfg format is a
custom key-value / block format used by Squad across all game data. This
module parses it into nested Python dicts and extracts the fields relevant
to rocket design and simulation.

Intended usage:
    from src.scraper import scrape_parts_directory
    parts = scrape_parts_directory(Path("/path/to/Squad/Parts"))
"""

import re
from pathlib import Path


# ---------------------------------------------------------------------------
# Low-level parser
# ---------------------------------------------------------------------------

def classify_line(raw_line):
    """
    Classify a single raw line from a KSP .cfg file.

    The KSP cfg grammar has five meaningful line types:
        - 'empty'      : blank line or pure comment (// ...) — skip it
        - 'open'       : '{' — opens a new block
        - 'close'      : '}' — closes the current block
        - 'kv'         : 'KEY = VALUE' pair; content is (key, raw_value)
        - 'block_name' : a bare word like MODULE or RESOURCE — the name of
                         an upcoming block whose '{' will appear on the next line

    Raw values are returned unmodified (including any trailing // comments)
    so that callers can decide how to handle localization strings.

    Parameters
    ----------
    raw_line : str
        A single line of text from a .cfg file, including leading whitespace.

    Returns
    -------
    tuple[str, any]
        (line_type, content) where content depends on the line type:
            'empty'      -> None
            'open'       -> None
            'close'      -> None
            'kv'         -> (key: str, raw_value: str)
            'block_name' -> block_name: str
    """
    line = raw_line.strip()

    if not line or line.startswith('//'):
        return ('empty', None)

    if line == '{':
        return ('open', None)

    if line == '}':
        return ('close', None)

    if '=' in line:
        key, _, value = line.partition('=')
        return ('kv', (key.strip(), value.strip()))

    return ('block_name', line)


def parse_cfg(text):
    """
    Parse a full KSP .cfg file into a nested dict structure.

    Uses a stack machine: when a '{' is encountered, a new block dict is
    pushed onto the stack. When '}' is encountered, the block is popped and
    attached to its parent's '_children' list.

    When the same key appears more than once within a block (e.g. multiple
    'key = ...' lines inside an atmosphereCurve block), the values are
    collected into a list.

    Parameters
    ----------
    text : str
        The full text content of a .cfg file, decoded with utf-8-sig to
        strip any leading BOM character.

    Returns
    -------
    dict
        A root dict with '_type': 'ROOT' and a '_children' list containing
        the top-level blocks (usually a single PART block). Each block has:
            '_type'     : str  — the block name (e.g. 'PART', 'MODULE')
            '_children' : list — nested sub-blocks
            <key>       : str or list[str] — key-value pairs from inside the block
    """
    root = {'_type': 'ROOT', '_children': []}
    stack = [root]
    pending_name = None

    for raw_line in text.splitlines():
        kind, content = classify_line(raw_line)

        if kind == 'empty':
            continue

        elif kind == 'block_name':
            pending_name = content

        elif kind == 'open':
            new_block = {'_type': pending_name or 'UNNAMED', '_children': []}
            stack[-1]['_children'].append(new_block)
            stack.append(new_block)
            pending_name = None

        elif kind == 'close':
            if len(stack) > 1:
                stack.pop()

        elif kind == 'kv':
            key, value = content
            current = stack[-1]
            if key in current:
                if not isinstance(current[key], list):
                    current[key] = [current[key]]
                current[key].append(value)
            else:
                current[key] = value

    return root


# ---------------------------------------------------------------------------
# Value cleaning
# ---------------------------------------------------------------------------

def clean_value(raw_value):
    """
    Clean a raw string value from a parsed .cfg block.

    KSP uses a localization system where human-readable strings are replaced
    with keys like '#autoLOC_500448'. The actual display name is embedded in
    a trailing comment on the same line:

        title = #autoLOC_500448 //#autoLOC_500448 = Mk-55 "Thud" Liquid Fuel Engine

    This function extracts the human-readable name in that case. For all
    other values, it strips any trailing '// comment' text.

    Parameters
    ----------
    raw_value : str
        A raw value string as returned by parse_cfg (may include // comments).

    Returns
    -------
    str
        Cleaned value with comments removed and localization resolved.
    """
    if raw_value.startswith('#autoLOC_'):
        match = re.search(r'//\s*#autoLOC_\d+\s*=\s*(.+)', raw_value)
        if match:
            return match.group(1).strip()
        return raw_value.split()[0]
    if '//' in raw_value:
        return raw_value[:raw_value.index('//')].strip()
    return raw_value


# ---------------------------------------------------------------------------
# Block navigation helpers
# ---------------------------------------------------------------------------

def get_children_of_type(block, block_type):
    """
    Return all direct child blocks of a given type within a parsed block.

    Parameters
    ----------
    block : dict
        A parsed block dict as returned by parse_cfg.
    block_type : str
        The '_type' value to match (e.g. 'MODULE', 'RESOURCE', 'PROPELLANT').

    Returns
    -------
    list[dict]
        All immediate children whose '_type' matches block_type.
    """
    return [c for c in block['_children'] if c['_type'] == block_type]


def get_module(block, module_name):
    """
    Find a MODULE child block by its internal 'name' field.

    KSP parts contain multiple MODULE blocks distinguished by their 'name'
    key (e.g. 'ModuleEngines', 'ModuleCommand', 'ModuleGimbal').

    Parameters
    ----------
    block : dict
        A parsed PART block dict.
    module_name : str
        The value of the 'name' key to search for (e.g. 'ModuleEngines').

    Returns
    -------
    dict or None
        The matching MODULE block dict, or None if not found.
    """
    for child in get_children_of_type(block, 'MODULE'):
        if child.get('name') == module_name:
            return child
    return None


# ---------------------------------------------------------------------------
# Field extractors
# ---------------------------------------------------------------------------

def parse_atmo_curve(engine_module_block):
    """
    Extract vacuum and sea-level Isp values from an atmosphereCurve sub-block.

    The atmosphereCurve block inside ModuleEngines encodes Isp as a function
    of atmospheric pressure. Each 'key' entry has the form:
        key = <pressure> <isp_value>
    where pressure=0 is vacuum and pressure=1 is sea level (1 atm).

    Parameters
    ----------
    engine_module_block : dict
        A parsed ModuleEngines block dict (a child of a PART block).

    Returns
    -------
    dict or None
        {'vacuum': float, 'sea_level': float}, or None if no curve is found.
        Either key may be absent if the curve only defines one pressure point.
    """
    curve_blocks = get_children_of_type(engine_module_block, 'atmosphereCurve')
    if not curve_blocks:
        return None

    curve = curve_blocks[0]
    keys = curve.get('key', [])
    if isinstance(keys, str):
        keys = [keys]

    isp = {}
    for entry in keys:
        parts = entry.split()
        if len(parts) >= 2:
            pressure, value = parts[0], parts[1]
            if pressure == '0':
                isp['vacuum'] = float(value)
            elif pressure == '1':
                isp['sea_level'] = float(value)

    return isp if isp else None


def extract_engine(part_block):
    """
    Extract engine performance data from a parsed PART block.

    Looks for a ModuleEngines or ModuleEnginesFX child module. Returns None
    if the part has no engine module (i.e. it is not an engine).

    Parameters
    ----------
    part_block : dict
        A parsed PART block dict.

    Returns
    -------
    dict or None
        Engine data dict with keys:
            'max_thrust_kn' : float — maximum thrust in kilonewtons
            'min_thrust_kn' : float — minimum thrust in kilonewtons (usually 0)
            'engine_type'   : str   — e.g. 'LiquidFuel', 'SolidFuel', 'Nuclear'
            'propellants'   : dict  — {resource_name: ratio} for each propellant
            'isp'           : dict or None — {'vacuum': float, 'sea_level': float}
        Returns None if this part has no engine module.
    """
    engine_mod = get_module(part_block, 'ModuleEngines')
    if engine_mod is None:
        engine_mod = get_module(part_block, 'ModuleEnginesFX')
    if engine_mod is None:
        return None

    propellants = {}
    for prop in get_children_of_type(engine_mod, 'PROPELLANT'):
        prop_name = prop.get('name', 'Unknown')
        prop_ratio = float(prop.get('ratio', 1.0))
        propellants[prop_name] = prop_ratio

    return {
        'max_thrust_kn': float(engine_mod.get('maxThrust', 0)),
        'min_thrust_kn': float(engine_mod.get('minThrust', 0)),
        'engine_type': engine_mod.get('EngineType', 'LiquidFuel'),
        'propellants': propellants,
        'isp': parse_atmo_curve(engine_mod),
    }


def extract_tank(part_block):
    """
    Extract resource storage data from a parsed PART block.

    Reads all RESOURCE child blocks, which define what a part can store
    (e.g. LiquidFuel, Oxidizer, MonoPropellant, XenonGas, ElectricCharge).

    Parameters
    ----------
    part_block : dict
        A parsed PART block dict.

    Returns
    -------
    dict or None
        {resource_name: max_amount} for each resource the part stores.
        Returns None if the part stores no resources.
    """
    resources = {}
    for res in get_children_of_type(part_block, 'RESOURCE'):
        name = res.get('name')
        max_amt = res.get('maxAmount')
        if name and max_amt:
            resources[name] = float(clean_value(max_amt))
    return resources if resources else None


def extract_nodes(part_block):
    """
    Extract attachment node definitions from a parsed PART block.

    KSP parts define attachment nodes as top-level key-value pairs:
        node_stack_top    = x, y, z, dx, dy, dz, size
        node_stack_bottom = x, y, z, dx, dy, dz, size
        node_attach       = x, y, z, dx, dy, dz       (surface attach)

    Position (x, y, z) is the local-space location of the node.
    Direction (dx, dy, dz) is the outward normal vector.
    Size is an integer (0=small, 1=medium, 2=large) indicating the
    attachment diameter class.

    Parameters
    ----------
    part_block : dict
        A parsed PART block dict.

    Returns
    -------
    dict
        {node_name: {'pos': [x,y,z], 'dir': [dx,dy,dz], 'size': int}}
        Node names are derived from the key (e.g. 'top', 'bottom', 'attach').
        Malformed nodes are silently skipped.
    """
    nodes = {}
    for key, raw_val in part_block.items():
        if key.startswith('node_stack_') or key == 'node_attach':
            parts = clean_value(raw_val).split(',')
            if len(parts) >= 6:
                node_name = key.replace('node_stack_', '').replace('node_', '')
                try:
                    nodes[node_name] = {
                        'pos': [float(parts[0]), float(parts[1]), float(parts[2])],
                        'dir': [float(parts[3]), float(parts[4]), float(parts[5])],
                        'size': int(float(parts[6])) if len(parts) > 6 else 0,
                    }
                except ValueError:
                    pass
    return nodes


def extract_part(part_block):
    """
    Extract all design-relevant fields from a parsed PART block.

    Combines common part metadata with category-specific data (engine
    performance, resource storage, attachment nodes, command capability).
    Fields not present in the .cfg are given sensible defaults.

    Parameters
    ----------
    part_block : dict
        A parsed PART block dict as returned by parse_cfg.

    Returns
    -------
    dict
        Clean part dict with keys:
            'name'            : str   — internal KSP part ID (used in .craft files)
            'title'           : str   — human-readable display name
            'category'        : str   — KSP editor category (e.g. 'Engine', 'FuelTank')
            'mass_t'          : float — dry mass in tonnes
            'cost'            : float — in-game cost in funds
            'crash_tolerance' : float — m/s impact tolerance
            'attach_rules'    : str   — raw attachRules flags from cfg
            'nodes'           : dict  — attachment nodes (see extract_nodes)
            'is_command'      : bool  — True if part has a ModuleCommand module
            'engine'          : dict or None — engine data (see extract_engine)
            'resources'       : dict or None — resource storage (see extract_tank)
    """
    raw_category = clean_value(part_block.get('category', ''))
    has_command = get_module(part_block, 'ModuleCommand') is not None

    return {
        'name': part_block.get('name', ''),
        'title': clean_value(part_block.get('title', '')),
        'category': raw_category,
        'mass_t': float(clean_value(part_block.get('mass', '0'))),
        'cost': float(clean_value(part_block.get('cost', '0'))),
        'crash_tolerance': float(clean_value(part_block.get('crashTolerance', '0'))),
        'attach_rules': clean_value(part_block.get('attachRules', '')),
        'nodes': extract_nodes(part_block),
        'is_command': has_command,
        'engine': extract_engine(part_block),
        'resources': extract_tank(part_block),
    }


# ---------------------------------------------------------------------------
# Directory scraper
# ---------------------------------------------------------------------------

def scrape_parts_directory(parts_dir):
    """
    Walk a KSP parts directory and extract all stock part definitions.

    Recursively finds all .cfg files under parts_dir, parses each one,
    and extracts any top-level PART blocks. Non-PART blocks (VARIANTTHEME,
    MODULE patches, RESOURCE_DEFINITION, etc.) are silently skipped.

    Files are read with utf-8-sig encoding to automatically strip the BOM
    character that Squad prepends to most of their .cfg files.

    Parameters
    ----------
    parts_dir : Path or str
        Path to the KSP parts directory, e.g.:
        /Users/.../Kerbal Space Program/GameData/Squad/Parts

    Returns
    -------
    tuple[list[dict], list[tuple[str, str]]]
        (parts, errors) where:
            parts  : list of extracted part dicts (see extract_part)
            errors : list of (file_path_str, error_message_str) for any
                     files that raised an exception during parsing
    """
    parts_dir = Path(parts_dir)
    cfg_files = sorted(parts_dir.rglob('*.cfg'))

    parts = []
    errors = []

    for cfg_path in cfg_files:
        try:
            text = cfg_path.read_text(encoding='utf-8-sig', errors='replace')
            parsed = parse_cfg(text)
            for child in parsed['_children']:
                if child['_type'] == 'PART':
                    part = extract_part(child)
                    part['_source_file'] = str(cfg_path.relative_to(parts_dir))
                    parts.append(part)
        except Exception as e:
            errors.append((str(cfg_path), str(e)))

    return parts, errors
