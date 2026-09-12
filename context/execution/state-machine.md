# Machine à états d'une commande d'exécution

Statut : accepté (EA-03). Implémentation pure et testée :
`lib/domain/execution-state.ts` (`transition()`), tests dans
`execution-state.test.ts`. Ce document est la narration ; le code est
l'autorité en cas de divergence.

## Les douze états

```
COMMAND_CREATED
      │ RISK_APPROVED
      ▼
RISK_APPROVED
      │ SENT
      ▼
SENT_TO_MT5 ──────── LINK_LOST ────────▶ UNKNOWN
      │ ACK_ACCEPTED                        │
      ▼                                     │ RECONCILED
RECEIVED                                     │ (RECONCILIATION_PENDING
      │ VALIDATION_STARTED                   │  boucle sur UNKNOWN)
      ▼                                      │
VALIDATING                                   │
      │ VALIDATION_PASSED                    │
      ▼                                      │
EXECUTING ──── EXECUTION_LINK_LOST ──────────┤
      │ EXECUTION_REPORTED                    │
      ▼                                       │
EXECUTED                                      │
      │ RECONCILED                            │
      ▼                                       ▼
RECONCILED ◀────────────────────────────────────

Terminaux atteignables depuis plusieurs états, selon la table ci-dessous :
REJECTED · EXPIRED · FAILED · CANCELLED
```

`REJECTED`, `EXPIRED`, `FAILED`, `CANCELLED`, `RECONCILED` sont **terminaux** :
aucune transition n'en repart. `UNKNOWN` n'est **pas** terminal — c'est un état
de première classe avec une seule sortie légale, vers `RECONCILED`.

## Table des transitions

Pour chaque état de départ : ce qui la déclenche, ce qui est persisté, et ce
qui se passe si le processus (gateway ou agent) meurt juste après.

### `COMMAND_CREATED`

Une `RiskDecision` approuvée a produit une commande
(`buildPlaceOrderCommand`). Rien n'a encore été envoyé.

| Événement | Vers | Déclencheur | Persisté | Si le processus meurt juste après |
|---|---|---|---|---|
| `RISK_APPROVED` | `RISK_APPROVED` | Le Risk Engine a approuvé la décision dont dépend cette commande. | La commande (avec `riskApprovalId`). | La commande n'existait que dans ce process. Rien n'a été envoyé à l'agent — sans danger, il suffit de la reconstruire depuis la décision si elle est encore actionnable. |
| `RISK_REJECTED` | `REJECTED` | Le Risk Engine a refusé — ne devrait normalement pas se produire ici car `buildPlaceOrderCommand` ne crée déjà une commande que pour une décision approuvée ; conservé pour les commandes futures qui pourraient se construire avant l'approbation. | Le motif de refus. | Sans conséquence : rien n'a été envoyé. |
| `EXPIRED` | `EXPIRED` | `expiresAt` dépassé avant même l'approbation. | Rien de nouveau. | Sans conséquence. |

### `RISK_APPROVED`

| Événement | Vers | Déclencheur | Persisté | Si le processus meurt juste après |
|---|---|---|---|---|
| `SENT` | `SENT_TO_MT5` | Le gateway a écrit la commande sur le socket de l'agent (`Mt5ObserverClient.SendCommandAsync` a retourné `true`). | L'enveloppe `execution.command.place_order` (déjà : `GatewayBridgeService.Persist`). | La commande a peut-être atteint l'agent sans que le gateway le sache : c'est exactement la fenêtre qui doit produire `UNKNOWN`, pas un rejeu — voir `SENT_TO_MT5`. |
| `SEND_FAILED` | `FAILED` | L'agent est injoignable (`SendCommandAsync` a retourné `false`). | Le motif (`AGENT_UNREACHABLE`). | Rien n'a atteint l'agent : sans danger de dupliquer. |
| `CANCEL_REQUESTED` | `CANCELLED` | L'utilisateur annule avant tout envoi. | Le motif d'annulation. | Sans conséquence. |
| `EXPIRED` | `EXPIRED` | `expiresAt` dépassé avant l'envoi. | Rien de nouveau. | Sans conséquence. |

### `SENT_TO_MT5`

