# T07 — Tracker d'erreurs et taux de conformité

Statut : **livré** (4 incréments, 2026-09-16) · Vague 2 · Effort 1–2 j ·
Valeur 5 · Dépend de : T06 (livré)

## Problème

Rien ne dit, aujourd'hui, si une règle de risque active a été contournée sur
un trade déjà clos. Le Risk Engine bloque en direct (ADR 0007), mais une
fois le trade clos, personne ne revient vérifier — et charter.md pose déjà
le vrai KPI : « le taux de conformité au plan, pas le P&L ».

## Écart trouvé avant tout code (cartographie)

Lu avant d'écrire quoi que ce soit : `roadmap.md`, `backlog.md` (section
T07), `catalogue.md` (#7), `T06-journal-auto.md` (dépendance, livrée),
`lib/risk/{sizing,policy,lockout}.ts`, `lib/market/symbols/registry.ts`,
`lib/analysis/sessions.ts`, `RiskTodayRepository.cs`, `schema.sql`.

**Taxonomie déjà réduite par une session précédente** (roadmap.md, suite au
retrait de T04) : *« trade hors plan »* et *« absence de ticket »* sont
sorties de la liste, aucune trace d'intention déclarée n'existant plus.
Reste : stop déplacé après l'entrée, taille hors politique, trade pendant un
lockout actif, trade hors fenêtre de session.

**Ce que j'ai vérifié cette fois, une par une, avant de les mettre toutes au
même plan** — deux le sont proprement, une ne l'est pas du tout, une l'est
mais pas avec l'outil qu'on croirait :

| Violation | Détectable aujourd'hui ? | Avec quoi |
|---|---|---|
| Trade pendant un lockout actif | **Oui, proprement.** | `position_opens.opened_at` contre les fenêtres `since`/`until`/`cleared_at` de `risk_lockouts`. Cas réel déjà connu : la position EURUSDm ouverte le 2026-09-15 pendant le lockout kill-switch (state.md, « Ce qui bloque »). |
| Trade hors fenêtre de session | **Oui, proprement.** | `position_opens.opened_at` contre `DEFAULT_SESSION_WINDOWS` (`lib/analysis/sessions.ts`, déjà réutilisé par T06 pour la ventilation par session) — `tradingEnabled: false` sur asia/NY PM/off-session. |
| Taille hors politique | **Oui, mais pas avec `evaluateSignalRisk`.** | Cette fonction (`lib/risk/sizing.ts`) code en dur le facteur XAUUSD (« 1.00 price move on 1.0 lot ≈ 100 USD », commentaire du fichier) — appliquée telle quelle à un trade EURUSD/GBPUSD (la majorité des trades réels), elle donnerait un volume attendu faux, silencieusement. La bonne formule est générique par symbole via `symbolMetadata` (`tickSize`/`tickValue`, `lib/market/symbols/registry.ts`, EA-04) + `defaultRiskPolicy().maxRiskPerTradePercent`. Manque en plus : la **balance au moment du trade** — rien ne persiste `account.snapshot` dans une table typée aujourd'hui (seulement dans `envelopes`, JSONB brut). Voir Décision 2. |
| Stop déplacé après l'entrée | **Non, pas du tout.** | Rien ne trace les modifications de stop-loss après l'ouverture — `Mt5ModifyCommand`/`execution.modify` existe dans le protocole wire mais n'a jamais été câblé (aucun handler, aucune persistance), et l'observer ne compare pas les stops entre deux sondages. Voir Décision 3. |

## Décisions à valider avant d'implémenter

1. **Deux violations dans ce tour : lockout actif + fenêtre de session.**
   Les deux seules détectables proprement, sans approximation ni nouvelle
   infrastructure de suivi.

2. **Taille hors politique : construite quand même, avec une approximation
   assumée.** Recommandation : utiliser la **balance courante** du compte
   comme substitut de la balance au moment du trade, plutôt que de construire
   un suivi historique de `account.snapshot` dans ce tour. Raisonnement :
   compte personnel, variations quotidiennes faibles (les P&L réels vus
   jusqu'ici sont de l'ordre de quelques dollars par trade) — l'approximation
   est raisonnable pour une majorité de cas, et le vrai correctif (mapper
   `account.snapshot` vers une table typée, `PersistenceMapper` a déjà le
   mécanisme) est un ajout court, séparable, si l'approximation se révèle
   insuffisante à l'usage. Alternative : le reporter aussi, ne livrer que
   2 violations sur 4 ce tour.

3. **Stop déplacé après l'entrée : reporté, hors périmètre de ce tour.**
   Le construire correctement exige un suivi des modifications de position
   (nouvelle table, ou comparaison de snapshots successifs côté observer) —
   un morceau à part entière, pas un sous-produit de T07. Resterait dans la
   taxonomie affichée, marqué comme non mesuré plutôt que silencieusement
   absent.

## Comportement attendu

1. Taxonomie fermée (2 à 4 violations selon la Décision 2/3), évaluée pour
   chaque trade clos.
2. Taux de conformité hebdomadaire = trades sans aucune violation / total de
   la semaine — **la seule courbe**, affichée dans `TopCommandBar` (badge,
   même famille que `NewsCalendarBadge`/`PersistenceHealthBadge`), à la
   place du P&L en tête de cockpit (charter.md, principe 2).
3. Détail par trade : quelles violations, sur `/journal` (T06) — une colonne
   ajoutée à la table existante, pas une seconde liste de trades.

## Ancrage dans le code

- `lib/analysis/sessions.ts`, `lib/market/symbols/registry.ts`,
  `lib/risk/policy.ts` — réutilisés, pas réécrits.
- `lib/risk/sizing.ts::evaluateSignalRisk` — **pas réutilisé** (formule
  XAUUSD-only) ; nouvelle formule générique dans le nouveau module ci-dessous.
- Nouveau : `lib/compliance/violations.ts` — fonctions pures, testées,
  une par type de violation (ADR 0004).
- `backend/src/TradingOs.Persistence/` — nouveau repository (nom à proposer
  à l'incrément 1) pour l'historique `risk_lockouts` sur une plage de dates
  (`/api/risk/today` ne couvre que « maintenant », pas un historique).
- `app/(cockpit)/journal/page.tsx` (T06) — colonne violations ajoutée,
  agrégée côté client comme le reste de cette page.
- `components/shell/top-command-bar.tsx` — nouveau badge de conformité.

## Découpage en incréments

1. `lib/compliance/violations.ts` — détection lockout + session, pures,
   testées unitairement contre le cas réel du 2026-09-15.
2. Endpoint historique des lockouts + branchement dans `/journal` (colonne
   violations) et calcul du taux hebdomadaire.
3. Badge `TopCommandBar`.
4. Taille hors politique (Décision 2), si validée.

## Critère de réussite

Le taux de conformité hebdomadaire s'affiche en haut du cockpit, calculé
automatiquement, sans saisie — et retrouve le cas réel du 2026-09-15 comme
une violation.

## Journal

- 2026-09-16 — fiche créée sur choix explicite de l'utilisateur (question
  posée après la livraison de T06). Cartographie faite violation par
  violation plutôt qu'en bloc : deux détectables proprement (lockout,
  session), une détectable mais avec un piège identifié avant qu'il ne
  devienne un bug silencieux (`evaluateSignalRisk` est XAUUSD-only —
  aurait donné un faux verdict sur la majorité des trades réels, tous
  EURUSD/GBPUSD), une pas détectable du tout (stop déplacé — rien ne trace
  les modifications de position). **Arrêt ici, en attente de validation des
  trois décisions.**

