# EA-02 — Mode OBSERVE et taux d'accord

Statut : **livré** (code) · Vague EA · Effort 1–2 j (révisé, voir note) · Valeur 5 · Dépend de : EA-01

C'est l'instrument de mesure, pas un écran de signaux : ce panneau existe pour comparer la machine à l'utilisateur, pas pour dire quoi faire. Aucune exécution, aucun ordre.

## Problème

EA-01 sait détecter un setup S01 sur une séquence de bougies fournie en argument. Rien ne le fait tourner sur des données réelles, en continu, ni ne compare ses propositions à ce que l'utilisateur trade réellement. Sans ça, le critère de réussite de S01 (fiche S01, section « Critère de réussite ») ne peut jamais être mesuré.

## Écart trouvé avant tout code (cartographie)

Le prompt EA-02 suppose que des bougies M1 EURUSD/GBPUSD existent déjà « sur le flux live ». **Ce n'est pas le cas.** La chaîne temps réel actuelle (`tools/mt5-observer/mt5_observer.py` → `Mt5ObserverClient.cs` → SignalR) ne streame **qu'un seul symbole, en M15** (XAUUSD aujourd'hui, contrôlé par `--symbol` en ligne de commande). Rien dans le dépôt ne fournit H4/D1/H1/M1 pour EURUSD et GBPUSD.

Options considérées, présentées à l'utilisateur :
- Étendre `mt5_observer.py` au multi-symbole/multi-timeframe : vraie diffusion temps réel, mais modifie en profondeur le composant que le dépôt traite avec le plus de précaution (« validé en live », stall connu du 28/07, piège documenté « réécrire du code qui existe déjà »).
- **Retenue** : un nouveau script Python, jetable au sens où il ne touche à rien d'existant, exporte le M1 périodiquement ; un worker TypeScript autonome (`npx tsx`, précédent : `scripts/import-candles.ts`) l'importe, agrège H1/H4/D1 en TS, évalue S01 et persiste. `mt5_observer.py` n'est pas touché.

Vérifié avant de choisir : `npx tsx` résout l'alias `@/*` de `tsconfig.json` en dehors de Next.js (testé directement) — le worker peut importer `lib/setup/`, `lib/risk/news-calendar.ts` (`isNewsBlackout`), `lib/risk/policy.ts` (`defaultRiskPolicy`) tels quels, sans en réécrire une ligne. Le schéma Postgres (`trading_day_anchors`, `risk_lockouts`, `news_releases`) porte déjà tout ce qu'il faut pour les pré-conditions T02a/T02b/T03, en lecture directe — aucune dépendance au process .NET en marche.

## Architecture retenue

```
MT5 terminal
   │ (lecture seule)
   ▼
tools/mt5-observer/export_m1_candles.py   — nouveau, boucle, écrit un JSONL
   │  par symbole toutes les N secondes (snapshot des ~500 dernières M1)
   ▼
scripts/run-setup-detection.ts (npx tsx)  — nouveau, boucle
   │  1. upsert JSONL → table candles (réutilise le pattern de import-candles.ts)
   │  2. agrège M1 → H1/H4/D1 (lib/analysis/aggregate.ts, nouveau, pur)
   │  3. lit trading_day_anchors / risk_lockouts / news_releases (pg direct)
   │  4. évalue les pré-conditions puis lib/setup/proposal.ts::evaluateSetup
   │  5. upsert le résultat → table setup_proposals (nouvelle)
   ▼
backend/.../SetupProposalRepository.cs + GET /api/setup-proposals (nouveau,
même famille que /api/captures) + GET /api/trades/closed (nouveau, manquait)
   ▼
components/cockpit/setup-proposals-panel.tsx (nouveau) + vue de rapprochement
```

Aucun chemin d'exécution nulle part. Le worker ne fait que lire MT5 (Python) et lire/écrire Postgres (TS) ; il ne parle jamais au Gateway ni à l'agent d'exécution (qui n'existe pas encore, EA-05).

## Comportement attendu

1. **Table `setup_proposals`** : horodatage, symbole, sens, niveau balayé, prix d'entrée, stop, cible, `c`, R:R attendu, et l'étape de blocage exacte quand la séquence n'aboutit pas (le champ le plus utile : il dit *pourquoi*).
2. **Panneau cockpit** : propositions de la séance en cours + étape de blocage de celles qui n'ont pas abouti.
3. **Vue de rapprochement** : propositions vs. `closed_trades`, classées PROPOSÉ_ET_PRIS / PROPOSÉ_ET_REFUSÉ / PRIS_SANS_PROPOSITION, avec tolérance temporelle (proposée : ±5 min sur le même symbole et même sens — à ajuster après observation, comme la fiche S01 le fait déjà pour sa propre notion de tolérance).

