# ADR 0002 — Fin de la recherche d'edge

Date : 2026-09-04. Statut : accepté. Rend caducs les anciens ADR 0006, 0012 et 0013.

## Contexte

Entre juillet 2026 et le 28 juillet 2026, le projet a construit un moteur d'analyse ICT/SMC, un déclencheur d'entrée FVG-retest, un backtester avec splits chronologiques, un verrou OOS, un profil de coûts et une machinerie de verdict sur holdout vierge.

Résultat honnête consigné à l'époque : le moteur v0.1 n'a pas d'edge ; le candidat NY AM a été **sélectionné post-hoc** puis « validé » en reproduisant le même sous-ensemble — les données de développement sont consommées. Le seul jeu vierge restant était le holdout, lisible une seule fois.

Fermer la Phase 13 demandait encore 1 à 2 jours : troisième session de ticks NY AM, calibration du spread, gel du SwapSpec, puis lecture unique.

## Décision

**La recherche d'edge est abandonnée. Le holdout ne sera pas lu.**

Le raisonnement : le verdict attendu était un FAIL ou un INCONCLUSIVE, et dans les deux cas la suite du projet était identique. Deux jours de travail pour un résultat sans conséquence sur la décision suivante ne se justifient pas.

Le code correspondant est supprimé, pas mis en commentaire ni derrière un drapeau.

## Conséquences

- `lib/backtest/`, `lib/strategy/`, les scripts de backtest, les tables `backtest_*` et `holdout_*` et l'endpoint `/api/backtests` disparaissent du dépôt.
- Le holdout `2024-06-01T00:00Z → 2025-06-06T13:30Z` n'a plus de statut particulier ; c'est de la donnée comme une autre.
- `lib/analysis/` survit **en tant que fournisseur de contexte** (ADR 0001), pas en tant que moteur de signal.
- Si un jour une recherche d'edge reprend, elle repart d'un dépôt neuf et d'un jeu de données neuf. Rien de l'ancien dispositif n'est réutilisable comme validation.
