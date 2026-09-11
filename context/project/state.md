# État du projet

Dernière mise à jour : 2026-09-11. Instantané seulement — l'historique vit
dans `session-log.md` (ADR 0008) et dans le journal de chaque fiche d'outil.

## En une phrase

Poste de travail personnel pour trader intraday, sorti de la recherche
d'edge (ADR 0002) ; **la Vague 1 est entièrement livrée** (T01–T05, statuts :
`context/product/tools/README.md`) — reste la clôture de vague elle-même
(voir `02_Plan_Projet/prompt-claude-code-vague-1.md`, section « Clôture »).

## Ce qui existe et fonctionne

Validé en live contre le compte de démonstration Exness (XAUUSDm) jusqu'au
28 juillet 2026 : la chaîne temps réel, les contrats, la persistance, le
chemin d'exécution. **Ce que la Vague 1 a ajouté par-dessus (T01–T05) n'a
jamais tourné contre un vrai terminal** — voir « Ce qui bloque ».

| Brique | Où | État |
|---|---|---|
| Chaîne temps réel MT5 → cockpit | `tools/mt5-observer/`, `backend/src/TradingOs.Gateway/`, `backend/src/TradingOs.Host/` | Validée live. Observer Python lecture seule → gateway .NET → SignalR → cockpit. |
| Contrats de domaine | `lib/domain/`, `lib/contracts/` | TypeScript portable, miroirs C# dans `TradingOs.Contracts`. |
| Moteur d'analyse | `lib/analysis/` | Swings, structure, liquidité, PD arrays, sessions, ATR, biais. Pur, testé. Sert de source de niveaux — **pas de source de signal**. |
| Risk Engine | `lib/risk/` | Gates FTMO, sizing, lockout (ledger stocké, pause de 30 min sur pertes consécutives depuis T02b), gate calendrier FRED fail-closed depuis T03. Pur, testé. |
| Chemin d'exécution | `lib/execution/`, `CockpitHub` | `RiskDecision → Command → ACK → Report`, mode `observe`/SIMULATED, idempotence validée en live. **Aucun appel de trade n'existe nulle part.** |
| Persistance | `backend/src/TradingOs.Persistence/`, `docker-compose.yml` | TimescaleDB port 5433, écriture non bloquante, audit JSONB. |
| Cockpit | `app/(cockpit)/`, `components/` | Coquille sombre et dense ; panneaux permanents T01/T04, bandeau kill switch T02a, chrono de pause T02b, chip calendrier FRED T03, viewer de capture T05 (`/journal/[brokerPositionId]`, pas le journal complet — T06). |
| Captures de trade | `lib/journal/`, `components/journal/`, `trade_captures` | T05 : faits immuables écrits par le Gateway (fenêtre, prix), rendu à la demande côté cockpit via `analyzeMarketContext` — jamais une image pré-rendue. |

## Ce qui a été supprimé le 2026-09-04

La recherche d'edge et la mémoire de la série 1, en entier. Liste exhaustive
et raisons : `context/project/pivot-2026-09-04.md`.

## Ce qui bloque

Un seul point, et c'est le critère de sortie de vague lui-même : **aucun des
cinq outils n'a été vérifié contre un vrai terminal MT5 ni dans un
navigateur**. Les gates vertes prouvent que le code compile et que la logique
pure est juste — pas que la chaîne tient sur des données MT5 réelles
(identifiants de position, deals partiels, offset serveur, rollover).
Séquence de validation : `02_Plan_Projet/prompt-claude-code-vague-1.md`.

Friction héritée du 28 juillet 2026 : l'observer a calé une fois (14:03) sur
une collecte longue. Piste si ça revient : `gmag11/MetaTrader5-Docker`.

## Prochaine action

**Clôture de la Vague 1**, en attente depuis le 2026-09-05
(`02_Plan_Projet/prompt-claude-code-vague-1.md`, section « Clôture ») :
écrire l'ADR 0009 « le serveur capture des faits immuables, le cockpit rend »
— candidat identifié en T05 — puis la séance réelle de bout en bout.
Ensuite T06, journal auto-alimenté ; sauf second compte prop firm ouvert
entre-temps, auquel cas T11/T12 remontent (voir `roadmap.md`).

## Questions ouvertes

- Quel déclencheur pour le multi-compte ? Par défaut : le jour où un deuxième compte prop firm est ouvert.
