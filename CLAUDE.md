# ksp rocket design project — agent instructions

## what this project is

a system to programmatically generate, validate, simulate, and eventually train a model to design rockets for **KSP1**. equally important: the user is learning how to build these systems and how to work with coding agents. completion speed is secondary to user understanding.

read `ksp_project_agent_brief.md` for full context. read the latest file in `llm_docs/sessions/` and `llm_docs/handoffs/` before starting any work.

---

## non-negotiable agent behavior

- **do not run ahead.** propose one piece at a time, explain it, wait for the go-ahead, then build it
- the user writes code in notebooks themselves — the agent explains, reviews, and catches bugs. do not write full implementations unprompted unless explicitly asked
- pause at natural checkpoints. do not make a large number of design decisions unilaterally
- optimize for user understanding, not completion speed
- if choosing between finishing faster (hiding logic) vs moving slower (building understanding): **choose slower**

## workflow conventions

- **notebooks first**: all new features are built and tested in notebooks before moving to `src/` or `scripts/`
- **then scripts**: once a notebook is verified, extract functions to `src/` and build a CLI in `scripts/`
- **no changes on extract**: when moving code from a notebook to `src/`, copy it exactly as written — do not refactor, simplify, or restyle. docstrings may be added, nothing else
- **verbose flag**: diagnostic functions take a `verbose=False` parameter — when True, print human-readable detail; when False, return only the machine-readable result
- **session docs**: create `llm_docs/sessions/session_YYYY-MM-DD.md` at the start of each session and update it continuously
- **handoffs**: write `llm_docs/handoffs/handoff_YYYY-MM-DD.md` at the end of each session

---

## project architecture (pipeline)

```
design generator               ← DONE (GA complete)
    ↓
structure validator            ← DONE (Goal 0)
    ↓
analytic filters               ← DONE (TWR, delta-v, burn time)
    ↓
craft serialization            ← IN PLACE (`src/craft.py`, prototype but usable)
    ↓
top candidates → KSP runner    ← IN ACTIVE DEVELOPMENT (`scripts/run_saved_rocket.py`)
    ↓
mission telemetry / run logs   ← IN PLACE (`results/ksp_runs/`)
    ↓
surrogate simulator / dataset / model training ← not started
```

KSP is slow. treat it as the expensive ground-truth oracle, not the primary training loop.

## curriculum goals

- **Goal 0** — structural validity (DONE)
- **Goal 1** — exit atmosphere (apoapsis >= 70 km)
- **Goal 2** — reach orbit (enough delta-v to circularize)
- **Goal 3** — reach Mun orbit
- **Goal 4** — land on Mun

## deferred milestones

- **CoM/CoL stability** — KSP checks center of mass vs center of lift. An aerodynamically unstable rocket will flip. Requires placing parts in 3D space (attachment offsets along vertical axis). Natural prerequisite for `to_craft()` since craft files encode part positions. Will become a cheap analytic filter sitting between the current filters and the KSP oracle.
- **Morphological freedom** — radial attachment, fairings, nose cones, fins. Deferred until linear stack GA is mature.
- **Progressive complexity** — increase `max_stages` after average dv threshold met. Planned, not yet implemented.
- **`Rocket.from_dict()`** — classmethod on `Rocket`. Needed before `to_craft()`. Note in `src/rocket.py`.

---

## key files and data

| path | description |
|------|-------------|
| `data/parts_library.json` | 358 parsed KSP1 stock parts (source of truth) |
| `data/toy_rocket.json` | minimal 3-part test rocket |
| `src/scraper.py` | KSP .cfg parser and part extractor |
| `src/structure.py` | all structural validity checks + `validate_rocket` |
| `src/filters.py` | TWR, delta-v, burn-time filters + `compute_delta_v` (return_breakdown flag) |
| `src/genetic_algorithm.py` | full GA: generate, score, evaluate, select, mutate, crossover, run_ga |
| `src/plots.py` | `plot_run` — visualise GA run with outlier clipping |
| `src/config.py` | `load_part_lists` → `(pods, tanks, engines, decouplers)` |
| `src/rocket.py` | `Rocket` class — TODO: add `from_dict()` classmethod |
| `src/craft.py` | linear-stack `.craft` serializer extracted from notebook research |
| `scripts/scrape_ksp_parts.py` | CLI to regenerate parts library from KSP install |
| `scripts/check_rocket_structure.py` | CLI to validate a rocket JSON |
| `scripts/filter_rocket.py` | CLI to score/filter a saved rocket JSON with analytic filters |
| `scripts/generate_rocket.py` | CLI to generate a random rocket from the current part lists |
| `scripts/run_ga.py` | CLI to run the GA |
| `scripts/plot_run.py` | CLI to plot a saved GA run |
| `scripts/run_saved_rocket.py` | generate/write/fly a saved rocket through the live KSP mission runner |
| `notebooks/building_the_parser.ipynb` | parser walkthrough (complete) |
| `notebooks/structural_validator.ipynb` | validator walkthrough (complete) |
| `notebooks/analytic_filters.ipynb` | filters walkthrough (complete) |
| `notebooks/design_generator.ipynb` | GA walkthrough (complete) |
| `ksp_project_agent_brief.md` | full project brief |
| `llm_docs/sessions/` | per-session progress logs |
| `llm_docs/handoffs/` | end-of-session handoff documents |
| `llm_docs/design_decisions.md` | running log of major design decisions |

## rocket dict format

```json
{
  "parts": [
    {"id": "pod_0",  "type": "mk1-3pod",     "parent": null},
    {"id": "tank_0", "type": "fuelTank",     "parent": "pod_0",  "attach_node": "bottom"},
    {"id": "eng_0",  "type": "liquidEngine", "parent": "tank_0", "attach_node": "bottom"}
  ],
  "stages": {"eng_0": 0}
}
```

- `type` must match an internal KSP part name from `parts_library.json`
- `attach_node` names a node on the **parent** part (not the child)
- `stages`: maps part id → stage number (non-negative int, 0 fires last)

---

## current status

The earlier analytic/GA phase is complete, and the project has already moved into live KSP execution.

Current reality:

- Goals 0 and 1 analytic filters are complete.
- The GA (`src/genetic_algorithm.py`) is fully built, tested, and extracted.
- `.craft` generation exists in `src/craft.py` and is already being used by the live runner.
- `scripts/run_saved_rocket.py` now writes craft files, loads them into a KSP save, runs a mission, and records run artifacts under `results/ksp_runs/`.
- The mission can now reach Kerbin orbit and survive into the Mun-transfer phase.

The active blocker from the latest handoff/session notes is narrow and runtime-specific:

- the surviving Terrier upper stage is present
- it still has `LiquidFuel` / `Oxidizer`
- it reports nonzero `available_thrust`
- but it produces `actual_thrust = 0.0` during the Mun transfer burn

**next work should prioritize:**
1. Diagnose engine runtime behavior in `scripts/run_saved_rocket.py` during upper-stage transfer burn.
2. Verify whether a more direct engine activation / throttle path is needed through kRPC.
3. Only after that, return to parking-orbit efficiency / mission-tuning cleanup.
4. Keep deferred infrastructure items in view: CoM/CoL filter, surrogate simulator, dataset-building, and training.
