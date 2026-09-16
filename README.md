# Trading Operating System

Poste de travail personnel pour trader intraday. Automatise, mesure et fait respecter le process de son unique utilisateur.

Ce n'est pas un Expert Advisor, pas un bot, pas un backtester. **Aucun module ne dit quoi trader, quand, ni dans quel sens.**

Depuis le 2026-09-15, le dépôt contient **un** appel d'exécution — `OrderSend`, dans `tools/mt5-execution-agent/TradingOsAgent.mq5` (EA-05 incrément 6, ADR 0010). Il vit dans une seule fonction dont la première instruction sort si le mode n'est pas `CONFIRM`, et le mode est une constante de compilation figée à `OBSERVE` : dans ce build, ce chemin est prouvablement mort. Le faire vivre demande l'échelle de mode d'EA-07, qui n'existe pas. Aucun ordre n'est envoyé sans qu'un humain l'ait déclenché (charte, principe 6).

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

Next.js / React / TypeScript / Tailwind pour le cockpit · .NET sous `backend/` (gateway, hub SignalR, persistance) · TimescaleDB · observer Python en lecture seule attaché au terminal MT5 de l'utilisateur.

Chaîne complète validée en live : `MT5 → observer Python → gateway .NET → SignalR → cockpit`.

## Démarrer

Le runbook complet — base de données, backend, observer, cockpit, variables d'environnement, ordre de démarrage — est dans **`context/infrastructure/runbook.md`**.

```bash
npm install
docker compose up -d
cd backend && dotnet run --project src/TradingOs.Host
npm run dev
```

## Structure

```
app/          cockpit Next.js
components/   composants du cockpit
lib/          domaine pur et testé — analysis, risk, execution, domain, contracts, realtime
backend/      solution .NET — Contracts, Gateway, Host, Persistence
tools/        observer MT5 (Python, lecture seule)
scripts/      utilitaires (import de bougies)
context/      mémoire du projet — charte, ADR, roadmap, fiches d'outil, runbook
```

## Comprendre le projet

Commencer par `context/README.md`, qui donne l'ordre de lecture. Les quatre documents qui comptent :

- `context/project/charter.md` — ce que le projet est et ce qu'il n'est plus ;
- `context/project/state.md` — état courant et prochaine action ;
- `context/adr/` — les sept décisions qui gouvernent ;
- `context/project/roadmap.md` — les vagues et les outils.

## Historique

Le projet a passé juillet 2026 à chercher un edge algorithmique. Cette recherche a été **abandonnée sans verdict le 2026-09-04** (ADR 0002), et le code correspondant supprimé. Les raisons sont dans `context/project/pivot-2026-09-04.md`.
