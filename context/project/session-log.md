# Journal de session

Append-only, la plus récente en haut. Une entrée par session, courte — le
détail vit dans la fiche de chaque outil (`context/product/tools/*.md`) et
dans `git log`. Voir ADR 0008 pour ce que ce fichier est et n'est pas.

---

## 2026-09-05 (suite 2)

Outil : T03 (livré) — gate calendrier économique FRED. Vague 1 : reste T05.

Suivi `02_Plan_Projet/prompt-claude-code-vague-1.md`. Trois décisions
proposées avant code, validées par l'utilisateur :
- **Liste blanche à 5, sans ISM** — vérifié que l'ISM a fait retirer toutes
  ses séries de FRED en 2016 (litige de licence), aucun `release_id` de
  remplacement n'existe. CPI (10), NFP (50), PCE (54), Retail Sales (9),
  FOMC (101) — chaque ID confirmé individuellement sur `fred.stlouisfed.org`.
- **Clé FRED côté backend .NET, jamais `.env.local`** — le fetch se fait
  serveur pour ne jamais exposer la clé dans le bundle navigateur ; déviation
  assumée de la fiche initiale.
- **Cache en table Postgres** `news_releases`, écrite directement par
  `NewsCalendarRepository` (hors pipeline `PersistenceWriter`, qui suppose un
  envelope → une ligne — un rafraîchissement remplace tout un `release_id`
  d'un coup).

Trouvaille en cours de route qui a changé la conception : FRED ne renvoie
qu'une **date**, jamais une heure de publication. Résolu en combinant la
date FRED avec l'heure de publication officielle et stable de chaque série
(8h30 ET pour CPI/NFP/PCE/Retail Sales, 14h00 ET pour FOMC), convertie en UTC
réel via `TimeZoneInfo`/`America/New_York` (jamais un offset figé — testé
contre un vrai communiqué FOMC daté du 10/12/2025).

Deuxième trouvaille, plus subtile : un backend qui vient de démarrer, avant
son premier fetch FRED réussi, a une table vide — si ça se traduisait par
« calendrier connu, rien à venir », la gate s'ouvrirait à tort au boot,
exactement le fail-open que l'outil doit empêcher. Résolu en distinguant
`null` (jamais synchronisé, gate refuse) de `[]` (synchronisé, rien à venir,
gate ouverte) — `NewsCalendarRepository.GetUpcomingOrNullAsync`.

`newsBlackoutMinutes` passé de 15 à 30 dans `defaultRiskPolicy` (lu depuis la
policy, jamais codé en dur). Chip permanent dans `TopCommandBar` (pas dans un
onglet, comme exigé).

Gates tous verts (`npm run lint`, `npx tsc --noEmit`, `npm test` — 101 tests,
`npm run build`, `dotnet build`, `dotnet test` — 38 tests). Non vérifié :
mise à jour du badge après hydratation et cycle FRED réel contre une vraie
clé API — pas d'extension Chrome connectée cette session (même limite qu'en
T02a/b) ; confirmé seulement par `curl` que le rendu serveur ne plante pas et
affiche honnêtement l'état fail-closed avant hydratation.

---

## 2026-09-05 (suite)

Outil : T02b (livré) — historique des deals MT5 et pause de 30 min sur deux
pertes consécutives, dernier morceau de T02. T02 est maintenant entièrement
livré.

Ce qui a changé, en suivant le plan écrit en session précédente
(`context/product/tools/T02-lockout.md`) sans déviation :
- **Observer** — `poll_positions()` (un seul appel `positions_get()` par
  tick, détecte les fermetures par diff de tickets) + `sum_realized_pnl` /
  `build_position_closed`, extraites en fonctions pures et testées
  (`tools/mt5-observer/test_mt5_observer.py`, stdlib `unittest`) : le test
  reproduit le piège signalé en revue (position gagnante fermée en deux
  deals partiels, le dernier négatif après swap — la somme doit rester
  positive).
- **Wire + Gateway** — `Mt5PositionClosedMessage` (TS/C#), publié en direct
  par le Gateway sous `journal.trade_closed` (comme `risk.day_anchor.resolved`,
  jamais via `PublishEvent`).
- **Persistance** — table `closed_trades`, sans scope de journée (la traîne
  de pertes consécutives ne se réinitialise pas à minuit, contrairement à
  `tradesToday`).
- **`GET /api/risk/today`** — étendu avec `consecutiveLosses` /
  `lastConsecutiveLossAt` ; `activeLockout` filtre désormais aussi
  `until IS NULL OR until > now()`.
- **`lib/risk/lockout.ts`** — `detectConsecutiveLossPause` (déclenché
  spécifiquement sur le gate `gate-consec-loss`, pas sur `mode === "locked"`
  en général) et `isLockoutExpired` extraite séparément ; `applyActiveLockout`
  prend maintenant un `now` obligatoire.
- **Cockpit** — chrono de la pause dans `RiskStatusPanel` (`setInterval` 1s
  local, dérivé de `risk.lockoutUntil`, aucun nouvel état dans le store).

Gates tous verts (`npm run lint`, `npx tsc --noEmit`, `npm test` — 84 tests,
`npm run build`, `dotnet build`, `dotnet test` — 35 tests, `python -m
py_compile`). Non vérifié en session : la chaîne complète contre un
terminal MT5 réel (pas d'extension Chrome connectée, même limite qu'en T02a).

---

## 2026-09-05

Outils : T01 (livré), T04 (livré), T02a (livré, T02b reste ouvert).

Ce qui a changé :
- **T01** — panneau de sizing permanent dans le cockpit, appelle
  `evaluateSignalRisk` sans le modifier. Trois défauts corrigés en revue
  avant tout commit : budget de perte quotidien calculé sur le solde
  restant (pas le total), `null` affiché comme « — » jamais « 0 % », R
  cible qui refuse un TP du mauvais côté de l'entrée.
- **T04** — ticket pré-trade en 4 boutons, publié via `PublishEvent`
  (pas de nouvel endpoint). Confirmation par écho (pas par soumission) après
  revue des trois refus silencieux de `PublishEvent` ; badge de persistance
  ajouté au cockpit pour le cas qu'aucun écho ne couvre (écriture perdue
  après diffusion).
- **T02a** — ancre de journée (minuit serveur, offset MT5 résolu
  dynamiquement), `tradesToday` réel (comptage de positions, pas de P&L),
  état verrouillé stocké dans un ledger (jamais dérivé), kill switch réel
  (verrouillage + bandeau + accusé de réception journalisé, aucun
  `close_all` simulé). Plan initial (7 incréments) coupé en T02a/T02b en
  revue : un seul verrou (pertes consécutives) a besoin de l'historique des
  deals MT5, les quatre autres non.
- **Gouvernance** — ADR 0008 : réintroduction bornée d'un journal de
  session (ce fichier), `state.md` redevient un instantané.

Ouvert : T02b (deal history MT5, verrou de pertes consécutives — plan détaillé
dans `context/product/tools/T02-lockout.md`). Rien n'est commité pour T04/T02a
au moment de cette entrée.
