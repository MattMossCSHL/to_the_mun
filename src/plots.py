"""
plots.py — visualisation utilities for GA run output.

Functions
---------
plot_run : scatter plot of delta-v by generation with median/best lines and per-gen stats
"""

import glob
import json
import os

import matplotlib.pyplot as plt
import numpy as np


def plot_run(run_dir: str):
    """Plot delta-v by generation for a saved GA run.

    Reads all gen_NNN.json files from run_dir. Scatter plots every rocket's
    score per generation, overlays median non-zero and best-score delta-v lines,
    clips the y-axis at the 99th percentile, and marks outliers with orange triangles.
    Per-generation stats (median non-zero, zeros, invalid) are annotated above the plot.

    Parameters
    ----------
    run_dir : str
        Path to a run directory containing gen_NNN.json files.
    """
    gen_files = sorted(glob.glob(os.path.join(run_dir, 'gen_*.json')))
    if not gen_files:
        print(f"no generation files found in {run_dir}")
        return

    generations = []
    all_scores = []
    median_nonzeros = []
    max_scores = []
    n_zeros = []
    n_invalid = []

    for f in gen_files:
        with open(f) as fh:
            data = json.load(fh)
        gen = data['generation']
        scores = [r['meta']['score'] for r in data['rockets']]
        invalids = [r for r in data['rockets'] if not r['meta'].get('valid', True)]

        generations.append(gen)
        all_scores.append(scores)
        nonzero_scores = [s for s in scores if s > 0]
        median_nonzeros.append(np.median(nonzero_scores) if nonzero_scores else 0)
        max_scores.append(max(scores) if scores else 0)
        n_zeros.append(sum(1 for s in scores if s == 0))
        n_invalid.append(len(invalids))

    flat_scores = [s for gen_scores in all_scores for s in gen_scores if s > 0]
    y_cap = np.percentile(flat_scores, 99) * 1.1 if flat_scores else 1

    fig, ax = plt.subplots(figsize=(12, 6))

    for gen, scores in zip(generations, all_scores):
        clipped = [min(s, y_cap) for s in scores]
        outlier_mask = [s > y_cap for s in scores]
        ax.scatter([gen] * len(clipped), clipped, alpha=0.2, s=10, color='steelblue')
        if any(outlier_mask):
            ax.scatter([gen] * sum(outlier_mask), [y_cap] * sum(outlier_mask),
                       marker='^', color='orange', s=30, zorder=5,
                       label='outlier (clipped)' if gen == generations[0] else '')

    clipped_max_scores = [min(score, y_cap) for score in max_scores]

    ax.plot(generations, median_nonzeros, color='tomato', linewidth=2, label='median non-zero delta-v')
    ax.plot(generations, clipped_max_scores, color='blue', linestyle=':', linewidth=2, label='best score')
    ax.set_ylim(0, y_cap * 1.15)

    for gen, median_nz, max_score, nz, ni in zip(generations, median_nonzeros, max_scores, n_zeros, n_invalid):
        ax.text(gen, y_cap * 1.08, f"median nz:{median_nz:.0f}\nmax:{max_score:.0f}\nzeros:{nz}\ninvalid:{ni}",
                ha='center', va='top', fontsize=7, color='dimgray')

    ax.set_xlabel('generation')
    ax.set_ylabel('delta-v (m/s)')
    ax.set_title('GA run — delta-v by generation')
    handles, labels = ax.get_legend_handles_labels()
    by_label = dict(zip(labels, handles))
    ax.legend(by_label.values(), by_label.keys())
    plt.tight_layout()
    plt.show()
