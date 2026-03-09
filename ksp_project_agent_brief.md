# ksp rocket design learning project

## purpose

this project is to build a system that can design rockets for **ksp1** using programmatic generation, cheap surrogate physics, and eventually in-game evaluation and model training.

but just as important:

> this project is also for me to learn how to build these systems and how to work with coding agents.

that means all agents working on this project must **not run ahead of me**.

## agent behavior constraints

agents should follow these rules:

- do **not** sprint ahead into a giant opaque implementation
- prefer **small, understandable components**
- explain architecture and rationale before building major features
- keep code modular and inspectable
- prefer scaffolding and incremental progress over “full solution” dumps
- pause at natural checkpoints rather than making a huge number of design decisions unilaterally
- optimize for **my understanding**, not just completion speed
- I strongly prefer to test new functionality in notebooks and demonstrate progress with prints and plots. I will want to verify each new feature in this way as we progress
- everything built in a notebook eventually gets turned into a script/module in `src/`. notebooks are for building and understanding; scripts are the deliverable
- functions that produce diagnostic output should support a `verbose` flag (or similar): when `True`, print human-readable detail (error messages, warnings, etc.); when `False`, return only the machine-readable result (bool, score, etc.). this supports both interactive debugging and automated pipeline use

this matters a lot. i do want to complete the project, but i also want to understand the moving parts and use this as a learning experience.

---

## high-level project idea

the long-term system will:

1. generate rocket designs
2. validate them structurally
3. evaluate them using cheap analytic / surrogate physics
4. send only promising designs into **ksp itself** for ground-truth evaluation
5. use the resulting data to train a model
6. eventually connect the model back to ksp for iterative improvement

the important architectural decision is that **ksp is expensive and slow**, so it should be treated as the final oracle, not the primary training environment.

the intended funnel is:

```text
design generator
    ↓
structure validator
    ↓
analytic constraints
    ↓
toy / surrogate simulator
    ↓
top candidates → ksp harness
    ↓
dataset
    ↓
model training
```

the core principle is:

> evaluate huge numbers of designs cheaply first, then use ksp only for the small subset worth testing in the real environment.

---

# PLAN

## path a: craft-file based pipeline

for ksp1, the practical first route is **not** writing an in-editor builder api. instead:

- represent rocket designs in a constrained machine-readable schema
- compile those designs into `.craft` files
- drop those craft files into the correct ksp save directory
- use a harness to load, launch, test, and record results

this avoids the pain of trying to manipulate the vab directly through a custom mod from day one.

## representation

the model / generator should **not** emit raw `.craft` text directly.

instead it should emit a constrained representation such as:

- parts
- parent / child relationships
- attachment nodes
- symmetry groups (later)
- stage assignments

or, even better, an action sequence like:

```text
add_part mk1pod
add_part fueltank
attach fueltank mk1pod bottom top
add_part liquidengine
attach liquidengine fueltank bottom top
set_stage liquidengine 0
end
```

this makes it easier to enforce validity during generation.

## infrastructure ordering

the intended order of development is:

1. build the **training set infrastructure**
2. build the **model infrastructure**
3. only after that, hook the model up to the game for iterative training

that ordering is deliberate. we do **not** want to jump straight into online in-game training.

## why not use only ksp?

because ksp is slow. the true rocket behavior we care about lives inside the game’s physics/runtime, but using that for all training would be painfully expensive.

so the compromise is:

- use **cheap filters and surrogate physics** to reject obvious trash
- use ksp only as the expensive ground-truth evaluator

## harness choice

when the time comes to connect to the game, the preferred path is a **small in-game harness/plugin**, not fragile gui automation.

the harness should eventually:

- load a named craft
- launch it
- execute a deterministic mission script
- collect telemetry
- write results to disk
- reset / revert for the next run

but this comes **after** the earlier infrastructure is in place.

---

# curriculum goals 0 through 4

## goal 0 — structural validity

before simulating anything, rocket designs must be structurally valid.

a valid design should satisfy at least:

- one connected part tree
- exactly one root part
- at least one command / control source
- at least one engine
- propellant compatibility for engines
- valid attachment nodes
- valid stage references
- no cycles
- no impossible part references

goal 0 is purely about generating **possible rockets**, not good rockets.

no physics is required here.

---

## goal 1 — exit atmosphere

### objective

build rockets that can leave kerbin’s atmosphere.

practical success criterion:

```text
apoapsis >= 70 km
```

### cheap offline constraints

before expensive simulation, candidates should pass simple filters such as:

- liftoff twr in a sane range, e.g. `1.2 <= twr <= 2.5`
- total delta-v above a rough threshold, e.g. `~2500 m/s`
- first-stage burn time above a minimum, e.g. `~25 s`

### surrogate sim

use a simplified ascent model with minimal state:

- altitude
- velocity
- mass

and simple physics:

