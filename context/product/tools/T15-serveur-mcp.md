# T15 — Serveur MCP « mon trading »

Statut : **livré** (4 incréments, 2026-09-17) · Vague 2 (avancé
délibérément — catalogue.md le note explicitement) · Effort 1–2 j ·
Valeur 4 · Dépend de : T06 (livré)

## Problème

Chaque nouvelle question sur ses propres données (« mes lundis sont-ils
rentables ? », « combien de trades hors lockout ce mois-ci ? ») exige
aujourd'hui soit une nouvelle vue cockpit, soit une requête SQL à la main.
Un serveur MCP en lecture seule remplace ça par une question en langage
naturel directement dans Claude — « 80 % de ce que ferait un AI Analyst
(#19) pour 5 % de l'effort » (catalogue.md).

## Écart trouvé avant tout code (cartographie)

Lu avant d'écrire quoi que ce soit : `catalogue.md` (#15), `backlog.md`
(T15), `context/adr/0005-ia-en-lecture-seule.md`, `context/adr/0011-banc-de-replay.md`,
tous les endpoints `/api/*` existants (`Program.cs`), `package.json`,
`scripts/run-setup-detection.ts` (précédent le plus proche).

**Les questions d'exemple de catalogue.md sont datées** (« confiance ≥ 4 »,
« trades hors plan ») — vocabulaire T04, retiré le 2026-09-14. L'esprit
reste valable (interroger ses données en langage naturel), le vocabulaire
non.

**Rien à construire côté données : tout existe déjà en REST.**
`/api/journal/trades` (T06), `/api/risk/lockouts` (T07), `/api/candles`,
`/api/setup-proposals`, `/api/execution/divergence` (EA-06), `/api/captures/{id}`
couvrent déjà trades, lockouts, bougies, propositions EA-02, divergence
d'exécution, captures. Aucun de ces endpoints n'a jamais été appelé que par
le cockpit — un serveur MCP est un second client HTTP en lecture, pas une
nouvelle source de données.

**Ce qui manque vraiment : les violations T07 ne sont persistées nulle
part.** `lib/compliance/` calcule tout côté navigateur, à la demande — il
n'y a pas de ligne « ce trade a violé telle règle » en base à lire. Un
serveur MCP ne peut pas faire un `SELECT` là-dessus ; il doit soit
recalculer (et avec quoi ?), soit ne pas exposer les violations du tout.
Voir Décision 3.

## Décisions à valider avant d'implémenter

1. **Node/TypeScript (`tsx`), pas Python, pas un service C# séparé.**
   Python est réservé à MT5 dans ce dépôt (ADR 0010 : séparation stricte de
   responsabilités) — un serveur MCP sans rapport avec MT5 n'a rien à y
   faire. `tsx` est déjà une dépendance (`scripts/run-setup-detection.ts`
   l'utilise pour exactement ce patron : un processus autonome dans le même
   paquet TS). L'avantage décisif, pas seulement la cohérence : ça permet
   d'**importer `lib/compliance/violations.ts`/`evaluate.ts` directement**
   pour la Décision 3, au lieu de réécrire la logique de conformité dans un
   troisième langage.

2. **Toujours via l'API REST existante, jamais une connexion Postgres ou
   MT5 directe depuis le serveur MCP.** Zéro nouvelle requête SQL, zéro
   nouveau chemin d'accès aux données — le serveur MCP est un client HTTP
   de plus, comme le cockpit. Conséquence assumée : si `TradingOs.Host`
   n'est pas démarré, les outils MCP échouent proprement (message clair),
   ils ne dégradent pas vers un accès direct.

3. **Le serveur expose des faits, jamais une métrique de performance déjà
   calculée.** Même ligne que la Décision 1 de T06 et qu'ADR 0011 : pas
   d'outil MCP `get_expectancy` ou `get_win_rate` qui affinerait un chiffre
   comme une vérité du système. Les violations T07 (lockout, session — pas
   la taille, voir Décision 4) sont recalculées **à la demande**, dans le
   process du serveur MCP, en import direct de `lib/compliance/` sur les
   faits bruts renvoyés par `/api/journal/trades` + `/api/risk/lockouts` —
   jamais persistées, jamais mises en cache. Poser « quelle est mon
   expectancy » reste possible : la réponse se construit dans la
   conversation à partir des faits exposés, ce n'est pas un outil dédié qui
   la calcule et la présente comme acquise.

4. **Contrôle de taille (T07) : absent de ce tour.** La balance du compte
   au moment présent n'existe que dans le flux SignalR live (le cockpit),
   pas dans un endpoint REST — `evaluateTrade` accepte déjà `balance: null`
   et saute proprement le contrôle de taille dans ce cas (T07). Le serveur
   MCP expose donc lockout + session, jamais la taille, sans inventer de
   nouveau chemin pour la balance dans ce tour.

## Comportement attendu

