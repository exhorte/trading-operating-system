# Agent Library

These are role definitions for Claude Code. They are not separate processes yet; they are thinking modes Claude should activate depending on the phase.

## Required Pattern

Each agent must:

- read the relevant context before acting
- operate inside its responsibility boundary
- produce structured outputs
- update project memory when its work changes project truth

## Agents

- `coordinator.md` - orchestrates phases and context.
- `principal-architect.md` - owns architecture and ADRs.
- `trading-domain-engineer.md` - owns trading concepts and ICT/SMC interpretation.
- `risk-engineer.md` - owns risk and prop firm constraints.
- `frontend-engineer.md` - owns dashboard implementation.
- `mt5-execution-engineer.md` - owns MQL5/MT5 connector evolution.
- `qa-reviewer.md` - owns verification and quality gates.

