# Quality Gates

## Before Product Code Changes

- Relevant context files are read.
- Existing structure is inspected.
- Impact is understood.
- For large work, a technical design exists.

## Before Merge Or Phase Completion

- Lint passes.
- Build passes when applicable.
- New domain logic has tests or documented test gap.
- Risk-related behavior is explicitly reviewed.
- Project memory is updated.

## Trading-Specific Gates

No live execution feature is acceptable unless:

- commands are auditable
- commands are sent through the approved realtime execution path
- commands are idempotent and acknowledged
- failures are reported
- duplicate commands are handled
- risk lockouts are enforced
- emergency stop path exists
- backtest/simulation path exists
- reconnect/resync behavior is specified

## Realtime Gates

Any WebSocket/SignalR feature must define:

- connection states
- authentication/authorization assumptions
- subscription scope
- event envelope
- reconnect behavior
- stale data behavior
- snapshot resync behavior
- observability fields