- thrust
- gravity
- exponential atmosphere density
- crude drag

the purpose of this sim is **not** realism. its purpose is to reject obvious garbage cheaply.

---

## goal 2 — exit atmosphere with enough fuel to orbit

### objective

build rockets that:

- exit the atmosphere
- still retain enough delta-v to circularize into orbit

practical success criterion:

```text
apoapsis >= 70 km
and
remaining delta-v >= circularization requirement
```

### cheap offline constraints

examples:

- total delta-v `>= ~4500 m/s`
- upper-stage delta-v `>= ~1200 m/s`

### surrogate orbital check

once the rocket reaches high apoapsis, estimate whether remaining fuel is sufficient to circularize.

again, the point is not perfect orbital fidelity. the point is to cheaply distinguish:

- rockets that only barely hop upward
- rockets that plausibly have orbital margin

---

## goal 3 — reach orbit of another body

initial target should be **mun**.

### objective

build rockets that can:

1. reach kerbin orbit
2. perform a transfer burn
3. enter the target body’s sphere of influence
4. capture into orbit around that body

### practical delta-v framing

rough mission ladder:

- low kerbin orbit
- transfer to mun
- mun capture

because guidance and control will be imperfect, designs should include margin rather than aiming for razor-thin numbers.

### surrogate sim

at this stage, move from the simple ascent model to a **patched-conic style orbital simulator**.

the simulator only needs enough fidelity to answer:

- can this design plausibly reach transfer conditions?
- can it plausibly capture at the destination?
- how much fuel margin remains?

---

## goal 4 — land on another body

initial landing target should also be **mun**.

### objective

build rockets that can:

1. reach mun orbit
2. descend safely
3. land intact

### additional constraints

at this stage, designs likely need:

- meaningful landing-stage delta-v margin
- sufficient thrust-to-weight on the destination body
- stable landing configuration
- appropriate final-stage engine choice

### surrogate sim

extend the orbital simulator with a simplified descent / landing phase.

this does not need full ksp fidelity. it only needs to cheaply estimate whether the design plausibly has enough:

- propulsive margin
- deceleration capability
- structural sanity for landing

---

# dataset-building infrastructure

the first implementation priority is the **training set infrastructure**.

the rough pipeline should be:

```text
design generator
    ↓
structure validator
    ↓
analytic filters
    ↓
surrogate simulator
    ↓
select top candidates
    ↓
optional ksp harness evaluation
    ↓
store results in dataset
```

each dataset example should eventually include some combination of:

- design specification
- derived structural / physics features
- surrogate metrics
- ksp metrics, if evaluated
- reward or success / failure labels
- failure mode information

important note:

> we do not need to start with the full end-state dataset format.

start simple and keep it inspectable.

---

# model-building infrastructure

after data infrastructure exists, the next priority is the **model infrastructure**.

this should likely include:

- a constrained representation for rocket designs
- a tokenizer / action vocabulary if using action sequences
- dataset loaders
- validation-aware generation
- simple baseline models before anything fancy

probable training progression:

1. supervised learning on valid / decent designs
2. reward-weighted learning from higher-performing designs
3. later, online improvement using ksp-evaluated results

important note:

> the model should be built after the data pipeline is understandable and stable enough to inspect.

---

# eventual ksp integration for training

only after the earlier infrastructure is working should the project connect the model back to ksp.

that later-stage loop will look something like:

```text
model proposes design
    ↓
compile to .craft
    ↓
harness loads + launches in ksp
    ↓
telemetry and outcome collected
    ↓
result appended to dataset / replay buffer
    ↓
model updated
```

ksp should be treated as the **expensive ground-truth oracle**, not the main place where basic learning happens.

---

# session progress documents

at the start of each working session, the agent should create a markdown document named `session_YYYY-MM-DD.md` (or with a short descriptor if multiple sessions occur in one day) in a `sessions/` directory at the repo root.

session documents live in `llm_docs/sessions/` at the repo root.

this document should track:

- what was worked on
- decisions made and why
- what was built or changed
- what the next steps are
- any open questions

this document should be updated continuously during the session, not just at the end.

the purpose is to support clean agent handoffs and avoid relying on conversation history or context compaction to carry state forward.

---

# final reminder for agents

this project is not just about finishing the system.

it is also about:

- me learning the architecture
- me learning the implementation details
- me learning how to collaborate with agents

so again:

> do not run ahead of me.

favor small steps, clean structure, explanation, and checkpoints over giant implementations.

if there is a choice between:

- finishing faster in a way that hides the logic
- moving slower in a way that helps me understand the system

the second option is preferred.

## note on agent behavior

the agent ran ahead and built the entire parser notebook without checking in at each step. this violated the project brief. the agreement going forward: propose one piece at a time, explain the idea, wait for the go-ahead, let user build it unless agent build is requested, let the user run and verify it, then move to the next piece.
