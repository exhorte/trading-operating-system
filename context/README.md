# Project Brain

This directory is the durable project brain for the Trading Operating System Algorithmique.

It exists so that Claude Code and future AI coding assistants can understand the project beyond a single chat session.

## Reading Order

1. `project/development_manifesto.md`
2. `project/project_state.md`
3. `project/roadmap.md`
4. Current phase in `project/phases/`
5. Relevant architecture and domain files
6. `realtime/` files for dashboard, backend, MT5, execution, risk, or market data flows
7. Governance, standards, templates, and workflows as needed

## Directory Map

- `project/` - vision, manifesto, roadmap, phases, memory, handoff.
- `agents/` - specialist Claude role definitions for architecture, trading, risk, frontend, MT5, and QA.
- `architecture/` - system design, bounded contexts, data flows.
- `domain/` - trading, ICT/SMC, EA analysis, FTMO/risk knowledge.
- `engineering/` - stack, standards, testing strategy.
- `governance/` - quality gates and decision process.
- `knowledge/` - source note index and long-term research memory.
- `frontend/` - dashboard cockpit planning.
- `backend/` - future server/platform planning.
- `realtime/` - WebSocket-first architecture, event contracts, dashboard subscriptions, MT5 lifecycle.
- `infrastructure/` - deployment and local infrastructure planning.
- `backtesting/` - historical validation strategy.
- `monitoring/` - observability and audit requirements.
- `security/` - secrets, execution safety, and access control.
- `ai/` - future AI-assisted optimization scope.
- `workflows/` - repeatable development process.
- `prompts/` - reusable prompts for Claude Code.
- `templates/` - reusable document templates.
- `adr/` - architecture decision records.

## History Files

Use these files to understand project evolution:

- `project/changelog.md` - chronological list of important changes.
- `project/handoff.md` - narrative handoff between sessions.
- `project/memory.md` - durable facts and recent project memory.
- `project/project_state.md` - current state, next phase, decisions, open questions.

## Project Source Material

The original notes live in `../NOTES/`.

Those files define the founding intent:

- Build a platform, not only an EA.
- Use the EA as an execution connector and knowledge source.
- Create a server-side ICT/SMC framework.
- Keep risk management and prop firm constraints central.
- Build a dashboard cockpit with explainable signals, risk, trades, and analytics.
