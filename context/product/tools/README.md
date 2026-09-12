# Fiches d'outil

Une fiche par outil. C'est l'unité de travail du projet (ADR 0006) : elle remplace le couple « document de design + fiche de phase » de la série 1.

La fiche est écrite **avant** de coder, complétée **pendant**, close **après**. Elle porte tout : le problème, le comportement attendu, les points d'ancrage dans le code existant, le critère de réussite, et le journal des décisions prises en route.

**Statuts** : `à faire` · `en cours` · `livré` · `abandonné`.

| Fiche | Outil | Vague | Statut |
|---|---|---|---|
| T01 | Calculateur de taille one-click | 1 | livré |
| T02 | Lockout comportemental | 1 | livré |
| T03 | Gate calendrier économique | 1 | livré |
| T04 | Ticket pré-trade | 1 | livré |
| T05 | Captures automatiques entrée/sortie | 1 | livré |
| S01 | Stratégie « Sweep aligné » | EA | à faire |

Les outils T06 à T19 sont décrits dans `../backlog.md`. Leur fiche est créée au moment de les démarrer, pas avant — une fiche écrite trois mois trop tôt décrit un problème qui a changé.

La série **S** porte les stratégies. Une stratégie n'est pas un outil du cockpit, mais elle suit la même discipline : écrite avant de coder, complétée pendant, close après. La série **EA** portera les fiches de l'agent d'exécution MT5 (ADR 0010).
