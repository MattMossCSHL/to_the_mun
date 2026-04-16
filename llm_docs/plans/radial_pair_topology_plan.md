# Radial Pair Topology Plan

## Provenance

This plan is not just an assistant-originated proposal.

The core concept was suggested and fleshed out by Matt in discussion:

- introduce a constrained second topology rather than arbitrary geometry
- focus on a symmetric `radial_pair`, not quads or general branching
- treat both radial boosters together as one mutable/crossable unit
- allow later cross-topology operations to act on the core or the paired radial branch

This document turns that collaboratively developed concept into a more explicit technical plan and implementation sequence.

## Goal

Add a second rocket topology to the search space:

- `linear`
- `radial_pair`

This is meant to be the next step toward Mun-capable vehicles without jumping all the way to arbitrary branching or quad-booster architectures.

The intent is not "general radial attachment." The intent is one constrained new species:

- one central inline core stack
- zero or one symmetric radial booster pair
- both boosters treated as one logical mutable unit


## Why This Is The Right Next Step

The current search space is good at finding narrow inline stacks, but it struggles to discover the kind of launch architecture that real KSP rockets often use for heavier ascent:

- a central sustainer/core
- paired radial boosters for early lift
- symmetric staging and separation

This keeps the next jump in complexity manageable while opening a materially more capable design family.


## Core Design Principle

The radial pair should be treated as one **logical genome unit**, not two independent physical side branches.

That means:

- mutation acts on the pair as one object
- crossover acts on the pair as one object
- left/right physical boosters are only instantiated symmetrically when validating, scoring, or serializing

This avoids left/right drift, asymmetric junk rockets, and a large amount of special-case logic.


## Proposed Representation

Keep one top-level rocket dict shape, but add explicit topology metadata.

Suggested structure:

```python
{
  "topology": "linear" | "radial_pair",
  "core": {
    "parts": [...],
    "stages": {...}
  },
  "radial_pair": None | {
    "attach_core_part_id": "tank_1",
    "symmetry": 2,
    "booster": {
      "parts": [...],
      "stages": {...}
    }
  }
}
```

Alternative if you want less immediate churn:

```python
{
  "topology": "linear" | "radial_pair",
  "parts": [...],
  "stages": {...},
  "topology_meta": {
    "radial_pair": {
      "enabled": true,
      "attach_core_part_id": "tank_1",
      "logical_booster_parts": [...],
      "symmetry": 2
    }
  }
}
```

My recommendation is the first version:

- `core` and `radial_pair.booster` stay logically separate
- mutations stay topology-aware
- the physical expanded part tree can be generated later for validation/craft output

That is cleaner than trying to stuff logical and physical identities into one flat `parts` list.


## Logical vs Physical Rocket

Introduce the distinction explicitly:

- **logical rocket**: the genome the GA mutates and crosses
- **physical rocket**: the expanded KSP-compatible part tree used for validation, scoring, and craft generation

For `linear`, logical and physical are almost identical.

For `radial_pair`:

- the logical booster exists once
- the physical booster exists twice, mirrored left/right

This separation is the key architectural move that keeps the system coherent.


## Phase Plan

### Phase 1: Topology Scaffolding

Add support for:

- `topology = "linear"`
- `topology = "radial_pair"`

But initially keep all generated rockets linear by default.

Work:

- define topology-aware rocket schema
- add helpers to identify logical rocket family
- add expansion function: `expand_logical_rocket(...) -> physical_rocket_dict`
- ensure old linear rockets still work unchanged

Success condition:

- existing linear workflow remains stable
- a hand-authored `radial_pair` logical rocket can be expanded deterministically


### Phase 2: Validation and Serialization Support

Make `radial_pair` physically valid in the current pipeline.

Work:

- validate logical-level invariants
- validate expanded physical rocket structure
- extend craft generation to emit mirrored radial attachments correctly
- stage translation must handle paired boosters and paired decouplers

Important constraint:

- do not support arbitrary radial placement
- do not support multiple radial layers
- do not support asymmetric detach

Success condition:

- one manually specified `radial_pair` rocket can become a valid `.craft`
- KSP loads it with both boosters placed symmetrically


### Phase 3: Seeded Entry Into GA Population

Do not let random generation produce radial-pair rockets immediately.

Instead:

- run early generations as linear only
- after a configurable generation threshold, inject 1-2 valid `radial_pair` exemplars
- let them compete under the same scoring pipeline