Un process Node/TS lancé en `stdio` (protocole MCP standard, ce que
Claude Desktop/Claude Code attendent d'un serveur MCP local), configuré par
l'utilisateur dans ses propres réglages MCP — jamais auto-enregistré par ce
projet. Outils exposés, tous en lecture seule (ADR 0005) :

- `get_trades(from, to, symbol?)` — `/api/journal/trades`.
- `get_lockouts(to)` — `/api/risk/lockouts`.
- `get_candles(symbol, timeframe, from, to)` — `/api/candles`.
- `get_setup_proposals(since)` — `/api/setup-proposals`.
- `get_execution_divergence()` — `/api/execution/divergence`.
- `get_compliance_violations(from, to)` — combine `get_trades`+`get_lockouts`
  via `lib/compliance/evaluate.ts::evaluateTrade` (balance `null`, Décision 4).

`accountId` configuré une fois (variable d'environnement — usage
strictement personnel, ADR/charter portée), jamais redemandé par outil.

## Ancrage dans le code

- `scripts/run-setup-detection.ts` — patron de processus `tsx` autonome
  dans ce même paquet, à suivre pour la structure.
- `backend/src/TradingOs.Host/Program.cs` — tous les endpoints déjà cités,
  aucun nouveau à créer.
- `lib/compliance/violations.ts`, `evaluate.ts` — importés directement, pas
  réécrits.
- `lib/realtime/backend-url.ts` — pour résoudre l'URL du backend, même
  convention que le cockpit.
- `package.json` — nouvelle dépendance `@modelcontextprotocol/sdk`
  (officielle Anthropic), nouveau script `mcp` (`tsx tools/mcp-server/index.ts`).

## Découpage en incréments

1. Squelette du serveur (`tools/mcp-server/index.ts`), transport stdio,
   `get_trades`/`get_lockouts`/`get_candles` — les trois passthrough les
   plus simples.
2. `get_setup_proposals`/`get_execution_divergence`.
3. `get_compliance_violations` (Décision 3/4).
4. Documentation de configuration (comment le brancher dans Claude Desktop/
   Claude Code) — pas d'auto-enregistrement.

## Critère de réussite

Poser une question factuelle sur ses trades en langage naturel dans une
conversation Claude configurée avec ce serveur, et obtenir une réponse
construite sur des faits réels, sans avoir ouvert le cockpit.

## Journal

- 2026-09-17 — fiche créée sur choix explicite de l'utilisateur (question
  posée après un redémarrage de session, T15 choisi plutôt que T08).
  Cartographie faite : aucune nouvelle donnée à construire, tout existe déjà
  en REST — la seule vraie question est où vit la logique de conformité
  (T07), puisqu'elle n'est persistée nulle part. Décision retenue : la
  réimporter directement (Node/TS le permet), jamais la réécrire, jamais
  l'exposer comme une métrique de performance figée. **Arrêt ici, en
  attente de validation des quatre décisions.**

- 2026-09-17 (suite) — les quatre décisions validées telles que proposées
  (« valide les quatre, enchaîne sur les incréments »). Quatre incréments,
  gates vertes à chaque étape (tsc, lint, vitest 206/206, `next build`) :

  1. `tools/mcp-server/backend-client.ts` (`fetchJson`/`requiredAccountId`)
     + squelette `index.ts` + `get_trades`/`get_lockouts`/`get_candles`.
  2. `get_setup_proposals`/`get_execution_divergence`.
  3. `get_compliance_violations` — importe `lib/compliance/evaluate.ts`
     directement (Décision 1), `balance: null` (Décision 4).
  4. `tools/mcp-server/README.md` (configuration Claude Desktop/Code) +
     script `npm run mcp`.

  **Vérifié par un vrai handshake MCP, pas seulement les gates.** Messages
  JSON-RPC (`initialize`, `tools/call`) construits à la main et envoyés sur
  stdin d'un process réel (`TRADING_OS_ACCOUNT_ID=477029930 npm run mcp`),
  backend et TimescaleDB relancés après le redémarrage de session. Les 6
  outils répondent sans erreur ; `get_trades`/`get_compliance_violations`
  vérifiés contre les vraies données du 2026-09-14/15 avec le contenu de la
  réponse inspecté, pas seulement le code retour.

  **Trouvaille en testant, sans rapport avec T15 lui-même : voir
  `state.md`, « Ce qui bloque ».** `get_compliance_violations` sur le
  2026-09-14/15 a fait remonter 5 trades ouverts pendant un lockout « Daily
  loss guard » actif (13:37:28 → 2026-09-15 08:54:25, jamais vu documenté
  nulle part avant ce test), en plus du trade du 2026-09-15 déjà connu.
  Vérifié à la main contre les horodatages bruts de `risk_lockouts`/
  `closed_trades` avant de le tenir pour acquis — y compris un trade ouvert
  1 seconde avant le début du lockout, correctement PAS marqué en
  violation, qui confirme que la limite n'est pas sur-déclenchée.
  N'implique aucun bug de T15 (ni de T07, dont la logique est réutilisée
  telle quelle) — un fait sur les données réelles, découvert parce que
  personne n'avait encore posé cette question précise sur toute la plage.
