# Protocole d'exécution cœur ↔ agent MT5

Statut : accepté (EA-03), **réécrit le 2026-10-09** pour le cœur Python (ADR 0016). Fige le contrat entre le Trading OS et l'agent d'exécution (ADR 0010). Le code qui le porte : `python/trading_os/infrastructure/mt5/wire.py` (le seul endroit où le vocabulaire du bord MT5 devient celui du domaine), `ea_link.py` (le serveur TCP), `domain/execution/` (commandes, états, refus) et `tools/mt5-execution-agent/TradingOsAgent.mq5` (l'autre bout). Le détail message par message est dans `context/realtime/mt5_wire_protocol.md` ; la machine à états dans `context/execution/state-machine.md`.

## Ce qui est sur le fil

Un socket TCP local (`127.0.0.1:9765`), **une ligne JSON par message**, UTF-8 sans BOM, `"version": 1` sur chaque ligne. L'agent se connecte au cœur (jamais l'inverse) et s'annonce par `agent.hello`, qui porte le jeton de l'agent. Le cœur envoie `execution.order`, `control.ping`, `control.halt` et, depuis l'ADR 0023, `execution.modify` (`positionId`, `sl`, `tp` — un `null` laisse le niveau tel quel), `execution.close` (`positionId`, `volume` optionnel pour une clôture partielle) et `execution.cancel` (`orderId`) ; `execution.order` porte aussi `orderType: "LIMIT"` et `limitPrice`. **L'agent 1.12 (ADR 0029) a un gestionnaire pour chacun** et annonce `limit`, `modify`, `close`, `cancel` dans son `agent.hello` ; un agent plus ancien ne les annonce pas et le cœur ne lui envoie rien d'autre que l'ordre au marché. L'agent envoie `agent.hello`, `agent.heartbeat`, `agent.error`, `execution.ack`, `execution.report`, `execution.reconciled`, `execution.position.scan`. Une ligne illisible ou d'un type inconnu est ignorée, jamais levée.

