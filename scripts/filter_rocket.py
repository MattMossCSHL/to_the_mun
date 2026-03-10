"""
filter_rocket.py — CLI to run analytic filters on a rocket design.

Reads a rocket design from a JSON file and a parts library from a JSON file,
scrapes resource densities from the KSP installation, runs TWR, delta-v, and
burn time checks, and prints pass/fail with reasons.

Usage
-----
    python scripts/filter_rocket.py \\
        --rocket data/my_rocket.json \\
        --goal orbit \\
        --resources "/path/to/KSP/GameData/Squad/Resources/ResourcesGeneric.cfg" \\
        --verbose

Goals
-----
    atmosphere   delta-v >= 1800 m/s
    orbit        delta-v >= 3400 m/s  (default)
    mun_orbit    delta-v >= 4300 m/s
    mun_landing  delta-v >= 5700 m/s
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.scraper import parse_cfg
from src.filters import filter_rocket, DV_THRESHOLDS

DEFAULT_PARTS = Path(__file__).resolve().parent.parent / "data" / "parts_library.json"
DEFAULT_RESOURCES = Path(
    "/Users/moss/Library/Application Support/Steam/steamapps/common/"
    "Kerbal Space Program/GameData/Squad/Resources/ResourcesGeneric.cfg"
)


def main():
    parser = argparse.ArgumentParser(
        description="Run analytic filters on a KSP rocket design JSON."
    )
    parser.add_argument(
        "--rocket",
        required=True,
        help="Path to the rocket design JSON file.",
    )
    parser.add_argument(
        "--parts",
        default=str(DEFAULT_PARTS),
        help=(
            "Path to the parts library JSON file. "
            "Defaults to data/parts_library.json in the repo root."
        ),
    )
    parser.add_argument(
        "--resources",
        default=str(DEFAULT_RESOURCES),
        help="Path to ResourcesGeneric.cfg from the KSP installation.",
    )
    parser.add_argument(
        "--goal",
        default="orbit",
        choices=list(DV_THRESHOLDS.keys()),
        help="Mission goal that sets the delta-v threshold. Defaults to 'orbit'.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-check detail.",
    )
    args = parser.parse_args()

    rocket_path = Path(args.rocket)
    parts_path = Path(args.parts)
    resources_path = Path(args.resources)

    if not rocket_path.exists():
        print(f"Error: rocket file not found: {rocket_path}")
        sys.exit(1)
    if not parts_path.exists():
        print(f"Error: parts library not found: {parts_path}")
        sys.exit(1)
    if not resources_path.exists():
        print(f"Error: resources config not found: {resources_path}")
        sys.exit(1)

    with open(rocket_path) as f:
        rocket_dict = json.load(f)

    with open(parts_path) as f:
        parts_library = json.load(f)

    with open(resources_path, encoding='utf-8-sig') as f:
        raw = f.read()

    parts_by_name = {p['name']: p for p in parts_library}

    resources_data = parse_cfg(raw)
    resource_lookup = {}
    for child in resources_data['_children']:
        resource_lookup[child['name']] = {'density': float(child['density'])}

    parts_list = [p['type'] for p in rocket_dict['parts']]

    passed, reasons = filter_rocket(
        rocket_dict,
        parts_list,
        parts_by_name,
        resource_lookup,
        DV_THRESHOLDS,
        goal=args.goal,
        verbose=args.verbose,
    )

    if passed:
        print(f"PASS: rocket meets all analytic filters for goal '{args.goal}'.")
    else:
        print(f"FAIL: rocket did not pass analytic filters for goal '{args.goal}'.")
        for reason in reasons:
            print(f"  - {reason}")
        sys.exit(1)


if __name__ == "__main__":
    main()
