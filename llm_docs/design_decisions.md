# design decisions — open questions and resolved choices

a running record of architectural decisions, deferred choices, and design tradeoffs.

---

## population tuple structure

**status: open**

original plan was `(rocket_dict, score)`. but if we want to support per-generation export and eventual feature selection / surrogate model training, we probably want richer metadata attached to each rocket.

### option A — `(rocket_dict, score)`
- simple to unpack
- score only — no breakdown of *why* a rocket passed or failed
- metadata would have to be reconstructed from the rocket dict later

### option B — `(rocket_dict, metadata_dict)`
where `metadata_dict` looks like:
```python
{
    'score':     float,    # delta-v or 0
    'valid':     bool,     # passed structural validation
    'filtered':  bool,     # passed analytic filters
    'n_stages':  int,
    'n_parts':   int,
    'stage_dv':  list,     # per-stage delta-v breakdown
    'generation': int,     # which generation it was born in
}
```
- richer data for export and eventual model training
- easy to add fields later without breaking function signatures
- slightly more verbose to unpack, but `m['score']` is readable

### option C — list of dicts (not tuples)
```python
{'rocket': rocket_dict, 'score': float, 'valid': bool, ...}
```
- most extensible
- loses the clean positional tuple feel
- harder to do tuple-style unpacking

**recommendation:** option B. metadata dict travels with the rocket, score is still easy to access (`m['score']`), and we get the full picture for export and future training. the tuple unpacking is `rocket, meta = individual` which is clean.

---

## per-generation export

**status: open — design not yet started**

user wants to export all rockets per generation to JSON for inspection and demos.

### natural format
```json
{
  "generation": 0,
  "rockets": [
    {
      "rocket": { "parts": [...], "stages": {...} },
      "score": 3200.0,
      "valid": true,
      "filtered": true,
      "n_stages": 2,
      "n_parts": 6,
      "stage_dv": [1800.0, 1400.0],
      "generation": 0
    },
    ...
  ]
}
```

### where to write it
- end of each generation in the main GA loop, not inside `evaluate_population`
- `evaluate_population` produces the population; the loop decides whether/where to save it
- suggests a `save_generation(population, generation_num, path)` utility function

### output directory
- `data/runs/run_YYYY-MM-DD-HHMMSS/gen_000.json` or similar
- keeps runs separated so demos are reproducible

---

## progressive complexity — max_stages

**status: open — not yet implemented**

after the GA finds good designs at a given complexity level, allow it to explore more complex rockets.

### idea A — increase max_stages over time

when the population's average score (or top-N average) crosses a threshold, increase `max_stages` from 2 → 3 → etc. new rockets generated in subsequent generations can have more stages; existing rockets in the population are unaffected.

**pros:**
- simple to implement — one parameter changes
- natural curriculum: master 1-2 stage rockets before trying 3+
- score threshold is better than generation threshold (generation-based could increase too early if the GA is stuck)

**cons:**
- threshold value needs tuning — too low means premature explosion of search space; too high means the GA plateaus and never grows
- could cause a "regression dip" as new more-complex (but initially low-scoring) rockets dilute the population

**mitigations:**
- track `top_k_average` rather than population average — less sensitive to the many 0-scoring rockets
- add complexity slowly (one stage at a time)
- consider a cooldown: once complexity increases, don't increase again for N generations

### idea B — allow radial attachment

after multi-stage is working, allow parts to attach to non-bottom nodes (side-mounted boosters, radial decouplers). this maps to real KSP staging where radial boosters are common for early ascent.

**pros:**
- opens up a much larger and more realistic design space
- radial staging is a key strategy in KSP (Atlas-style, Falcon 9 crossfeed, etc.)

**cons:**
- bigger structural change than idea A — the rocket part tree becomes branching, not linear
- structural validator assumes a linear chain in several places; would need updating
- `generate_random_rocket` would need a new code path for radial attachment
- attach node names vary by part and aren't uniformly 'side' — would need to scrape valid node names per part

**recommendation:** do idea A first. get the GA working well with linear multi-stage rockets. treat idea B as a separate milestone (likely Goal 2 or Goal 3 territory) once the pipeline is proven.

---

## `Rocket.from_dict()` — deferred

**status: deferred**

mutation functions currently manipulate rocket dicts directly because there's no way to reconstruct a `Rocket` object from an existing dict. a `from_dict(rocket_dict, parts_by_name)` classmethod would allow mutation functions to use `add_part` and `set_stage` properly instead of appending to lists and dicts by hand.

implement when: the mutation/crossover functions get complex enough that direct dict manipulation becomes error-prone, or when a refactor of the GA functions is warranted.

---

## fitness function

**status: resolved**

`fitness = delta_v or 0`. cliff at 0, gradient above it. no partial credit.
revisit only if generation 0 yields zero valid designs.

---

## selection method

**status: resolved**

tournament selection (not fitness-proportionate). robust to skewed score distributions, preserves diversity, simpler implementation.

---

## crossover method

**status: resolved in principle, not yet implemented**

stage-level crossover: upper stages from parent A, lower stages from parent B.

---

## tournament selection — how it works

```
POPULATION (n=8)
┌─────────────────────────────────────────────────────┐
│  A:4200  B:0  C:3100  D:0  E:5800  F:0  G:2400  H:0 │
└─────────────────────────────────────────────────────┘

ROUND 1 — pick tournament_size=3 random rockets, keep the best
  randomly pick → [ C:3100,  F:0,  E:5800 ]
                                    ↑ winner
  → survivor 1: E

ROUND 2 — repeat
  randomly pick → [ B:0,  A:4200,  G:2400 ]
                          ↑ winner
  → survivor 2: A

ROUND 3 — repeat
  randomly pick → [ E:5800,  D:0,  C:3100 ]
                    ↑ winner
  → survivor 3: E   ← same rocket can win twice, that's intentional

... repeat until n_survivors collected

SURVIVORS: [ E, A, E, ... ]
```

the key lever is `tournament_size`:
- **small (2)** — weak rockets can survive if they avoid strong opponents. more diversity, slower convergence.
- **large (5+)** — the best rockets almost always win. population converges fast, risk of losing diversity.
- **3** is the typical default — enough pressure to improve, not so much that everything collapses to one design.
