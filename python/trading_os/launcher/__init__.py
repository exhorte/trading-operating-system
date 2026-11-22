"""The Trading OS launcher (ADR 0038): it **prepares and observes**, it never authorizes.

This package knows how to look at the machine (which components run, who holds a port, whether a process is ours), how to plan a
start-up from what it saw, and how to remember — in files, because it runs before the database — what it started. It never decides
anything about trading: it imports nothing from risk, execution, the Guardian or the autonomy ladder (a test enforces it), writes no
MetaTrader permission or credential, and ends no process that is not recorded in its registry.

Increment I1 (this one) is **read-only**: models, ports, the process registry, structured events, the pure plan, read-only adapters
and ``python -m trading_os launcher plan|status``. Starting and stopping come in I2.
"""
