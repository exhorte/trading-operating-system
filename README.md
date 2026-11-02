# Trading Operating System

Poste de travail personnel pour trader intraday. Automatise, mesure et fait respecter le process de son unique utilisateur.

Ce n'est pas un Expert Advisor, pas un bot, pas un backtester. **Aucun module ne dit quoi trader, quand, ni dans quel sens.**

Depuis le 2026-09-15, le dépôt contient **un** appel d'exécution — `OrderSend`, dans `tools/mt5-execution-agent/TradingOsAgent.mq5` (EA-05 incrément 6, ADR 0010). Il vit dans une seule fonction dont la première instruction sort si le mode n'est pas `CONFIRM`, et le mode est une constante de compilation figée à `OBSERVE` : dans ce build, ce chemin est prouvablement mort. Le faire vivre demande l'échelle de mode d'EA-07, qui n'existe pas. Aucun ordre n'est envoyé sans qu'un humain l'ait déclenché (charte, principe 6).

Depuis le 2026-11-01 (ADR 0029), cet unique `OrderSend` porte les **cinq natures de commande** que le cœur sait envoyer — ordre au marché, ordre `LIMIT` (toujours avec une expiration chez le courtier), déplacement de stop (qui ne s'éloigne jamais du prix), clôture et clôture partielle, annulation — toutes derrière la même fonction, après la même validation locale. L'agent reste compilé en `OBSERVE` : il valide et répond `SIMULATED`, rien n'atteint un courtier. Il n'a **jamais été éprouvé chez un courtier** ; ce qui reste à vérifier sur un terminal de démonstration est listé dans `tools/mt5-execution-agent/README.md`.

Le projet comprend aussi deux stratégies formalisées (S01, S02 — chacune avec ses propres fenêtres horaires en heure de New York, ADR 0030), un Position Manager, un Account Guardian, un banc de validation d'une configuration figée, et un plafond de risque N8 qui ne fait que baisser le risque et qui est **désactivé** tant que sa plus petite unité n'est pas écrite (ADR 0031). Aucune n'agit sans que l'utilisateur ait monté lui-même le mode d'autonomie ; l'état exact est dans `context/project/state.md`.

Usage strictement personnel — pas de distribution, pas de vente.

## Ce que ça fait

| Domaine | Rôle |
|---|---|
| Préparation pré-séance | Assembler le contexte du jour : niveaux, sessions, publications économiques, état des comptes. |
| Exécution & discipline | Dimensionner, vérifier, refuser. Les règles que l'utilisateur s'impose sont appliquées par le moteur de risque, pas par l'interface. |
| Revue & journal | Enregistrer chaque trade et son contexte sans une seule saisie manuelle. |
| Admin prop firm | Connaître à tout instant la marge de manœuvre réglementaire par compte. |

Le KPI du produit est le **taux de conformité au plan**, pas le P&L.

## Stack

Cockpit **Next.js** / React / TypeScript / Tailwind · **cœur Python** (FastAPI, REST + WebSocket, un seul processus : comptes, marché, stratégie, risque, exécution, réconciliation, journal, autonomie, superviseur) · API **MetaTrader5** lue dans un processus enfant en lecture seule · agent **MQL5** `TradingOsAgent` (exécution locale et garde-fous) · PostgreSQL/TimescaleDB (Docker).

```
cockpit Next.js ⇄ cœur Python (127.0.0.1:8000) ⇄ MT5 ⇄ Exness | FTMO
                        │                         ▲
                        └── lien local 127.0.0.1:9765 ── agent MQL5 (le seul `OrderSend`)
```

Plus de .NET, de SignalR ni d'observateur Python (ADR 0016) : `docs/architecture/python-native-architecture.md` décrit le système, `docs/architecture/python-native-migration-report.md` ce qui a été supprimé et pourquoi.

## Démarrer

Le runbook complet est dans **`context/infrastructure/runbook.md`**. En résumé, une fois (Windows, Docker Desktop, Python ≥ 3.12 (développé en 3.14), Node) :

```powershell
cd python; py -3.14 -m venv .venv; .venv\Scripts\python.exe -m pip install -e ".[dev]"; cd ..
npm install
```

puis, à chaque session :

```powershell
pwsh -File scripts\start.ps1              # base, schéma, cœur, cockpit
pwsh -File scripts\start.ps1 -Simulated   # même chose sans MT5 : un terminal de démonstration en mémoire
pwsh -File scripts\start.ps1 -Plan        # dit ce qu'il ferait, ne change rien
```

Le script n'ouvre jamais MT5, ne demande aucun mot de passe et ne relève jamais le plafond de mode (`TRADING_MODE`, `OBSERVE` par défaut). Le compte se rattache dans le cockpit (Settings).

## Vérifier

```powershell
cd python; .venv\Scripts\python.exe -m pytest -q; .venv\Scripts\python.exe -m ruff check .; .venv\Scripts\python.exe -m mypy trading_os; cd ..
npm test; npm run typecheck; npm run lint; npm run build
```

## Structure

```
app/ components/ lib/        cockpit Next.js — client typé lib/api, WebSocket lib/websocket, store lib/realtime
python/trading_os/           le cœur — domain/ (pur) · services/ · infrastructure/ (mt5, database, news) · api/ · runtime/ · cli/ · mcp/
python/tests/                pytest : unitaires, intégration, base jetable, architecture
tools/mt5-execution-agent/   l'agent MQL5 TradingOsAgent
scripts/start.ps1            démarrage
docs/architecture/           architecture cible, carte de migration, rapport de migration
context/                     mémoire du projet — charte, ADR, roadmap, fiches d'outil, runbook
```

## Comprendre le projet

Commencer par `context/README.md`, qui donne l'ordre de lecture. Les quatre documents qui comptent :

- `context/project/charter.md` — ce que le projet est et ce qu'il n'est plus ;
- `context/project/state.md` — état courant et prochaine action ;
- `context/adr/` — les décisions qui gouvernent ;
- `context/project/roadmap.md` — les vagues et les outils.

## Historique

Le projet a passé juillet 2026 à chercher un edge algorithmique. Cette recherche a été **abandonnée sans verdict le 2026-09-04** (ADR 0002), et le code correspondant supprimé. Les raisons sont dans `context/project/pivot-2026-09-04.md`.
