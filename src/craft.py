"""
craft.py — prototype `.craft` serialization for KSP1.

This module is extracted from `notebooks/to_craft_research.ipynb`.
It currently focuses on linear-stack VAB craft and returns both the
generated craft text and metadata about template coverage / fallbacks.
"""

from pathlib import Path
import random
import re

from src.scraper import clean_value, parse_cfg


DEFAULT_KSP_ROOT = Path(
    "/Users/moss/Library/Application Support/Steam/steamapps/common/Kerbal Space Program"
)


def make_ksp_part_ids(rocket_dict, craft_part_names, seed=12345):
    rng = random.Random(seed)
    id_map = {}
    for part in rocket_dict['parts']:
        suffix = rng.randint(1_000_000_000, 4_294_967_295)
        craft_name = craft_part_names[part['id']]
        id_map[part['id']] = f"{craft_name}_{suffix}"
    return id_map


def build_children_lookup(rocket_dict):
    children = {part['id']: [] for part in rocket_dict['parts']}
    for part in rocket_dict['parts']:
        parent = part['parent']
        if parent is not None:
            children[parent].append(part['id'])
    return children


def choose_child_attach_node(part_type, parts_by_name):
    """Choose the child-side node used to attach into a linear stack."""
    nodes = parts_by_name[part_type]['nodes']
    for candidate in ('top', 'bottom', 'attach'):
        if candidate in nodes:
            return candidate
    raise ValueError(f'part {part_type} has no usable attach node for linear stack placement')


def choose_parent_attach_node(part_type, requested_node, parts_by_name):
    """Choose the parent-side node used to attach a child in a linear stack."""
    nodes = parts_by_name[part_type]['nodes']
    for candidate in (requested_node, 'bottom', 'top', 'attach'):
        if candidate in nodes:
            return candidate
    raise ValueError(f'part {part_type} has no usable parent attach node for linear stack placement')


def linear_stack_positions(rocket_dict, parts_by_name, root_pos=(0.0, 15.0, 0.0)):
    """Place a linear rocket stack by aligning parent/child attach nodes."""
    positions = {}
    attach_offsets = {}

    root = next(part['id'] for part in rocket_dict['parts'] if part['parent'] is None)
    positions[root] = root_pos
    attach_offsets[root] = (0.0, 0.0, 0.0)

    current = root
    while True:
        children = [part['id'] for part in rocket_dict['parts'] if part['parent'] == current]
        if not children:
            break

        child = children[0]
        parent_part = next(part for part in rocket_dict['parts'] if part['id'] == current)
        child_part = next(part for part in rocket_dict['parts'] if part['id'] == child)

        parent_attach_name = choose_parent_attach_node(
            parent_part['type'],
            child_part.get('attach_node', 'bottom') or 'bottom',
            parts_by_name,
        )
        child_attach_name = choose_child_attach_node(child_part['type'], parts_by_name)

        parent_attach = parts_by_name[parent_part['type']]['nodes'][parent_attach_name]['pos']
        child_attach = parts_by_name[child_part['type']]['nodes'][child_attach_name]['pos']

        px, py, pz = positions[current]
        parent_node_world = (
            px + parent_attach[0],
            py + parent_attach[1],
            pz + parent_attach[2],
        )

        child_world = (
            parent_node_world[0] - child_attach[0],
            parent_node_world[1] - child_attach[1],
            parent_node_world[2] - child_attach[2],
        )

        positions[child] = child_world
        attach_offsets[child] = tuple(parent_attach)
        current = child

    return positions, attach_offsets


def render_prototype_header(ship_name='prototype craft'):
    return '\n'.join([
        f'ship = {ship_name}',
        'version = 1.6.0',
        'description = generated prototype',
        'type = VAB',
        'size = 1,1,1',
        'steamPublishedFileId = 0',
        'persistentId = 123456789',
        'rot = 0,0,0,1',
        'missionFlag = Squad/Flags/default',
        'vesselType = Debris',
    ])


