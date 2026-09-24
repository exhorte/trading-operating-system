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
| T02 | Lockout comportemental | 1 | livré (T02a/T02b 2026-09-05 ; **T02c 2026-09-17** — alerte temps réel dès qu'une position s'ouvre pendant un verrou actif, accusé de réception obligatoire pour lever tout verrou non chronométré ; le chemin Gateway de l'alerte n'a jamais été exercé en réel) |
| T03 | Gate calendrier économique | 1 | livré |
| T04 | Ticket pré-trade | 1 | retiré (2026-09-14) |
| T05 | Captures automatiques entrée/sortie | 1 | livré |
| T06 | Journal auto-alimenté, zéro saisie | 2 | livré (4 incréments, 2026-09-16 — vérifié contre les vrais trades du 2026-09-14/15 ; rendu navigateur jamais vu, aucun agent MT5 connecté à cette session) |
| T07 | Tracker d'erreurs et taux de conformité | 2 | livré (4 incréments, 2026-09-16 — lockout + fenêtre de session + taille, stop déplacé reporté ; rendu navigateur jamais vu, aucun agent MT5 connecté à cette session) |
| T15 | Serveur MCP « mon trading » (lecture seule) | 2 | livré (4 incréments, 2026-09-17 — vérifié par un vrai handshake MCP contre des données réelles ; a révélé un second incident de lockout contourné, voir `state.md`) |
| T08 | Revue hebdomadaire générée | 2 | livré (3 incréments, 2026-09-17 — vérifié contre les vraies données du 2026-09-14/15, document Markdown inspecté) |
| T09 | Checklist de pré-vol exécutable | 3 | livré (3 incréments, 2026-09-17 — `/preflight`, gate de connexion ajouté ; **premier rendu vérifié à l'écran depuis T05**, via le mode `mock` ; **le mock masquait un bug, corrigé le 2026-09-18** : le gate de connexion lisait l'observer et non l'agent d'exécution, vu en vérifiant contre le vrai backend) |
| T12 | Prop Firm Control Center | 3 | en cours — incrément 1 « un compte à la fois » livré le 2026-09-21 (profil FTMO/Exness détecté par le nom du broker, perte max mesurée depuis la taille du challenge, objectifs MetriX ; vérifié contre le verdict réel de FTMO sur le challenge 511333949) ; **incrément 2 livré le 2026-09-23** : écrans Account et Settings, registre de paramètres avec verrou anti-tilt décidé côté backend, `scripts/start-live.ps1` — vérifié en réel (écriture, report, annulation, diffusion entre onglets) ; chemin « appliqué tout de suite » vu seulement en tests (MT5 fermé) ; multi-compte simultané = T11, non commencé |
| S01 | Stratégie « Sweep aligné » | EA | à faire |
| EA-01 | Détection S01, en TypeScript pur | EA | livré |
| EA-02 | Mode OBSERVE et taux d'accord | EA | livré (code) — pipeline débloqué le 2026-09-18 (trois gates fermées, voir la fiche) ; entonnoir jusqu'à l'étape 4/9, zéro proposition ; taux d'accord non mesurable, pipeline à l'arrêt au 2026-09-20 |
| EA-03 | Protocole d'exécution et machine à états | EA | livré |
| EA-04 | Profils de compte, modèle de coût, registre de symboles | EA | livré |
| EA-05 | Agent MQL5 | EA | livré (incrément 6 inclus, 2026-09-15 — `OrderSend` écrit, inatteignable hors `CONFIRM`, jamais exécuté) — **vérification réelle du 2026-09-12 non corroborée** (2026-09-23 : jamais chargé dans le terminal d'après ses journaux, zéro commande en base) ; installé par jonction le 2026-09-23, à re-vérifier (README, étapes 1–4) |
| EA-06 | Réconciliation (`UNKNOWN`, positions externes) | EA | livré (4 incréments, 2026-09-16 — le scan de positions externes tourne déjà en réel ; la résolution `UNKNOWN` reste sans trafic tant qu'`OrderSend` est inatteignable) |

Les outils T06 à T19 sont décrits dans `../backlog.md`. Leur fiche est créée au moment de les démarrer, pas avant — une fiche écrite trois mois trop tôt décrit un problème qui a changé.

La série **S** porte les stratégies. Une stratégie n'est pas un outil du cockpit, mais elle suit la même discipline : écrite avant de coder, complétée pendant, close après. La série **EA** portera les fiches de l'agent d'exécution MT5 (ADR 0010).
