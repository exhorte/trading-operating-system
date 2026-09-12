# EA-03 — Protocole d'exécution et machine à états

Statut : **livré** · Vague EA · Effort 1–2 j · Dépend de : EA-01 (contrats de
commande existants), ADR 0010

Des contrats et une machine à états. Aucun MQL5, aucun réseau, aucun ordre.
C'est la partie qui décide de la robustesse de tout le reste : EA-05 (agent
MQL5) et EA-06 (réconciliation) s'appuient dessus sans la redéfinir.

## Problème

Le chemin `RiskDecision → Command → ACK → Report` existe et son idempotence a
été validée en live, mais seulement comme un enchaînement d'appels — pas comme
une machine à états explicite. Rien dans le dépôt ne nomme les états
intermédiaires d'une commande, ne rend illégales les transitions interdites au
niveau du type, ni ne traite l'état `UNKNOWN` comme un citoyen de première
classe. Avant qu'un agent MQL5 capable de passer un ordre réel n'existe
(EA-05), ce contrat doit être figé.

## Écart trouvé avant tout code (cartographie)

Lu en entier avant d'écrire quoi que ce soit : `lib/domain/execution.ts`,
`lib/execution/command-builder.ts` (+ test), `lib/contracts/commands.ts`,
`enums.ts`, `envelope.ts`, `events.ts`, `mt5-wire.ts`,
`backend/src/TradingOs.Contracts/{Execution.cs,Mt5Wire.cs,Envelope.cs}`,
`backend/src/TradingOs.Gateway/{Mt5WireTranslator.cs,Mt5ObserverClient.cs}`,
`backend/src/TradingOs.Host/CockpitHub.cs`.

Ce qui existe déjà et qu'il ne faut pas réécrire :

| Brique | Fichier | Couvre déjà |
|---|---|---|
| Commandes typées | `lib/domain/execution.ts` | Union `ExecutionCommand` (place_order/modify/close/close_all/cancel), `CommandAck`, `ExecutionReport`, `ExecutionReportStatus` (9 statuts, dont `simulated` — jamais confondu avec un fill). `commandId`, `accountId`, `agentId`, `riskApprovalId` obligatoire, `expiresAt` sont déjà sur `ExecutionCommandBase`. |
| Construction de commande | `lib/execution/command-builder.ts` | `buildPlaceOrderCommand` : seule porte d'entrée d'une commande, dérivée d'une `RiskDecision` approuvée. `commandId = cmd-${signalId}` — déterministe par signal, ce qui est déjà une forme d'idempotence, mais rien ne persiste ni ne vérifie un rejeu. |
| Wire lean OS↔EA | `lib/contracts/mt5-wire.ts` + miroir `Mt5Wire.cs` | Enveloppe plate versionnée (`version: 1`), `execution.order/modify/close/close_all/cancel`, `execution.ack` (statuts `ACCEPTED/REJECTED/DUPLICATE/EXPIRED`), `execution.report` (statuts `SIMULATED/FILLED/PARTIALLY_FILLED/MODIFIED/CLOSED/FAILED/REJECTED`). |
| Orchestration bout en bout | `CockpitHub.SubmitCommand` | Diffuse la commande, vérifie que l'agent est en mode `"observe"` (chaîne brute, pas un type), aplatit vers le wire lean, envoie, et rejette si le mode n'est pas observe ou si l'agent est injoignable. |
| Réception agent → gateway | `Mt5ObserverClient.Handle` | Route `execution.ack`/`execution.report` vers des événements diffusés. Aucun état persisté par `commandId` : chaque message est traduit et rediffusé, point. |

Ce qui **n'existe nulle part** et que cette fiche doit produire :

