# État du projet

Dernière mise à jour : 2026-09-12. Instantané seulement — l'historique vit
dans `session-log.md` (ADR 0008) et dans le journal de chaque fiche d'outil.

## En une phrase

Poste de travail personnel pour trader intraday, sorti de la recherche
d'edge (ADR 0002). La Vague 1 est livrée mais **non close**, et sa clôture
attend par décision : la priorité est passée à l'**agent d'exécution MT5**
(ADR 0010), construit jusqu'au mode CONFIRM uniquement. Phase 0 et EA-01 à
EA-04 sont livrés ; EA-05 (agent MQL5) est vérifié en conditions réelles
jusqu'à la validation locale — **il ne contient toujours aucun `OrderSend`**,
et son dernier incrément (exécution) attend un accord explicite séparé.

## Ce qui existe et fonctionne

Validé en live contre le compte de démonstration Exness (XAUUSDm) jusqu'au
28 juillet 2026 : la chaîne temps réel, les contrats, la persistance, le
chemin d'exécution. **Ce que la Vague 1 a ajouté par-dessus (T01–T05) n'a
jamais tourné contre un vrai terminal** — voir « Ce qui bloque ».

| Brique | Où | État |
|---|---|---|
| Chaîne temps réel MT5 → cockpit | `tools/mt5-observer/`, `backend/src/TradingOs.Gateway/`, `backend/src/TradingOs.Host/` | Validée live. Observer Python lecture seule → gateway .NET → SignalR → cockpit. |
| Contrats de domaine | `lib/domain/`, `lib/contracts/` | TypeScript portable, miroirs C# dans `TradingOs.Contracts`. |
| Moteur d'analyse | `lib/analysis/` | Swings, structure, liquidité, PD arrays, sessions, ATR. Pur, testé. Sert de source de niveaux — **pas de source de signal**. |
| Risk Engine | `lib/risk/` | Gates FTMO, sizing, lockout (ledger stocké, pause de 30 min sur pertes consécutives depuis T02b), gate calendrier FRED fail-closed depuis T03. Pur, testé. |
| Chemin d'exécution | `lib/execution/`, `lib/domain/execution-state.ts`, `CockpitHub`, `Mt5AgentServer` | `RiskDecision → Command → ACK → Report`, mode `observe`/SIMULATED. Protocole et machine à états figés (EA-03) : `commandId`/`accountId`/`protocolVersion`, `UNKNOWN` de premier ordre, `ACCOUNT_MISMATCH` typé. **Aucun `OrderSend` n'existe nulle part dans le dépôt** — le seul point qui pourrait un jour en contenir un (`tools/mt5-execution-agent/TradingOsAgent.mq5`, EA-05) ne l'a pas encore, par accord explicite requis. |
| Comptes et symboles | `lib/accounts/`, `lib/market/symbols/` | EA-04 : `defaultRiskPolicy` résout par compte (registre vide à ce jour — aucun compte FTMO/réel confirmé), registre canonique↔broker EURUSD/GBPUSD/XAUUSD. |
| Agent d'exécution MT5 | `tools/mt5-execution-agent/`, `backend/src/TradingOs.Gateway/Mt5AgentServer.cs` | EA-05 : connexion, heartbeat, réception, validation locale, persistance `commandId → résultat` sur disque — **vérifiés par l'utilisateur contre un vrai terminal** (2026-09-12). Mode figé à `OBSERVE` par construction. |
| Persistance | `backend/src/TradingOs.Persistence/`, `docker-compose.yml` | TimescaleDB port 5433, écriture non bloquante, audit JSONB. |
| Cockpit | `app/(cockpit)/`, `components/` | Coquille sombre et dense ; panneaux permanents T01/T04, bandeau kill switch T02a, chrono de pause T02b, chip calendrier FRED T03, viewer de capture T05 (`/journal/[brokerPositionId]`, pas le journal complet — T06). |
| Captures de trade | `lib/journal/`, `components/journal/`, `trade_captures` | T05 : faits immuables écrits par le Gateway (fenêtre, prix), rendu à la demande côté cockpit via `analyzeMarketContext` — jamais une image pré-rendue (ADR 0009). |

## Ce qui a été supprimé le 2026-09-04

La recherche d'edge et la mémoire de la série 1, en entier. Liste exhaustive
et raisons : `context/project/pivot-2026-09-04.md`.

## Ce qui bloque

**Aucun des cinq outils de la Vague 1 n'a été vérifié contre un vrai terminal
MT5 ni dans un navigateur.** Les gates vertes prouvent que le code compile et
que la logique pure est juste — pas que la chaîne tient sur des données MT5
réelles (identifiants de position, deals partiels, offset serveur, rollover).

Ce point ne bloque plus l'avancement — la clôture de vague a été repoussée
par décision le 2026-09-11 — mais il **bloque toujours le passage en mode
CONFIRM** : T02a (kill switch) et T02b (lockout) deviennent de la sécurité
d'exécution dès que l'EA peut placer un ordre (ADR 0010).

Friction héritée du 28 juillet 2026 : l'observer a calé une fois (14:03) sur
une collecte longue. Piste si ça revient : `gmag11/MetaTrader5-Docker`.

## Prochaine action

**EA-05, incrément 6 (exécution).** Les incréments 2 à 5 sont vérifiés par
l'utilisateur contre un vrai terminal. Écrire l'appel `OrderSend`
(structurellement inatteignable hors `CONFIRM`) attend un accord explicite
séparé — pas encore donné.

Ensuite : EA-06 (réconciliation de l'état `UNKNOWN`, positions externes),
EA-07 (mode CONFIRM, sous condition de la barrière listée dans sa fiche —
T02a/T02b vérifiés en réel, taux d'accord d'EA-02 connu).

## Questions ouvertes

- Quel déclencheur pour le multi-compte ? Par défaut : le jour où un deuxième compte prop firm est ouvert.
- Le compte FTMO existe-t-il déjà ? Toute la modélisation de ses règles est urgente ou spéculative selon la réponse.
- Veut-on pousser un trade manuel par le même chemin d'exécution, pour qu'il soit journalisé identiquement ?
