# Instructions Claude

Ce dépôt est un **poste de travail personnel pour trader intraday**. Ce n'est pas un EA, pas un bot, pas un backtester.

## Avant toute implémentation

1. Lire `AGENTS.md` et garder l'avertissement Next.js actif.
2. Lire `context/project/charter.md` — ce que le projet est et ce qu'il n'est plus.
3. Lire `context/project/state.md` — instantané de ce qui existe et la prochaine action.
4. Lire `context/project/session-log.md` — ce qui s'est passé dans les dernières sessions (ADR 0008 ; ne pas confondre avec `state.md`, qui ne raconte rien).
5. Lire `context/adr/` en entier. Huit ADR courts ; ils tranchent la plupart des questions.
6. Lire la fiche de l'outil en cours dans `context/product/tools/`.
7. Lire les documents de domaine, d'architecture et d'ingénierie pertinents **avant** de toucher au code.

## Direction non négociable

- **Le process est le produit, pas le signal.** Aucun module ne dit quoi trader, quand, ni dans quel sens (ADR 0001).
- **La recherche d'edge est close** (ADR 0002). Ne pas proposer de backtester, d'optimiseur, de générateur de signaux, ni de « juste tester rapidement une idée ». `lib/analysis/` fournit du contexte, pas des signaux.
- **L'EA n'est pas le cerveau.** MT5 est un point d'exécution et de télémétrie.
- **Le Risk Engine est le point de contrôle unique** (ADR 0007). Toute règle passe par une gate testée, jamais par un bouton grisé.
- **L'IA reste en lecture** (ADR 0005). Classer, résumer, retrouver, expliquer. Jamais décider, jamais ordonner.
- Aucun appel de trade n'existe dans ce dépôt. Le mode `observe` / SIMULATED est le seul chemin implémenté.
- Pas de martingale, pas de grille, pas de moyenne à la baisse.
- Aucun identifiant de compte n'est jamais demandé, stocké ou partagé.

## Mode de travail

Agir en ingénieur principal :

1. Lire le contexte d'abord.
2. Analyser l'impact.
3. Concevoir avant de coder pour tout travail non trivial.
4. Implémenter par incréments qui gardent les gates vertes.
5. Vérifier — `context/governance/quality_gates.md`.
6. Mettre à jour la fiche d'outil, `session-log.md` (une entrée courte, ADR 0008), et si nécessaire `state.md` (instantané seulement, jamais de récit qui s'accumule) et les ADR.

Le cycle complet est décrit dans `context/workflows/development_workflow.md`. Commandes : `/outil-start Tnn`, `/outil-close Tnn`.

## Piège le plus fréquent dans ce dépôt

Réécrire du code qui existe déjà. `lib/risk/`, `lib/analysis/`, `lib/domain/`, `lib/contracts/` et toute la chaîne temps réel sont écrits, testés et **validés en live**. Les fiches d'outil nomment les fichiers d'ancrage : les lire avant de créer quoi que ce soit.

## Sécurité

Un logiciel de trading peut causer des pertes financières. Ne jamais présenter une logique non testée comme rentable. Tout objectif de performance est une hypothèse.
