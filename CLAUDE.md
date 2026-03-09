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
design generator
    ↓
structure validator       ← Goal 0 (DONE)
    ↓
analytic filters          ← Goal 1+
    ↓
surrogate simulator       ← Goal 1+
    ↓
top candidates → ksp harness
    ↓
dataset → model training
```

KSP is slow. treat it as the expensive ground-truth oracle, not the primary training loop.

## curriculum goals

- **Goal 0** — structural validity (DONE)
- **Goal 1** — exit atmosphere (apoapsis >= 70 km)
- **Goal 2** — reach orbit (enough delta-v to circularize)
- **Goal 3** — reach Mun orbit
- **Goal 4** — land on Mun

---

## key files and data

| path | description |
|------|-------------|
| `data/parts_library.json` | 358 parsed KSP1 stock parts (source of truth) |
| `data/toy_rocket.json` | minimal 3-part test rocket |
| `src/scraper.py` | KSP .cfg parser and part extractor |
| `src/structure.py` | all structural validity checks + `validate_rocket` |
| `scripts/scrape_ksp_parts.py` | CLI to regenerate parts library from KSP install |
| `scripts/check_rocket_structure.py` | CLI to validate a rocket JSON |
| `notebooks/building_the_parser.ipynb` | parser walkthrough (complete) |
| `notebooks/structural_validator.ipynb` | validator walkthrough (complete) |
| `ksp_project_agent_brief.md` | full project brief |
| `llm_docs/sessions/` | per-session progress logs |
| `llm_docs/handoffs/` | end-of-session handoff documents |

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

Goal 0 is complete. the structural validator is fully implemented and tested.
The `Rocket` class is complete (`src/rocket.py`, `notebooks/rocket_representation.ipynb`).

**next task**: `notebooks/analytic_filters.ipynb`

build three analytic filters — TWR, delta-v, burn time — that cheaply screen rocket designs before KSP simulation. resource densities are scraped from `ResourcesGeneric.cfg` via `parse_cfg`. all filter functions take `(rocket_dict, parts_by_name, resource_lookup)`. extract to `src/filters.py` when done.
