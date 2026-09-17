# Fiches d'outil

Une fiche par outil. C'est l'unité de travail du projet (ADR 0006) : elle remplace le couple « document de design + fiche de phase » de la série 1.

La fiche est écrite **avant** de coder, complétée **pendant**, close **après**. Elle porte tout : le problème, le comportement attendu, les points d'ancrage dans le code existant, le critère de réussite, et le journal des décisions prises en route.

**Statuts** : `à faire` · `en cours` · `livré` · `abandonné` · `retiré`.
`abandonné` = jamais fini ; `retiré` = livré, validé, puis sorti du dépôt par
décision explicite — la distinction compte pour ne pas relire un retrait
volontaire comme un échec.

| Fiche | Outil | Vague | Statut |
|---|---|---|---|
| T01 | Calculateur de taille one-click | 1 | retiré (2026-09-14) |
| T02 | Lockout comportemental | 1 | livré |
| T03 | Gate calendrier économique | 1 | livré |
| T04 | Ticket pré-trade | 1 | retiré (2026-09-14) |
| T05 | Captures automatiques entrée/sortie | 1 | livré |
| T06 | Journal auto-alimenté, zéro saisie | 2 | livré (4 incréments, 2026-09-16 — vérifié contre les vrais trades du 2026-09-14/15 ; rendu navigateur jamais vu, aucun agent MT5 connecté à cette session) |
| T07 | Tracker d'erreurs et taux de conformité | 2 | livré (4 incréments, 2026-09-16 — lockout + fenêtre de session + taille, stop déplacé reporté ; rendu navigateur jamais vu, aucun agent MT5 connecté à cette session) |
| T15 | Serveur MCP « mon trading » (lecture seule) | 2 | livré (4 incréments, 2026-09-17 — vérifié par un vrai handshake MCP contre des données réelles ; a révélé un second incident de lockout contourné, voir `state.md`) |
| T08 | Revue hebdomadaire générée | 2 | livré (3 incréments, 2026-09-17 — vérifié contre les vraies données du 2026-09-14/15, document Markdown inspecté) |
| S01 | Stratégie « Sweep aligné » | EA | à faire |
| EA-01 | Détection S01, en TypeScript pur | EA | livré |
| EA-02 | Mode OBSERVE et taux d'accord | EA | livré (code) |
| EA-03 | Protocole d'exécution et machine à états | EA | livré |
| EA-04 | Profils de compte, modèle de coût, registre de symboles | EA | livré |
| EA-05 | Agent MQL5 | EA | livré (incrément 6 inclus, 2026-09-15 — `OrderSend` écrit, inatteignable hors `CONFIRM`, jamais exécuté) |
| EA-06 | Réconciliation (`UNKNOWN`, positions externes) | EA | livré (4 incréments, 2026-09-16 — le scan de positions externes tourne déjà en réel ; la résolution `UNKNOWN` reste sans trafic tant qu'`OrderSend` est inatteignable) |

Les outils T06 à T19 sont décrits dans `../backlog.md`. Leur fiche est créée au moment de les démarrer, pas avant — une fiche écrite trois mois trop tôt décrit un problème qui a changé.

La série **S** porte les stratégies. Une stratégie n'est pas un outil du cockpit, mais elle suit la même discipline : écrite avant de coder, complétée pendant, close après. La série **EA** portera les fiches de l'agent d'exécution MT5 (ADR 0010).
