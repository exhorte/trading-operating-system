# Protocole d'exécution cœur ↔ agent MT5

Statut : accepté (EA-03), **réécrit le 2026-10-09** pour le cœur Python (ADR 0016). Fige le contrat entre le Trading OS et l'agent d'exécution (ADR 0010). Le code qui le porte : `python/trading_os/infrastructure/mt5/wire.py` (le seul endroit où le vocabulaire du bord MT5 devient celui du domaine), `ea_link.py` (le serveur TCP), `domain/execution/` (commandes, états, refus) et `tools/mt5-execution-agent/TradingOsAgent.mq5` (l'autre bout). Le détail message par message est dans `context/realtime/mt5_wire_protocol.md` ; la machine à états dans `context/execution/state-machine.md`.

## Ce qui est sur le fil

Un socket TCP local (`127.0.0.1:9765`), **une ligne JSON par message**, UTF-8 sans BOM, `"version": 1` sur chaque ligne. L'agent se connecte au cœur (jamais l'inverse) et s'annonce par `agent.hello`, qui porte le jeton de l'agent. Le cœur n'envoie que trois types : `execution.order`, `control.ping`, `control.halt`. L'agent envoie `agent.hello`, `agent.heartbeat`, `agent.error`, `execution.ack`, `execution.report`, `execution.reconciled`, `execution.position.scan`. Une ligne illisible ou d'un type inconnu est ignorée, jamais levée.

Deux notions de version, volontairement séparées : `version` (la forme du message, `1`) ; `agentVersion` (le build de l'agent, `1.11`), simple information — le cœur n'en déduit rien. Tant qu'une seule forme existe, il n'y a rien à négocier ; le jour où elle change, `agent.hello` portera la plus haute version comprise et le cœur refusera au-delà.

## Champs obligatoires de toute commande (ADR 0010)

| Champ | Invariant |
|---|---|
| `commandId` | Unique (3 à 64 caractères). Clé d'idempotence : un rejeu ne produit jamais une seconde position. |
| `accountId` | Compte réellement connecté, égal au compte du terminal qui reçoit la commande ; sinon `ACCOUNT_MISMATCH`, jamais une exécution « au mieux ». Pour les commandes automatiques : le compte actif, et lui seul. |
| `kind` | `OPEN`, `MODIFY`, `CLOSE`, `PARTIAL_CLOSE`, `CANCEL` ; seuls ceux dont l'agent annonce la capacité sont envoyés (aujourd'hui `OPEN`) — les autres sont refusés à la soumission (`AGENT_CAPABILITY_MISSING`), pas envoyés dans le vide. |
| `riskDecisionId` | Une décision de risque **approuvée**, liée au même compte, non expirée (`RISK_NOT_APPROVED`, `RISK_DECISION_EXPIRED`, `RISK_DECISION_MISMATCH`) — sauf pour une commande qui ne fait que réduire le risque. |
| `expiresAt` | L'agent refuse toute commande reçue après cet instant (`EXPIRED`). Défaut : maintenant + la durée de vie du profil d'exécution du compte. |
| `stopLoss` | Obligatoire pour `OPEN` (`STOP_REQUIRED` côté cœur, `STOP_MISSING` côté agent). |

## Règle d'idempotence

