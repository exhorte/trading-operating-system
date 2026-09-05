<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

# Ce projet

Poste de travail personnel pour trader intraday. Le process est le produit, pas le signal.

Avant de coder, lire `.claude/CLAUDE.md`, puis `context/project/charter.md` et `context/project/state.md`.

Trois règles qui coupent court à la plupart des mauvaises pistes :

- La recherche d'edge est close (`context/adr/0002-fin-de-la-recherche-d-edge.md`). Pas de backtester, pas d'optimiseur, pas de générateur de signaux.
- Toute règle de trading passe par une gate du Risk Engine, jamais par l'interface (ADR 0007).
- L'IA reste en lecture : classer, résumer, expliquer. Jamais décider (ADR 0005).