def craft_name_aliases(part_name):
    aliases = [part_name]

    dotted_version = re.sub(r'_v(\d+)$', r'.v\1', part_name)
    if dotted_version not in aliases:
        aliases.append(dotted_version)

    dotted_suffix = re.sub(r'_(\d+)$', r'.\1', part_name)
    if dotted_suffix not in aliases:
        aliases.append(dotted_suffix)

    dotted_upper_suffix = re.sub(r'_([A-Z][A-Z0-9]*)$', r'.\1', part_name)
    if dotted_upper_suffix not in aliases:
        aliases.append(dotted_upper_suffix)

    return aliases


def default_craft_part_name(part_name):
    """Best-effort mapping from cfg-style part names to .craft-style names."""
    for alias in craft_name_aliases(part_name):
        if alias != part_name:
            return alias
    return part_name


def extract_part_blocks(craft_text):
    """Return raw PART blocks from a craft file by brace counting."""
    lines = craft_text.splitlines()
    blocks = []
    i = 0
    while i < len(lines):
        if lines[i].strip() == 'PART':
            block_lines = [lines[i]]
            i += 1
            brace_depth = 0
            while i < len(lines):
                line = lines[i]
                block_lines.append(line)
                brace_depth += line.count('{')
                brace_depth -= line.count('}')
                i += 1
                if brace_depth == 0 and line.strip() == '}':
                    break
            blocks.append('\n'.join(block_lines))
        else:
            i += 1
    return blocks


def template_search_files(search_root):
    """Prefer stock/example craft and avoid generated save craft pollution."""
    search_root = Path(search_root)
    preferred_dirs = [
        search_root / 'Ships' / 'VAB',
        search_root / 'Ships' / 'SPH',
        search_root / 'GameData' / 'Squad' / 'Missions',
        search_root / 'Missions',
        search_root / 'Tutorial',
        search_root / 'Scenarios',
    ]

    craft_files = []
    seen = set()
    for base in preferred_dirs:
        if not base.exists():
            continue
        for craft_file in sorted(base.rglob('*.craft')):
            if craft_file not in seen:
                craft_files.append(craft_file)
                seen.add(craft_file)

    if craft_files:
        return craft_files

    return sorted(search_root.rglob('*.craft'))


def find_template_blocks_for_parts(part_names, search_root):
    """Search local craft files for PART blocks matching requested internal part names."""
    wanted = {name: None for name in part_names}
    craft_files = template_search_files(search_root)

    for craft_file in craft_files:
        if all(wanted[name] is not None for name in wanted):
            break
        text = craft_file.read_text(errors='ignore')
        for block in extract_part_blocks(text):
            for name in wanted:
                if wanted[name] is not None:
                    continue
                for alias in craft_name_aliases(name):
                    if f'part = {alias}_' in block:
                        wanted[name] = {'file': craft_file, 'block': block, 'matched_token': alias}
                        break
    return wanted


def parse_part_template_block(block_text):
    """Parse one raw PART block into top-level fields plus preserved nested blocks."""
    lines = block_text.splitlines()
    if not lines or lines[0].strip() != 'PART':
        raise ValueError('expected PART block')

    fields = []
    nested_blocks = []
    i = 2
    while i < len(lines) - 1:
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        next_stripped = lines[i + 1].strip() if i + 1 < len(lines) else ''

        # Nested blocks in .craft files usually appear as:
        #   MODULE
        #   {
        #     ...
        #   }
        # Preserve the block name plus its contents verbatim.
        if '=' not in stripped and next_stripped == '{':
            block_lines = [line, lines[i + 1]]
            brace_depth = 1
            i += 2
            while i < len(lines):
                block_lines.append(lines[i])
                brace_depth += lines[i].count('{') - lines[i].count('}')
                i += 1
                if brace_depth == 0:
                    break
            nested_blocks.append('\n'.join(block_lines))
            continue

        if '=' in stripped:
            key, value = stripped.split('=', 1)
            fields.append((key.strip(), value.strip()))

        i += 1

    return {'fields': fields, 'nested_blocks': nested_blocks}


def sanitize_nested_blocks(nested_blocks):
    """Drop template-carried blocks that should not leak vessel-specific state."""
    sanitized = []
    for block in nested_blocks:
        lines = block.splitlines()
        if not lines:
            continue
        block_name = lines[0].strip()
        if block_name == 'VESSELNAMING':
            continue
        sanitized.append(block)
    return sanitized


