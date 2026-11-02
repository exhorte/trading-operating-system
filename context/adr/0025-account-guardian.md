# ADR 0025 — Account Guardian : un surveillant indépendant des positions du cœur (phase 4)

Date : 2026-11-01. Statut : **accepté** — mission « Trading OS autonome » du 2026-11-01 (phase 4 : « surveillance continue, kill switch,
reprise après panne »), confirmée le 2026-11-01. **Étend l'ADR 0007** : le Risk Engine reste le seul point de contrôle des *entrées* ;
le Guardian ne contrôle que des *sorties*. **Ne lève aucun verrou de l'agent.**

## Contexte

Le Risk Engine verrouille le compte quand une limite de perte est atteinte : plus aucune entrée. Il ne ferme rien. Une position ouverte
continue donc de perdre au-delà de la limite, et sous une règle de prop firm la limite *est* l'échec du compte. Le Position Manager
(ADR 0023) protège chaque position, mais s'il est lui-même défaillant — ou si le courtier refuse ses ordres — rien d'autre ne regarde.
Après une panne du cœur, personne ne vérifie non plus que les positions encore ouvertes sont protégées.

## Décision

1. **Le Guardian est un service distinct** (`services/guardian.py`, règles pures dans `domain/guardian/`) qui ne partage aucun état avec
   le Position Manager : il relit le compte (usage des limites par le Risk Engine, positions, ordres) à chaque cycle et ne se fie à
   aucun autre composant pour savoir si tout va bien.
2. **Trois règles, toutes des sorties.**
   - **Limite atteinte** : dès que la perte du jour, de la semaine ou le total atteint `flatten_at_fraction` de sa limite (valeur de
     départ 1,0 — la limite elle-même, écrite par l'utilisateur ; l'abaisser, par exemple à 0,9, est son choix), toutes les positions
     **du cœur** sont fermées et ses ordres en attente annulés.
   - **Position du cœur sans stop** depuis plus de `protect_grace_seconds` (30 s — le Position Manager a eu sa chance) : elle est fermée.
   - **Position qui n'est pas du cœur** (ouverte à la main ou par un autre outil) : jamais touchée. Si une limite est atteinte alors qu'il
     en reste, le Guardian le **signale** (alerte), il ne la ferme pas.
3. **Mêmes voies que tout le reste.** Chaque fermeture est un `ExecutionRequest` (`CLOSE` / `CANCEL`) soumis à `ExecutionService.submit` :
   même validation, même routage par mode, même trace, même idempotence (`gd-<règle>-<position>-<n>`, au plus 5 tentatives, une
   pause de 60 s entre deux — `services/attempts.py`, partagé avec le Position Manager). Il n'ouvre rien et ne contourne rien.
4. **Selon le mode.** OFF et HALTED : rien (un système arrêté ne ferme pas de lui-même ; le kill switch de l'agent garde ses stops au
   courtier). OBSERVE et PAPER : le verdict est calculé et **montré**, aucune commande n'est créée. CONFIRM, ARMED, AUTONOMOUS : les
   commandes sont créées (en CONFIRM, elles attendent le geste humain, comme toute commande).
5. **Reprise après panne.** Au premier cycle d'un compte après le démarrage du cœur, le Guardian écrit un constat de reprise (positions
   du cœur trouvées, sans stop, ordres en attente, commandes douteuses) lisible sur `GET /api/guardian` ; les positions sans stop suivent
   ensuite la règle ci-dessus. Les commandes `UNKNOWN` restent le travail de la réconciliation (ADR 0010), pas le sien.
6. **Il ne coupe pas le système, sauf en dernier recours.** Un `halt` refuserait ses propres fermetures (`HALTED`) : la limite atteinte verrouille déjà les
   entrées par le Risk Engine. Mais le plan (§9) veut qu'il puisse passer le système en `HALTED` : il le fait **une seule fois**, quand une sortie protectrice
   (fermer une position, annuler un ordre) a été refusée cinq fois — le système cesse alors de courir un risque nouveau et appelle un humain.
7. **Les ordres en attente sont retirés dès qu'une limite est atteinte**, qu'une position soit ouverte ou non (plan, §6.5) — un défaut de la première version
   ne les retirait qu'avec une position.

## Ce que cet ADR ne fait pas

- Il ne choisit pas de seuil avant la limite à la place de l'utilisateur, et ne ferme pas ce qu'il n'a pas ouvert.
- Il n'ajoute pas de seizième contrôle d'autonomie : son état est lu sur `GET /api/guardian` et dans « Pourquoi pas de trade ? » (phase 7).
- Il ne dit rien de la marge : le niveau de marge n'est pas dans le modèle de compte du cœur.
- Il ne change pas ce que fait un système `HALTED` : l'ExecutionService refuse **toute** commande en `HALTED`, fermetures comprises
  (`HALTED` dans `validation.py`, règle antérieure), et l'agent en fait autant avec son arrêt local. Un compte arrêté avec une position
  ouverte n'est donc pas fermé par le Guardian ; ses stops restent chez le courtier. Autoriser les sorties seules pendant un arrêt
  change le sens du kill switch : c'est une décision de l'utilisateur, à prendre dans son propre ADR.
- Constat de test : un stop retiré chez le courtier sous un mode automatique fait déjà arrêter le système par la réconciliation
  (`POSITION_MISMATCH`). Le Guardian couvre donc surtout CONFIRM et le délai qui précède cet arrêt.

## Conséquences

- Tests : règles pures (limite atteinte, fraction, stop manquant et délai de grâce, positions externes), service (fermeture des seules
  positions du cœur, annulation des ordres du cœur, aucune commande en OBSERVE, aucune répétition, constat de reprise).
- Types TypeScript régénérés (`GuardianReport`).
