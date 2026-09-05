# Architecture Decision Records — série 2

La série 1 (`0001-platform-over-ea` à `0013-backtest-diagnostics`, juillet 2026) a été supprimée le 2026-09-04 avec le reste de l'historique de recherche.

Les décisions de la série 1 qui gouvernent encore ont été reprises et réécrites ici. Celles qui portaient sur la recherche d'edge (moteur de signal, backtesting, diagnostics, holdout) sont caduques.

| # | Titre | Statut |
|---|---|---|
| 0001 | Le process est le produit | Accepté |
| 0002 | Fin de la recherche d'edge | Accepté |
| 0003 | Stack et topologie | Accepté |
| 0004 | Contrats de domaine et wire MT5 | Accepté |
| 0005 | L'IA reste en lecture | Accepté |
| 0006 | Gouvernance par outils et vagues | Accepté |
| 0007 | Le Risk Engine est le point de contrôle unique | Accepté |

Format : contexte, décision, conséquences. Un ADR ne se modifie pas — il se remplace par un ADR suivant qui le supersède.

## Correspondance série 1 → série 2

Des documents techniques hérités et quelques commentaires de code citent encore les numéros de la série 1. Table de conversion :

| Série 1 | Devient |
|---|---|
| 0001 platform over EA | **0001** — Le process est le produit |
| 0002 Next.js + .NET · 0003 WebSocket-first · 0009 backend bootstrap · 0011 persistance Timescale | **0003** — Stack et topologie |
| 0004 schéma TypeScript · 0005 wire MT5 lean | **0004** — Contrats de domaine et wire MT5 |
| 0008 risk engine TypeScript · 0010 execution bridge | **0007** — Le Risk Engine est le point de contrôle unique |
| 0006 moteur ICT/SMC · 0012 backtesting MVP · 0013 diagnostics de backtest | **Caducs** — voir 0002, fin de la recherche d'edge |
| 0007 prototype live observe | Absorbé dans **0003** ; le raccourci de traduction côté navigateur qu'il décrivait n'existe plus (traduction serveur depuis la Phase 08) |

Aucune de ces citations n'a été corrigée dans les documents hérités : elles sont exactes pour l'époque décrite, et cette table suffit à les résoudre.