- 2026-09-16 (suite) — les trois décisions validées telles que proposées
  (« valide les trois, enchaîne sur les incréments »). Quatre incréments,
  gates vertes à chaque étape (tsc, lint, `dotnet build` 0 warning,
  `dotnet test` 34/34, vitest 206/206 — 22 nouveaux, `next build`) :

  1. `lib/compliance/violations.ts` — trois détecteurs purs. Bug évité avant
     d'exister, pas juste théorique : `evaluateSignalRisk` n'a **pas** été
     réutilisé pour la taille (facteur XAUUSD codé en dur) ; la formule
     générique passe par `symbolMetadata` (tick size/value). Testé contre le
     **vrai** lockout du 2026-09-15 (`lockout-mu2h6tvb-8qosw0`, requêté
     directement en base pour le fixture) : le trade EURUSDm de 09:36:00
     ressort bien en `LOCKOUT_ACTIVE`.
  2. `lib/compliance/evaluate.ts` (`evaluateTrade`/`complianceRate`) +
     `GET /api/risk/lockouts` (nouveau `RiskLockoutHistoryRepository` —
     `RiskTodayRepository` ne couvre que « maintenant », pas un historique)
     + colonne Violations sur `/journal`. Bug trouvé et corrigé en écrivant
     l'intégration, pas en la concevant : `closed_trades.symbol` est le nom
     **broker** (`EURUSDm`), pas le canonique que `symbolMetadata` attend —
     `ComplianceTradeInput.symbol` est donc `SymbolCode | null`
     (`toCanonicalSymbol` côté appelant), et seul le contrôle de taille est
     sauté sur un symbole non résolu, jamais lockout/session avec lui.
  3. `ComplianceBadge` dans `TopCommandBar`, fenêtre glissante de 7 jours
     indépendante du filtre de `/journal` — même détecteurs, fetch séparé.
  4. Taille hors politique (Décision 2) : déjà branchée dans `evaluateTrade`
     depuis l'incrément 2 (conçue dès le départ pour l'inclure) — rien à
     ajouter séparément, juste vérifié (tests dédiés : trade sur-dimensionné
     flaggé, ignoré sans balance connue, pas de faux positif sur un stop
     jamais posé).

  **Vérifié contre de vraies données.** `GET /api/risk/lockouts` appelé
  directement : retrouve le vrai lockout kill-switch du 2026-09-15 (et, au
  passage, les 4 lignes « Daily loss guard » dupliquées à 73 ms d'intervalle
  du 2026-09-14 — l'ancien bug de course corrigé le 2026-09-15, artefact
  historique en base, sans conséquence ici puisque les doublons ne changent
  pas le résultat « un lockout était actif »). `ComplianceBadge` chargé dans
  le navigateur intégré : rendu correct de son état « Conformité — »
  (aucun compte connecté), aucune erreur console nouvelle, `/health` répond
  200. Même limite que T06 : jamais vu rendu avec de vraies données à
  l'écran, aucun agent MT5 connecté à cette session.

