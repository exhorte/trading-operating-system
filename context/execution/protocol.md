# Protocole d'exécution OS ↔ agent MT5

Statut : accepté (EA-03). Fige le contrat entre le Trading OS et l'agent
d'exécution (ADR 0010) avant qu'un agent MQL5 n'existe (EA-05). Ce document
ne remplace pas `context/realtime/mt5_wire_protocol.md` (le wire lean déjà
implémenté) — il en documente les invariants nouveaux et la place dans le
protocole plus large.

## Ce qui existe déjà, et sur quoi ce document s'appuie

Le wire lean OS↔EA (`lib/contracts/mt5-wire.ts`, miroir
`backend/src/TradingOs.Contracts/Mt5Wire.cs`) est implémenté et validé en
live pour le marché (tick, candle, snapshots) et pour le cycle de commande en
mode `observe` : `execution.order` → `execution.ack`
(`ACCEPTED`/`REJECTED`/`DUPLICATE`/`EXPIRED`) → `execution.report`
(`SIMULATED`/`FILLED`/`PARTIALLY_FILLED`/`MODIFIED`/`CLOSED`/`FAILED`/`REJECTED`).
Détail message par message : `context/realtime/mt5_wire_protocol.md`.

Ce que ce document ajoute, en plus de ce wire :

1. Un `protocolVersion` explicite porté par la commande **côté domaine**
   (`lib/domain/execution.ts::ExecutionCommandBase.protocolVersion`), distinct
   du `version` de l'enveloppe de message. Le premier identifie le contrat
   métier (ce fichier) ; le second identifie la forme du message lean. Les
   deux valent `1` aujourd'hui et peuvent diverger plus tard sans se
   contraindre l'un l'autre.
2. Un vocabulaire de rejet **typé** (`lib/contracts/execution/reject-reason.ts`,
   miroir `CommandRejectCode`/`CommandRejection` dans
   `TradingOs.Contracts/Execution.cs`), pour que `ACCOUNT_MISMATCH` (et les
   codes qui suivront) soient un type, pas une sous-chaîne d'un champ
   `reason: string` libre.
3. La machine à états du cycle de vie d'une commande, qui structure ce que
   les messages ci-dessus signifient dans le temps —
   `context/execution/state-machine.md`.

## Champs obligatoires de toute commande (ADR 0010)

| Champ | Type | Invariant |
|---|---|---|
| `commandId` | `CommandId` (string) | Unique. Un rejeu avec le même `commandId` ne produit jamais une seconde position — voir la règle d'idempotence ci-dessous. |
| `accountId` | `AccountId` (string) | Doit correspondre au compte du terminal qui reçoit la commande. Sinon : rejet `ACCOUNT_MISMATCH`, jamais une exécution « au mieux ». |
| `protocolVersion` | `1` (littéral) | Le contrat que l'agent doit parler pour accepter la commande. |
| `expiresAt` | `UtcTimestamp` (ISO) | L'agent doit refuser toute commande reçue après cet instant. |

Ces quatre champs existent déjà sur `PlaceOrderCommand` et les futures
commandes `modify_position` / `close_position` / `close_all` / `cancel_order`
(`ExecutionCommandBase`, `lib/domain/execution.ts`) — ils sont hérités par
toute commande, pas seulement `place_order`.

## Règle d'idempotence

Un `commandId` déjà vu retourne son résultat déjà connu ; il ne relance
jamais l'exécution ni ne produit une seconde position. La règle est posée
comme fonction pure et testée dans
`lib/contracts/execution/idempotency.ts::recordOrReplay` — sans store réel :
c'est le contrat, pas encore l'implémentation persistée. Deux fiches futures
en dépendent sans le redéfinir :

- **EA-05** persiste la correspondance `commandId → résultat` sur disque, côté
  agent MQL5 — elle doit survivre à un redémarrage de l'agent ou du terminal.
- **EA-06** ajoute la réconciliation : que faire quand aucun résultat n'est
  connu du tout (voir `state-machine.md`, état `UNKNOWN`).