- **Aucune machine à états nommée.** Les statuts actuels (`ACCEPTED`, `SIMULATED`, `FILLED`…) sont des *résultats de message wire*, pas les huit états du cycle de vie demandés (`COMMAND_CREATED → RISK_APPROVED → SENT_TO_MT5 → RECEIVED → VALIDATING → EXECUTING → EXECUTED → RECONCILED`) ni les quatre états terminaux/exceptionnels (`REJECTED`, `EXPIRED`, `FAILED`, `CANCELLED`, `UNKNOWN`). Rien ne code les transitions légales, donc rien n'empêche aujourd'hui d'écrire un rejeu depuis `UNKNOWN`.
- **`UNKNOWN` n'existe pas.** Aucun type, aucun statut agent ou wire ne le porte.
- **`ACCOUNT_MISMATCH` n'existe pas.** `CockpitHub.SubmitCommand` ne compare jamais l'`accountId` de la commande à celui de l'agent connecté (`state.Hello?.AccountId`) — c'est un trou de sécurité que cette fiche doit combler au niveau du contrat, même si l'application complète (agent réel, plusieurs comptes) vient plus tard.
- **Pas de `protocolVersion` porté par la commande elle-même.** Le wire porte un `version` au niveau du message (`Mt5Message.version = 1`), mais `ExecutionCommandBase` (domaine) n'a pas de champ `protocolVersion` explicite — l'ADR 0010 le demande sur *toute commande*.
- **`lib/contracts/execution/` n'existe pas** : les contrats de commande vivent aujourd'hui dispersés entre `lib/domain/execution.ts` (canonique) et `lib/contracts/{commands,mt5-wire}.ts` (wire). Rien ne consolide encore le protocole versionné dans un sous-dossier dédié.

## Décision d'architecture proposée (à valider)

Un point s'écarte légèrement de la lettre du prompt de lancement et mérite une
validation explicite avant implémentation, parce qu'il touche à l'ADR 0004
(séparation domaine/contrats) :

**La machine à états (les 12 états et leurs transitions légales) est de la
logique de domaine pure — pas une forme de wire.** Elle est donc proposée dans
`lib/domain/execution-state.ts` (nouveau fichier, étend `execution.ts` sans le
modifier), pas dans `lib/contracts/execution/`. `lib/contracts/execution/`
porte à la place le **protocole versionné** au sens strict : le vocabulaire de
rejet typé (dont `ACCOUNT_MISMATCH`), le `protocolVersion` négocié, et les
formes de message qui encadrent les transitions vues depuis l'extérieur (ce
que `protocol.md` documente). C'est cohérent avec l'ADR 0004 : « `lib/contracts/`
peut dépendre du domaine, jamais l'inverse » — la machine à états est
consommée par la couche contrats, pas l'inverse.

Si tu préfères que tout (machine à états incluse) vive sous
`lib/contracts/execution/` pour rester au plus près du texte du prompt de
lancement, dis-le et je déplace — c'est un renommage, pas une reconception.

## Comportement attendu

1. **`context/execution/protocol.md`** — le contrat versionné, messages OS→EA
   et EA→OS, schéma exact et invariants pour chacun. Documente ce qui existe
   déjà (`mt5-wire.ts`) et ce qui s'ajoute : `protocolVersion` par commande,
   vocabulaire de rejet typé (`ACCOUNT_MISMATCH` en premier ; les autres codes
   de rejet cités par les fiches suivantes — `SYMBOL_MISMATCH`, barrières
   locales — sont nommés ici mais implémentés en EA-04/EA-05, pas ici).
2. **`context/execution/state-machine.md`** — les 12 états, un diagramme des
   transitions légales, et pour chacune : déclencheur, ce qui est persisté, ce
   qui se passe si le processus meurt juste après. `UNKNOWN` y est traité comme
   un état de première classe : sa seule sortie légale est `RECONCILED`, via un
   événement de réconciliation dédié — jamais un rejeu.
3. **`context/execution/safety.md`** — les barrières locales de l'agent (à
   implémenter en EA-05) et leur raison d'être : whitelist de symboles, volume
   max, positions max, stop obligatoire, spread max, kill switch local, magic
   number, `ACCOUNT_MISMATCH`. Descriptif seulement ici — aucun code MQL5.