- 2026-09-24 — **le taux quitte la barre du haut pour la tête du Command
  Center.** Refonte visuelle demandée (ADR 0012) : la barre du haut ne garde
  que le compte. Le critère de réussite — « s'affiche en haut du cockpit » —
  est désormais tenu par la première carte de l'écran d'accueil
  (`ComplianceCard`, à côté du verdict de séance), plus par une pastille
  visible sur chaque écran : **lecture de ma part**, signalée à
  l'utilisateur. Même nombre que la jauge de `/risk` (même hook). La carte
  détaille aussi les trois types de manquement.

  **Défaut trouvé en le faisant, corrigé** : `useJournalWindow` transformait
  une réponse refusée (HTTP 503) en historique **vide** — contraire à son
  propre contrat (« null après un échec, jamais un tableau vide »). Or un
  historique vide vaut 100 % de conformité : l'ancien badge affichait donc
  « 100 % conformité » base arrêtée, exactement l'écran qui rassure parce
  qu'il n'a rien à lire. Un refus lève désormais `failed` ; la carte, la
  jauge et l'historique des verrous disent « illisible — le backend
  répond-il ? ». Et sans aucun trade sur la période, la carte affiche « — »,
  pas 100 %. Vérifié à l'écran avec la base réellement arrêtée.