def render_part_template_struct(part_struct):
    lines = ['PART', '{']
    for key, value in part_struct['fields']:
        lines.append(f'\t{key} = {value}')
    for block in part_struct['nested_blocks']:
        for line in block.splitlines():
            lines.append(line)
    lines.append('}')
    return '\n'.join(lines)


def project_part_stage_context(part, rocket_dict):
    """Classify a part into linear-stack project-stage context."""
    part_id = part['id']
    project_stage = rocket_dict['stages'].get(part_id)

    if project_stage is not None:
        if part_id.startswith('decoupler_'):
            return {'project_stage': project_stage, 'role': 'decoupler'}
        if part_id.startswith('eng_'):
            return {'project_stage': project_stage, 'role': 'engine'}

    current = part['id']
    while True:
        children = [p['id'] for p in rocket_dict['parts'] if p['parent'] == current]
        if not children:
            break
        child_id = children[0]
        if child_id in rocket_dict['stages']:
            return {'project_stage': rocket_dict['stages'][child_id], 'role': 'passive'}
        current = child_id

    return {'project_stage': 0, 'role': 'passive'}


def translate_staging_linear(part, rocket_dict):
    """Translate project stages into KSP istg/dstg/etc for a linear stack."""
    ctx = project_part_stage_context(part, rocket_dict)
    stage = ctx['project_stage']
    role = ctx['role']

    if stage == 0:
        if role == 'engine':
            return {'istg': 0, 'dstg': 0, 'sidx': 0, 'sqor': 0, 'sepI': -1}
        return {'istg': -1, 'dstg': 0, 'sidx': -1, 'sqor': -1, 'sepI': -1}

    if role == 'decoupler':
        ksp_stage = 2 * stage - 1
        return {'istg': ksp_stage, 'dstg': ksp_stage, 'sidx': 0, 'sqor': ksp_stage, 'sepI': ksp_stage}

    if role == 'engine':
        return {'istg': 2 * stage, 'dstg': 2 * stage, 'sidx': 0, 'sqor': 2 * stage, 'sepI': 2 * stage - 1}

    return {'istg': 2 * stage - 1, 'dstg': 2 * stage, 'sidx': -1, 'sqor': -1, 'sepI': 2 * stage - 1}


def render_resource_block(name, amount):
    return '\n'.join([
        '\tRESOURCE',
        '\t{',
        f'\t\tname = {name}',
        f'\t\tamount = {amount}',
        f'\t\tmaxAmount = {amount}',
        '\t\tflowState = True',
        '\t\tisTweakable = True',
        '\t\thideFlow = False',
        '\t\tisVisible = True',
        '\t\tflowMode = Both',
        '\t}',
    ])


def resolve_part_cfg_path(part_data, search_root=DEFAULT_KSP_ROOT):
    """Resolve the stock cfg path for a scraped part record."""
    source_file = part_data.get('_source_file')
    if not source_file:
        return None

    search_root = Path(search_root)
    candidate_paths = [
        search_root / 'GameData' / 'Squad' / 'Parts' / source_file,
        search_root / source_file,
    ]

    for candidate in candidate_paths:
        if candidate.exists():
            return candidate
    return None


def render_cfg_block(block, indent_level=1):
    """Render a parsed cfg block as craft text with cleaned values."""
    indent = '\t' * indent_level
    child_indent = '\t' * (indent_level + 1)
    lines = [f'{indent}{block["_type"]}', f'{indent}{{']

    for key, value in block.items():
        if key.startswith('_'):
            continue
        values = value if isinstance(value, list) else [value]
        for item in values:
            lines.append(f'{child_indent}{key} = {clean_value(item)}')

    for child in block.get('_children', []):
        lines.append(render_cfg_block(child, indent_level + 1))

    lines.append(f'{indent}}}')
    return '\n'.join(lines)