4. **`lib/domain/execution-state.ts`** — `CommandLifecycleState` (union de 12
   valeurs), `CommandLifecycleEvent` (ce qui fait avancer la machine), et
   `transition(state, event): TransitionResult` pure, qui rend une erreur
   typée pour toute transition illégale plutôt que de la laisser possible par
   construction.
5. **`lib/contracts/execution/`** (nouveau dossier TS) + miroir C# dans
   `backend/src/TradingOs.Contracts/` — `protocolVersion`, `CommandRejectReason`
   (dont `ACCOUNT_MISMATCH`), et les formes de message qui portent ces deux
   ajouts. Une seule source de vérité, deux représentations (ADR 0004).

## Exigences non négociables (ADR 0010)

- Toute commande porte un `commandId` unique, un `accountId`, un
  `protocolVersion` et un `expiresAt`. Un rejeu du même `commandId` doit
  produire, au niveau du type, le même résultat déjà connu — jamais une
  nouvelle entrée dans la machine à états depuis `COMMAND_CREATED`.
- `UNKNOWN` est un état de première classe. La seule transition sortante
  légale est vers `RECONCILED`. Le type doit rendre une transition
  `UNKNOWN → EXECUTING` (ou vers tout autre état) impossible à exprimer ou,
  a minima, garantie d'échouer — testé explicitement.
- Une commande dont l'`accountId` ne correspond pas à celui de l'agent est
  rejetée avec `ACCOUNT_MISMATCH`, jamais exécutée « au mieux ».

## Ancrage dans le code

- `lib/domain/execution.ts` — étendu (ajout de `protocolVersion` sur
  `ExecutionCommandBase`), pas réécrit. Impact direct sur
  `lib/execution/command-builder.ts` et son test (nouveau champ requis).
- `lib/contracts/mt5-wire.ts` / `Mt5Wire.cs` — pas modifiés dans cette fiche ;
  le wire lean garde son `version` de message. Le `protocolVersion` de la
  commande est un concept domaine distinct, documenté dans `protocol.md`.
- `backend/src/TradingOs.Contracts/Execution.cs` — miroir à étendre en même
  temps que `lib/domain/execution.ts` et `lib/contracts/execution/`.
- `CockpitHub.SubmitCommand` — **non modifié dans cette fiche.** Le contrôle
  `ACCOUNT_MISMATCH` et le câblage de la machine à états dans le flux réel
  sont documentés ici mais branchés en EA-05/EA-06, une fois l'agent réel et
  la réconciliation en jeu. Cette fiche pose le contrat, pas le branchement.

## Découpage en incréments

1. `lib/domain/execution-state.ts` — états, événements, `transition()` pure +
   tests (dont les transitions interdites, `UNKNOWN → EXECUTING` en premier).
2. `ExecutionCommandBase.protocolVersion` (extension additive) +
   mise à jour de `command-builder.ts`/son test + miroir C#
   `PlaceOrderCommand.ProtocolVersion`.
3. `lib/contracts/execution/` — `CommandRejectReason` (dont
   `ACCOUNT_MISMATCH`), types de protocole versionné, + miroir C# dans
   `TradingOs.Contracts`. Test : rejeu du même `commandId` rend le résultat
   précédent (simulé en mémoire, sans store réel — le store vient avec
   EA-05/EA-06).
4. `context/execution/protocol.md`.
5. `context/execution/state-machine.md`.
6. `context/execution/safety.md`.

Chaque incrément garde les gates vertes (`npm run lint`, `npx tsc --noEmit`,
`npm test`, `npm run build`, `dotnet build`, `dotnet test`).

## Critère de réussite

- Les trois documents `context/execution/` existent et sont précis au niveau
  du schéma — un lecteur qui ne connaît pas le dépôt peut implémenter l'agent
  MQL5 (EA-05) rien qu'à partir d'eux.
