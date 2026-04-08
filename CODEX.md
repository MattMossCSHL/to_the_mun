# Codex Agent Notes

This file exists so Codex has a repo-local entry point. It does not replace the canonical project guidance in `CLAUDE.md`; it points to it.

## Read First

Before doing substantive work in this repo, read:

1. `CLAUDE.md`
2. `ksp_project_agent_brief.md`
3. the latest file in `llm_docs/sessions/`
4. the latest file in `llm_docs/handoffs/`

## Working Rules

- Do not run ahead of the user.
- Optimize for user understanding over delivery speed.
- Build and test new ideas in notebooks first.
- When extracting notebook code into `src/` or `scripts/`, copy logic exactly. Only docstrings may be added.
- Treat existing uncommitted changes as user work unless clearly proven otherwise.
- Keep session docs updated in `llm_docs/sessions/`.
- Write a handoff in `llm_docs/handoffs/` at the end of a working session.

## Current Direction

As of the latest recorded notes, the project is already past the pure-GA phase:

1. the GA / analytic pipeline is complete
2. `.craft` generation exists in `src/craft.py`
3. the live KSP runner exists in `scripts/run_saved_rocket.py`
4. current mission progress reaches Kerbin orbit and the Mun-transfer phase
5. the active blocker is runtime upper-stage behavior: the surviving Terrier has fuel and nonzero `available_thrust` but still shows `actual_thrust = 0.0` during transfer burn

Near-term focus:

1. inspect and fix upper-stage engine activation / throttle / feed behavior in the runner
2. only then return to mission-efficiency tuning
3. keep longer-horizon deferred work in view: CoM/CoL, surrogate sim, dataset, training
