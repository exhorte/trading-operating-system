"""MT5 integration (ADR 0016). Two separate things, never merged (ADR 0010):

* **read** — ``Mt5Client`` drives a read-only worker process around the ``MetaTrader5`` package (account, positions,
  orders, ticks, candles, history, symbol specifications). The worker's whitelist contains no order function.
* **execute** — ``EaLinkServer`` speaks to the MQL5 execution agent over a local TCP socket (NDJSON). The agent holds the
  only ``OrderSend`` of the repository, behind its compiled mode ceiling.

``MetaTrader5`` is imported in exactly one module (``worker.py``) — a test enforces it.
"""