Why:

- avoids exploding the early search space
- gives the GA known-good footholds
- lets radial-pair designs prove value before becoming common

Suggested config knobs:

- `radial_pair_intro_generation`
- `radial_pair_seed_count`
- `max_radial_pair_fraction`


### Phase 4: Topology-Aware Mutation

Mutation should dispatch on topology.

Shared mutations:

- swap core part
- add/remove core stage
- change staging assignments where valid

`radial_pair`-specific mutations:

- mutate booster tank
- mutate booster engine
- mutate booster decoupler
- add/remove one booster stage from the logical radial booster
- move radial pair attach point up/down the core stack

Important rule:

- left and right boosters are never mutated independently

The mutation acts on:

- `core`
- `radial_pair.booster`
- `radial_pair.attach_core_part_id`

not on physical left/right instances.


### Phase 5: Topology-Aware Crossover

Initially allow crossover only within the same topology:

- linear x linear
- radial_pair x radial_pair

Do **not** start with linear x radial_pair crossover.

That should come later and be explicit.

For `radial_pair` crossover, choose a logical crossover target with weighted RNG:

- `core`
- `radial_pair.booster`
- later maybe `attach point`

If crossover selects `radial_pair.booster`, it acts on the logical booster genome once, then expands symmetrically.

That is the right abstraction.


### Phase 6: Controlled Cross-Topology Operations

Once both species are stable, add limited cross-topology crossover/mutation.

This should not be "normal crossover but with flags."

It should be treated as a special operation, e.g.:

- `linear -> radial_pair`: graft a paired booster unit onto a linear core
- `radial_pair -> linear`: strip the radial pair away and keep/refit the core
- `radial_pair core swap`: core crosses with linear rocket core, radial pair retained or dropped by explicit rule

Weighted RNG can choose the target:

- `core`
- `radial_pair`

But if `radial_pair` is selected, it must remain paired.

This is exactly the user's intuition, and it is the right model.


## Logical Invariants For `radial_pair`

These should be enforced before physical expansion:

- exactly one core stack
- zero or one radial pair
- radial pair symmetry fixed at 2
- left/right boosters share the same logical parts and staging
- booster attach point references a valid core part
- attach point must be on an allowed core segment
- booster stages must be internally valid
- booster separation is paired

Optional but strongly recommended:

- booster mass or thrust ratio bounds relative to core
- booster root diameter compatibility constraints
- no radial pair attachment to command pod or tiny adapter tops unless explicitly allowed


## Scoring and Comparability

Both topologies should compete in one population only if:

- both expand into physical rockets before validation/filtering
- both are scored through the same downstream pipeline
- both respect comparable part-count and stage-count rules

Avoid giving radial-pair rockets hidden structural privileges.

If a logical booster expands to two physical boosters, that should count in some transparent way when comparing complexity or part count.


## What Should Not Be Attempted Yet

Do not attempt these in the first radial-pair milestone:

- arbitrary branching trees
- quad symmetry
- asparagus crossfeed
- independent left/right staging
- radial-only engines without a clean booster abstraction
- cross-topology crossover as a default operator
- multiple radial-pair layers

Those are all plausible later, but they dramatically enlarge the failure surface.


## Recommended First Exemplar

Seed exactly one or two hand-authored radial-pair designs:

- a simple central sustainer + two identical radial liquid boosters
- paired radial decouplers with shared stage timing
- no crossfeed
- no fancy upper-stage logic beyond what the current runner already handles

This gives the GA a realistic architecture to learn from without forcing it to invent radial symmetry from scratch.


## Suggested Implementation Order

1. Add topology metadata and logical/physical expansion helpers.
2. Hand-author one `radial_pair` logical rocket and expand it.
3. Extend craft serialization for paired radial attachments.
4. Extend validation/filtering to score expanded radial rockets.
5. Seed 1-2 radial-pair exemplars into later generations.
6. Add topology-aware mutation.
7. Add same-topology crossover for `radial_pair`.
8. Add restricted cross-topology operations.


## Main Recommendation

Treat `radial_pair` as a second species, not a small patch on the current linear model.

That means:

- explicit topology
- logical paired booster genome
- physical mirrored expansion
- topology-aware mutation and crossover

If this boundary is kept clean, the feature is very achievable.

If instead radial support is mixed directly into the current flat linear assumptions, the project will accumulate brittle special cases quickly.