## Vocabulaire de rejet

`CommandRejectCode` (`lib/contracts/execution/reject-reason.ts`) :

| Code | Signification | Où il est déjà levé |
|---|---|---|
| `ACCOUNT_MISMATCH` | `accountId` de la commande ≠ compte de l'agent. | Nulle part encore dans le code — posé ici par le contrat ; câblé dans `CockpitHub.SubmitCommand` en EA-05 quand un agent réel porte une identité de compte vérifiable. |
| `MODE_NOT_OBSERVE` | L'agent n'est pas en mode `observe` (le seul mode garanti sûr aujourd'hui). | `CockpitHub.SubmitCommand` (comme chaîne libre aujourd'hui ; à faire pointer vers ce code). |
| `AGENT_UNREACHABLE` | La commande n'a pas pu être délivrée à l'agent. | `CockpitHub.SubmitCommand` (idem). |
| `RISK_NOT_APPROVED` | Une commande a été construite sans approbation de risque valide et correspondante. | `lib/execution/command-builder.ts::buildPlaceOrderCommand` rend `null` dans ce cas — aucune commande n'est même créée, donc ce code sert surtout de documentation de l'invariant. |

D'autres codes sont **nommés mais pas encore implémentés**, parce que la
gate qui les lèverait n'existe pas encore :

- `SYMBOL_MISMATCH` — vient avec le registre de symboles canonique↔broker
  d'EA-04.
- Codes de barrière locale (volume max, positions max, stop absent, spread
  max) — viennent avec l'agent MQL5 d'EA-05 ;
  `context/execution/safety.md` les documente par avance.

Ajouter un de ces codes à `CommandRejectCode` avant que le code qui le lève
existe serait une promesse non tenue — ne pas anticiper.

## Messages, par famille

Voir `context/realtime/mt5_wire_protocol.md` pour le détail champ par champ.
Ce tableau ne fait que situer chaque message dans la machine à états
(`state-machine.md`) :

| Message | Sens | Fait avancer la machine vers |
|---|---|---|
| `execution.order` / `.modify` / `.close` / `.close_all` / `.cancel` | Gateway → Agent | `SENT_TO_MT5` (déclenché par l'envoi, pas par la réception) |
| `execution.ack` (`ACCEPTED`) | Agent → Gateway | `RECEIVED` |
| `execution.ack` (`REJECTED`) | Agent → Gateway | `REJECTED` |
| `execution.ack` (`DUPLICATE`) | Agent → Gateway | Ne fait rien avancer : c'est la preuve qu'un rejeu a eu lieu, la machine de la commande d'origine est déjà ailleurs. Voir `recordOrReplay`. |
| `execution.ack` (`EXPIRED`) | Agent → Gateway | `EXPIRED` |
| `execution.report` (`SIMULATED`) | Agent → Gateway | `EXECUTED` (mode `observe` : validé de bout en bout, aucun ordre broker réel — jamais confondu avec un fill, `ExecutionReportStatus.simulated`) |
| `execution.report` (`FILLED`/`PARTIALLY_FILLED`) | Agent → Gateway | `EXECUTED` |
| `execution.report` (`FAILED`) | Agent → Gateway | `FAILED` |
| *(absence de message)* | — | Si aucun `execution.ack` n'arrive avant que le lien meure : `UNKNOWN`. Si aucun `execution.report` n'arrive après un `ACCEPTED` et que le lien meurt : `UNKNOWN`. |

## Négociation de version

`agent.hello` (déjà implémenté) porte `agentVersion` mais pas encore de
négociation de `protocolVersion` métier. Tant qu'une seule valeur (`1`)
existe, il n'y a rien à négocier. Le jour où une seconde valeur apparaît (un
changement cassant dans `lib/contracts/execution/`), `agent.hello` devra
porter le `protocolVersion` le plus élevé que l'agent comprend, et le gateway
refusera toute commande au-delà — à concevoir à ce moment, pas maintenant.