La commande a quitté le gateway. C'est la première frontière où une panne
crée une incertitude réelle.

| Événement | Vers | Déclencheur | Persisté | Si le processus meurt juste après |
|---|---|---|---|---|
| `ACK_ACCEPTED` | `RECEIVED` | `execution.ack` avec `status: ACCEPTED`. | L'accusé de réception. | La commande est confirmée reçue ; sûr de continuer. |
| `ACK_REJECTED` | `REJECTED` | `execution.ack` avec `status: REJECTED` (ex. futur `ACCOUNT_MISMATCH`). | Le motif typé (`CommandRejectCode`). | Sans conséquence : l'agent n'a rien exécuté. |
| `LINK_LOST` | `UNKNOWN` | Le socket se ferme, ou aucun ACK ne revient avant un délai, avant qu'un `ACCEPTED`/`REJECTED` n'arrive. | Le fait qu'un envoi a eu lieu sans confirmation. | **C'est l'entrée `UNKNOWN` nommée par l'ADR 0010.** Rien n'est rejoué automatiquement : le système attend une reconnexion puis une réconciliation (`RECONCILED`/`RECONCILIATION_PENDING`, EA-06). |
| `CANCEL_REQUESTED` | `CANCELLED` | Annulation avant tout ACK — l'agent peut déjà avoir reçu la commande ; l'annulation à ce stade est un souhait, pas une garantie (documenté, pas résolu ici — EA-05/EA-06 le traitent avec le magic number et le rapprochement). | Le motif d'annulation. | Ambigu par nature ; laissé à la réconciliation. |
| `EXPIRED` | `EXPIRED` | `expiresAt` dépassé sans ACK. | Rien de nouveau. | Si l'agent l'exécute quand même après expiration côté OS, c'est une divergence que la réconciliation (EA-06) doit détecter — pas cette machine. |

### `RECEIVED`

| Événement | Vers | Déclencheur | Persisté | Si le processus meurt juste après |
|---|---|---|---|---|
| `VALIDATION_STARTED` | `VALIDATING` | L'agent commence ses barrières locales (`safety.md`). | — | La commande reste `RECEIVED` du point de vue du gateway tant qu'aucun message suivant n'arrive ; sans danger, aucun ordre n'a été passé. |
| `CANCEL_REQUESTED` | `CANCELLED` | Annulation avant validation. | Le motif. | Sans danger : aucun ordre passé. |
| `EXPIRED` | `EXPIRED` | `expiresAt` dépassé avant validation. | Rien de nouveau. | Sans danger. |

### `VALIDATING`

Les barrières locales de l'agent (`safety.md`) tournent : whitelist de
symbole, volume max, positions max, stop obligatoire, spread max,
`ACCOUNT_MISMATCH`, magic number.

| Événement | Vers | Déclencheur | Persisté | Si le processus meurt juste après |
|---|---|---|---|---|
| `VALIDATION_PASSED` | `EXECUTING` | Toutes les barrières locales passent. | — | Aucun ordre encore passé ; sans danger. |
| `VALIDATION_FAILED` | `REJECTED` | Une barrière échoue (ex. `ACCOUNT_MISMATCH`, spread trop large). | Le motif typé. | Sans danger : rejet avant tout ordre. |
| `CANCEL_REQUESTED` | `CANCELLED` | Annulation pendant la validation. | Le motif. | Sans danger. |
| `EXPIRED` | `EXPIRED` | `expiresAt` dépassé pendant la validation. | Rien de nouveau. | Sans danger. |

### `EXECUTING`

**Aucune annulation, aucune expiration à partir d'ici.** Une fois la
validation passée, l'ordre peut déjà être en vol vers le broker ; annuler ou
expirer côté OS ne changerait rien côté broker et créerait une divergence
non détectée. Seule la vérité broker (rapport, ou perte de lien) fait avancer
la machine.

