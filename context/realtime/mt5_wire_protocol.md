# Protocole du lien agent MT5 ↔ cœur

Réécrit le 2026-10-09 (ADR 0016). Le cœur Python et l'agent MQL5 `TradingOsAgent` échangent des lignes JSON sur un **socket TCP local** (`127.0.0.1:9765`). Types canoniques : `python/trading_os/infrastructure/mt5/wire.py` ; serveur : `ea_link.py` ; l'autre bout : `tools/mt5-execution-agent/TradingOsAgent.mq5`. Le contrat d'exécution (champs obligatoires, idempotence, refus) est dans `context/execution/protocol.md`.

## Pourquoi du TCP simple, et un seul protocole

L'agent n'a que des sockets MQL5 : pas de client WebSocket maintenu, pas de SignalR. Le lien est **loopback**, entre deux processus d'une machine personnelle : pas de WSS, une ligne JSON par message, UTF-8 **sans BOM** (un BOM avant la première commande a déjà été un vrai bug). Il n'y a plus qu'**une** forme de message : celle du bord MT5 est convertie vers le domaine à un seul endroit (`wire.py` : `BUY`/`SELL` → `Side`, millisecondes époque → dates) ; rien en aval ne la voit. Plus de seconde enveloppe, plus de traducteur.

## Enveloppe commune