def load_cfg_nested_blocks(part_data, search_root=DEFAULT_KSP_ROOT):
    """Load RESOURCE/MODULE blocks for a part directly from the stock cfg."""
    cfg_path = resolve_part_cfg_path(part_data, search_root=search_root)
    if cfg_path is None:
        raise ValueError(f'no stock cfg found for {part_data["name"]}')

    parsed = parse_cfg(cfg_path.read_text(encoding='utf-8-sig'))
    part_blocks = [child for child in parsed.get('_children', []) if child.get('_type') == 'PART']
    if not part_blocks:
        raise ValueError(f'no PART block found in cfg for {part_data["name"]}')

    nested_blocks = [
        '\tEVENTS\n\t{\n\t}',
        '\tACTIONS\n\t{\n\t}',
        '\tPARTDATA\n\t{\n\t}',
    ]

    for child in part_blocks[0].get('_children', []):
        if child.get('_type') not in {'MODULE', 'RESOURCE'}:
            continue
        nested_blocks.append(render_cfg_block(child))

    return nested_blocks, cfg_path


def make_cfg_part_struct(part, rocket_dict, parts_by_name, ksp_id_map, positions, search_root=DEFAULT_KSP_ROOT):
    """Build a PART structure from the stock part cfg when no craft template exists."""
    x, y, z = positions[part['id']]
    if part['parent'] is None:
        att_pos0 = f'{x},{y},{z}'
    else:
        px, py, pz = positions[part['parent']]
        att_pos0 = f'{x - px},{y - py},{z - pz}'
    fields = [
        ('part', ksp_id_map[part['id']]),
        ('partName', 'Part'),
        ('persistentId', str(random.randint(1_000_000_000, 4_294_967_295))),
        ('pos', f'{x},{y},{z}'),
        ('attPos', '0,0,0'),
        ('attPos0', att_pos0),
        ('rot', '0,0,0,1'),
        ('attRot', '0,0,0,1'),
        ('attRot0', '0,0,0,1'),
        ('mir', '1,1,1'),
        ('symMethod', 'Radial'),
        ('autostrutMode', 'Off'),
        ('rigidAttachment', 'False'),
        ('resPri', '0'),
        ('attm', '0'),
        ('modCost', '0'),
        ('modMass', '0'),
        ('modSize', '0,0,0'),
    ]

    staging = translate_staging_linear(part, rocket_dict)
    fields.extend([
        ('istg', str(staging['istg'])),
        ('dstg', str(staging['dstg'])),
        ('sidx', str(staging['sidx'])),
        ('sqor', str(staging['sqor'])),
        ('sepI', str(staging['sepI'])),
    ])

    children = build_children_lookup(rocket_dict)[part['id']]
    for child_id in children:
        fields.append(('link', ksp_id_map[child_id]))
        child_part = next(p for p in rocket_dict['parts'] if p['id'] == child_id)
        parent_node = choose_parent_attach_node(
            part['type'],
            child_part.get('attach_node', 'bottom') or 'bottom',
            parts_by_name,
        )
        _, parent_ay, _ = parts_by_name[part['type']]['nodes'][parent_node]['pos']
        fields.append(('attN', f'{parent_node},{ksp_id_map[child_id]}_0|{parent_ay}|0'))

    if part['parent'] is not None:
        parent_ksp_id = ksp_id_map[part['parent']]
        child_node = choose_child_attach_node(part['type'], parts_by_name)
        _, ay, _ = parts_by_name[part['type']]['nodes'][child_node]['pos']
        fields.append(('attN', f'{child_node},{parent_ksp_id}_0|{ay}|0'))

    nested_blocks = [
        '\tEVENTS\n\t{\n\t}',
        '\tACTIONS\n\t{\n\t}',
        '\tPARTDATA\n\t{\n\t}',
    ]
    cfg_nested_blocks, cfg_path = load_cfg_nested_blocks(parts_by_name[part['type']], search_root=search_root)
    nested_blocks.extend(cfg_nested_blocks[3:])

    return {'fields': fields, 'nested_blocks': nested_blocks}, cfg_path


