# ADR 0032 — Account Guardian complet : surveiller spread, glissement et santé ; demander une réconciliation (plan §9)

Date : 2026-11-02. Statut : **accepté** — Exhorte, le 2026-11-02 (« Oui, le Guardian » : incrément E du plan de reprise). **Étend l'ADR 0025** ; ne change ni les trois règles de sortie de
l'ADR 0025, ni le Risk Engine (seul point de contrôle des *entrées*, ADR 0007), ni le sort de `HALTED`.

## Contexte

Le plan (§9) fait surveiller au Guardian, en plus des limites de perte : le spread, le glissement, la connexion MT5, la santé de l'agent et du courtier, l'état du système, le nombre de positions,
l'exposition par symbole, et lui donne le pouvoir d'autoriser ou bloquer, annuler les ordres en attente, alerter, **demander une réconciliation** et passer le système en `HALTED`. L'ADR 0025 en
faisait trois règles de sortie plus le `HALTED` de dernier recours ; ni spread, ni glissement, ni santé, ni réconciliation n'étaient regardés.

## Décision

1. **Il observe** (`domain/guardian/watch.py`, pur ; `GuardianReport.watch`, lisible sur `GET /api/guardian`) : équité, solde, usage des trois limites de perte, risque ouvert, nombre de positions et de
   trades du jour, **exposition par symbole** (lots longs et courts, ordres en attente — **rapportée, jamais limitée** : la limite par symbole a été retirée, ADR 0022), **spread** de chaque symbole où le
   cœur est exposé, **glissement** de chaque position ouverte par un ordre `LIMIT`, **santé** (terminal MT5, flux de cotations, agent d'exécution, courtier, réconciliation, état du système) et **« une
   nouvelle entrée serait-elle autorisée ? »** (lu sur le Risk Engine, avec les portes qui la bloquent — dit, jamais décidé ici).
2. **Aucun seuil n'est inventé.** Le spread est jugé contre le plafond **que l'utilisateur a écrit** pour le symbole (`max_spread_by_symbol`) ; un symbole sans plafond est *lu*, pas jugé. Le glissement
   défavorable est comparé au **seuil de coût du compte** (`cost_threshold`, 0,25 : la part du risque d'un trade que les coûts peuvent manger — la propre limite de l'utilisateur) ; un ordre au
   marché ne nomme aucun prix de référence, son glissement est borné à l'agent (`deviation`) et n'est pas mesuré ici.
3. **Alertes** (phrases du verdict, donc dans « Pourquoi pas de trade ? » comme alertes non bloquantes) : spread au-dessus du plafond pendant que le cœur y est exposé ; glissement au-dessus du seuil ;
   et, **seulement tant que quelque chose est exposé**, toute composante de santé en défaut (sans exposition, les portes du Risk Engine et le rapport de préparation le disent déjà).
4. **Une sortie de plus, désactivée par défaut** : `GUARDIAN_CANCEL_ORDERS_ON_WIDE_SPREAD=true` fait annuler les ordres en attente **du cœur** sur un symbole dont le spread dépasse le plafond de l'utilisateur
   (une commande `CANCEL` ordinaire, `gd-cancel-spread-<ordre>-<n>`, par `ExecutionService.submit`). Une **position** n'est jamais fermée pour un spread : fermer dans un spread large coûte cher et son stop
   est chez le courtier. Nouvelle conduite automatique ⇒ c'est un geste de l'utilisateur de l'allumer.
5. **Il demande une réconciliation** (`ReconciliationService.reconcile`, lecture seule vis-à-vis du courtier) quand seule une comparaison avec le courtier peut trancher : une commande en `UNKNOWN` ou
   `RECONCILING`, des passes de réconciliation qui n'ont pas pu lire le courtier, un agent qui s'est reconnecté (ce qu'il a fait pendant son absence est inconnu), une sortie protectrice refusée pour de
   bon. Au plus **une fois par minute** et par compte ; la dernière demande et sa raison sont dans le rapport (`reconciliation_asked`, `reconciliation_asked_at`).
6. **Ce qui ne change pas** : les trois règles de sortie de l'ADR 0025 (limite atteinte, position du cœur sans stop passé 30 s, positions externes jamais touchées) ; le `HALTED` de dernier recours après
   cinq refus d'une sortie protectrice ; le comportement par mode (OFF et HALTED : rien ; OBSERVE et PAPER : montré, aucune commande ; CONFIRM, ARMED, AUTONOMOUS : commandes créées) ; le fait que le
   Guardian **n'ouvre rien, n'élargit rien** (un test vérifie que tout ce qu'il envoie est `execution.close` ou `execution.cancel`).

## Point restant — **tranché le 2026-11-02 : « Laisser passer » (ADR 0033)**

**Un système `HALTED` refuse toute commande, fermetures comprises** (`validation.py`, et l'arrêt local de l'agent) : un compte arrêté avec une position ouverte n'est pas fermé, ses stops restent chez le
courtier. Autoriser les **sorties seules** pendant un arrêt change le sens du kill switch (ADR 0025, « ce que cet ADR ne fait pas ») : ce n'est pas une décision à prendre à la place de l'utilisateur.
Question à lui poser : *« Un arrêt (`HALTED`) doit-il laisser passer les fermetures et les annulations, ou tout refuser comme aujourd'hui ? »* — sa réponse appelle un ADR à part, côté cœur et côté agent.

## Ce que cet ADR ne fait pas

- Il ne mesure pas la marge (absente du modèle de compte du cœur) ni le glissement des ordres au marché ; il ne juge pas un spread sans plafond écrit ; il n'ajoute pas de seizième contrôle d'autonomie.
- Il ne bloque ni n'autorise les entrées : il lit ce que le Risk Engine répond.

## Conséquences

- Tests : `tests/unit/domain/test_guardian_watch.py` (spread jugé contre le plafond de l'utilisateur seulement, glissement défavorable seulement et part du risque, exposition rapportée, alertes, raisons de
  réconciliation) ; `tests/unit/services/test_guardian_service.py` (rapport écrit à chaque cycle, entrées autorisées ou non dites sans agir, alerte de spread et **rien d'annulé par défaut**, annulation
  des seuls ordres du cœur avec l'option, jamais de fermeture pour un spread, glissement, santé seulement si exposé, réconciliation demandée au plus une fois par minute et à la reconnexion de l'agent,
  rien d'autre que `CLOSE` / `CANCEL` envoyé).
- Types TypeScript régénérés (`GuardianReport.watch`, `reconciliationAsked`).
