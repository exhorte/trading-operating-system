# Workflow de développement

Version 2 — 2026-09-04. L'unité de travail est l'outil, pas la phase (ADR 0006).

## Cycle d'un outil

1. **Ouvrir la fiche** — `context/product/tools/Tnn-*.md`. Si elle n'existe pas, l'écrire d'abord : problème, comportement attendu, ancrage dans le code, critère de réussite. Passer le statut à `en cours`.
2. **Lire le code d'ancrage** avant d'écrire quoi que ce soit. Les fiches nomment les fichiers existants ; ils sont presque toujours plus complets qu'attendu, et les réécrire est le piège classique de ce dépôt.
3. **Implémenter par incréments**, en gardant les gates vertes à chaque étape.
4. **Vérifier** — voir `context/governance/quality_gates.md`.
5. **Clore la fiche** — statut `livré`, journal complété avec les décisions réellement prises et ce qui a été écarté. Si le critère de réussite n'est pas atteint, la fiche reste ouverte.

Un travail qui ne rentre pas dans une fiche est soit une correction de bug (commit direct), soit une décision d'architecture (nouvel ADR).

## Règle de conception temps réel

Pour tout ce qui touche aux données de marché, à l'état live, à l'exécution, à l'observer MT5 ou aux alertes de risque, la conception du flux précède l'implémentation :

- propriétaire de la connexion ;
- topic d'abonnement ;
- snapshot initial ;
- types d'événements ;
- cycle commande / acquittement / rapport ;
- comportement de reconnexion et de resynchronisation ;
- états d'échec.

## Règle de risque

Toute règle que l'utilisateur veut s'imposer passe par le Risk Engine, jamais par l'interface (ADR 0007). Une gate se teste en unitaire comme fonction pure avant d'être branchée.

## Discipline documentaire

La documentation est la mémoire du projet. Concrètement, une seule obligation : **chaque outil livré laisse le dépôt plus lisible pour la session suivante** que celle qui l'a construit.

Il n'y a plus ni changelog quotidien, ni fiche de handoff : l'historique git, le statut des fiches et `context/project/state.md` suffisent. `state.md` se met à jour à la fin de chaque vague, ou dès qu'un fait qu'il énonce devient faux.
