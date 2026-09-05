# ADR 0006 — Gouvernance par outils et vagues

Date : 2026-09-04. Statut : accepté. Remplace la gouvernance par phases numérotées de la série 1.

## Contexte

La série 1 travaillait par phases : une phase = un document de design validé, une implémentation, des gates, une clôture écrite. Le dispositif était rigoureux et a produit une documentation exacte — mais calibré pour des lots de une à deux semaines, avec un coût fixe de plusieurs heures de rédaction par phase.

La nouvelle roadmap est faite de lots de 0,5 à 3 jours. Le coût fixe d'une phase dépasserait celui du travail.

## Décision

L'unité de travail est **l'outil**, identifié `Tnn`, décrit par une fiche unique dans `context/product/tools/`. Les outils sont groupés en **vagues** dans `context/project/roadmap.md`.

La fiche d'outil porte tout le cycle de vie : problème, comportement attendu, points d'ancrage dans le code, effort, dépendances, critère de réussite, décisions prises pendant la construction, et statut. Elle est écrite avant, complétée pendant, close après. Il n'y a pas de document de design séparé.

Commandes : `/outil-start Tnn` et `/outil-close Tnn` (voir `.claude/commands/`).

Les statuts sont : `à faire`, `en cours`, `livré`, `abandonné`.

## Conséquences

- `context/project/phases/` n'existe plus.
- Le changelog quotidien n'existe plus : l'historique git et le statut des fiches suffisent.
- Un travail qui ne rentre pas dans une fiche d'outil est soit une correction de bug (commit direct), soit une décision d'architecture (ADR).
- Une vague se clôt sur un critère observable, pas sur une date.
