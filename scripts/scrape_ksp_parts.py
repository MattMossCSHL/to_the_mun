"""
scrape_ksp_parts.py — CLI script to scrape KSP1 stock part data into JSON.

Walks a KSP parts directory, parses all .cfg files, and writes a JSON file
containing one dict per part with all design-relevant fields extracted.

Usage
-----
    python scripts/scrape_ksp_parts.py \\
        --parts-dir "/path/to/KSP/GameData/Squad/Parts" \\
        --output data/parts_library.json

The default parts directory is the Steam install location on macOS. The
default output path is data/parts_library.json relative to the repo root.
"""

import argparse
import json
import sys
from pathlib import Path

# Allow imports from src/ regardless of where the script is run from
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.scraper import scrape_parts_directory

DEFAULT_PARTS_DIR = (
    "/Users/moss/Library/Application Support/Steam/steamapps/common/"
    "Kerbal Space Program/GameData/Squad/Parts"
)
DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "data" / "parts_library.json"


def main():
    parser = argparse.ArgumentParser(
        description="Scrape KSP1 stock part .cfg files into a JSON parts library."
    )
    parser.add_argument(
        "--parts-dir",
        default=DEFAULT_PARTS_DIR,
        help=(
            "Path to the KSP Squad/Parts directory. "
            f"Defaults to the macOS Steam install location."
        ),
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help=(
            "Path for the output JSON file. "
            "Defaults to data/parts_library.json in the repo root."
        ),
    )
    args = parser.parse_args()

    parts_dir = Path(args.parts_dir)
    output_path = Path(args.output)

    if not parts_dir.exists():
        print(f"Error: parts directory not found: {parts_dir}")
        sys.exit(1)

    print(f"Scraping parts from: {parts_dir}")
    parts, errors = scrape_parts_directory(parts_dir)

    if errors:
        print(f"\n{len(errors)} file(s) failed to parse:")
        for path, err in errors:
            print(f"  {path}: {err}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(parts, f, indent=2)

    print(f"\nSaved {len(parts)} parts to {output_path}")
    print(f"File size: {output_path.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
