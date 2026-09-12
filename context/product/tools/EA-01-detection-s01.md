# EA-01 — Détection S01, en TypeScript pur

Statut : **en cours** · Vague EA · Effort 2–3 j · Valeur 5 · Dépend de : rien pour la détection (l'exécution dépendra d'EA-01 à EA-06)

## Problème

Le poste de travail sait dimensionner, verrouiller, refuser et journaliser (Vague 1). Il ne sait pas reconnaître un setup S01 : tant que la reconnaissance vit uniquement dans la tête de l'utilisateur, rien ne peut être proposé, mesuré ou exécuté (voir fiche `S01-strategie-sweep-aligne.md`).

EA-01 construit la partie la plus sûre de toute la Vague EA : des fonctions pures qui prennent des bougies et rendent une proposition de setup, ou rien. Pas de réseau, pas d'exécution, pas d'ordre.

## Comportement attendu

`lib/setup/` — neuf modules purs, un par étape de la séquence S01, chacun testé sur des séquences de bougies construites à la main :

- `bias.ts` — biais H4/D1, BOS/CHoCH validé en clôture de corps
- `dealing-range.ts` — range 1H, external high/low, équilibre 50 %
- `liquidity.ts` — PDH/PDL, Asia H/L, EQH/EQL, cible opposée
- `sweep.ts` — dépassement + réintégration dans la même bougie
- `displacement.ts` — MSS en corps + FVG non comblé + corps ≥ 1,5 × ATR(14)
- `poi.ts` — FVG du déplacement, sinon OB/Breaker d'origine, et le CE
- `stop.ts` — au-delà de la mèche du sweep + buffer de spread
- `gates.ts` — porte de coût et porte R:R (S01, section « Portes de viabilité »)
- `proposal.ts` — assemble le tout, rend `SetupProposal | null`

`lib/strategy/` n'existe pas et ne doit pas être créé (ADR 0002 : le nom a été supprimé avec la recherche d'edge).

