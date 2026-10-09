# Plan d'infrastructure

Réécrit le 2026-10-09 (ADR 0016). Le démarrage concret est dans `runbook.md`, la base dans `persistence.md`.

## Cible locale (la seule qui existe)

Une machine Windows, personnelle, tout sur la boucle locale :

| Brique | Où | Port |
|---|---|---|
| PostgreSQL + TimescaleDB | conteneur Docker `tradingos-timescaledb`, volume existant | `127.0.0.1:5433` |
| Cœur Python (API, WebSocket, moteur, lien agent) | hôte Windows, un processus (`python -m trading_os serve`) | `127.0.0.1:8000` et `127.0.0.1:9765` |
| Cockpit Next.js | hôte Windows (`npm run dev`) | `127.0.0.1:3000` |
| Terminal MT5 + agent EA | hôte Windows | — |

Le cœur ne peut pas vivre dans un conteneur : le paquet `MetaTrader5` est Windows-only et parle à un terminal de cette machine. C'est pourquoi Docker ne porte que la base. Ni Redis, ni RabbitMQ, ni Seq, ni Prometheus : rien dans le système n'a besoin d'eux (un événement interne est un appel de fonction ; l'audit est une table ; les journaux vont sur la console).

## Direction de déploiement

Aucune. Usage strictement personnel, une seule machine ; pas de VPS, pas de reverse proxy, pas de service managé. Si un jour le cœur devait tourner ailleurs, ce serait une décision d'architecture à part (ADR) : le terminal MT5 reste sur Windows, le lien agent et l'API cesseraient d'être de simples boucles locales, et la surface de sécurité (`context/security/security_principles.md`) serait à reprendre à zéro.

## Préoccupations de fiabilité

- durabilité des commandes d'exécution : écrites avant d'agir, base indisponible ⇒ refus ;
- supervision du lien agent : battement toutes les 5 s, silence > 30 s = agent mort, interrupteur d'homme mort côté agent ;
- reprise du flux du cockpit : instantané à chaque connexion, `resync` à la demande ;
- supervision du cœur lui-même : un superviseur évalue la santé toutes les 2 s et déclenche SAFE / DISARM / HALT / RECONNECT / RECONCILE ;
- journal d'audit ; **sauvegardes** (aujourd'hui à la main : `pg_dump -Fc` avant toute recréation du conteneur) ;
- secrets : fichier `.env` gitignoré, jetons générés par `scripts/start.ps1`, aucun identifiant de compte stocké ;
- observabilité : `GET /api/system/health`, l'écran Agents & Audit du cockpit.
