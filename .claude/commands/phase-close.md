# Phase Close Command

Use this command when a phase or substantial task is completed.

## Required Procedure

1. Run the relevant checks:
   - `npm run lint`
   - `npm run build` when UI or Next.js behavior changed
   - targeted tests when available
2. Update:
   - `context/project/project_state.md`
   - `context/project/handoff.md`
   - the active phase file
   - ADRs if an architecture decision was made
   - domain or engineering context if the implementation changed project truth
3. Summarize:
   - what changed
   - what was verified
   - what remains open
   - next recommended phase

Never leave project memory stale after a meaningful change.

