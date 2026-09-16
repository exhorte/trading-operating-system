# T06 — Journal auto-alimenté, zéro saisie

Statut : **livré** (4 incréments, 2026-09-16) · Vague 2 · Effort 3–5 j ·
Valeur 5 · Dépend de : T05 (livré)

## Problème

Un trade se termine, et rien ne le rend browsable. `/journal/[brokerPositionId]`
(T05) est un lien profond vers une seule capture, pas une liste ; `/journal`
lui-même est toujours le stub T06. Pour revoir sa semaine, l'utilisateur n'a
que l'onglet Historique de MT5 — que ce projet a choisi de ne pas dupliquer,
mais dont il ne veut pas non plus dépendre pour la chose la plus basique
qu'une revue exige : parcourir ce qu'on a réellement tradé. C'est le
troisième goulot du charter (« Revue & journal : enregistrer chaque trade et
son contexte sans une seule saisie manuelle »).

## Écart trouvé avant tout code (cartographie)

Lu avant d'écrire quoi que ce soit : `charter.md`, `state.md`, `roadmap.md`,
`backlog.md` (section T06), `catalogue.md` (raisonnement d'origine, #6), les
11 ADR, `schema.sql`, `SetupProposalRepository.cs`, `TradeCaptureRepository.cs`,
`Program.cs`, `positions-table.tsx`, `journal/[brokerPositionId]/page.tsx`.

### Ce qui existe déjà et qu'il ne faut pas dupliquer

Tout ce que backlog.md décrit comme « à construire : le modèle de données du
journal » **existe déjà, éclaté sur quatre tables** — la vraie tâche n'est
pas un nouveau schéma, c'est une vue de lecture par-dessus :

| Brique | Fichier | État |
|---|---|---|
| Trades clos, P&L réel | `closed_trades` (`account_id, broker_position_id, symbol, side, volume, realized_pnl, exit_price, closed_at`) | T02b, une ligne par position fermée. |
| Heure d'ouverture | `position_opens` (`account_id, broker_position_id, opened_at`) | T02a. Nécessaire pour la durée — `SetupProposalRepository.GetClosedTradesAsync` fait déjà exactement cette jointure (voir plus bas). |
| Contexte visuel | `trade_captures` (kind `entry`/`exit`) | T05. Existe seulement depuis le 2026-09-05, et pas pour tout trade depuis (voir Décision 3). |
| Contexte machine, quand ça coïncide | `setup_proposals` (EA-02) | Biais/structure/liquidité au moment détecté — jamais le « pourquoi » de l'utilisateur, qui n'existe plus depuis le retrait de T04. |
| Précédent le plus proche, à ne PAS réutiliser tel quel | `SetupProposalRepository.GetClosedTradesAsync` / `ClosedTradeSummaryRow` | Même jointure `closed_trades ⋈ position_opens`, mais **sans `realized_pnl`, volontairement, pour une raison qui ne s'applique pas ici** — voir Décision 1. Bon modèle pour la jointure, mauvaise forme pour le journal. |

## Décisions à valider avant d'implémenter

Trois choix — le premier parce qu'il touche une frontière déjà posée par un
ADR sur un sujet voisin et qu'il vaut mieux trancher une fois, explicitement,
que le redécouvrir en relisant le code plus tard.

1. **P&L réalisé et vues agrégées : jusqu'où ?**

   `ClosedTradeSummaryRow` omet délibérément `realized_pnl` — son commentaire
   dit pourquoi : « no performance metric to leak into a reconciliation view
   that must not have one » (ADR 0011). Et ADR 0011 est explicite, mais
   **sur le banc de replay**, pas sur ce dépôt : « aucun P&L, aucun taux de
   réussite, aucune espérance, aucun drawdown, aucun profit factor, aucune
   courbe d'équité ». `catalogue.md` (avant le pivot, avant ADR 0011) prévoyait
   pourtant ces mêmes vues pour T06 : « calendrier P&L, courbe d'equity,
   expectancy, profit factor, R moyen ».

   Je recommande de **couper la liste en deux**, pas de la reprendre ou de la
   rejeter en bloc :
   - **Oui — des faits, pas une preuve.** P&L réalisé par trade (déjà affiché
     en direct pour les positions ouvertes, `positions-table.tsx`, uP&L) et un
     calendrier de P&L réalisé jour par jour. C'est un registre de ce qui
     s'est passé, pas une évaluation de stratégie — la même distinction que
     charter.md pose déjà (principe 2 : le KPI est la conformité, pas le
     P&L) sans l'interdire pour autant : un carnet de comptes n'est pas un
     verdict.
   - **Non, pas dans ce tour.** Expectancy, profit factor, taux de réussite,
     courbe d'équité — exactement le vocabulaire qu'ADR 0011 bannit, et
     exactement ce que charter.md écarte comme KPI (« le P&L sur 20 trades
     est du bruit »). Ce sont des statistiques qui prétendent dire si la
     stratégie marche — la question qu'ADR 0002 a fermée sans verdict. Rien
     n'empêche de les ajouter un jour sur un échantillon qui a du sens, mais
     ce jour-là c'est une décision explicite, pas un sous-produit de T06.

   R multiple par trade reste dans le « oui » : c'est une mesure de risque
   pris, pas de succès de la stratégie (déjà affiché en direct sur les
   positions ouvertes).

2. **Nouvelle table, ou vue de lecture pure ?**

   Je recommande **aucune nouvelle table**. Les quatre briques ci-dessus
   couvrent tout ce que backlog.md demande (liste, calendrier, ventilations
   par symbole/session/heure/jour). Une nouvelle table de journal dupliquerait
   `closed_trades`/`position_opens` — le piège que `.claude/CLAUDE.md` nomme
   explicitement en premier. Les ventilations et le calendrier sont des
   agrégations pures, calculables côté TypeScript à partir de la même liste
   déjà récupérée (même principe que T05 : le serveur sert des faits, le
   rendu/l'agrégation vivent en TS, ADR 0004/0009).

3. **Trades sans capture T05 : les montrer quand même ?**

   Oui — `trade_captures` n'existe que depuis le 2026-09-05, et deux trades du
   2026-09-14 ont définitivement perdu leur capture de sortie (journal T05).
   La liste doit rester correcte pour ces cas : lien « Capture » seulement
   quand une ligne `trade_captures` existe pour cette position, jamais un
   lien mort. Pas de degré intermédiaire à inventer.

## Comportement attendu

1. Liste filtrable des trades clos (compte, plage de dates, symbole),
   triée par clôture décroissante — chaque ligne : symbole, côté, volume,
   entrée/sortie, R multiple, P&L réalisé, durée, lien Capture si disponible,
   contexte EA-02 si une proposition coïncide.
2. Vue calendrier du P&L réalisé jour par jour.
3. Ventilations simples : par symbole, session (`lib/analysis/sessions.ts`,
   à réutiliser — pas à réinventer), heure d'entrée, jour de la semaine.
4. Zéro action manuelle pour qu'une ligne apparaisse — tout vient de
   `closed_trades`/`position_opens`/`trade_captures`/`setup_proposals`.

## Ancrage dans le code

- `backend/src/TradingOs.Persistence/schema.sql` — lecture seule dans ce
  tour (Décision 2) : `closed_trades`, `position_opens`, `trade_captures`,
  `setup_proposals`.
- `backend/src/TradingOs.Persistence/SetupProposalRepository.cs` —
  `GetClosedTradesAsync` est le patron de jointure à suivre, pas la méthode
  à appeler : nouvelle méthode/nouveau repository (nom à proposer à
  l'incrément 1), même jointure, forme différente (Décision 1).
- `backend/src/TradingOs.Host/Program.cs` — nouvel endpoint, même famille que
  `/api/trades/closed`/`/api/setup-proposals` (essai/catch/`Results.Problem`,
  même style).
- `app/(cockpit)/journal/page.tsx` — remplace le stub `EmptyState`.
- `app/(cockpit)/journal/[brokerPositionId]/page.tsx` — inchangé, cible du
  lien Capture par ligne (même convention que `positions-table.tsx`).
- `lib/format.ts` (`formatSignedMoney`, `formatPrice`) — réutilisés, pas
  redéfinis.
- `lib/analysis/sessions.ts` — réutilisé pour la ventilation par session, à
  lire en détail avant l'incrément concerné plutôt que supposé ici.

## Découpage en incréments

Chaque incrément garde les gates vertes.

1. Repository + endpoint de lecture (jointure `closed_trades ⋈ position_opens`
   ⋈ existence `trade_captures`, P&L inclus — Décision 1/2).
2. Page `/journal` : table filtrable (compte/dates/symbole), lien Capture
   conditionnel (Décision 3).
3. Vue calendrier + ventilations, agrégées côté TypeScript depuis la même
   liste (Décision 2) — pas de nouvel endpoint par vue.
4. Enrichissement EA-02 : coïncidence trade ↔ `setup_proposals` par
   symbole/fenêtre temporelle (approximation du contexte, jamais le pourquoi
   de l'utilisateur — même limite que backlog.md la pose déjà).

## Critère de réussite

Parcourir n'importe quel trade clos, avec son contexte disponible, sans
ouvrir MT5 et sans avoir rien saisi à la main.

## Journal

- 2026-09-16 — fiche créée sur choix explicite de l'utilisateur (question
  posée après la livraison d'EA-06 : Vague 2/T06 choisi plutôt qu'EA-07 ou
  la clôture de Vague 1). Cartographie faite : les quatre tables qu'il faut
  couvrent déjà tout ce que backlog.md demandait comme « nouveau modèle de
  données » — pas de nouvelle table proposée. Trouvé en lisant
  `SetupProposalRepository.cs` : `ClosedTradeSummaryRow` omet `realized_pnl`
  par une décision ADR 0011 qui ne s'applique pas à ce fichier de la même
  façon — à trancher explicitement plutôt qu'à copier sans réfléchir (Décision
  1). **Arrêt ici, en attente de validation des trois décisions.**

- 2026-09-16 (suite) — les trois décisions validées telles que proposées
  (« valide les trois, enchaîne sur les incréments »). Quatre incréments,
  gates vertes à chaque étape (tsc, lint, `dotnet build` 0 warning,
  `dotnet test` 34/34, vitest 184/184, `next build`) :

  1. **`JournalRepository.GetTradesAsync`** + `GET /api/journal/trades`.
     `LEFT JOIN` partout (pas l'`INNER JOIN` de
     `SetupProposalRepository.GetClosedTradesAsync`) : un trade reste visible
     même sans `position_opens` ou sans capture — voir le commentaire du
     fichier pour le raisonnement complet. Aucune nouvelle table (Décision 2).
  2. **`/journal`** : table filtrable (compte déjà implicite, dates, symbole
     calculé côté client), lien Capture seulement quand `hasCapture` est vrai
     (Décision 3, jamais de lien mort).
  3. **Calendrier + ventilations**, agrégées côté TypeScript depuis la même
     liste déjà récupérée — aucun nouvel endpoint par vue, comme prévu. R
     multiple recalculé localement (même formule que
     `mt5-translate.ts::toPosition`, réimplémentée plutôt qu'importée : celle
     du live prend un `currentPrice`, celle-ci un `exitPrice` fixe) — retourne
     `null`, jamais `0`, quand `entryPrice`/`stopLoss` sont absents (aucune
     capture, ou stop jamais posé).
  4. **Enrichissement EA-02** — trouvaille en cours de route : une fonction
     pure de rapprochement existait déjà, `lib/setup/reconciliation.ts::reconcile`
     (tolérance 5 min, déjà utilisée par `reconciliation-view.tsx` sur
     `/setups`), avec exactement le même besoin d'appariement
     symbole+côté+fenêtre temporelle que backlog.md demandait de construire
     pour T06. Réutilisée telle quelle plutôt que réinventée avec une fenêtre
     différente — j'avais commencé à en écrire une à 30 min avant de trouver
     celle-ci ; jetée. La tolérance (5 min) n'est donc pas redéfinie ici, elle
     est réaffirmée avec un commentaire qui pointe vers l'original pour
     qu'elle ne dérive pas silencieusement des deux côtés. Colonne « Setup »
     : badge seulement quand une proposition coïncide, détail (niveau balayé,
     cost ratio, R:R) en `title` — jamais le pourquoi de l'utilisateur, qui
     n'existe plus depuis le retrait de T04.

  **Vérifié contre de vraies données, pas seulement par les gates.**
  TimescaleDB redémarré (`docker start tradingos-timescaledb`, arrêté depuis
  6 h), backend relancé, `GET /api/journal/trades?accountId=477029930&…`
  appelé directement contre les vrais trades du 2026-09-14/15. Confirme en
  conditions réelles, pas seulement en théorie : `entryPrice`/`stopLoss`
  sont bien `null` sur le seul trade sans capture (`3225412263`,
  `hasCapture:false`) ; **tous les autres trades réels ont `stopLoss: 0`**
  (jamais posé pendant cette période de test OBSERVE) — donc `computeRMultiple`
  renvoie `null` partout sur les données actuelles, colonne R vide mais
  honnête, pas une régression. `GET /api/setup-proposals` ne renvoie que des
  `status:"blocked"` (cohérent avec le taux d'accord EA-02 toujours à 0/595
  proposées) : l'enrichissement de l'incrément 4 n'a donc aujourd'hui rien à
  accrocher, vérifié comme correctement vide plutôt que supposé.

  **Non vérifié : le rendu visuel dans le navigateur.** `/journal` chargé
  dans le navigateur intégré : aucune erreur console, l'état de chargement
  (squelette, avant compte résolu) s'affiche correctement — mais aucun agent
  MT5 n'est connecté à ce backend fraîchement relancé, donc `useCockpit().account`
  reste `null` indéfiniment (même comportement que toutes les autres pages du
  cockpit sans connexion live, pas une limite propre à T06) et la table/le
  calendrier/les ventilations n'ont jamais été vus rendus à l'écran avec ces
  données réelles. À vérifier à la prochaine séance avec MT5 + l'observer
  connectés.
