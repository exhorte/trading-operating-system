# Changelog

This file tracks meaningful changes to the project brain and architecture.

## 2026-07-06

### Added - AI Project Brain

- Created `.claude/` operating instructions for Claude Code.
- Created the `context/` project brain.
- Added project manifesto, roadmap, phase files, memory, and handoff.
- Added architecture overview and bounded contexts.
- Added trading ontology, ICT/SMC framework notes, FTMO risk context, and EA analysis.
- Added engineering stack, standards, testing strategy, governance, workflows, prompts, ADRs, and agent role definitions.

### Added - Source Analysis

- Indexed source notes from `../NOTES/`.
- Analyzed `Ultimate_ICT_Gold_Scalper_v4.0.mq5`.
- Documented that the EA is a knowledge source and future MT5 execution/telemetry agent, not the platform brain.

### Changed - WebSocket-First Architecture

- Replaced API-first direction with WebSocket/SignalR-first architecture for trading flows.
- Added `context/realtime/`.
- Added realtime event envelope, event families, execution commands, acknowledgements, and execution report examples.
- Added MT5 agent realtime lifecycle guidance.
- Updated architecture, backend plan, frontend plan, stack, governance, prompts, roadmap, phases, and handoff.

### Added - ADR

- Added `ADR 0001 - Platform Over EA`.
- Added `ADR 0002 - Next.js Dashboard And .NET Backend Target`.
- Added `ADR 0003 - WebSocket-First Infrastructure`.

### Added - Visual Interface Direction

- Analyzed visual references added in `context/templates/`.
- Added `context/templates/README.md`.
- Added `context/frontend/visual_reference_analysis.md`.
- Added `context/frontend/final_interface_spec.md`.
- Updated Phase 01 to use the visual spec.

### Changed - Phase 00 Closure

- Audited Phase 00 against its acceptance criteria; all met.
- Committed the full project brain (`.claude/`, `context/`, `CLAUDE.md`) to git for durability.
- Renamed visual reference images in `context/templates/` to descriptive `reference-*` names and updated `frontend/visual_reference_analysis.md`.
- Closed Phase 00; Phase 01 - Frontend Foundation is now the active phase.

### Current Next Step

Start Phase 01 by designing the frontend command center around:

- dark dense trading cockpit
- mock realtime subscriptions
- WebSocket state
- risk-first KPI strip
- MT5 agent health
- ICT/SMC market context
- signal queue
- execution reports
- trade journal and future replay workspace