Deux notions de version, volontairement séparées : `version` (la forme du message, `1`) ; `agentVersion` (le build de l'agent, `1.11`), simple information — le cœur n'en déduit rien. Tant qu'une seule forme existe, il n'y a rien à négocier ; le jour où elle change, `agent.hello` portera la plus haute version comprise et le cœur refusera au-delà.

## Champs obligatoires de toute commande (ADR 0010)

| Champ | Invariant |
|---|---|
| `commandId` | Unique (3 à 64 caractères). Clé d'idempotence : un rejeu ne produit jamais une seconde position. |
| `accountId` | Compte réellement connecté, égal au compte du terminal qui reçoit la commande ; sinon `ACCOUNT_MISMATCH`, jamais une exécution « au mieux ». Pour les commandes automatiques : le compte actif, et lui seul. |
| `kind` | `OPEN`, `MODIFY`, `CLOSE`, `PARTIAL_CLOSE`, `CANCEL` ; seuls ceux dont l'agent annonce la capacité (`modify`, `close`, `cancel` ; `limit` pour un ordre `LIMIT`) sont envoyés — l'agent 1.11 n'en annonçait aucune (seul `OPEN` au marché partait), l'agent 1.12 les annonce toutes ; sans capacité, la commande est refusée à la soumission (`AGENT_CAPABILITY_MISSING`), pas envoyée dans le vide. OBSERVE et PAPER n'envoient rien et acceptent les cinq. Un `MODIFY` n'éloigne jamais un stop du prix (`STOP_LOOSENED`) et n'en retire jamais (`STOP_REQUIRED` côté cœur, `STOP_MISSING` côté agent). Un `CLOSE`, un `PARTIAL_CLOSE` et un `CANCEL` ne visent que ce que l'agent a lui-même placé (`TARGET_NOT_OURS`). |
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
| `MODE_NOT_PERMITTING`, `HALTED`, `KILL_SWITCH` | cœur ; agent pour `HALTED` | l'état d'autonomie, le plafond de mode, l'arrêt ou le kill switch interdisent l'envoi. **Depuis l'ADR 0033 (agent 1.13), un arrêt ne refuse plus une fermeture ni une annulation émise par un geste humain** (`CLOSE`, `PARTIAL_CLOSE`, `CANCEL`) : il refuse les ouvertures, les `MODIFY` et toute commande automatique |
| `AGENT_UNREACHABLE`, `AGENT_CAPABILITY_MISSING` | cœur | l'agent n'est pas joignable, ou n'annonce pas la capacité de la commande |
| `DEAD_MAN` | agent (build 1.11) | aucun `control.ping` du cœur depuis `InpDeadManSeconds`, ou aucun encore sur cette connexion : aucun nouvel ordre |
| `RISK_NOT_APPROVED`, `RISK_DECISION_EXPIRED`, `RISK_DECISION_MISMATCH` | cœur | pas de décision approuvée correspondante |
| `INVALID_REQUEST`, `STOP_REQUIRED`, `SYMBOL_MISMATCH`, `ORDER_TYPE_UNSUPPORTED`, `COMMAND_EXPIRED`, `DUPLICATE_CONFLICT`, `STORE_UNAVAILABLE` | cœur ; agent pour `INVALID_REQUEST`, `SYMBOL_MISMATCH`, `ORDER_TYPE_UNSUPPORTED` | forme de la demande ; côté agent, `ORDER_TYPE_UNSUPPORTED` couvre aussi un symbole qui n'accepte pas d'ordre en attente avec expiration (un ordre en attente n'est jamais laissé sans fin) |
| `POSITION_NOT_FOUND`, `ORDER_NOT_FOUND`, `STOP_LOOSENED`, `VOLUME_INVALID` | cœur ; agent depuis 1.12 | commande de gestion (ADR 0023, 0029) : cible introuvable, stop qui s'éloignerait du prix, volume hors du pas/min/max du symbole, ou clôture partielle qui n'est pas strictement dans le volume ouvert (ou qui laisserait un reste inférieur au minimum) |
| `VOLUME_LIMIT`, `POSITIONS_LIMIT`, `STOP_MISSING`, `SPREAD_LIMIT_MISSING`, `SPREAD_TOO_WIDE`, `IDENTITY_REFUSED`, `STORE_UNWRITABLE` | agent seul | barrières locales (`context/execution/safety.md`). `POSITIONS_LIMIT` compte, depuis 1.12, les positions **et** les ordres en attente ; `STOP_MISSING` couvre aussi un `MODIFY` qui retirerait le stop |
| `STOP_INVALID`, `LIMIT_PRICE_INVALID`, `TARGET_NOT_OURS`, `SYMBOL_UNAVAILABLE`, `LOGIN_NOT_TRADABLE`, `LOGIN_NOT_CLOSABLE` | agent seul (1.12) | stop ou cible du mauvais côté du prix ou à moins du niveau d'arrêts du courtier ; prix d'un `LIMIT` du mauvais côté du marché ; position ou ordre qui n'est pas celui de l'agent (autre numéro magique) ; aucune cotation ni pas de prix pour le symbole ; compte absent de `InpTradableLogins` (ouvrir, déplacer un stop) ou de `InpClosableLogins` (fermer, annuler) |

Ne nommer un code qu'avec le code qui le lève : un code sans porte serait une promesse non tenue.

## Messages et machine à états

| Message | Sens | Fait avancer la commande vers |
|---|---|---|
| `execution.order` | cœur → agent | `SENT` (déclenché par l'écriture sur le socket, pas par la réception) |
| `execution.ack` `ACCEPTED` | agent → cœur | `ACKNOWLEDGED` |
| `execution.ack` `REJECTED` / `EXPIRED` | agent → cœur | `REJECTED` / `EXPIRED` |
| `execution.ack` `DUPLICATE` | agent → cœur | rien : la preuve qu'un rejeu a eu lieu, l'état d'origine est déjà ailleurs |
| `execution.report` `FILLED` / `PARTIALLY_FILLED` | agent → cœur | `EXECUTED` (ordre au marché) |
| `execution.report` `SUBMITTED` / `MODIFIED` / `CLOSED` / `CANCELLED` | agent → cœur | `EXECUTED` (ADR 0029) : un ordre `LIMIT` posé chez le courtier (rien n'est rempli : ni position, ni volume, ni prix — la réconciliation n'attend pas de position tant qu'aucune ne porte la trace), un stop déplacé, une position fermée en tout ou en partie, un ordre en attente supprimé. `side` vaut `null` quand le rapport n'a pas de sens propre, jamais `""` |
| `execution.report` `SIMULATED` | agent → cœur | `SIMULATED` (agent compilé `OBSERVE` : validé de bout en bout, aucun ordre réel — jamais confondu avec un remplissage) |
| `execution.report` `FAILED` | agent → cœur | `FAILED` (refus définitif seulement ; les retours ambigus `10011`, `10012`, `10031` sont `UNKNOWN`) |
| *(silence ou perte du lien après `SENT`)* | — | `UNKNOWN` puis `RECONCILING` (jamais rejoué) |
| `execution.reconciled` | agent → cœur | résultat de la réconciliation que l'agent fait de lui-même à chaque connexion pour une commande restée `UNKNOWN` (`executed` / `rejected` / `not_found`) |
| `execution.position.scan` | agent → cœur | rien : l'inventaire des positions du terminal, pour détecter `UNEXPECTED_POSITION` |
| `control.ping` (toutes les 5 s) | cœur → agent | rien : la preuve de vie du cœur, dont dépend l'interrupteur d'homme mort |
| `control.halt` | cœur → agent | l'agent s'arrête de lui-même ; **seul un humain, sur le graphique, le lève** |

## Compatibilité

Un agent construit avant 1.11 envoie `gatewaySilentMs` au lieu de `coreSilentMs` dans son battement : le cœur lit les deux noms. Ce nom de remplacement (`wire.py`, `AgentHeartbeat.core_silent_ms`) s'enlève quand tous les agents sont recompilés.