def apply_common_overrides(part_struct, part, rocket_dict, ksp_id_map, positions, parts_by_name):
    """Override the vessel-specific fields in a parsed template structure."""
    x, y, z = positions[part['id']]
    children = build_children_lookup(rocket_dict)[part['id']]
    if part['parent'] is None:
        att_pos0 = f'{x},{y},{z}'
    else:
        px, py, pz = positions[part['parent']]
        att_pos0 = f'{x - px},{y - py},{z - pz}'

    field_map = []
    skip_keys = {
        'link', 'attN', 'part', 'persistentId', 'pos', 'attPos0',
        'istg', 'dstg', 'sidx', 'sqor', 'sepI',
        'sym', 'srfN',
    }
    for key, value in part_struct['fields']:
        if key not in skip_keys:
            field_map.append((key, value))

    def upsert(key, value):
        for idx, (existing_key, _) in enumerate(field_map):
            if existing_key == key:
                field_map[idx] = (key, value)
                return
        field_map.append((key, value))

    field_map.insert(0, ('part', ksp_id_map[part['id']]))
    field_map.insert(1, ('persistentId', str(random.randint(1_000_000_000, 4_294_967_295))))
    field_map.insert(2, ('pos', f'{x},{y},{z}'))
    field_map.insert(3, ('attPos0', att_pos0))
    upsert('attm', '0')
    upsert('symMethod', 'Radial')
    upsert('attPos', '0,0,0')
    upsert('rot', '0,0,0,1')
    upsert('attRot', '0,0,0,1')
    upsert('attRot0', '0,0,0,1')

    staging = translate_staging_linear(part, rocket_dict)
    field_map.extend([
        ('istg', str(staging['istg'])),
        ('dstg', str(staging['dstg'])),
        ('sidx', str(staging['sidx'])),
        ('sqor', str(staging['sqor'])),
        ('sepI', str(staging['sepI'])),
    ])

    for child_id in children:
        field_map.append(('link', ksp_id_map[child_id]))
        child_part = next(p for p in rocket_dict['parts'] if p['id'] == child_id)
        parent_node = choose_parent_attach_node(
            part['type'],
            child_part.get('attach_node', 'bottom') or 'bottom',
            parts_by_name,
        )
        _, parent_ay, _ = parts_by_name[part['type']]['nodes'][parent_node]['pos']
        field_map.append(('attN', f'{parent_node},{ksp_id_map[child_id]}_0|{parent_ay}|0'))

    if part['parent'] is not None:
        parent_ksp_id = ksp_id_map[part['parent']]
        child_node = choose_child_attach_node(part['type'], parts_by_name)
        _, ay, _ = parts_by_name[part['type']]['nodes'][child_node]['pos']
        field_map.append(('attN', f'{child_node},{parent_ksp_id}_0|{ay}|0'))

    return {'fields': field_map, 'nested_blocks': sanitize_nested_blocks(part_struct['nested_blocks'])}


def to_craft(rocket_dict,
             parts_by_name,
             ship_name='prototype craft',
             search_root=DEFAULT_KSP_ROOT):
    """Prototype notebook-extracted serializer for linear-stack VAB craft.

    Returns
    -------
    tuple
        (craft_text, metadata)
    """
    templates = find_template_blocks_for_parts([part['type'] for part in rocket_dict['parts']], search_root)
    craft_part_names = {}
    for part in rocket_dict['parts']:
        info = templates.get(part['type'])
        if info is not None and info.get('matched_token') is not None:
            craft_part_names[part['id']] = info['matched_token']
        else:
            craft_part_names[part['id']] = default_craft_part_name(part['type'])

    ksp_id_map = make_ksp_part_ids(rocket_dict, craft_part_names)
    positions, _ = linear_stack_positions(rocket_dict, parts_by_name)

    metadata = {
        'template_parts': [],
        'cfg_parts': [],
        'warnings': [],
        'cfg_sources': {},
        'craft_part_names': craft_part_names,
    }

    part_blocks = []
    for part in rocket_dict['parts']:
        template_info = templates.get(part['type'])
        if template_info is not None:
            parsed = parse_part_template_block(template_info['block'])
            updated = apply_common_overrides(parsed, part, rocket_dict, ksp_id_map, positions, parts_by_name)
            metadata['template_parts'].append(part['type'])
        else:
            updated, cfg_path = make_cfg_part_struct(
                part,
                rocket_dict,
                parts_by_name,
                ksp_id_map,
                positions,
                search_root=search_root,
            )
            metadata['cfg_parts'].append(part['type'])
            metadata['cfg_sources'][part['type']] = str(cfg_path)

        part_blocks.append(render_part_template_struct(updated))

    craft_text = render_prototype_header(ship_name=ship_name) + '\n' + '\n'.join(part_blocks)
    return craft_text, metadata
