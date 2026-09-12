# Journal de session

Append-only, la plus récente en haut. Une entrée par session, courte — le
détail vit dans la fiche de chaque outil (`context/product/tools/*.md`) et
dans `git log`. Voir ADR 0008 pour ce que ce fichier est et n'est pas.

---

## 2026-09-12 (EA-02 — livré côté code)

Écart trouvé avant tout code : la chaîne temps réel ne fournit ni le
multi-symbole ni le M1 nécessaires à S01 (un seul symbole, M15, en dur).
Architecture validée avec l'utilisateur : `tools/mt5-observer/export_m1_candles.py`
(nouveau, ne touche pas `mt5_observer.py`) + `scripts/run-setup-detection.ts`
(worker `npx tsx`, Postgres direct pour les pré-conditions T02a/T02b/T03).

Dix incréments livrés et vérifiés de bout en bout contre le terminal démo
réel : extension d'EA-01 (`evaluateSetup`), agrégation M1→H1/H4/D1,
killzones NY (DST-aware, valeurs ICT provisoires), export Python, table
`setup_proposals`, worker de détection, endpoint .NET + rapprochement,
panneau cockpit (`/setups`) — observé dans Chrome avec de vraies données.

Quatre défauts réels trouvés en testant (pas en relisant) : double comptage
de volume dans l'agrégation de bougies ; un bug de mapping Dapper
(`DateTimeOffset` dans un record lu, même classe de bug que celui déjà
documenté dans `/api/audit/recent` le 2026-07-12) ; `closed_trades` sans
heure d'ouverture (jointure `position_opens` ajoutée) ; un appariement de
rapprochement premier-arrivé-premier-servi au lieu du plus proche
globalement. Détail complet dans `EA-02-observe-taux-accord.md`.

Gates verts : lint, tsc, 165 tests TS, build, dotnet build/test (38,
inchangé). Non fait : le critère de réussite de S01 (taux d'accord sur un
échantillon de séances) — demande de faire tourner le worker plusieurs
séances réelles, pas du code qui manque.

---

## 2026-09-12 (EA-01 — livré)

`lib/setup/` : neuf modules purs (bias, dealing-range, liquidity, sweep,
displacement, poi, stop, gates, proposal) détectant la séquence S01 sur des
bougies, sans réseau ni exécution. `SetupProposal` (nouveau, distinct de
`StrategySignal`) dans `lib/domain/setup.ts`. 36 tests dédiés, 143 au total
dans le dépôt, quatre gates vertes (lint, tsc, test, build). `lib/analysis/`
et `lib/risk/` non modifiés ; `lib/strategy/` n'existe pas.

Défaut trouvé et corrigé en construisant : calculer le pool de liquidité sur
des bougies qui contiennent déjà la bougie du sweep se contredit tout seul
(`detectLiquidity` marque le niveau « balayé » avant que `detectSweep` ait pu
tester la réintégration). Corrigé en séparant l'entrée en `contextCandles` /
`reactionCandles`. Détail complet et cinq autres décisions dans la fiche
`EA-01-detection-s01.md`.

