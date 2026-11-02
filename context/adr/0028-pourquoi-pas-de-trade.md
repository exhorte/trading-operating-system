# ADR 0028 — « Pourquoi pas de trade ? » : une seule réponse lisible, assemblée à partir de ce que le cœur sait (phase 7)

Date : 2026-11-01. Statut : **accepté** — mission « Trading OS autonome » du 2026-11-01 (phase 7 : « opportunités, raisons de blocage
(WHY NO TRADE ?), état de l'autonomie »), confirmée le 2026-11-01. **Ne décide rien** : lecture seule (ADR 0005).

## Contexte

Quand rien ne se passe, la raison est éparpillée : le mode d'autonomie, les 16 contrôles de préparation, les portes du Risk Engine, l'étape où
la stratégie s'est arrêtée, le Guardian. Les écrans les montrent chacun de leur côté ; la question que l'utilisateur se pose est une seule :
*pourquoi le système ne prend-il pas de trade en ce moment ?*

## Décision

1. **Une fonction pure** (`domain/autonomy/why.py`) prend l'état déjà calculé ailleurs — mode et plafond, préparation, état du Risk Engine,
   dernières évaluations des stratégies, rapport du Guardian — et rend une `WhyNoTrade` : un titre d'une phrase, la liste ordonnée des
   raisons (source, code, détail, bloquante ou non), les opportunités récentes et la dernière évaluation de chaque stratégie. Elle ne
   calcule aucune règle nouvelle : elle **range** les raisons que les composants ont déjà énoncées, avec leurs mots.
2. **Ordre de lecture** : l'état du système (arrêté, observation seulement…), puis le Guardian, puis les portes du Risk Engine fermées,
   puis la préparation, puis l'étape où chaque stratégie s'est arrêtée. Le titre est la première raison bloquante ; sans raison bloquante,
   c'est l'opportunité en cours ; sans opportunité, « rien ne bloque, en attente d'un setup » avec la dernière étape atteinte.
3. **`GET /api/why-no-trade`** (service `WhyNoTradeService`, lecture seule) et un **panneau du cockpit** « Pourquoi pas de trade ? » sur le
   tableau de bord, mis à jour avec le flux existant. Le panneau n'ajoute aucune action : pas de bouton qui contourne une raison.
4. **Un mode qui n'envoie rien n'est pas une panne** : OBSERVE et PAPER sont listés comme raison *bloquante pour un ordre réel*, formulée
   comme un état (« mode OBSERVE : le cœur évalue et enregistre, aucun ordre ne part »), pas comme une erreur.

## Ce que cet ADR ne fait pas

- Il ne propose pas de « forcer » une raison, ni de raccourci vers un réglage. L'IA n'intervient pas.
- Il ne remplace pas les écrans de détail (Risque, Setups, Pré-vol) : il y renvoie par les codes qu'il affiche.

## Conséquences

- Tests : chaque source de raison, l'ordre, le titre selon les cas, la fenêtre des opportunités, la route, et le rendu du panneau.
- Types TypeScript régénérés.
