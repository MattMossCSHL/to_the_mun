"""
generate_rocket.py — CLI to construct and validate a KSP rocket via the Rocket class.

Reads a rocket design from a JSON file, constructs it part-by-part through
the Rocket class (with validation at each step), and writes the resulting
rocket dict to a JSON file or stdout.

This is distinct from check_rocket_structure.py: it exercises the Rocket class
rather than calling validate_rocket directly, which means construction errors
(unknown part type, bad parent reference, etc.) are caught and reported as the
rocket is built, not as a single end-of-pipeline check.

Rocket design JSON format:
    {
        "parts": [
            {"id": "pod_0",  "type": "mk1-3pod",     "parent": null},
            {"id": "tank_0", "type": "fuelTank",     "parent": "pod_0",  "attach_node": "bottom"},
            {"id": "eng_0",  "type": "liquidEngine", "parent": "tank_0", "attach_node": "bottom"}
        ],
        "stages": {"eng_0": 0}
    }

Usage
-----
    # build a rocket and print to stdout
    python scripts/generate_rocket.py --rocket data/my_rocket.json

    # build, validate, and save to a file
    python scripts/generate_rocket.py \\
        --rocket data/my_rocket.json \\
        --output data/built_rocket.json \\
        --validate \\
        --verbose
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.rocket import Rocket

DEFAULT_PARTS = Path(__file__).resolve().parent.parent / "data" / "parts_library.json"


def main():
    parser = argparse.ArgumentParser(
        description="Construct a KSP rocket via the Rocket class and optionally validate it."
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
        "--output",
        default=None,
        help="Path to write the resulting rocket dict JSON. Prints to stdout if omitted.",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Run validate_rocket on the finished design and report the result.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print each construction step and, if --validate is set, which check failed.",
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
        spec = json.load(f)

    with open(parts_path) as f:
        parts_library = json.load(f)

    parts_by_name = {p['name']: p for p in parts_library}

    rocket = Rocket(parts_by_name)

    # add parts
    for part in spec['parts']:
        try:
            rocket.add_part(
                id=part['id'],
                part_type=part['type'],
                parent=part['parent'],
                attach_node=part.get('attach_node'),
            )
            if args.verbose:
                print(f"  added: {part['id']} ({part['type']})")
        except ValueError as e:
            print(f"Error adding part '{part['id']}': {e}")
            sys.exit(1)

    # set stages
    for part_id, stage in spec.get('stages', {}).items():
        try:
            rocket.set_stage(part_id, stage)
            if args.verbose:
                print(f"  staged: {part_id} → stage {stage}")
        except ValueError as e:
            print(f"Error staging part '{part_id}': {e}")
            sys.exit(1)

    if args.verbose:
        print(f"\n{rocket}")

    # validate if requested
    if args.validate:
        result = rocket.validate(verbose=args.verbose)
        if result:
            print("VALID: rocket passed all structural checks.")
        else:
            print("INVALID: rocket failed one or more structural checks.")
            sys.exit(1)

    # output
    output_dict = rocket.to_dict()
    output_json = json.dumps(output_dict, indent=2)

    if args.output:
        output_path = Path(args.output)
        with open(output_path, 'w') as f:
            f.write(output_json)
        if args.verbose:
            print(f"\nwritten to: {output_path}")
    else:
        print(output_json)


if __name__ == "__main__":
    main()