Aucune métrique de performance (ADR 0011) : ni P&L, ni win rate, ni espérance, ni courbe, nulle part dans le panneau.

## Écarts supplémentaires trouvés en cartographiant les pré-conditions S01

Aucune des cinq pré-conditions de S01 n'a d'implémentation prête à consommer telle quelle :

| Pré-condition S01 | État |
|---|---|
| Fenêtre horaire (killzone Londres/NY, heure NY) | **N'existe nulle part.** `lib/analysis/sessions.ts` a des fenêtres UTC statiques (asia/london/ny_am/ny_pm) pour un usage différent (scoring de contexte) — pas d'heure de New York, pas de résolution DST. Aucune heure de killzone n'est écrite dans le dépôt (ni dans S01, ni dans `ict_smc_framework.md`). **Valeurs ICT standard retenues à titre provisoire, posées et non dérivées comme le seuil `c`** : Londres 02:00–05:00 NY, NY AM 07:00–10:00 NY (`America/New_York`, DST géré par `Intl`/`zoneinfo`, pas un offset figé). À confirmer ou ajuster après observation. |
| NY Lunch (aucune position après 12:00 NY) | Valeur donnée par S01 (12:00 NY) — même mécanisme de zone que ci-dessus. |
| Calendrier (gate FRED) | `isNewsBlackout` existe (`lib/risk/news-calendar.ts`), pur, réutilisable tel quel. |
| Verrous T02a/T02b | `risk_lockouts` (table), requête déjà écrite dans `RiskTodayRepository.cs` — reprise à l'identique côté worker. |
| Profil de marché (chemin dégagé, pas de consolidation) | **Aucune définition opérationnelle nulle part.** Non implémenté en EA-02 ; noté comme écart assumé, pas deviné. |

## Extension d'EA-01 nécessaire (pas une réécriture)

`proposeSetup` ne rend que `SetupProposal | null` — EA-02 a besoin de savoir *où* la séquence s'est arrêtée. Ajout d'un type `SetupStage` (union des neuf étapes) et d'une fonction `evaluateSetup` qui rend `{ status: "proposed", proposal } | { status: "blocked", stage, detail }`. `proposeSetup` reste exporté (implémenté par-dessus `evaluateSetup`) pour ne rien casser ; aucun des tests EA-01 n'est modifié.

## Ancrage dans le code

- `lib/setup/proposal.ts` — étendu (voir ci-dessus), pas réécrit.
- `lib/risk/news-calendar.ts` (`isNewsBlackout`), `lib/risk/policy.ts` (`defaultRiskPolicy`, pour `maxTradesPerDay`) — réutilisés tels quels par le worker.
- `backend/src/TradingOs.Persistence/RiskTodayRepository.cs` — requête `risk_lockouts` reprise à l'identique (même SQL) côté worker TS.
- `scripts/import-candles.ts` — pattern d'upsert `candles` réutilisé.
- `backend/src/TradingOs.Persistence/schema.sql` — nouvelle table `setup_proposals`, additive.
- `backend/src/TradingOs.Host/Program.cs` — deux nouveaux `MapGet`, même famille que `/api/captures/{brokerPositionId}`.

## Découpage en incréments

1. `lib/domain/setup.ts` — `SetupStage`, résultat `SetupOutcome`.
2. `lib/setup/proposal.ts` — `evaluateSetup` (remplace le corps de `proposeSetup`), tests par étape de blocage.
3. `lib/analysis/aggregate.ts` — agrégation M1 → timeframe supérieur, pur, testé (nouveau fichier, n'en modifie aucun).
4. `lib/setup/preconditions.ts` — fenêtres killzone/NY-lunch en heure de New York (zone-aware), pur, testé.
5. `tools/mt5-observer/export_m1_candles.py` — export périodique, ne touche pas `mt5_observer.py`.
6. `backend/.../schema.sql` — table `setup_proposals`.
7. `scripts/run-setup-detection.ts` — orchestration (upsert candles, agrégation, pré-conditions, `evaluateSetup`, upsert proposals).
8. `backend/.../SetupProposalRepository.cs` + `GET /api/setup-proposals` + `GET /api/trades/closed`.
9. `lib/setup/reconciliation.ts` — classement PROPOSÉ_ET_PRIS / PROPOSÉ_ET_REFUSÉ / PRIS_SANS_PROPOSITION, pur, testé.
10. `components/cockpit/setup-proposals-panel.tsx` + vue de rapprochement.

Chaque incrément garde les gates vertes.

## Critère de réussite

Voir S01, section « Critère de réussite » : sur un échantillon de séances en OBSERVE, tout trade réellement pris a été proposé, et tout refus s'explique par une règle nommable. Le seuil et la taille de l'échantillon restent à fixer (S01 le dit déjà). Rien ici ne mesure la performance.

## Journal

- 2026-09-12 — fiche créée. Écart majeur trouvé avant tout code : la chaîne
  temps réel ne fournit ni le multi-symbole ni le M1 nécessaires à S01.
  Architecture proposée à l'utilisateur (worker TS périodique, lecture
  Postgres directe, aucune modification de `mt5_observer.py`) — validée.
  Deux paramètres non spécifiés par S01 identifiés et posés à titre
  provisoire (killzones ICT standard) plutôt que devinés silencieusement.
  Extension d'EA-01 (`evaluateSetup`) planifiée, pas une réécriture.

