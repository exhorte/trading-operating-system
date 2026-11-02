# ADR 0031 — N8 « Drawdown Flatlining » : un plafond qui ne fait que baisser le risque, par pas de 0,1 %

Date : 2026-11-01. Statut : **accepté** — décision d'Exhorte du 2026-11-01 (« 0,1 % est l'unité minimale de granularité ; ce n'est pas un risque minimum obligatoire : le
système peut réduire le risque autorisé à 0 %, ce qui bloque le nouveau trade ; N8 peut réduire, jamais augmenter ; la grille déjà définie reste prioritaire ; le risque
final est le plus faible de tous les plafonds ; ne pas inventer ce que les sources ne définissent pas — rendre configurable et documenter »). **Étend l'ADR 0019** (un plafond de plus).

## Décision

1. **N8 est un plafond de plus** dans le minimum de `resolve_risk_allowance` (`extra_caps`, code `n8_flatlining`). Il ne produit jamais de valeur propre ni de hausse : la grille, le
   plafond du profil, le déclencheur de 200 $ et les budgets de perte jour/semaine/total continuent de décider, et le plus bas gagne. À égalité, la grille garde la mention.
2. **Granularité 0,1 %.** Les valeurs de N8 sont des multiples entiers de 0,1 % (`percent_to_units`, entiers : 3 unités = 0,3 % exactement). Une valeur entre deux unités est
   **refusée** au démarrage, jamais arrondie. La plus petite unité peut valoir **0** : un plafond à 0 % bloque le prochain trade (`risk_budget_exhausted`, `binding_cap = n8_flatlining`).
3. **Déclencheurs construits — ceux que la note N8 (§j, §l) chiffre, et qui ne font que réduire** : (a) une perte → plafond à la plus petite unité jusqu'à ce qu'un trade gagne ;
   (b) 5 gains consécutifs → le 6ᵉ trade à la plus petite unité, puis le compteur repart à zéro (Win Set Cycle) ; (c) équité sous le capital de départ → plus petite unité. Chacun
   se coupe séparément. Un trade à résultat nul n'est ni un gain ni une perte. Historique illisible (base indisponible) → la plus petite unité s'applique, jamais une hypothèse de plus de risque.
4. **Réglage** (`.env`, désactivé par défaut) : `RISK_N8_ENABLED=false`, `RISK_N8_MINIMUM_PERCENT` (vide), `RISK_N8_REDUCE_AFTER_LOSS=true`, `RISK_N8_WINS_BEFORE_MINIMUM=5` (0 = coupé),
   `RISK_N8_REDUCE_BELOW_STARTING_EQUITY=true`. **Tant que `RISK_N8_MINIMUM_PERCENT` n'est pas écrit, N8 ne fait rien** (état `unconfigured`, un avertissement au démarrage).

## Point restant avant l'activation (à trancher par Exhorte — rien n'est inventé)

- **La valeur de « la plus petite unité »** : la note dit qu'elle « dépend du confort ». À écrire dans `RISK_N8_MINIMUM_PERCENT` (multiple de 0,1 ; 0 = bloquer).
- **Non construits, faute de règle dans les sources** : la **montée par palier** (« gain avec solde supérieur au dépôt initial → un palier de plus » : elle augmenterait un risque, et la taille du palier
  n'est pas donnée — le plafond reste la grille) ; le **Soft Start** (« session » non définie). La fenêtre de comptage du cycle de gains est bornée aux 50 derniers trades clôturés.

## Conséquences

Tests : `tests/unit/domain/risk/test_n8.py` (granularité, inertie, déclencheurs, « ne fait que baisser », budgets non contournés, zéro = blocage) et deux tests de service dans
`test_risk_service.py`. Aucune migration, aucun changement d'API ni de types générés.
