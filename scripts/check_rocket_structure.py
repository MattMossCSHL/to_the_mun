"""
check_rocket_structure.py — CLI to validate a rocket design against the parts library.

Reads a rocket design from a JSON file and a parts library from a JSON file,
runs all structural validity checks, and prints the result.

Rocket design JSON format:
    {
        "parts": [
            {"id": "pod_0",  "type": "mk1-3pod",    "parent": null},
            {"id": "tank_0", "type": "fuelTank",    "parent": "pod_0",  "attach_node": "bottom"},
            {"id": "eng_0",  "type": "liquidEngine", "parent": "tank_0", "attach_node": "bottom"}
        ],
        "stages": {"eng_0": 0}
    }

Usage
-----
    python scripts/check_rocket_structure.py \\
        --rocket data/my_rocket.json \\
        --parts  data/parts_library.json \\
        --verbose
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.structure import validate_rocket

DEFAULT_PARTS = Path(__file__).resolve().parent.parent / "data" / "parts_library.json"


def main():
    parser = argparse.ArgumentParser(
        description="Validate a KSP rocket design JSON against the parts library."
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
        "--verbose",
        action="store_true",
        help="Print which check failed and why.",
    )
    args = parser.parse_args()

    rocket_path = Path(args.rocket)
    parts_path = Path(args.parts)

    if not rocket_path.exists():
        print(f"Error: rocket file not found: {rocket_path}")
        sys.exit(1)

    if not parts_path.exists():
        print(f"Error: parts library not found: {parts_path}")
        sys.exit(1)

    with open(rocket_path) as f:
        rocket_dict = json.load(f)

    with open(parts_path) as f:
        parts_library = json.load(f)

    parts_by_name = {p['name']: p for p in parts_library}

    result = validate_rocket(rocket_dict, parts_by_name, verbose=args.verbose)

    if result:
        print("VALID: rocket passed all structural checks.")
    else:
        print("INVALID: rocket failed one or more structural checks.")
        sys.exit(1)


if __name__ == "__main__":
    main()
