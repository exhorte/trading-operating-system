"""The HTTP / WebSocket surface of the core (FastAPI). No business rule lives here: a route reads a service, calls one, or
shapes what it returned — the rules are in ``domain/`` and the orchestration in ``services/``."""
