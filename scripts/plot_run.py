"""
plot_run.py — CLI to plot delta-v by generation for a saved GA run.

Usage
-----
python scripts/plot_run.py <run_dir>

Examples
--------
python scripts/plot_run.py data/runs/run_2026-03-10-2130
"""

import argparse

from src.plots import plot_run


def main():
    parser = argparse.ArgumentParser(description='Plot delta-v by generation for a saved GA run.')
    parser.add_argument('run_dir', type=str, help='path to run directory containing gen_NNN.json files')
    args = parser.parse_args()

    plot_run(args.run_dir)


if __name__ == '__main__':
    main()
