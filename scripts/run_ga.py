"""
run_ga.py — CLI to run the genetic algorithm and save all generations.

Usage
-----
python scripts/run_ga.py [options]

Examples
--------
python scripts/run_ga.py
python scripts/run_ga.py --n_rockets 200 --n_generations 20 --save_dir data/runs/my_run
python scripts/run_ga.py --n_rockets 100 --n_generations 10 --n_elites 10 --mutation_rate 0.4 --detailed
"""

import argparse
import json
from datetime import datetime

from src.config import load_parts_by_name, load_resource_lookup, load_part_lists
from src.genetic_algorithm import run_ga


def main():
    parser = argparse.ArgumentParser(description='Run the KSP rocket design genetic algorithm.')
    parser.add_argument('--n_rockets',      type=int,   default=100,   help='population size per generation (default: 100)')
    parser.add_argument('--n_generations',  type=int,   default=10,    help='number of generations to run (default: 10)')
    parser.add_argument('--max_stages',     type=int,   default=2,     help='maximum stages per rocket (default: 2)')
    parser.add_argument('--n_elites',       type=int,   default=5,     help='elites carried forward unchanged (default: 5)')
    parser.add_argument('--mutation_rate',  type=float, default=0.3,   help='probability of mutating each child (default: 0.3)')
    parser.add_argument('--detailed',       action='store_true',        help='store full metadata per rocket')
    parser.add_argument('--save_dir',       type=str,   default=None,  help='directory to save generations (default: data/runs/run_TIMESTAMP)')
    args = parser.parse_args()

    save_dir = args.save_dir or f"data/runs/run_{datetime.now().strftime('%Y-%m-%d-%H%M%S')}"

    parts_by_name = load_parts_by_name()
    resource_lookup = load_resource_lookup()
    pods, tanks, engines, decouplers = load_part_lists(parts_by_name)

    print(f"starting GA: {args.n_rockets} rockets × {args.n_generations} generations")
    print(f"saving to: {save_dir}")

    final_population = run_ga(
        n_rockets=args.n_rockets,
        n_generations=args.n_generations,
        parts_by_name=parts_by_name,
        resource_lookup=resource_lookup,
        pods=pods,
        tanks=tanks,
        engines=engines,
        decouplers=decouplers,
        max_stages=args.max_stages,
        n_elites=args.n_elites,
        mutation_rate=args.mutation_rate,
        detailed=args.detailed,
        save_dir=save_dir,
    )

    scores = [meta['score'] for _, meta in final_population]
    print(f"\nfinal generation:")
    print(f"  best:    {max(scores):.0f} m/s")
    print(f"  mean:    {sum(scores)/len(scores):.0f} m/s")
    print(f"  nonzero: {sum(1 for s in scores if s > 0)}/{len(scores)}")


if __name__ == '__main__':
    main()
