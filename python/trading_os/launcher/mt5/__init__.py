"""The MetaTrader 5 side of the launcher (ADR 0038 § 6, ADR 0039 § 4): finding terminals, remembering them, and describing what preparing them
would take. Everything here **looks**; the one thing it writes is the launcher's own ``var/launcher/terminals.json``. It writes nothing inside a
MetaTrader folder — that comes with the deployment increments, behind their own tests."""
