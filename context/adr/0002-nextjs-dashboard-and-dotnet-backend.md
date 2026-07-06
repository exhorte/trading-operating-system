# ADR 0002 - Next.js Dashboard And .NET Backend Target

## Status

Accepted As Direction

## Context

The source notes recommend a professional stack optimized for dashboard development, realtime communication, computation, and maintainability.

## Decision

Use Next.js with React and TypeScript for the dashboard.

Target ASP.NET Core with SignalR for backend trading services.

## Consequences

- The current repository can begin with frontend and project-brain work.
- Backend contracts should be designed so they can later map cleanly to .NET DTOs.
- Realtime UX should anticipate SignalR/WebSocket flows.
- Domain logic should not be trapped in frontend components.

