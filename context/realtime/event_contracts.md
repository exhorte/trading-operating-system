# Contrats d'événements

Réécrit le 2026-10-09 (ADR 0016). Les événements sont des **modèles pydantic du domaine** (`python/trading_os/domain/events.py`), publiés par les services sur un dispatcher interne (`shared/events/`). Le même modèle sert trois fois, sans traduction : il est **persisté** (table `events`, journal d'audit), **diffusé** au cockpit par le WebSocket, et **typé** côté cockpit par `lib/api/generated.ts` (`EventPayloads`, `CockpitEvent`), généré par `python -m trading_os gen-types` — un test échoue si le fichier est périmé. Il n'y a ni seconde enveloppe, ni DTO, ni traducteur.

## Trame

```json
{ "type": "risk.state_updated", "id": "evt_…", "occurredAt": "2026-10-09T15:35:27Z",
  "accountId": "exness-1000001", "correlationId": "cmd-1245", "payload": { … } }
```

- `type` — nom stable de l'événement (`famille.nom`) ;
- `id` — identifiant unique : un événement n'est traité **qu'une fois** (`ON CONFLICT DO NOTHING` côté base, déduplication côté cockpit) ;
- `occurredAt` — instant UTC ;
- `accountId` — le compte concerné, ou `null` pour un fait global (battement, calendrier, santé) ;
- `correlationId` — relie un fil de bout en bout (intention → décision → commande → rapport) ;
- `payload` — les champs propres à l'événement.

**La première trame d'une connexion est `system.snapshot`** : tout l'état (comptes, compte actif, autonomie, santé, calendrier, état de chaque compte). Un client qui se connecte ou se reconnecte n'a jamais à deviner.

## Familles (54 événements aujourd'hui)

| Famille | Événements |
|---|---|
| `account` | `created`, `updated`, `archived`, `connected`, `disconnected`, `error`, `active_changed`, `trading_toggled`, `rules_changed`, `snapshot` |
| `agent` | `connected`, `disconnected`, `heartbeat`, `status_changed` |
| `autonomy` | `mode_changed`, `armed`, `disarmed`, `halted`, `readiness_changed` |
| `market` | `tick`, `candle_closed`, `calendar_updated` |
| `position`, `positions` | `opened`, `modified`, `closed` ; `positions.snapshot` |
| `strategy`, `trade` | `strategy.evaluation_started`, `…_completed` ; `trade.intent_created`, `trade.rejected` |
| `risk` | `evaluation_started`, `approved`, `rejected`, `state_updated`, `lockout_enabled`, `lockout_violated`, `lockout_acknowledged`, `lockout_cleared` |
| `execution` | `command_created`, `command_sent`, `acknowledged`, `reported`, `failed`, `unknown`, `rejected`, `reconciled` |
| `reconciliation` | `started`, `mismatch`, `completed` |
| `system` | `heartbeat`, `heartbeat_missed`, `health_changed`, `incident_opened`, `incident_resolved` |

La liste fait foi dans le code (`EVENT_REGISTRY`) ; un test d'architecture vérifie que chaque nom est unique, pointé et enregistré, et qu'**aucun champ d'événement ne peut porter un secret**.

## Messages du client

`{"type":"subscribe","accountIds":[…]}` restreint les trames à ces comptes (les événements globaux sont toujours envoyés) et répond par un nouvel instantané ; `{"type":"resync"}` demande un instantané frais. Le jeton passe en `?access_token=` (un navigateur ne peut pas poser d'en-tête sur un WebSocket), avec une Origin autorisée ; il est masqué dans les journaux du cœur.

## Règles

- **Idempotence** : toute commande porte un `commandId` stable ; les rapports reprennent l'identifiant de la commande d'origine ; le cœur réconcilie les rapports avec ce qu'il a voulu (`context/execution/state-machine.md`).
- **Contre-pression** : une file bornée par client (500 trames) ; quand elle déborde, les trames de télémétrie les plus anciennes (un tick, un instantané de compte) sont jetées — jamais un événement de cycle de vie (ordre accusé, position clôturée, arrêt) ; si la file n'est faite que de ceux-là, le client est fermé (code 1013) et repart d'un instantané.
- **Reconnexion** : un instantané frais avant de faire confiance à quoi que ce soit.
