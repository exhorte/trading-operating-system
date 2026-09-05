# État du projet

Dernière mise à jour : 2026-09-05. Instantané seulement — l'historique
détaillé vit dans `context/project/session-log.md` (ADR 0008) et dans le
journal de chaque fiche d'outil.

## En une phrase

Poste de travail personnel pour trader intraday, sorti de la recherche
d'edge (ADR 0002) ; la Vague 1 est en cours (statuts : `context/product/tools/README.md`). T01, T02, T03 et T04 sont livrés — reste T05.

## Ce qui existe et fonctionne

Tout ce qui suit a été **validé en live** contre le compte de démonstration Exness de l'utilisateur (XAUUSDm) entre juillet 2026 et le 28 juillet 2026.

| Brique | Où | État |
|---|---|---|
| Chaîne temps réel MT5 → cockpit | `tools/mt5-observer/`, `backend/src/TradingOs.Gateway/`, `backend/src/TradingOs.Host/` | Validée live. Observer Python lecture seule → gateway .NET → SignalR → cockpit. |
| Contrats de domaine | `lib/domain/`, `lib/contracts/` | TypeScript portable, miroirs C# dans `TradingOs.Contracts`. |
| Moteur d'analyse | `lib/analysis/` | Swings, structure, liquidité, PD arrays, sessions, ATR, biais. Pur, testé. Sert de source de niveaux — **pas de source de signal**. |
| Risk Engine | `lib/risk/` | Gates FTMO, sizing, lockout (ledger stocké, pause de 30 min sur pertes consécutives depuis T02b), gate calendrier FRED fail-closed depuis T03. Pur, testé. |
| Chemin d'exécution | `lib/execution/`, `CockpitHub` | `RiskDecision → Command → ACK → Report`, mode `observe`/SIMULATED, idempotence validée en live. **Aucun appel de trade n'existe nulle part.** |
| Persistance | `backend/src/TradingOs.Persistence/`, `docker-compose.yml` | TimescaleDB port 5433, écriture non bloquante, audit JSONB. |
| Cockpit | `app/(cockpit)/`, `components/` | Coquille sombre et dense ; panneaux permanents T01/T04, bandeau kill switch T02a, chrono de pause T02b, chip calendrier FRED T03. |

## Ce qui a été supprimé le 2026-09-04

`lib/backtest/`, `lib/strategy/`, les scripts de backtest, `app/(cockpit)/backtests/`, les tables `backtest_*`/`holdout_*`, l'ancienne série d'ADR 0001–0013, et les anciens fichiers de suivi (`changelog.md`, `session-history.md`, `handoff.md`, `memory.md`, `project_state.md`). Détail complet : `context/project/pivot-2026-09-04.md`. Reste consultable dans le reflog git local.

## Ce qui bloque

Rien de bloquant. Un point de friction connu, hérité du 28 juillet 2026 :
l'observer a calé une fois (28/07, 14:03) pendant une collecte longue. Piste
retenue si ça revient : conteneuriser via `gmag11/MetaTrader5-Docker`.

## Prochaine action

T01, T02 (T02a+T02b) et T03 sont livrés. Dernier outil de la Vague 1 :
**T05 — captures automatiques entrée/sortie** (`context/product/tools/T05-captures-auto.md`),
non démarré. Décision d'architecture à trancher avant tout code : rendu
maison (candles + niveaux, position par défaut) vs capture de la fenêtre MT5
— voir `02_Plan_Projet/prompt-claude-code-vague-1.md`, section T05.

## Questions ouvertes

- Quel déclencheur pour le multi-compte ? (Réponse par défaut : le jour où un deuxième compte prop firm est ouvert.)
- Rendu maison ou capture MT5 pour les screenshots ? Position par défaut : rendu maison, à trancher avec l'utilisateur au démarrage de T05.
- Authentification : hors sujet tant que l'usage est personnel et local.