- Contrats TS et miroirs C# alignés, aucune divergence.
- Les transitions interdites sont testées et échouent, `UNKNOWN → EXECUTING`
  en tête.
- Le rejeu d'un même `commandId` est testé et rend le résultat précédent.
- Aucun code MQL5, aucun appel réseau, aucun appel d'ordre.
- Gates vertes des deux côtés (TS et .NET).

## Journal

- 2026-09-12 — fiche créée avant tout code. Cartographie de l'existant faite :
  le chemin `RiskDecision → Command → ACK → Report` couvre déjà commandes,
  ACK et rapports au niveau wire, mais aucune machine à états nommée,
  aucun `UNKNOWN`, aucun `ACCOUNT_MISMATCH`, aucun `protocolVersion` explicite
  sur la commande. Point d'architecture soumis à validation : la machine à
  états proposée en `lib/domain/` plutôt que `lib/contracts/execution/`, par
  cohérence avec l'ADR 0004 (contrats = wire, domaine = logique pure) —
  **validé par l'utilisateur**, ainsi que le découpage en six incréments.

- 2026-09-12 (suite) — **livré**. Les six incréments :
  1. `lib/domain/execution-state.ts` — 12 états, `transition()` pure,
     18 tests dont les transitions interdites (`UNKNOWN → EXECUTING` en
     premier) et les deux points d'entrée réels dans `UNKNOWN` (`LINK_LOST`
     depuis `SENT_TO_MT5`, `EXECUTION_LINK_LOST` depuis `EXECUTING` — ce
     dernier est le scénario « mort entre `OrderSend` et l'accusé » qu'EA-06
     devra retester en conditions réelles).
  2. `protocolVersion` ajouté à `ExecutionCommandBase`
     (`lib/domain/execution.ts`), extension additive. Répercuté dans
     `lib/execution/command-builder.ts` (et son test), `lib/realtime/store.test.ts`
     (seul autre constructeur de littéral `PlaceOrderCommand` trouvé dans le
     dépôt), et le miroir C# `PlaceOrderCommand` + le test qui le construit
     par arguments nommés (`ExecutionTranslationTests.cs`) — aucun site de
     construction positionnelle trouvé, donc aucune rupture binaire.
  3. `lib/contracts/execution/` — `CommandRejectCode`/`CommandRejection`
     (dont `ACCOUNT_MISMATCH` ; les autres codes sont nommés dans
     `protocol.md` mais pas encore ajoutés au type, faute de gate qui les
     lève) et `recordOrReplay` (règle d'idempotence posée comme fonction pure
     sur un store injecté, testée : un rejeu ne ré-exécute jamais et rend le
     résultat déjà connu). Miroir C# : `CommandRejectCode` (constantes,
     cohérent avec le style `string` déjà utilisé pour les statuts du fichier)
     et `CommandRejection`.
  4–6. `context/execution/{protocol,state-machine,safety}.md`.

  Écart volontaire par rapport au texte du prompt de lancement, déjà
  documenté et validé : la machine à états vit dans `lib/domain/`, pas dans
  `lib/contracts/execution/`.

  `CockpitHub.SubmitCommand` n'a pas été modifié — le contrat est posé, le
  branchement (vérification `ACCOUNT_MISMATCH` réelle, persistance de l'état
  par `commandId`, résolution d'`UNKNOWN`) est explicitement hors périmètre
  de cette fiche et revient en EA-05/EA-06.

  Gates vertes : `npm run lint`, `npx tsc --noEmit`, `npm test` (187 tests,
  dépôt entier — 22 nouveaux), `npm run build`, `dotnet build`,
  `dotnet test` (38, inchangé — seul un test existant modifié pour le nouveau
  champ), `python -m py_compile tools/mt5-observer/*.py` (fichiers non
  touchés). Aucun code MQL5, aucun appel réseau, aucun appel d'ordre.
