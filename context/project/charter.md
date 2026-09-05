# Charte du projet

Version 2 — 2026-09-04. Remplace `development_manifesto.md` et `project_state.md` (série 1, supprimés le 2026-09-04, récupérables au tag `archive/pre-pivot-2026-09-04`).

## Ce que ce projet est

Un **poste de travail personnel pour trader intraday**. Un logiciel qui automatise, mesure et fait respecter le process de son unique utilisateur.

Le produit, c'est le **process**. Pas le signal.

## Ce que ce projet n'est plus

La série 1 du projet (juillet 2026, phases 00 à 13) cherchait un edge : moteur d'analyse ICT/SMC, déclencheur d'entrée, backtester, splits train/validation/OOS, holdout vierge, verdict statistique.

**Cette recherche est close, sans verdict, par décision du 2026-09-04.** Le holdout ne sera pas lu. Le candidat `CANDIDATE_CONFIG_2026_07_18` est abandonné. `lib/backtest/`, `lib/strategy/`, les scripts de backtest et les 24 fiches de phase ont été supprimés.

La raison est écrite dans l'audit du 2026-09-03 et n'a pas changé : le candidat NY AM a été sélectionné post-hoc puis « validé » en reproduisant le même sous-ensemble. Le seul jeu vierge restant était le holdout, lisible une seule fois. Plutôt que dépenser deux jours à obtenir un verdict qui, quel qu'il soit, ne changeait pas la suite du projet, la suite du projet commence maintenant.

**Conséquence à assumer : ce projet ne contient plus aucune prétention de performance.** Aucun module ne dit quoi trader, quand, ni dans quel sens.

## Les quatre goulots que ce projet attaque

| Goulot | Ce que la plateforme doit faire |
|---|---|
| Préparation pré-séance | Assembler le contexte de la journée sans intervention : niveaux, sessions, publications, état des comptes. |
| Exécution & discipline | Rendre impossible — ou coûteux — de violer ses propres règles en séance. |
| Revue & journal | Enregistrer chaque trade et son contexte sans une seule saisie manuelle. |
| Admin prop firm | Connaître à tout instant sa marge de manœuvre réglementaire par compte. |

## Principes

### Produit

1. **Le process avant le signal.** Un outil qui supprime une violation de règle est un gain certain ; un outil qui améliore un signal est un pari.
2. **Le KPI est le taux de conformité au plan**, pas le P&L. Le P&L sur 20 trades est du bruit ; le respect du process ne l'est pas.
3. **Zéro saisie manuelle.** Tout ce qui demande dix minutes par soir sera abandonné en trois semaines.
4. **Ne pas reconstruire MT5.** MT5 affiche déjà les prix mieux que nous. On construit ce qu'il ne fait pas : le process, les règles, l'historique.

### Trading

5. **L'EA n'est pas le cerveau.** MT5 est un point d'exécution et de télémétrie.
6. **Aucune décision automatique.** Aucun ordre n'est envoyé sans qu'un humain l'ait déclenché.
7. Pas de martingale, pas de grille de récupération, pas de moyenne à la baisse illimitée.
8. Toute position a un risque explicite, une invalidation, un stop et une trace d'audit.

### Ingénierie

9. **Le Risk Engine est le point de contrôle unique.** Un refus est une `RiskDecision` refusée sur le chemin `RiskDecision → Command → ACK → Report`, jamais un bouton grisé.
10. Domaine pur, testé, sans dépendance à l'UI ni au broker.
11. Monolithe modulaire. Extraction de services seulement si opérationnellement justifiée.
12. Temps réel modélisé en événements, commandes, acquittements et rapports — pas en appels HTTP ad hoc.
13. **L'IA reste en lecture.** Classer, résumer, retrouver, expliquer *a posteriori*. Jamais décider, jamais ordonner.
14. La documentation est la mémoire du projet, pas de la décoration.

## Portée

**Usage strictement personnel.** Aucune distribution, aucune vente, aucun utilisateur tiers. Cette contrainte est un choix, et elle simplifie : pas de multi-tenant, pas d'authentification tierce, pas de conformité produit, pas de support.

## Sécurité

Un logiciel de trading peut causer des pertes financières. Aucune logique non testée n'est présentée comme rentable. Tout objectif de performance est une hypothèse.