| Événement | Vers | Déclencheur | Persisté | Si le processus meurt juste après |
|---|---|---|---|---|
| `EXECUTION_REPORTED` | `EXECUTED` | `execution.report` avec un statut de succès (`SIMULATED` en mode observe, `FILLED`/`PARTIALLY_FILLED` en mode réel). | Le rapport complet (`brokerOrderId`, `brokerPositionId`, prix, volume). | Le rapport est déjà arrivé ; sûr de continuer. |
| `EXECUTION_FAILED` | `FAILED` | `execution.report` avec `status: FAILED`. | Le motif, le retcode broker si présent. | L'agent sait que l'ordre a échoué côté broker ; sans position ouverte à réconcilier. |
| `EXECUTION_LINK_LOST` | `UNKNOWN` | Le lien meurt entre l'envoi de l'ordre (`OrderSend` côté agent, EA-05) et la réception du rapport. | Le fait qu'un `OrderSend` a peut-être eu lieu, sans confirmation. | **C'est le scénario « mort entre `OrderSend` et l'accusé »** qu'EA-06 doit tester explicitement. Le système ne sait pas si une position existe. Aucun rejeu : réconciliation obligatoire — interroger MT5 par magic number + trace du `commandId`. |

### `EXECUTED`

| Événement | Vers | Déclencheur | Persisté | Si le processus meurt juste après |
|---|---|---|---|---|
| `RECONCILED` | `RECONCILED` | Le rapprochement périodique (EA-06) confirme que ce que MT5 détient correspond à ce rapport. | La confirmation de rapprochement. | Sans danger : l'exécution est déjà un fait acquis, seule la confirmation manque. |

### `UNKNOWN`

**L'état de première classe.** Atteint depuis `SENT_TO_MT5` (`LINK_LOST`) ou
`EXECUTING` (`EXECUTION_LINK_LOST`). Sa seule fonction est d'attendre une
réconciliation ; il ne devine jamais.

| Événement | Vers | Déclencheur | Persisté | Si le processus meurt juste après |
|---|---|---|---|---|
| `RECONCILIATION_PENDING` | `UNKNOWN` (inchangé) | Une tentative de réconciliation n'a rien conclu (position introuvable après N tentatives — EA-06). | Le nombre de tentatives, l'horodatage de la dernière. | Reste `UNKNOWN` ; remonte à l'humain si le nombre de tentatives dépasse le seuil (EA-06). |
| `RECONCILED` | `RECONCILED` | La réconciliation conclut, avec un `outcome` (`executed`, `rejected`, `not_found`). L'`outcome` est une donnée du rapprochement (EA-06), pas un nouvel état — `UNKNOWN` n'a qu'une seule porte de sortie au niveau du type. | L'`outcome` et sa preuve (identifiant de position ou de deal trouvé). | Sans danger : la réconciliation a déjà eu lieu. |
| *(tout autre événement, ex. `EXECUTION_REPORTED`, `ACK_ACCEPTED`)* | **illégal** | Un rapport ou un ACK tardif arrive après coup pour la tentative d'origine. | — | **Refusé par construction** (`transition()` rend `ok: false`). Ce message ne fait pas avancer la commande hors de `UNKNOWN` ; il alimente au mieux la réconciliation en cours, jamais un rejeu automatique. C'est la règle non négociable de l'ADR 0010, testée explicitement (`execution-state.test.ts`). |

### États terminaux (`REJECTED`, `EXPIRED`, `FAILED`, `CANCELLED`, `RECONCILED`)

Aucune transition n'en repart — `transition()` rend `ok: false` pour tout
événement reçu dans un de ces états. Un message qui arrive après coup (ACK ou
rapport tardif sur une commande déjà `EXPIRED`, par exemple) est journalisé
comme une anomalie de la fiche EA-06 (rapprochement), jamais traité comme une
nouvelle transition.

## Ce que ce document ne couvre pas encore

- **Le déclenchement précis de `LINK_LOST`/`EXECUTION_LINK_LOST`** (délai
  d'attente avant de conclure que le lien est perdu) : paramètre à fixer avec
  l'agent réel, EA-05.
- **La résolution effective d'`UNKNOWN`** (comment on interroge MT5, combien
  de tentatives avant de remonter à l'humain) : EA-06.
- **Le stockage persistant de l'état par `commandId`** : cette fiche ne pose
  que la fonction de transition pure ; la persistance sur disque (survit à un
  redémarrage) est EA-05, la table de rapprochement est EA-06.
