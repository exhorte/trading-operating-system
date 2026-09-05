# État du projet

Dernière mise à jour : 2026-09-05.

## En une phrase

La plateforme sort de neuf mois de recherche d'edge abandonnée ; le premier outil de la Vague 1 (T01, sizing) est livré.

## Ce qui existe et fonctionne

Tout ce qui suit a été **validé en live** contre le compte de démonstration Exness de l'utilisateur (XAUUSDm) entre juillet 2026 et le 28 juillet 2026.

| Brique | Où | État |
|---|---|---|
| Chaîne temps réel MT5 → cockpit | `tools/mt5-observer/`, `backend/src/TradingOs.Gateway/`, `backend/src/TradingOs.Host/` | Validée live. Observer Python lecture seule → gateway .NET → SignalR → cockpit. |
| Contrats de domaine | `lib/domain/`, `lib/contracts/` | TypeScript portable, miroirs C# dans `TradingOs.Contracts`. |
| Moteur d'analyse | `lib/analysis/` | Swings, structure, liquidité, PD arrays, sessions, ATR, biais. Pur, testé. Sert de source de niveaux — **pas de source de signal**. |
| Risk Engine | `lib/risk/` | Gates FTMO (perte quotidienne, drawdown, risque ouvert, trades max, pertes consécutives, spread, session), sizing, lockout. Pur, testé. |
| Chemin d'exécution | `lib/execution/`, `CockpitHub` | `RiskDecision → Command → ACK → Report`, mode `observe`/SIMULATED, idempotence validée en live. **Aucun appel de trade n'existe nulle part.** |
| Persistance | `backend/src/TradingOs.Persistence/`, `docker-compose.yml` | TimescaleDB port 5433, écriture non bloquante, audit JSONB. Milliers d'enveloppes persistées, 0 perdue. |
| Cockpit | `app/(cockpit)/`, `components/` | Coquille sombre et dense. Pages : Command Center, Market Context, Signals, Positions, Risk, Journal, Replay, Agents, Settings — la plupart sont des coquilles. |

## Ce qui a été supprimé le 2026-09-04

`lib/backtest/`, `lib/strategy/`, `scripts/backtest*.ts`, `scripts/calibrate-spread.ts`, `query_ticks.csx`, `app/(cockpit)/backtests/`, `components/cockpit/backtests-workspace.tsx`, `BacktestRepository.cs`, les endpoints `/api/backtests`, les tables `backtest_*` et `holdout_*` du schéma, `tools/mt5-observer/inspect_symbol.py`, les 24 fiches de phase, l'ancienne série d'ADR 0001–0013, `changelog.md`, `session-history.md`, `handoff.md`, `memory.md`, `project_state.md`, l'ancien `roadmap.md`, `development_manifesto.md`, `context/agents/`, `context/backtesting/`, `search.md`.

L'ancien contenu n'a plus de référence dans le dépôt ni sur GitHub ; il reste temporairement consultable dans le reflog git du clone local.

## Ce qui bloque

Rien de bloquant. Deux points de friction connus, hérités du 28 juillet 2026 :

1. **L'observer a calé une fois** (28/07, 14:03) pendant une collecte longue. Piste retenue : conteneuriser via `gmag11/MetaTrader5-Docker`. Non urgent — les outils de la Vague 1 ne demandent pas de collecte longue.
2. **Les tables `backtest_*` et `holdout_*` existent encore dans la base locale.** Elles ne sont plus dans `schema.sql` et ne seront plus recréées. Les supprimer est optionnel — voir `context/infrastructure/runbook.md`.

## Prochaine action

**Outil T04 — Ticket pré-trade.** Voir `context/product/tools/T04-ticket-pretrade.md`.

T01 est livré le 2026-09-05 (panneau de sizing permanent dans le cockpit, voir
sa fiche). Ordre conseillé de la roadmap : T04 avant T02, car le ticket
produit les compteurs de séance dont le lockout a besoin.

## Questions ouvertes

- Quel déclencheur pour le multi-compte ? (Réponse par défaut : le jour où un deuxième compte prop firm est ouvert.)
- Source du calendrier économique : liste blanche FRED d'abord, API commerciale seulement si le consensus devient utile. Voir `context/product/tools/T03-gate-news.md`.
- Rendu maison ou capture MT5 pour les screenshots ? Position par défaut : rendu maison. Voir `T05`.
- Authentification : hors sujet tant que l'usage est personnel et local.