| Champ | Type | Note |
| --- | --- | --- |
| `version` | nombre | version de la forme du message (aujourd'hui `1`) |
| `type` | chaîne | famille ci-dessous |
| `accountId` | chaîne | le **login** MT5 du terminal (`ACCOUNT_LOGIN`), plus jamais une entrée de l'EA |
| `time` | nombre | millisecondes depuis l'époque, UTC (deux ticks dans la même seconde restent ordonnés) |

## Messages

Agent → cœur :

- `agent.hello` — à chaque (re)connexion : le jeton de l'agent, ce qu'il sait faire et ce qu'il est.
- `agent.heartbeat` — toutes les 5 s, et aussitôt qu'un état change.
- `agent.error`
- `execution.ack` — accusé immédiat, reprend l'`id` de la commande : `ACCEPTED`, `REJECTED`, `DUPLICATE`, `EXPIRED`.
- `execution.report` — issue : `SIMULATED`, `SUBMITTED`, `FILLED`, `PARTIALLY_FILLED`, `MODIFIED`, `CLOSED`, `FAILED`, `REJECTED`.
- `execution.reconciled` — ce que l'agent a conclu, à la connexion, d'une commande restée `UNKNOWN` : `executed`, `rejected`, `not_found`.
- `execution.position.scan` — une position du terminal (`magicNumber`, `isExternal`, `knownCommandId`), à chaque battement.

Cœur → agent :

- `execution.order`
- `control.ping` — toutes les 5 s, aux agents qui annoncent la capacité `ping`.
- `control.halt` — avec une `reason`, aux agents qui annoncent `halt` : il **pose** l'arrêt local, il ne le lève jamais (seul un humain, sur le graphique MT5).

Le cœur ne reçoit plus ni ticks, ni bougies, ni instantanés de compte de l'agent : il les lit lui-même dans MT5, dans un processus enfant en lecture seule. L'agent n'est plus la source de rien d'autre que de son exécution et de sa télémétrie.

## Exemples

Commande (cœur → agent) :

```json
{"version":1,"type":"execution.order","accountId":"477029930","time":1780000000000,"id":"cmd-1245","expiresAt":1780000005000,"symbol":"EURUSDm","side":"BUY","orderType":"MARKET","volume":0.2,"limitPrice":null,"sl":1.0820,"tp":1.0890}
```

Accusé puis rapport en mode `observe` (agent → cœur) :

```json
{"version":1,"type":"execution.ack","accountId":"477029930","time":1780000000100,"commandId":"cmd-1245","status":"ACCEPTED","reason":null}
{"version":1,"type":"execution.report","accountId":"477029930","time":1780000000150,"commandId":"cmd-1245","status":"SIMULATED","symbol":"EURUSDm","side":"BUY","brokerOrderId":null,"brokerPositionId":null,"filledVolume":null,"averagePrice":null,"brokerRetcode":null,"detail":"observe mode: order not sent to broker"}
```

## `agent.hello` et `agent.heartbeat`

**`agent.hello`** : `token` (vérifié par le cœur sur la ligne brute, **jamais gardé** : aucun modèle n'a de champ pour lui), `agentId`, `agentVersion` (build, `1.11`), `buildId`, `capabilities` (`ping`, `halt`, `dead_man`), `mode` (effectif) et `modeCeiling` (le plus haut mode que ce build peut jamais atteindre), `identity` (`ok` | `mismatch` | `no_account`) et `expectedAccountId`, `broker`, `server`, `symbol` (le premier symbole seulement : héritage du prototype à un symbole), `orderTypes`, `minVolume`, `maxVolume`, `volumeStep`, `fillingMode`, `stopsLevelPoints`, `tradeMode`, `marginMode` (`hedging` | `netting` | `exchange`), `fifoClose`, `leverage`, `currency`, les quatre permissions de trading (`terminalTradeAllowed`, `expertTradeAllowed`, `accountTradeExpert`, `accountTradeAllowed`), `tradable`, `closable`, `halted`, `attachedExperts` (tous les autres EA du terminal — le bouton Algo Trading les arme tous).

**`agent.heartbeat`** : ce qui peut changer en cours de connexion — `mode`, `identity`, les quatre permissions, `halted`, `attachedExperts`, `latencyMs`, et **`coreSilentMs`** : depuis combien de temps l'agent n'a rien entendu du cœur. Le cœur ne considère un battement comme un *changement d'état* que si autre chose que ses deux horloges a bougé. Un agent construit avant 1.11 envoie ce champ sous le nom `gatewaySilentMs` : le cœur lit les deux.

## Modes d'exécution

L'agent applique un mode à chaque commande ; la charge utile est identique d'un mode à l'autre.

| Mode | Action du terminal | Statut du rapport |
| --- | --- | --- |
| `observe` (le seul de ce build) | n'envoie jamais rien au courtier | `SIMULATED` |
| `paper` | route vers un compte de démonstration | statuts réels du courtier |
| `confirm` | route vers le vrai courtier, un ordre à la fois, après validation humaine explicite (EA-07) | statuts réels du courtier |

Le mode effectif ne dépasse jamais le plafond **compilé** de l'agent (`OBSERVE` dans ce build) ni celui que le cœur impose (`TRADING_MODE`, plafond du compte, état d'autonomie).

## Idempotence, reprise, réconciliation

- L'agent déduplique par `id` : un `id` revu reçoit `execution.ack` `DUPLICATE`, sans réexécution, même après un redémarrage du terminal (journal disque).
- L'agent refuse toute commande reçue après son `expiresAt` : `EXPIRED`.
- Chaque `ack` et chaque `report` reprennent l'`id` de la commande ; le cœur les réconcilie avec ce qu'il a voulu.
- À chaque reconnexion l'agent renvoie `agent.hello`, rejoue les rapports finaux de la dernière heure (`replayed: true`, avec leur `time` d'origine ; l'identifiant d'un rapport est `commandId:statut:heure`, donc une copie d'un rapport déjà stocké est sans effet), réconcilie ses `UNKNOWN` (`execution.reconciled`) et rescanne les positions. Aucune nouvelle commande n'est de confiance avant cela.
- Les identifiants du courtier et `brokerRetcode` sont des **chaînes** JSON ; le cœur accepte aussi des nombres nus (un agent ancien en envoyait). Le commentaire d'un ordre est une courte trace (`"TOS " + 16 hex du SHA-256(commandId)`, 20 caractères) : un commentaire plus long dépasse ce qu'un courtier conserve et ruinerait la réconciliation.

## Codes de refus qui mènent la raison d'un `REJECTED`

`HALTED`, `DEAD_MAN`, `IDENTITY_REFUSED`, `ACCOUNT_MISMATCH`, `SYMBOL_MISMATCH`, `ORDER_TYPE_UNSUPPORTED`, `VOLUME_LIMIT`, `STOP_MISSING`, `POSITIONS_LIMIT`, `SYMBOL_UNAVAILABLE`, `SPREAD_LIMIT_MISSING`, `SPREAD_TOO_WIDE` ; et, sur le chemin d'exécution (inatteignable dans ce build) : `LOGIN_NOT_TRADABLE`, `STORE_UNWRITABLE`. Voir `context/execution/protocol.md` et `safety.md`.