Quatre cas pièges testés explicitement (ce sont les erreurs qui coûtent de l'argent en réel) :
- sweep : dépassement sans réintégration → `null` (une cassure, pas un sweep) ;
- displacement : cassure par la mèche seule, corps en deçà → `null` ;
- poi : FVG dont un corps a clôturé au-delà du CE → invalidé ;
- gates : stop très serré dont le coût dépasse le seuil → refusé.

Aucune fonction ne lit l'horloge, le réseau ou un état global — tout entre par les arguments.

## Ancrage dans le code

Cartographie faite avant tout code, comme demandé par le prompt EA-01. Pour chacune des neuf étapes, ce qui existe déjà dans `lib/analysis/`, `lib/domain/`, `lib/risk/` et ce qui manque réellement :

| Étape S01 | Brique existante | État |
|---|---|---|
| 1. Biais | `structure.ts` (`detectStructureShifts`, `structuralBias`) | **Existe, réutilisable tel quel.** BOS/CHoCH déjà validés en clôture de corps, no-look-ahead. Appliquer sur des bougies H4/D1 donne directement le biais S01 — aucun code de biais spécifique à écrire. |
| 2. Dealing range | `swings.ts` (`detectSwings`), `bias.ts` (`priceLocationOf`) | **Partiel.** Les swings et le ratio premium/discount existent, mais sur la *dernière plage de swings connue*, pas sur « la dernière impulsion + external high/low en 1H » que demande S01. `priceLocationOf` calcule une position générique, pas un range ancré sur une impulsion précise. À écrire : la sélection de l'impulsion et de ses extrêmes ; le ratio 50 % peut réutiliser `priceLocationOf` une fois le range isolé. |
| 3. Liquidité | `liquidity.ts` (`detectLiquidity` : PDH/PDL, equal highs/lows) | **Partiel.** PDH/PDL et EQH/EQL existent. **Manque : Asia High/Low** — aucune brique ne borne les swings à la session Asia (`sessions.ts` sait bucketiser un timestamp, mais rien n'agrège un high/low par session). Manque aussi la sélection de « la cible opposée non encore purgée » — logique de sélection, pas de détection. |
| 4. Sweep | `liquidity.ts` (`sweptAt` = mèche au-delà du niveau, sans réintégration) | **Insuffisant tel quel.** Le `sweptAt` existant répond à « le niveau a-t-il été dépassé par une mèche, un jour », pas à « dépassement ET réintégration dans la même bougie ». C'est une notion différente — `sweep.ts` doit être écrit, mais peut consommer les `LiquidityLevel[]` de `detectLiquidity` comme source de niveaux plutôt que refaire la détection PDH/PDL/EQH/EQL. |
| 5. Déplacement | `pd-arrays.ts` (`detectFairValueGaps`), `atr.ts` (`averageTrueRange`), `structure.ts` | **Bases présentes, assemblage à écrire.** FVG et ATR(14) existent et sont directement réutilisables. Manque la règle composée : corps de la bougie de rupture ≥ 1,5×ATR **et** FVG non comblé **et** clôture de corps au-delà du swing opposé (pas juste une mèche). `StructureShiftKind` a déjà une valeur `"liquidity_sweep_reversal"` dans `lib/domain/analysis.ts`, jamais produite par `detectStructureShifts` — à noter, pas nécessairement à utiliser telle quelle. |
| 6. POI | `pd-arrays.ts` (`detectFairValueGaps`, `detectOrderBlocks`) | **FVG et OB existent, Breaker et CE manquent.** Aucune détection de Breaker Block dans le dépôt. Le CE (point médian du FVG) n'est calculé nulle part — trivial (`(high+low)/2`) mais absent. Logique de repli FVG → OB/Breaker à écrire. |
| 7. Stop | rien de direct | **À écrire entièrement**, mais trivial : extrême de la mèche du sweep (connu depuis l'étape 4) + buffer de spread (donné en paramètre, pas lu ici — le spread réel vient du compte, cf. Phase 0/EA-04). |
| 8. Gates (coût, R:R) | `lib/risk/gates.ts` existe mais **c'est un concept différent** (gates FTMO : news, session, drawdown) | **À écrire entièrement**, sans toucher `lib/risk/`. Attention au nom : `lib/setup/gates.ts` (porte de coût/R:R de S01) et `lib/risk/gates.ts` (gates de risque FTMO) coexistent sans lien — noms proches, responsabilités disjointes, à ne pas fusionner. Le seuil de `c` est un paramètre par défaut 0,25, pas lu depuis `defaultRiskPolicy` (`RiskPolicy` n'a pas ce champ — il arrivera avec EA-04). |
| 9. Proposal | `lib/domain/strategy.ts` (`StrategySignal`, `SignalStatus`) | **Un type de domaine existe déjà pour la sortie**, mais pas nommé `SetupProposal` et pas taillé pour EA-01 : `StrategySignal` porte un `MarketContextState` complet et un cycle de vie post-détection (`risk_review`, `commanded`, etc.) qui n'a pas de sens avant EA-03. Décision proposée : `SetupProposal` est un **nouveau type**, plus étroit (niveaux + étape de blocage), et la conversion `SetupProposal → StrategySignal` sera le travail d'EA-02/EA-03, pas d'EA-01. À valider avec vous avant d'écrire le type. |

Autres points relevés pendant la cartographie, hors des neuf étapes mais pertinents pour la suite :

- `lib/domain/market.ts` a déjà `SymbolMetadata` (tickSize, tickValue, contractSize, digits, volumes) — c'est la forme que prendra le registre de symboles d'EA-04 ; Phase 0 (`context/domain/symbols-broker.md`) lui correspond déjà.
- `lib/risk/sizing.ts` (`evaluateSignalRisk`) code en dur un facteur XAUUSD (« 1.00 price move on 1.0 lot ≈ 100 USD ») pour convertir un risque en volume. EA-01 ne touche pas ce fichier, mais **EA-04 devra le corriger** avant que S01 (EURUSD/GBPUSD) puisse être sized correctement à travers le Risk Engine — sinon un trade EURUSD serait dimensionné avec la valeur de point de l'or.
- `lib/analysis/test-helpers.ts` (`candleAt`, `series`) est directement réutilisable pour les tests de `lib/setup/`, y compris sur des timeframes autres que M15.

## Découpage en incréments proposé

Chaque incrément laisse les gates vertes (`npm run lint`, `npx tsc --noEmit`, `npm test`, `npm run build`).

1. **`bias.ts`** — pas de nouveau code de détection, un adaptateur mince qui applique `detectStructureShifts`/`structuralBias` sur des bougies H4/D1 et documente pourquoi rien de plus n'est nécessaire ici.
2. **`dealing-range.ts`** — sélection de la dernière impulsion + external high/low en 1H, réutilise `priceLocationOf` pour le ratio 50 %.
3. **`liquidity.ts`** — ajoute Asia High/Low (agrégation par session, nouvelle logique) par-dessus `detectLiquidity` ; sélection de la cible opposée non purgée.
4. **`sweep.ts`** — dépassement + réintégration même bougie, consommant les niveaux de l'étape 3.
5. **`displacement.ts`** — règle composée corps ≥ 1,5×ATR + FVG non comblé + clôture de corps au-delà du swing opposé.
6. **`poi.ts`** — FVG du déplacement, repli OB, CE ; Breaker Block écarté du périmètre v1 si aucun order block d'origine n'est trouvé (à confirmer : accepter une proposition sans Breaker plutôt que bloquer sur du code non écrit).
7. **`stop.ts`** — extrême de la mèche + buffer.
8. **`gates.ts`** — porte de coût (`c`, seuil paramétrable défaut 0,25) et porte R:R (≥ 1:3 après coût).
9. **`proposal.ts`** — nouveau type `SetupProposal`, assemblage des huit étapes, `null` à la première étape qui échoue, avec l'étape de blocage renseignée (utile dès EA-02).

Les quatre cas pièges (sweep sans réintégration, displacement par la mèche, POI invalidé par le CE, gate de coût qui refuse un stop serré) sont testés dans les incréments 4, 5, 6 et 8 respectivement.

## Question ouverte avant de coder

Le type `SetupProposal` (étape 9) : le confirmer comme nouveau type distinct de `StrategySignal`, ou préférez-vous que je regarde d'abord s'il peut réutiliser un sous-ensemble de `StrategySignal` pour éviter deux types qui se ressemblent ? Ma lecture du domaine penche pour un type distinct (le cycle de vie de `StrategySignal` suppose une intégration au Risk Engine qui n'existe pas encore), mais c'est une décision de modélisation, pas un détail d'implémentation.

## Critère de réussite

Voir `S01-strategie-sweep-aligne.md`, section « Critère de réussite » — c'est le taux d'accord machine/humain mesuré en EA-02 qui tranche, pas EA-01. Le critère propre à EA-01 est plus étroit : les neuf modules sont purs, testés, et les quatre cas pièges passent.

## Journal

- 2026-09-12 — fiche créée. Cartographie faite avant tout code (voir tableau
  ci-dessus) : la majorité de la géométrie (structure, swings, liquidité,
  FVG, OB, ATR) existe déjà dans `lib/analysis/` et sera consommée telle
  quelle, jamais réécrite. Ce qui manque réellement se limite à l'assemblage
  spécifique à S01 (Asia H/L, sweep avec réintégration, règle de
  déplacement composée, CE, portes de viabilité) et au nouveau type
  `SetupProposal`. En attente de validation du découpage en incréments et
  de la question sur `SetupProposal` avant d'écrire du code.
