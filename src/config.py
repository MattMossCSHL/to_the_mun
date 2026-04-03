"""
config.py — central loader for shared project data.

Provides loader functions for the parts library and resource densities so
notebooks and scripts don't repeat the loading boilerplate.

Usage
-----
    from src.config import load_parts_by_name, load_resource_lookup, load_part_lists

    parts_by_name        = load_parts_by_name()
    resource_lookup      = load_resource_lookup()
    pods, tanks, engines, decouplers = load_part_lists(parts_by_name)
"""

import json
from pathlib import Path

from src.scraper import parse_cfg

# --- paths -------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent

PARTS_LIBRARY_PATH = REPO_ROOT / "data" / "parts_library.json"

RESOURCES_CFG_PATH = Path(
    "/Users/moss/Library/Application Support/Steam/steamapps/common/"
    "Kerbal Space Program/GameData/Squad/Resources/ResourcesGeneric.cfg"
)

# --- loaders -----------------------------------------------------------------


def load_parts_by_name(path=PARTS_LIBRARY_PATH):
    """Load the parts library and return a dict keyed by part name.

    Parameters
    ----------
    path : Path or str, optional
        Path to parts_library.json. Defaults to data/parts_library.json.

    Returns
    -------
    dict
        {part_name: part_dict} for all parts in the library.
    """
    with open(path) as f:
        parts_library = json.load(f)
    return {p["name"]: p for p in parts_library}


def load_resource_lookup(path=RESOURCES_CFG_PATH):
    """Scrape resource densities from ResourcesGeneric.cfg.

    Parameters
    ----------
    path : Path or str, optional
        Path to ResourcesGeneric.cfg. Defaults to the local KSP Steam install.

    Returns
    -------
    dict
        {'LiquidFuel': {'density': 0.005}, ...} — density in tonnes per unit.
    """
    with open(path, encoding="utf-8-sig") as f:
        raw = f.read()
    resources_data = parse_cfg(raw)
    resource_lookup = {}
    for child in resources_data["_children"]:
        resource_lookup[child["name"]] = {"density": float(child["density"])}
    return resource_lookup


def load_part_lists(parts_by_name):
    """Split parts_by_name into pods, tanks, and engines by part type.

    Parameters
    ----------
    parts_by_name : dict
        {part_name: part_dict} as returned by load_parts_by_name().

    Returns
    -------
    tuple
        (pods, tanks, engines, decouplers) — each a list of part name strings.
    """
    stack_unsafe_tokens = ("mk2", "mk3")
    tank_propellants = {"LiquidFuel", "Oxidizer", "SolidFuel", "XenonGas"}

    def is_stack_safe(name):
        lowered = name.lower()
        return not any(token in lowered for token in stack_unsafe_tokens)

    pods = []
    tanks = []
    engines = []
    decouplers = []
    for name, part in parts_by_name.items():
        resources = set((part["resources"] or {}).keys())

        if not is_stack_safe(name):
            continue

        if part["category"] == "Pods" or str(part.get("_source_file", "")).startswith("Command/"):
            pods.append(name)
        elif part["engine"] is not None:
            engines.append(name)
        elif resources & tank_propellants:
            tanks.append(name)
        elif name.startswith("Decoupler_"):
            decouplers.append(name)
    return pods, tanks, engines, decouplers
