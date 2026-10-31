# Stratégie de test

Réécrit le 2026-10-09 (ADR 0016). Les commandes exactes sont dans `context/governance/quality_gates.md`.

## Cœur Python — pytest

| Famille | Contenu |
|---|---|
| Domaine | risque (portes, verrous, dimensionnement sur XAUUSD/EURUSD/GBPUSD/GBPJPY/BTCUSD, corrélation, actualité, spread, session), exécution (états, idempotence, expiration), réconciliation, autonomie, comptes et profils, S01 et analyse (vecteurs d'or hérités du TypeScript, voir `python/tests/golden/README.md`) |
| Services / API | services avec dépôts réels ou simulés ; routes via un client ASGI ; WebSocket (file bornée, reprise) |
| Intégration | lien agent par **sockets réels** sur la boucle locale ; processus enfant de lecture MT5 (`FakeMt5`) ; superviseur |
| Base de données | cluster PostgreSQL **jetable** lancé par les tests (ou `TRADINGOS_TEST_DATABASE_URL`) ; **échoue** s'il n'y en a pas, ne tourne jamais « à vide », ne touche jamais la base `tradingos` |
| Architecture | domaine pur, aucun `if provider`, aucun appel d'ordre côté Python, secrets à sens unique, MCP en lecture seule, **sources de l'agent MQL5** (un seul `OrderSend` derrière le plafond `OBSERVE`, interrupteur d'homme mort) |
| Contrat | `lib/api/generated.ts` identique à ce que le cœur écrirait aujourd'hui ; OpenAPI ; liste blanche MT5 |
| MT5 réel | suite en lecture seule, activée par `MT5_LIVE_TESTS=1`, **jamais d'ordre** |

## Cockpit — Vitest, tsc, eslint, build

Vitest (environnement node) sur `lib/**` : client typé, transport WebSocket (horloges simulées), store/contrôleur, vues dérivées. `npm run typecheck`, `npm run lint`, `npm run build` (le build échoue sur une erreur de type).

## Vérification dans un vrai navigateur

Les écrans se vérifient contre le **vrai cœur** (terminal simulé : `MT5_ENABLED=false`) avec un Chrome headless : 12 écrans, clair/sombre, bureau/mobile, aucune erreur console, aucun débordement, contraste AA. Un onglet de navigateur caché ne se peint pas (React n'y révèle pas le flux) : ne pas conclure d'un « Chargement » dans un onglet invisible.

## Exécution

Idempotence d'une commande, refus (compte, symbole, expiration, risque non approuvé), commande inconnue, échec, réconciliation (position manquante / inattendue / mauvais volume / SL / TP) — d'abord en `OBSERVE`, `PAPER`, `CONFIRM`, avec l'agent simulé, avant tout essai réel.

## Stratégie de trading

Forward-test avant tout argent réel ; mode « prop firm » à blanc avant un compte de challenge. Aucun backtester : la recherche d'edge est close (ADR 0002).