Deux verrous, un à chaque bout. **Cœur** : un `commandId` déjà connu renvoie la commande existante ; avec une charge utile différente, c'est un conflit (`DUPLICATE_CONFLICT`, HTTP 409). La commande est **persistée `PENDING` avant tout envoi** ; base indisponible ⇒ refus (`STORE_UNAVAILABLE`), rien n'est envoyé. **Agent** : la correspondance `commandId → résultat` est écrite sur disque (`UNKNOWN` *avant* l'appel au courtier, réécrite après) ; un `commandId` revu renvoie son résultat d'origine (`DUPLICATE`), jamais une seconde exécution, même après un redémarrage du terminal. Une ligne `UNKNOWN` qui ne peut être écrite arrête l'ordre (`STORE_UNWRITABLE`).

## Vocabulaire de refus

Un refus est une **valeur** (code stable + raison), pas un texte libre. Côté cœur : `RejectCode` (`domain/execution/reasons.py`). Côté agent : la raison d'un `execution.ack` `REJECTED` commence par le code, suivi de deux-points (`DEAD_MAN: no ping for 31s`) ; le cœur lit tout ce qui précède le premier deux-points comme code.

| Code | Qui le lève | Signification |
|---|---|---|
| `ACCOUNT_MISMATCH`, `NOT_ACTIVE_ACCOUNT`, `ACCOUNT_NOT_CONNECTED`, `TRADING_DISABLED` | cœur (agent : `ACCOUNT_MISMATCH`) | le compte visé n'est pas celui qui peut recevoir cet ordre |
| `MODE_NOT_PERMITTING`, `HALTED`, `KILL_SWITCH` | cœur ; agent pour `HALTED` | l'état d'autonomie, le plafond de mode, l'arrêt ou le kill switch interdisent l'envoi |
| `AGENT_UNREACHABLE`, `AGENT_CAPABILITY_MISSING` | cœur | l'agent n'est pas joignable, ou n'annonce pas la capacité de la commande |
| `DEAD_MAN` | agent (build 1.11) | aucun `control.ping` du cœur depuis `InpDeadManSeconds`, ou aucun encore sur cette connexion : aucun nouvel ordre |
| `RISK_NOT_APPROVED`, `RISK_DECISION_EXPIRED`, `RISK_DECISION_MISMATCH` | cœur | pas de décision approuvée correspondante |
| `INVALID_REQUEST`, `STOP_REQUIRED`, `SYMBOL_MISMATCH`, `ORDER_TYPE_UNSUPPORTED`, `COMMAND_EXPIRED`, `DUPLICATE_CONFLICT`, `STORE_UNAVAILABLE` | cœur ; agent pour `SYMBOL_MISMATCH`, `ORDER_TYPE_UNSUPPORTED` | forme de la demande |
| `VOLUME_LIMIT`, `POSITIONS_LIMIT`, `STOP_MISSING`, `SPREAD_LIMIT_MISSING`, `SPREAD_TOO_WIDE`, `IDENTITY_REFUSED`, `STORE_UNWRITABLE` | agent seul | barrières locales (`context/execution/safety.md`) |

Ne nommer un code qu'avec le code qui le lève : un code sans porte serait une promesse non tenue.

## Messages et machine à états

| Message | Sens | Fait avancer la commande vers |
|---|---|---|
| `execution.order` | cœur → agent | `SENT` (déclenché par l'écriture sur le socket, pas par la réception) |
| `execution.ack` `ACCEPTED` | agent → cœur | `ACKNOWLEDGED` |
| `execution.ack` `REJECTED` / `EXPIRED` | agent → cœur | `REJECTED` / `EXPIRED` |
| `execution.ack` `DUPLICATE` | agent → cœur | rien : la preuve qu'un rejeu a eu lieu, l'état d'origine est déjà ailleurs |
| `execution.report` `FILLED` / `PARTIALLY_FILLED` | agent → cœur | `EXECUTED` |
| `execution.report` `SIMULATED` | agent → cœur | `SIMULATED` (agent compilé `OBSERVE` : validé de bout en bout, aucun ordre réel — jamais confondu avec un remplissage) |
| `execution.report` `FAILED` | agent → cœur | `FAILED` (refus définitif seulement ; les retours ambigus `10011`, `10012`, `10031` sont `UNKNOWN`) |
| *(silence ou perte du lien après `SENT`)* | — | `UNKNOWN` puis `RECONCILING` (jamais rejoué) |
| `execution.reconciled` | agent → cœur | résultat de la réconciliation que l'agent fait de lui-même à chaque connexion pour une commande restée `UNKNOWN` (`executed` / `rejected` / `not_found`) |
| `execution.position.scan` | agent → cœur | rien : l'inventaire des positions du terminal, pour détecter `UNEXPECTED_POSITION` |
| `control.ping` (toutes les 5 s) | cœur → agent | rien : la preuve de vie du cœur, dont dépend l'interrupteur d'homme mort |
| `control.halt` | cœur → agent | l'agent s'arrête de lui-même ; **seul un humain, sur le graphique, le lève** |

## Compatibilité

Un agent construit avant 1.11 envoie `gatewaySilentMs` au lieu de `coreSilentMs` dans son battement : le cœur lit les deux noms. Ce nom de remplacement (`wire.py`, `AgentHeartbeat.core_silent_ms`) s'enlève quand tous les agents sont recompilés.
