# EA-04 — Profils de compte, modèle de coût, registre de symboles

Statut : **livré** · Vague EA · Effort 1–2 j · Dépend de : EA-01 (porte de
coût déjà écrite, en attente d'un seuil par compte)

Ce qui rend FTMO et le compte réel différents sans un seul `if (ftmo)` dans le
code.

## Problème

`defaultRiskPolicy(accountId)` ignore aujourd'hui l'`accountId` qu'on lui
passe : un seul jeu de limites, en dur, pour tout compte. La porte de coût
d'EA-01 (`lib/setup/gates.ts::evaluateViabilityGates`) attend un
`costThreshold` et un `commission` en paramètre, mais le seul appelant réel
(`scripts/run-setup-detection.ts`) leur passe `0.25` et `0` en dur, avec un
commentaire qui pointe explicitement vers cette fiche. Rien ne distingue un
compte FTMO d'un compte réel, ni un symbole canonique de son nom broker.

## Écart trouvé avant tout code (cartographie)

Lu en entier avant d'écrire quoi que ce soit : `lib/domain/account.ts`,
`lib/domain/risk.ts`, `lib/risk/policy.ts`, `lib/risk/sizing-panel.ts`,
`lib/setup/gates.ts`, `lib/setup/proposal.ts`, `scripts/run-setup-detection.ts`,
`lib/realtime/signalr-client.ts` (bloc `recomputeRisk`),
`context/domain/risk_ftmo.md`, `context/domain/symbols-broker.md`.

### Ce qui existe déjà et qu'il ne faut pas dupliquer

| Brique | Fichier | État |
|---|---|---|
| Compte, domaine | `lib/domain/account.ts` | `TradingAccount`, `BrokerAccount`, `AccountKind` (`prop_challenge`/`prop_funded`/`demo`/`live`/`paper`) **existent déjà** — et ne sont utilisés **nulle part ailleurs dans le dépôt**. C'est le point d'ancrage à étendre, pas un `Account` à réinventer dans un nouveau `lib/accounts/Account`. |
| Profil de risque | `lib/domain/risk.ts::RiskPolicy` | Porte déjà exactement les champs que le prompt de lancement appelle « RiskProfile » : risque par trade, perte quotidienne, perte max, risque ouvert max, trades par jour, pertes consécutives. **`RiskProfile` et `RiskPolicy` sont le même concept** — inutile d'introduire un second type qui ferait doublon (ADR 0004 : une seule source de vérité par concept). |
| Résolution de policy | `lib/risk/policy.ts::defaultRiskPolicy(accountId)` | Retourne toujours le même objet, quel que soit `accountId`. Cinq appelants réels, tous à ne pas casser : `lib/risk/sizing-panel.ts` (T01, panneau de sizing), `lib/realtime/signalr-client.ts` (recalcul du risque live), `lib/mock/initial-snapshot.ts` (données de démo), `scripts/run-setup-detection.ts` (worker EA-02), `components/shell/news-calendar-badge.tsx` (badge T03). |
| Porte de coût | `lib/setup/gates.ts::evaluateViabilityGates` | Prend déjà `costThreshold` et `commission` en paramètres explicites — son commentaire dit littéralement *« jusqu'à ce que le profil de compte (EA-04) le fournisse »*. **Rien à changer dans ce fichier.** |
| Seul appelant réel de la porte | `scripts/run-setup-detection.ts:49,284` | `costThreshold: 0.25` et `commission: 0` en dur, chacun commenté « jusqu'à EA-04 ». C'est le seul câblage à faire. |
| Registre broker | `context/domain/symbols-broker.md` | Rempli en Phase 0 : EURUSD↔`EURUSDm`, GBPUSD↔`GBPUSDm`, XAUUSD↔`XAUUSDm` **ou** `XAUUSD247m` (ambiguïté non tranchée, voir plus bas), avec digits/point/tick value/tick size/volume min-max-step pour chacun. |
| Coût FTMO documenté | `context/product/tools/S01-strategie-sweep-aligne.md`, section « À vérifier avant de coder » | Donne déjà un ordre de grandeur sourcé : FTMO ≈ 5 $/lot aller-retour, différent d'Exness Raw/Pro — utilisable comme valeur de départ documentée, pas devinée. |

### Ce que « la policy devient multiple » casse — la question posée explicitement par le prompt de lancement

Aucun des cinq appelants de `defaultRiskPolicy` ne regarde aujourd'hui le
*type* de compte — ils passent juste un `accountId` et récupèrent le même
objet. Rendre la policy multiple est donc sûr **tant que
`defaultRiskPolicy` garde sa signature actuelle** (`(accountId) => RiskPolicy`)
et se contente de résoudre un profil différent selon l'`accountId` en
interne, avec un repli sur les valeurs actuelles pour tout compte non
enregistré. Aucun des cinq appelants n'a besoin d'être modifié.

**Ce qui casserait, et que cette fiche NE fait PAS** : `lib/risk/sizing-panel.ts`
(T01) code en dur des constantes propres à XAUUSD
(`XAUUSD_USD_PER_POINT_PER_LOT = 100`, conversion spread `/ 0.01`) — le
fichier le documente lui-même (« there is no second symbol anywhere in the
product yet »). `lib/realtime/signalr-client.ts::recomputeRisk` fait la même
hypothèse XAUUSD pour convertir le spread en points. Rendre la *policy* (les
limites en %, le seuil de coût) multi-compte ne touche à aucune de ces deux
hypothèses XAUUSD — mais rendre le *sizing* multi-symbole en dépendrait, et
ce n'est pas demandé ici. Pour qu'il n'y ait « pas de surprise en T01 » :
**T01 continue de fonctionner à l'identique après cette fiche, toujours pour
XAUUSD** ; il n'apprend pas à sizer un second symbole. C'est un écart de
périmètre assumé, pas un oubli.

## Décisions à valider avant d'implémenter

Trois points où je préfère ton arbitrage plutôt que trancher seul :

1. **Vocabulaire de type de compte.** Le prompt de lancement demande un
   `AccountType = ftmo | real`. Le dépôt a déjà `AccountKind` (`prop_challenge`
   / `prop_funded` / `demo` / `live` / `paper`), inutilisé mais plus proche de
   l'axe réel (le type de compte, pas le broker qui l'émet — un compte
   `demo`/`live` peut exister chez n'importe quel broker). Je propose de
   **réutiliser `AccountKind`** et de faire de « FTMO » vs « Réel » une
   propriété du *profil* résolu pour un `accountId` (quelle policy/coût/
   exécution s'applique), pas un second type concurrent — plus simple, un
   seul axe de vérité.
2. **XAUUSD : `XAUUSDm` ou `XAUUSD247m`.** `symbols-broker.md` note les deux
   comme trouvés sur le terminal, sans trancher, et dit explicitement
   « à trancher avant EA-04 ». XAUUSD est hors périmètre S01 v1, donc ça ne
   bloque rien techniquement, mais le registre de symboles de cette fiche
   doit choisir une entrée canonique. Je propose `XAUUSDm` (celui déjà utilisé
   partout ailleurs dans le dépôt — mock, sizing panel), avec `XAUUSD247m`
   documenté à part comme variante non câblée.
3. **Valeurs FTMO réelles.** Le compte FTMO n'existe peut-être pas encore
   (question ouverte dans `state.md`). Je construis la structure (types de
   challenge 1-step/2-step, phases Challenge/Verification/Funded) avec des
   valeurs placeholder explicitement marquées « à renseigner depuis la
   source FTMO officielle », sauf le coût (≈5 $/lot, déjà sourcé dans S01).
   Confirme que c'est bien ce que tu veux plutôt que je devine des
   pourcentages FTMO (5%/10% etc.) qui circulent publiquement mais que je
   n'ai pas vérifiés pour ton challenge précis.

## Comportement attendu

`lib/accounts/` (nouveau) :

- **`types.ts`** — `CostModel` (spread attendu par symbole, commission par
  lot, `costThreshold`), `ExecutionMode` (`"observe" | "paper" | "confirm"` —
  littéral, `"auto"` irreprésentable, ADR 0010), `ExecutionProfile` (mode,
  symboles autorisés, volume max, positions max, spread max — les mêmes
  valeurs que `context/execution/safety.md` décrit sans les chiffrer),
  `AccountEnvironment` (terminal, `AgentId`, magic number), `AccountProfile`
  (agrège `TradingAccount` + `RiskPolicy` + `CostModel` + `ExecutionProfile`
  + `AccountEnvironment`).
- **`ftmo.ts`** — structure par type de challenge (1-step/2-step) et par
  phase (2-step : Challenge/Verification ; funded ensuite), valeurs en
  configuration, documentées comme à confirmer depuis la source officielle,
  sauf le coût (S01, ≈5 $/lot).
- **`real.ts`** — profil réel, perte quotidienne plus stricte.
- **`registry.ts`** — `resolveAccountProfile(accountId): AccountProfile |
  null`, table de correspondance `accountId → AccountProfile`.
- **`cost-model.ts`** — convertit une commission par lot (devise du compte)
  en unités de prix comparables au spread, via tick value/tick size du
  registre de symboles (`spread` et `commission` de `gates.ts` doivent être
  dans la même unité — voir son commentaire).

`lib/market/symbols/` (nouveau) :

- **`registry.ts`** — le registre canonique↔broker (`context/domain/symbols-broker.md`
  transcrit en TypeScript, typé), avec digits/point/tickValue/tickSize/volumeMin/
  volumeMax/volumeStep. Le domaine ne connaît que `EURUSD`/`GBPUSD`/`XAUUSD` ;
  ce module sait qu'un terminal donné les appelle `EURUSDm` etc.

Branchement (les deux seuls sites de comportement réel qui changent) :

- `lib/risk/policy.ts::defaultRiskPolicy` — consulte `resolveAccountProfile`
  en premier, retombe sur les valeurs actuelles si le compte n'est pas
  enregistré. Signature inchangée.
- `scripts/run-setup-detection.ts:49,284` — `costThreshold` et `commission`
  viennent du `CostModel` résolu pour `ACCOUNT_ID`, plus le calcul de
  commission en unités de prix via `cost-model.ts`.

## Ancrage dans le code

- `lib/domain/account.ts` — non modifié dans son contenu ; `TradingAccount`
  reste le seul type de compte. `lib/accounts/` le consomme, ne le duplique
  pas.
- `lib/domain/risk.ts::RiskPolicy` — non modifié ; c'est déjà le `RiskProfile`.
- `lib/risk/policy.ts` — étendu (voir ci-dessus), signature de
  `defaultRiskPolicy` inchangée : `sizing-panel.ts`, `signalr-client.ts`,
  `initial-snapshot.ts`, `news-calendar-badge.tsx` continuent de fonctionner
  sans modification.
- `lib/setup/gates.ts` — **non modifié**, il attend déjà les bons paramètres.
- `context/domain/symbols-broker.md` — source de données de
  `lib/market/symbols/registry.ts`, pas remplacé.

## Découpage en incréments

1. `lib/market/symbols/registry.ts` — registre canonique↔broker, typé, pur,
   testé (couvre les trois symboles de `symbols-broker.md`).
2. `lib/accounts/types.ts` — `CostModel`, `ExecutionMode`, `ExecutionProfile`,
   `AccountEnvironment`, `AccountProfile`.
3. `lib/accounts/cost-model.ts` — conversion commission→unités de prix via le
   registre de symboles, pur, testé.
4. `lib/accounts/ftmo.ts` + `lib/accounts/real.ts` — profils concrets,
   valeurs en configuration documentées.
5. `lib/accounts/registry.ts` — `resolveAccountProfile`, testé (compte connu
   → bon profil ; compte inconnu → `null`).
6. `lib/risk/policy.ts::defaultRiskPolicy` — branché sur le registre, repli
   sur l'existant, testé (compte enregistré vs compte inconnu).
7. `scripts/run-setup-detection.ts` — câblage réel du `costThreshold` et de
   la `commission`.

Chaque incrément garde les gates vertes.

## Critère de réussite

- `defaultRiskPolicy` a été étendu sans casser T01 — le panneau de sizing
  fonctionne toujours, à l'identique, pour XAUUSD.
- Les règles FTMO sont structurées par type et par phase, valeurs en
  configuration et non devinées (sauf le coût, sourcé S01).
- Le registre de symboles isole complètement les noms broker du domaine.
- Le seuil de `c` et la commission viennent du compte dans
  `scripts/run-setup-detection.ts` — plus de `0.25`/`0` en dur.
- Gates vertes.

## Journal

- 2026-09-12 — fiche créée avant tout code. Cartographie faite : `TradingAccount`/
  `AccountKind` existent déjà mais ne sont utilisés nulle part — point
  d'ancrage à étendre, pas à dupliquer. `RiskProfile` (prompt de lancement)
  et `RiskPolicy` (existant) sont le même concept. La porte de coût d'EA-01
  attend déjà ses paramètres ; seul `scripts/run-setup-detection.ts` les
  code en dur, aux lignes 49 et 284. Trois décisions soumises à
  l'utilisateur avant implémentation, toutes validées : réutiliser
  `AccountKind` (pas de second axe `AccountType`), `XAUUSDm` comme symbole
  canonique (`XAUUSD247m` documenté à part, non câblé), et FTMO en structure
  + placeholders `TODO(FTMO-rules)` documentés plutôt que des chiffres
  devinés — le compte FTMO n'existe pas encore.

- 2026-09-12 (suite) — **livré**. Les sept incréments :
  1. `lib/market/symbols/registry.ts` — registre canonique↔broker
     (EURUSD/GBPUSD/XAUUSD↔`*m`), réutilise `SymbolMetadata`
     (`lib/domain/market.ts`), jusque-là défini mais jamais produit nulle
     part dans le dépôt.
  2. `lib/accounts/types.ts` — `CostModel`, `ExecutionMode` (littéral
     `"observe"|"paper"|"confirm"`, `"auto"` irreprésentable),
     `ExecutionProfile`, `AccountEnvironment`, `AccountProfile`.
     `AccountProfile` exclut délibérément balance/equity (valeurs live, déjà
     portées par `AccountSummary`) — la config statique ne les invente pas.
  3. `lib/accounts/cost-model.ts` — conversion commission→unités de prix via
     `tickSize/tickValue` du registre de symboles, testée (5 $/lot EURUSD
     → 0,00005 en unités de prix, cohérent avec l'ordre de grandeur des
     spreads mesurés).
  4. `lib/accounts/ftmo.ts` + `real.ts` — structure par type/phase, valeurs
     `TODO(FTMO-rules)`/`TODO(real-account-rules)` explicites ; seul le coût
     FTMO (5 $/lot) est sourcé (S01).
  5. `lib/accounts/registry.ts` — `resolveAccountProfile` pure sur un
     registre injecté (même style que `lib/contracts/execution/idempotency.ts`).
     `ACCOUNT_PROFILES`, le registre réel, est **vide** — aucun compte FTMO
     ou réel confirmé à ce jour ; enregistrer un compte reste une action
     future et délibérée.
  6. `lib/risk/policy.ts::defaultRiskPolicy` — paramètre `registry` optionnel
     (défaut `ACCOUNT_PROFILES`), signature compatible : les cinq appelants
     réels (`sizing-panel.ts`/T01, `signalr-client.ts`, `initial-snapshot.ts`,
     `run-setup-detection.ts`, `news-calendar-badge.tsx`/T03) continuent de
     recevoir exactement la policy d'avant, puisque le registre est vide.
  7. `scripts/run-setup-detection.ts` — `costThreshold`/`commission` ne sont
     plus des littéraux dans `FX_DETECTION_CONFIG` ; ils viennent de
     `resolveCostInputs(canonical)`, qui retombe sur 0,25/0 (comportement
     identique à avant) tant qu'aucun compte n'est enregistré.

  T01 vérifié inchangé : aucune de ses hypothèses XAUUSD (constante
  `XAUUSD_USD_PER_POINT_PER_LOT`, conversion `/0.01`) n'a été touchée — ce
  n'était pas l'objet de cette fiche, seule la *policy* devient
  multi-compte, pas le *sizing* multi-symbole.

  Gates vertes : `npm run lint`, `npx tsc --noEmit`, `npm test` (202 tests,
  +15), `npm run build`, `dotnet build`, `dotnet test` (38, inchangé —
  aucun mirror C# nécessaire, `lib/accounts/`/`lib/market/symbols/` ne
  traversent pas le wire), `python -m py_compile` (inchangé).
