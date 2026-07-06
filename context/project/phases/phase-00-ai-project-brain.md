# Phase 00 - AI Project Brain Bootstrap

## Objective

Create a durable project brain so Claude Code can work on this platform with continuity, discipline, and domain awareness.

## Scope

Included:

- `.claude` operating instructions
- `context` structure
- project manifesto
- roadmap
- phase system
- architecture overview
- domain knowledge
- EA analysis
- governance and standards

Excluded:

- product UI implementation
- backend implementation
- EA modification
- live trading

## Acceptance Criteria

- Claude can load project intent from repository files.
- The EA is documented as a knowledge source and future agent, not as the platform brain.
- Next phase is explicit.
- Risk and governance constraints are documented.

## Completion Status

Completed and closed on 2026-07-06.

Verification performed at closure:

- All acceptance criteria confirmed against the repository content.
- `../NOTES/` source material fully indexed in `context/knowledge/source_notes_index.md`.
- Visual reference images renamed to descriptive names (`reference-*.png/webp`) and references updated in `context/frontend/visual_reference_analysis.md`.
- Baseline `npm run lint` passes.
- The full project brain (`.claude/`, `context/`, `CLAUDE.md`) committed to git so the memory is durable.

## Completion Notes

Created:

- `.claude/` operating instructions
- `context/` project brain
- project manifesto
- roadmap and phases
- handoff and memory files
- architecture overview and bounded contexts
- domain notes for ICT/SMC, FTMO risk, EA analysis, and trading ontology
- engineering, governance, workflow, prompt, and template files
- WebSocket-first realtime context
- visual reference analysis and final interface specification

Important decisions recorded:

- platform over EA
- Next.js dashboard and .NET/SignalR backend direction
- WebSocket-first infrastructure

Phase 00 is closed. Context refinements discovered later should be recorded through normal handoff/changelog updates, not by reopening this phase. The active next phase is Phase 01 - Frontend Foundation, which must start with a design per `.claude/commands/phase-start.md`.
