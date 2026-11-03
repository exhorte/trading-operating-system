# ADR 0027 — Critères de passage de chaque mode d'autonomie : mesurés, affichés, jamais imposés (phase 6)

Date : 2026-11-01. Statut : **accepté** — mission « Trading OS autonome » du 2026-11-01 (phase 6 : « critères de passage de chaque mode »),
confirmée le 2026-11-01. **Complète l'ADR 0014/0015** (l'échelle et la préparation en 16 contrôles existent) **sans en changer les
règles de montée** : une montée reste un geste humain, d'un cran, plafonné, avec une préparation verte pour les crans automatiques.

## Contexte

L'échelle `OFF → OBSERVE → PAPER → CONFIRM → ARMED → AUTONOMOUS` et la préparation (16 contrôles de l'état du système) disent *si le système est
en état de monter*. Rien ne dit *si l'expérience accumulée le justifie* : combien de séances évaluées, combien d'ordres simulés puis
confirmés, quelle validation chiffrée. Sans critère écrit, la montée se décide à l'humeur — ce que le projet cherche à éviter.

## Décision

1. **Un rapport de passage par cran** (`domain/autonomy/promotion.py`, `GET /api/autonomy/promotion`) : pour chaque montée possible, la liste
   des critères, chacun *rempli*, *non rempli* ou *non mesuré* (un critère non mesuré ne compte jamais comme rempli), avec la preuve chiffrée.
2. **Les critères sont des critères de processus, pas de rentabilité.** Aucun ne dit « le P&L est positif » : un gain passé ne prouve rien (ADR 0026).
   Les seuils sont **posés** (`PromotionPlan`), à relire et à écrire par l'utilisateur :
   - `OBSERVE → PAPER` : limites écrites par l'utilisateur ; S01 évaluée sur au moins 5 jours de trading ; aucun incident critique ouvert ;
   - `PAPER → CONFIRM` : limites écrites ; au moins 20 ordres simulés par le chemin complet ; aucune commande en doute ; préparation verte ;
   - `CONFIRM → ARMED` : au moins 20 ordres exécutés sous CONFIRM ; aucune commande en doute ; une validation (ADR 0026) d'au moins 100
     trades dont la probabilité d'atteindre la limite totale (Monte Carlo) ne dépasse pas 5 % ; préparation verte ;
   - `ARMED → AUTONOMOUS` : au moins 5 jours en ARMED sans arrêt d'urgence — **non mesuré aujourd'hui** (l'historique des transitions n'est pas
     lu par ce rapport) : le cran reste donc « non rempli ».
3. **Consultatif.** Le rapport n'empêche rien : `arm` continue d'appliquer ses règles actuelles. Le rendre contraignant est un choix de
   l'utilisateur, à prendre dans son propre ADR quand il aura vu le rapport tourner. Un seuil que personne n'a relu ne doit pas bloquer une
   montée à sa place.
4. **Les preuves viennent des enregistrements du cœur** (évaluations de stratégie, commandes d'exécution et leur état, incidents, préparation,
   rapports de validation `exports/validation/*.json`) — jamais d'une saisie.

## Ce que cet ADR ne fait pas

- Il ne monte aucun cran et n'abaisse aucun plafond. Il ne change pas `TRADING_MODE`.
- Il ne définit pas ce qu'est un « bon » résultat : seulement ce qu'il faut avoir *fait et mesuré* avant de demander plus de confiance.

## Conséquences

- Tests : chaque critère (rempli, non rempli, non mesuré), le cran courant, le rapport sans validation, la lecture des rapports de validation.
- Types TypeScript régénérés.
