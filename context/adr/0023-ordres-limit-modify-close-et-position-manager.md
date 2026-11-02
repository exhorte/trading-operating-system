# ADR 0023 — Ordres `LIMIT`, `MODIFY`, `CLOSE`, `PARTIAL_CLOSE`, `CANCEL` et Position Manager (phase 3)

Date : 2026-11-01. Statut : **accepté** — mission « Trading OS autonome » du 2026-11-01 (accord nommé dans `session-log.md` :
« ordres LIMIT/MODIFY/CLOSE/PARTIAL_CLOSE », chacun « après son ADR »), confirmée par l'utilisateur le 2026-11-01 : « continue la
suite des phases restantes jusqu'à la fin ». **Étend l'ADR 0007** (le Risk Engine reste le seul point de contrôle) et **l'ADR 0010**
(commandes idempotentes) ; **ne lève aucun verrou de l'agent** : le plafond reste `OBSERVE` et le mode de l'agent reste une
constante compilée.

## Contexte

Le domaine connaît déjà les cinq natures de commande (`CommandKind`) et le type d'ordre `LIMIT`, mais le protocole de l'agent ne porte
que `OPEN` **au marché** : tout le reste est refusé (`ORDER_TYPE_UNSUPPORTED`, `AGENT_CAPABILITY_MISSING`). Conséquences : l'entrée
`LIMIT` de S01 aboutit à un refus enregistré, et personne ne gère une position ouverte (blocage d'autonomie « gestion des
positions », TD-09). Aucun module ne déplace un stop, ne ferme en partie ni n'aplatit en fin de séance.

## Décision

1. **Types d'ordre.** `MARKET` et `LIMIT` (ordre en attente). `STOP` reste refusé : la mission ne le nomme pas.
   Un `LIMIT` exige un prix, un stop du bon côté du prix (sous le prix pour un achat, au-dessus pour une vente) et une cible du bon
   côté. Il porte une expiration (celle de l'intention) : un ordre en attente n'est jamais illimité.
2. **Quatre commandes de gestion**, toutes validées par le cœur **avant** l'agent, sur la position ou l'ordre que le cœur voit :
   - `MODIFY` (stop et/ou cible d'une position ouverte) : **un stop ne s'éloigne jamais du prix** (`STOP_LOOSENED`) ; un stop ne se
     retire pas (`stop_loss > 0` ou absent) ; une position sans stop peut en recevoir un ;
   - `CLOSE` (toute la position) ; `PARTIAL_CLOSE` (volume strictement inférieur au volume ouvert, sinon c'est un `CLOSE`) ;
   - `CANCEL` (un ordre en attente existant).
   Ces trois dernières ne font que **réduire** l'exposition (`reduces_risk_only`) : pas de dimensionnement, un enregistrement.
   Position ou ordre introuvable : `POSITION_NOT_FOUND` / `ORDER_NOT_FOUND`. Volume invalide : `VOLUME_INVALID`.
3. **Capacités.** L'agent annonce ce qu'il sait faire (`limit`, `modify`, `close`, `cancel`) ; une capacité absente refuse la commande
   (`AGENT_CAPABILITY_MISSING`), comme aujourd'hui. L'agent 1.11 n'en annonce aucune : **rien de nouveau n'atteint un courtier**.
   OBSERVE et PAPER (qui n'envoient rien) acceptent les cinq commandes : le chemin entier se vérifie sans courtier.
4. **Fil** (`infrastructure/mt5/wire.py`) : `execution.modify`, `execution.close` (avec `volume` optionnel), `execution.cancel`, au même
   format que `execution.order` (version, `accountId`, `id`, `expiresAt`). Les rapports `MODIFIED` et `CLOSED` existent déjà.
5. **Position Manager** (`domain/positions/manager.py`, pur ; `services/position_manager.py`, le cycle). Il ne gère **que** les positions
   dont l'ouverture est une commande du cœur (`for_position`) : jamais une position manuelle ou externe. Règles, toutes dans un
   `ExitPlan` en code (comme `S01Config`), avec ces valeurs de départ :
   - **break-even** à `+1 R` : le stop passe au prix d'entrée plus un tampon (spread + commission en prix) du côté du gain, jamais
     plus loin que le prix courant ; le R se mesure sur le **stop initial** de la commande d'ouverture, pas sur le stop courant ;
   - **clôture partielle** : désactivée par défaut (`partial_at_r = None`) ; si l'utilisateur la fixe, une seule fois par position ;
   - **suivi de stop** : désactivé par défaut (`trail_distance_r = None`) ; s'il est fixé, le stop suit à cette distance et ne
     fait que se resserrer ;
   - **fin de séance** : à `flat_minutes_before_window_end` minutes (5) de la fin de la fenêtre de trading (Londres 05:00, New York AM
     10:00, heure de New York), toute position gérée est fermée et tout ordre en attente est annulé ; hors fenêtre, une position
     gérée encore ouverte est fermée ;
   - **ordre en attente périmé** : annulé si son **objectif est atteint avant le remplissage** (note N6, « nix the trade »), si la fenêtre se termine, ou s'il attend
     depuis plus de 30 minutes. L'invalidation par clôture de corps au-delà du CE (S01) n'est **pas** appliquée : la fiche ne dit pas ce qu'on en fait pour un ordre en
     attente ou une position ouverte, et la règle financière n'est pas inventée (plan, §23).
   Un identifiant de commande **déterministe** (`pm-<action>-<position>-<n>`) rend chaque action idempotente : relancer le cycle ne
   la rejoue jamais (ADR 0010). Le Position Manager n'ouvre rien, n'augmente aucun risque, et ne contourne rien : ses commandes
   passent par `ExecutionService.submit`, donc par la même validation, le même mode et la même trace que les autres.
6. **Prêt pour l'autonomie.** Le contrôle `position_management` devient vrai lorsque le Position Manager a un plan valide, a tourné
   récemment et n'a pas échoué ; il ne dit rien de la rentabilité (aucune ne se déduit d'un plan de sortie).

## Ce que cet ADR ne fait pas

- Il **ne modifie pas l'agent MQL5** : ses nouveaux gestionnaires d'ordres se construisent dans un incrément séparé (ils ajoutent des
  appels d'exécution, donc exigent leur propre relecture), et l'agent compilé reste `OBSERVE`. Tant que l'agent n'annonce pas
  `modify`/`close`/`cancel`/`limit`, le Position Manager ne peut agir qu'en OBSERVE (enregistré) et en PAPER (simulé).
- Il n'élève aucun plafond d'autonomie et ne démarre rien.
- Il ne choisit pas les valeurs de l'`ExitPlan` à la place de l'utilisateur : ce sont des valeurs de départ, visibles, à écrire.

## Conséquences

- Tests : validation de chaque commande (refus et acceptation), règle « le stop ne s'éloigne jamais », fil, expéditeurs (agent,
  papier), Position Manager pur (break-even, R sur stop initial, fin de séance, idempotence), service (positions gérées seulement),
  contrôle de prêt.
- Les enregistrements de `execution_commands` accueillent déjà `MODIFY`/`CLOSE`/… (colonne `kind`) : pas de migration.
- La fiche d'outil EA-05 reçoit l'entrée « protocole d'ordres, côté cœur ».
