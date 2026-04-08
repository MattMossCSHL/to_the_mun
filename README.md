# KSP Rocket Evolution

AI system for designing Kerbal Space Program 1 rockets with a staged pipeline:

parts parser -> structural validator -> analytic filters -> genetic algorithm -> `.craft` generation -> live KSP runner

## Current State

The parser, validator, filters, and GA are already built. The repo also now contains:

- `src/craft.py` for prototype-but-usable `.craft` serialization
- `scripts/run_saved_rocket.py` for writing a craft into a save, flying it through KSP via kRPC, and recording run artifacts in `results/ksp_runs/`

Latest progress from the handoff/session docs:

- mission runs now reach Kerbin orbit and survive into the Mun transfer phase
- the active blocker is the Terrier upper stage producing zero `actual_thrust` during transfer burn despite existing, having fuel, and reporting nonzero `available_thrust`

Project guidance and state history live in:

- `CLAUDE.md`
- `CODEX.md`
- `ksp_project_agent_brief.md`
- `llm_docs/sessions/`
- `llm_docs/handoffs/`

By: Matt Moss
