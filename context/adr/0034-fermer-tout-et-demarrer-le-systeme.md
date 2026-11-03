# ADR 0034 — « Fermer toutes les positions » et « Démarrer le système » depuis le cockpit

Statut : accepté le 2026-11-02 — amende 0023 (route des sorties humaines), 0033 (sorties sous arrêt) et 0014/0015 (l'échelle porte maintenant les noms du plan). Demande explicite d'Exhorte du 2026-11-02 (« rendre le Trading OS opérationnel depuis le cockpit »). Rien n'est envoyé à un courtier par ce code tant que l'agent MQL5 est compilé `OBSERVE` (ADR 0010, 0029).

## Contexte

Le cockpit n'avait ni geste « tout fermer » (le texte du bouton d'arrêt d'urgence disait même qu'« aucune commande `close_all` n'existe »), ni geste « démarrer » : le cœur lance déjà tous ses moteurs au démarrage (`runtime/engine.py`), mais l'autonomie reste `OFF` et seul l'appel REST `POST /api/autonomy/arm` la fait monter, sans écran.

Ce qui existe déjà et qui est **réutilisé, pas doublé** : `ExecutionService.submit` (idempotence par `commandId`, commande persistée avant l'envoi, `UNKNOWN` jamais rejoué, accusés et rapports), la commande `CLOSE`/`CANCEL` et sa validation (ADR 0023), le passage des sorties humaines sous `HALTED` (ADR 0033), la réconciliation (`ReconciliationService`), les seize contrôles de `readiness`, `autonomy.arm`/`disarm`/`halt`, le superviseur.

Deux manques réels, vérifiés dans le code :

1. une sortie humaine n'atteint l'agent qu'en `CONFIRM` et sous `HALTED` ; en `OFF`, `OBSERVE` et `PAPER` la route est `NONE` (la commande est seulement enregistrée) ;
2. l'interrupteur « Disable Trading » du compte (`trading_enabled = false`) refuse **aussi** une fermeture (`TRADING_DISABLED`).

## Décision

### 1. Une sortie humaine est une commande prioritaire, quel que soit le mode

`ExecutionService._route_for` : une commande qui ne fait que réduire le risque (`CLOSE`, `PARTIAL_CLOSE`, `CANCEL`) émise par un **geste humain** (`automatic=False`) prend la route `CONFIRM` dans **tous** les modes (`OFF`, `OBSERVE`, `PAPER`, `CONFIRM`, `HALTED`…) : le geste est la confirmation, la commande part tout de suite vers l'agent. Une commande automatique (stratégie, Position Manager, Guardian) ne change pas : elle suit la route de son mode, et reste refusée sous `HALTED`.

`validate` : `trading_enabled = false` ne refuse plus une sortie humaine (il refuse toujours les ouvertures, les `MODIFY` et l'automatique). Conséquence assumée : en `OFF`/`OBSERVE`, une sortie humaine **exige** un agent joignable (`AGENT_UNREACHABLE` sinon) — avant, elle était enregistrée « pour rien ». C'est la vérité : sans agent, rien n'est fermé.

### 2. Fermer toutes les positions (`CloseAllService`, pas de second mécanisme)

* `GET  /api/execution/close-all/preview` — lit le compte (lecture fraîche du terminal), liste positions et ordres en attente (symbole, sens, volume, entrée, SL, TP, P&L latent), le compte (nom, fournisseur, numéro masqué, environnement), un `batchId` généré par le cœur, les avertissements.
* `POST /api/execution/close-all` — corps `{accountId, batchId, positionIds, includePendingOrders, orderIds, confirmation: "CLOSE_ALL"}`. Ferme **exactement** les positions que l'utilisateur a vues dans la confirmation (une position apparue depuis n'est pas fermée : elle est signalée). Une commande `CLOSE` par position, `commandId = ca-<batch>-<positionId>` (un double clic, un rejeu après coupure : mêmes identifiants → `replayed`, jamais une seconde exécution), soumise par `ExecutionService.submit(..., automatic=False)`. Option explicite : un `CANCEL` par ordre en attente (`ca-<batch>-o<orderId>`), jamais mélangé avec les fermetures.
* `GET  /api/execution/close-all/{batchId}` — le rapport en direct, **dérivé** des commandes enregistrées et du dernier instantané du courtier (aucune table nouvelle : l'état d'un lot survit à un redémarrage). `POST …/{batchId}/verify` force une lecture du terminal puis une réconciliation, et renvoie le rapport.
* Un élément n'est `CONFIRMED` que si la commande est `EXECUTED`/`RECONCILED` **et** que la position a disparu de l'instantané du courtier. Une commande `SIMULATED` (agent compilé `OBSERVE`, mode `PAPER`) n'a rien fermé et le dit. `UNKNOWN` reste `UNKNOWN` (jamais rejoué : la réconciliation tranche). Le lot n'est `COMPLETE` que si tout est confirmé **et** qu'une réconciliation lisible a terminé après le dernier règlement, sans divergence critique.
* **Limite assumée (à trancher par Exhorte)** : l'agent ne ferme que ce qu'il a lui-même placé (`TARGET_NOT_OURS`, numéro magique, ADR 0010/0029). Une position ouverte à la main dans MT5 ou par un autre EA est marquée `NOT_CLOSABLE`, comptée parmi les « positions encore ouvertes » avec l'action « à fermer dans MT5 ». Lever cette barrière demande une modification de l'unique `OrderSend` : un accord et un ADR séparés, pas ici.

### 3. Démarrer le système (`StartupService`)

Trois choses distinctes, jamais fusionnées :

* **A — l'application** : cœur + base + cockpit. `scripts/start.ps1` les lance déjà ; le bouton ne peut pas démarrer un cœur qui n'écoute pas (il n'est pas là pour recevoir le clic). Ses étapes 1-3 *vérifient* donc l'application, les jobs et la base. Elles n'autorisent aucun ordre.
* **B — le système de trading** : `POST /api/system/startup` lance, en tâche de fond, la séquence de treize étapes (application, services, base, terminal MT5, compte, agent, réconciliation **forcée**, données de marché, Strategy Engine, Account Guardian, Risk Engine, mode d'autonomie, autorisation). Chaque étape a un état `STOPPED`/`STARTING`/`READY`/`RUNNING`/`DEGRADED`/`FAILED`/`HALTED` et une raison. Elle tente `accounts.connect` **sans mot de passe** si le compte actif est enregistré mais déconnecté (le terminal est déjà identifié ; ADR 0013 : aucun secret ne passe par le cockpit). Si tout est vert, le système monte `OFF → OBSERVE` (le mode de départ configuré), ou jusqu'à la cible demandée parmi `PAPER`/`CONFIRM`, un échelon à la fois par `autonomy.arm`. **Elle ne monte jamais plus haut.**
* **C — le trading automatique** : `POST /api/system/startup/authorize-automatic`, geste séparé, un échelon (`CONFIRM → ARMED → AUTONOMOUS`) par `autonomy.arm`, donc avec la préparation verte évaluée pour cet appel et le plafond du compte. Sur un compte réel, `acknowledgeRealAccount: true` est exigé, aussi pour tout passage à `CONFIRM` ou au-dessus. Un redémarrage du cœur retombe toujours `OFF` (ADR 0014) : aucun redémarrage n'active `LIVE_AUTO`.

Le verdict « le système peut-il prendre une position ? » (`entriesAuthorized`) est la conjonction des seize contrôles de préparation et de six contrôles propres au démarrage (données de marché fraîches, Account Guardian opérationnel, aucune commande `UNKNOWN`, limites jour/semaine et capital de référence chargés, aucun verrou ni blocage de sécurité, mode explicitement autorisé par le plafond). Les six sont exigés **à l'autorisation** du mode automatique et affichés en continu ; ils ne rétrogradent pas un mode déjà monté (la perte de l'une des seize le fait déjà, après tolérance — ADR 0014/0015). Écart connu et écrit dans le plan de reprise.

### 4. Correspondance de l'échelle du dépôt avec celle du plan (§18)

| Plan | Dépôt | Condition |
|---|---|---|
| (arrêté) | `OFF` | — |
| `OBSERVE` | `OBSERVE` | — |
| `PAPER` | `PAPER` | — |
| `CONFIRM` | `CONFIRM` | environnement `DEMO` ou `SIMULATED` |
| `DEMO_AUTO` | `ARMED`, `AUTONOMOUS` | environnement `DEMO` ou `SIMULATED` |
| `LIVE_CONFIRM` | `CONFIRM` | environnement `LIVE` |
| `LIVE_AUTO` | `ARMED`, `AUTONOMOUS` | environnement `LIVE` |
| (arrêt) | `HALTED` | — |

La table est une **lecture**, pas un nouvel état : aucun état du dépôt n'est renommé, ajouté ni supprimé. `domain/autonomy/plan_modes.py` la porte, avec les droits de chaque mode (envoie un ordre ? attend un humain ? exige la préparation verte ?).

### 5. Arrêter, arrêter les entrées, tout fermer : trois gestes, jamais fusionnés

`HALT` (arrêt d'urgence) bloque les entrées et pose le kill switch de l'agent ; il **ne ferme rien** et laisse les fermetures humaines passer (ADR 0033). « Fermer toutes les positions » est un geste à part, avec sa confirmation. Le bouton d'arrêt d'urgence n'appelle jamais la fermeture. Annuler les ordres en attente est une option explicite de la fermeture globale, jamais implicite.

## Conséquences

* Le chemin reste `cockpit → FastAPI → ExecutionService → agent MQL5 → MT5` ; aucun `OrderSend` nouveau, aucun changement de l'agent. Tant que l'agent est compilé `OBSERVE`, toute fermeture répond `SIMULATED` et le cockpit l'écrit en toutes lettres.
* Claude ne clique jamais ces boutons (`.claude/CLAUDE.md`) : tests avec agent et courtier simulés ; l'essai sur démo est le geste d'Exhorte (`tools/mt5-execution-agent/README.md`).
* Reste ouvert : fermeture des positions étrangères à l'agent (accord séparé) ; rétrogradation continue sur les six contrôles de démarrage ; la barrière `OBSERVE` de l'agent est une décision d'Exhorte (constante de compilation).
