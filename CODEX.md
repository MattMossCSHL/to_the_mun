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

As of the latest recorded notes, the GA pipeline is complete and the next likely work items are:

1. atmospheric delta-v handling for air-breathing engines
2. `to_craft()` and craft-file generation
3. `Rocket.from_dict()`
4. progressive complexity for `max_stages`
5. kRPC research
