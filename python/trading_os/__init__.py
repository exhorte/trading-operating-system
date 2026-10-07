"""Trading Operating System — Python-native core (ADR 0016).

One process, modular: ``domain`` (pure rules) → ``services`` (orchestration) →
``infrastructure`` (MT5, database, news, secrets) behind ``api`` (FastAPI) and
``runtime`` (engine, supervisor, heartbeat, scheduler).
"""

__version__ = "0.2.0"
