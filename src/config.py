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
    """Split parts_by_name into crewed pods, tanks, engines, and decouplers.

    Parameters
    ----------
    parts_by_name : dict
        {part_name: part_dict} as returned by load_parts_by_name().

    Returns
    -------
    tuple
        (pods, tanks, engines, decouplers) — each a list of part name strings.
        `pods` contains only crew-capable command parts, not probe cores.
    """
    tank_propellants = {"LiquidFuel", "Oxidizer", "SolidFuel", "XenonGas"}
    supported_engine_propellants = {"LiquidFuel", "Oxidizer", "SolidFuel"}

    def has_node(part, node_name):
        return node_name in (part.get("nodes") or {})

    def has_inline_top_bottom(part):
        return has_node(part, "top") and has_node(part, "bottom")

    def top_bottom_sizes_match(part):
        nodes = part.get("nodes") or {}
        if "top" not in nodes or "bottom" not in nodes:
            return False
        return nodes["top"]["size"] == nodes["bottom"]["size"]

    def is_crewed_command(part):
        return part.get("is_command") and int(part.get("crew_capacity", 0) or 0) > 0

    def is_rocket_pod(part):
        return (
            is_crewed_command(part)
            and part.get("vessel_type") != "Plane"
            and has_inline_top_bottom(part)
        )

    def is_rocket_tank(part, resources):
        return (
            part["engine"] is None
            and not part.get("is_command")
            and part["category"] in {"FuelTank", "Propulsion"}
            and bool(resources & tank_propellants)
            and has_inline_top_bottom(part)
            and top_bottom_sizes_match(part)
        )

    def is_rocket_engine(part):
        if part["engine"] is None:
            return False
        propellants = set((part["engine"].get("propellants") or {}).keys())
        return (
            part["category"] in {"Engine", "none"}
            and bool(propellants)
            and propellants.issubset(supported_engine_propellants)
            and has_inline_top_bottom(part)
        )

    pods = []
    tanks = []
    engines = []
    decouplers = []
    for name, part in parts_by_name.items():
        resources = set((part["resources"] or {}).keys())

        if not part.get("stack_safe", True):
            continue

        if is_rocket_pod(part):
            pods.append(name)
        elif is_rocket_engine(part):
            engines.append(name)
        elif is_rocket_tank(part, resources):
            tanks.append(name)
        elif name.startswith("Decoupler_"):
            decouplers.append(name)
    return pods, tanks, engines, decouplers