Prochaine étape : EA-02 (mode OBSERVE + taux d'accord machine/humain) —
voir `02_Plan_Projet/prompt-claude-code-vague-ea.md`.

---

## 2026-09-12 (Phase 0 — préalables et mesure)

Aucun code de production, conformément au bloc Phase 0 de
`02_Plan_Projet/prompt-claude-code-vague-ea.md`.

Écrits : `tools/mt5-observer/log_spread.py` (échantillonnage jetable du
spread EURUSD/GBPUSD toutes les 5 s, JSONL local, ne touche pas à
`mt5_observer.py`), `analyze_spread.py` (médiane/p90/p99/max par tranche de
15 min en heure de New York), `list_symbols.py` (résolution des suffixes
broker). Testés en syntaxe et sur un JSONL synthétique.

Bloqué : le terminal MT5 local est lancé mais pas connecté à un compte
(`mt5.initialize()` échoue avec `Authorization failed`) — aucun identifiant
n'est demandé ni stocké ici (charte). `context/domain/symbols-broker.md` est
créé avec la structure attendue et un statut « en attente » ; la connexion
manuelle puis `list_symbols.py` restent à faire pour le remplir, et
`log_spread.py` doit tourner au moins cinq séances avant de calibrer le
seuil de `c`.

Tags d'archive : confirmé via `git ls-remote --tags origin` que
`archive/pre-pivot-2026-09-04` et `archive/pivot-commits-2026-09-04`
n'existaient que localement. Poussés sur `origin` après confirmation.

---

## 2026-09-11 (suite — cadrage EA)

Aucun code. Interview de cadrage sur une proposition d'évolution arrivée de
l'extérieur (`01_Recherche/EA_implementation.md`) : ajouter un agent d'exécution
MT5 et deux profils de compte séparés, FTMO et réel.

Décisions prises : l'EA passe en priorité **devant** la clôture de la Vague 1,
qui attend ; construction jusqu'au mode CONFIRM seulement, AUTO explicitement
exclu ; v1 sur EURUSD/GBPUSD ; stratégie unique synthétisée depuis trois systèmes
réellement tradés (SCALP, Liquidity Trap, FULL 1:20RR), régime de sortie hybride ;
banc de replay autorisé en dépôt séparé, sans aucune métrique de performance.

Écrit : **ADR 0009** (dette de T05, en attente depuis le 05/09), **ADR 0010**
(le Trading OS exécute, l'EA est un agent), **ADR 0011** (banc de replay ≠
backtester), **fiche S01** (stratégie « Sweep aligné »).

Ouvert : les vérifications listées en fin de S01 — le spread réel contre un SL de
3 à 7 pips en tête, parce qu'il peut invalider le régime de sortie — puis les
fiches EA-01 à EA-06.

---

## 2026-09-11 (suivi)

Aucun code. Six jours sans session depuis le 2026-09-05 : la clôture de la
Vague 1 n'a pas été faite. Mise à jour de `state.md` — « Ce qui bloque »
nomme désormais le seul point ouvert, la validation contre un vrai terminal
MT5 — et remplissage de `03_Suivi_Projet/Suivi.md`, vide depuis la création
du dossier.
Ouvert : ADR 0009 (faits capturés / rendu à la demande), puis la séance
réelle de bout en bout qui clôt la vague.

---

## 2026-09-05 (revue T05)

Deux défauts trouvés en revue sur `tools/mt5-observer/mt5_observer.py`
(T05, livré dans la session précédente), corrigés avant tout usage réel —
détail complet dans `context/product/tools/T05-captures-auto.md` :

1. **Mauvais identifiant comme clé** — le diff et
   `history_deals_get(position=...)` utilisaient `p.ticket` au lieu de
   `p.identifier` (`POSITION_IDENTIFIER`, égal à `DEAL_POSITION_ID`). Les deux
   coïncident dans le cas courant (d'où le bug invisible) mais divergent sur
   des opérations de service côté broker — le jour où ça arrive sur une
   position vivante : fausse clôture, fausse ouverture, `tradesToday` faussé,
   capture d'entrée sur le mauvais trade, entrée parasite dans la série de
   pertes consécutives.
2. **Trade ouvert-et-fermé entre deux sondages invisible** — le sondage à
   2 s ne peut voir un aller-retour plus court : le ticket/identifiant
   n'entre jamais dans `_known_position_ids`, donc ne peut jamais en sortir
   côté diff. Exactement les scalps courts et les stops touchés
   immédiatement — les trades qui pèsent le plus sur les métriques de
   discipline.

Corrections : `identifier` partout où une position est clé ; nouvelle
fonction `scan_missed_round_trips` (balayage des deals de sortie récents à
chaque poll, reconstruit `opened`+`closed` pour tout `position_id` fermé
jamais vu ouvert — `stopLoss`/`takeProfit` à `0.0`, la convention MT5
elle-même pour « pas de stop », pas une valeur inventée, puisque les deals ne
portent pas ces champs). 7 tests ajoutés (17 au total côté observer),
`unittest.mock` stdlib, aucune nouvelle dépendance. `python -m py_compile`
et `python -m unittest` verts ; aucun changement côté TS/C#.

---

## 2026-09-05 (suite 3)

Outil : T05 (livré) — captures automatiques entrée/sortie. **La Vague 1 est
entièrement livrée** (T01–T05) ; reste la clôture de vague elle-même.

Décision d'architecture rediscutée en session et inversée par rapport à la
fiche initiale : la fiche proposait un rendu côté serveur .NET (SVG ou PNG).
L'utilisateur a signalé le défaut de raisonnement — porter `lib/analysis/` en
C# pour dessiner créerait une seconde source de vérité (contraire à l'ADR
0004), et le cockpit devra de toute façon savoir rendre un graphique pour
T06. Conception retenue : **le serveur capture des faits immuables et bornés
(fenêtre, prix), le cockpit rend l'image à la demande** avec
`analyzeMarketContext` — jamais une image pré-calculée. Candidat ADR identifié
pour la clôture de vague (le principe dépasse ce seul outil).

Deux trouvailles ont élargi le périmètre au-delà de la fiche :
- Le vrai événement de fill est `journal.position.opened`/`journal.trade_closed`
  (T02a/T02b), pas les rapports SIMULATED de la boucle de décision transitoire.
- `journal.position.opened` était détecté côté navigateur (T02a) — un trade
  manuel pris sans onglet cockpit ouvert ne déclenchait ni le comptage
  `tradesToday` ni, pour T05, la capture d'entrée. Migré côté Gateway (même
  schéma que la fermeture T02b : un seul diff `positions.snapshot` calcule
  ouvertures et fermetures, `seed_known_positions` évite tout événement
  fantôme au démarrage). Corrige un vrai bug T02a en le faisant.

Ajouts : `exitPrice` sur `journal.trade_closed`/`closed_trades` (moyenne
pondérée par volume, même risque de piège que T02b si on prenait un seul
deal) ; table `trade_captures` (écrite par une réplique dédiée hors pipeline
`PersistenceWriter` — l'écriture de la ligne 'exit' doit relire la ligne
'entry' d'abord, un envelope ne mappe pas vers deux tables) ; premier
endpoint de lecture par plage sur `candles` ; `lib/journal/chart-scale.ts`
(pur, testé) + `components/journal/trade-chart.tsx` (SVG) + viewer minimal
`/journal/[brokerPositionId]` (pas le journal complet — T06 reste le stub).

Gates tous verts : `npm run lint`, `npx tsc --noEmit`, `npm test` (107,
+6), `npm run build`, `dotnet build`, `dotnet test` (38, inchangé — glue DB
non testée en unitaire, même convention qu'ailleurs), `python -m unittest`
(10, +6). Non vérifié : la chaîne complète contre un terminal MT5 réel (pas
d'extension Chrome connectée, même limite qu'en T02/T03).

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