- 2026-09-12 (suite) — **livré côté code**, vérifié de bout en bout contre
  le terminal démo réel (login 477029930) : export Python → upsert
  TimescaleDB → agrégation → pré-conditions → `evaluateSetup` → écriture
  `setup_proposals` → `GET /api/setup-proposals` → panneau cockpit, observé
  dans le navigateur avec de vraies données (deux lignes EURUSDm/GBPUSDm,
  bloquées `precondition_session_window`, horaire du run hors killzone).

  Dix incréments livrés : `evaluateSetup`/`SetupStage` (extension EA-01),
  `lib/analysis/aggregate.ts`, `lib/setup/preconditions.ts`,
  `tools/mt5-observer/export_m1_candles.py`, `setup_proposals` (schema),
  `scripts/run-setup-detection.ts`, `SetupProposalRepository` + deux
  endpoints (`/api/setup-proposals`, `/api/trades/closed` — celui-ci
  manquait), `lib/setup/reconciliation.ts`, panneau cockpit + vue de
  rapprochement (`/setups`, nouvelle entrée de nav).

  Quatre défauts réels trouvés en testant contre de vraies données, corrigés
  avant tout usage :
  1. **Double comptage du volume dans `aggregateCandles`** — le bucket
     initialisait `volume` à la valeur de la première bougie, puis
     l'incrément générique la recomptait une seconde fois. 3 bougies de
     100 donnaient 400, pas 300. Trouvé par le test, pas en relisant le code.
  2. **`sweepTriggerCandidate` avait un problème de conception, pas un bug
     de code** : calculer le pool de liquidité sur des bougies qui
     contiennent déjà le sweep rend le niveau « déjà balayé » avant même que
     `detectSweep` s'exécute — auto-contradictoire. Corrigé en amont, dans
     EA-01 (`contextCandles`/`reactionCandles`), pas ici — mais c'est en
     construisant le worker EA-02 que la conséquence se serait vue en
     premier si EA-01 ne l'avait pas déjà réglé.
  3. **`ClosedTradeRow` (write-side, `PersistenceMapper.cs`) ne se lit pas
     via Dapper** — `DateTimeOffset` dans le constructeur positionnel d'un
     `record` reproduit exactement le bug de mapping que le commentaire de
     `/api/audit/recent` documentait déjà (2026-07-12, `DateTimeOffset` vs
     `DateTime`). Reproduit contre la vraie DB, pas deviné. Corrigé par un
     type de lecture dédié (`ClosedTradeSummaryRow`, `DateTime`), qui ne
     porte pas non plus `RealizedPnl` (ADR 0011).
  4. **`closed_trades` seul n'a pas l'heure d'ouverture** — le rapprochement
     compare la détection d'une proposition à l'OUVERTURE d'une position,
     pas à sa clôture. `GetClosedTradesAsync` fait maintenant un `JOIN`
     avec `position_opens` (T02a) pour `OpenedAt`.

  Un test de `reconciliation.ts` a aussi trouvé une vraie faute d'appariement
  (premier arrivé, premier servi, au lieu du plus proche globalement) —
  corrigé avant que quoi que ce soit d'autre en dépende.

  Gates verts : `npm run lint`, `npx tsc --noEmit`, `npm test` (165 tests,
  dépôt entier), `npm run build`, `dotnet build`, `dotnet test` (38, inchangé).
  `mt5_observer.py` non modifié (diff vide). Panneau vérifié dans Chrome
  (dev server + backend + worker + terminal réel) — un avertissement
  d'hydratation React vient d'une extension navigateur (attribut
  `translate-tooltip-mtz`), pas du code.

  Non fait, volontairement hors périmètre de ce tour : le **critère de
  réussite de S01 lui-même** (taux d'accord sur un échantillon de séances)
  ne peut être jugé qu'après que `export_m1_candles.py` et
  `run-setup-detection.ts` aient tourné en continu sur plusieurs séances
  réelles — ce n'est pas un manque de code, c'est un manque de temps qui
  passe. `TRADINGOS_ACCOUNT_ID` doit être positionné (env var) avant de
  lancer le worker en continu ; pas fait automatiquement pour ne pas figer
  un identifiant de compte dans un script committé.
