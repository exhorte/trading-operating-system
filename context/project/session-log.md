# Journal de session

Append-only, la plus récente en haut. Une entrée par session, courte — le
détail vit dans la fiche de chaque outil (`context/product/tools/*.md`) et
dans `git log`. Voir ADR 0008 pour ce que ce fichier est et n'est pas.

---

## 2026-09-17 (**T15 livré** — serveur MCP ; second incident de lockout découvert en testant)

Session redémarrée (Docker/backend retombés, rien perdu — le commit
`1299753` était déjà poussé). Choix explicite après reprise : T15 plutôt que
T08. Fiche écrite en cartographiant d'abord ce qui existe déjà : aucune
nouvelle donnée nécessaire, tout passe déjà par du REST
(`/api/journal/trades`, `/api/risk/lockouts`, `/api/candles`,
`/api/setup-proposals`, `/api/execution/divergence`) — la seule vraie
question était où vit la logique de conformité T07, puisqu'elle n'est
persistée nulle part (calculée côté navigateur, à la demande).

Quatre décisions validées (« valide les quatre, enchaîne sur les
incréments ») : Node/TS via `tsx` (déjà une dépendance,
`scripts/run-setup-detection.ts` en est le patron), jamais Python (réservé
à MT5, ADR 0010) ni un service C# séparé — pour pouvoir **importer**
`lib/compliance/` directement plutôt que la réécrire dans un troisième
langage ; toujours via l'API REST existante, jamais Postgres/MT5 en
direct ; le serveur expose des faits, jamais une métrique de performance
pré-calculée (même ligne qu'ADR 0011) ; taille hors politique hors
périmètre (balance courante absente du REST).

Quatre incréments, gates vertes (tsc, lint, vitest 206/206, `next build`) :
squelette + `get_trades`/`get_lockouts`/`get_candles` ;
`get_setup_proposals`/`get_execution_divergence` ; `get_compliance_violations`
(import direct de `lib/compliance/evaluate.ts`) ; `tools/mcp-server/README.md`
+ `npm run mcp`.

**Vérifié par un vrai handshake MCP**, pas seulement les gates : messages
JSON-RPC construits à la main (`initialize`, `tools/call`), backend et
TimescaleDB relancés après le redémarrage de session, les 6 outils appelés
contre le vrai compte (477029930) et leurs réponses inspectées.

**En testant `get_compliance_violations` sur toute la plage 2026-09-14/15
plutôt que sur un seul trade, 5 positions EURUSDm de plus ressortent
ouvertes pendant un lockout actif** — la gate « Daily loss guard » du
2026-09-14 (`lockout-mu1af4l7-8lbceb`, verrouillée 13:37:28, jamais
acquittée avant le lendemain 08:54:25) : 3225706315, 3225729956, 3225966706,
3226050174, 3226089957. Jamais documenté avant ce jour — le seul incident
connu jusqu'ici était le trade isolé du 2026-09-15. Vérifié à la main
contre les horodatages bruts avant d'être retenu comme un fait, pas une
suspicion : une position XAUUSDm ouverte une seconde avant le
déclenchement du lockout (3225577967) n'est, à raison, pas comptée —
signe que la détection ne sur-déclenche pas. Ni un bug de T15 ni de T07 :
un fait réel, resté invisible parce que personne n'avait encore posé cette
question précise sur toute la plage. `state.md` mis à jour en conséquence
(« Ce qui bloque » — l'ampleur du problème double, pas la conclusion :
Vague 1 était déjà ouverte).

---

## 2026-09-16 (suite — **T07 livré**, tracker d'erreurs et taux de conformité)

Choisi explicitement après T06 (question ouverte : T07/T15/T08, tous
débloqués par T06). Fiche écrite en vérifiant chaque violation de la
taxonomie réduite (déjà posée par une session antérieure après le retrait
de T04) une par une plutôt qu'en bloc :

- Lockout actif, fenêtre de session : détectables proprement, données déjà
  là (`risk_lockouts`, `DEFAULT_SESSION_WINDOWS`).
- Taille hors politique : détectable, mais **pas** avec
  `evaluateSignalRisk` (`lib/risk/sizing.ts`) — cette fonction code en dur
  le facteur XAUUSD (« 1.00 price move on 1.0 lot ≈ 100 USD ») et aurait
  donné un faux verdict sur la majorité des trades réels, tous
  EURUSD/GBPUSD. La bonne formule passe par `symbolMetadata`
  (`lib/market/symbols/registry.ts`, tick size/value).
- Stop déplacé après l'entrée : pas détectable du tout — rien ne trace les
  modifications de position (`execution.modify` existe dans le protocole
  wire, jamais câblé).

Trois décisions soumises et validées (« valide les trois, enchaîne sur les
incréments ») : deux violations ce tour (lockout, session) ; taille
construite quand même avec la balance courante comme approximation de la
balance au moment du trade (pas de suivi historique de `account.snapshot`,
séparable plus tard si besoin) ; stop déplacé reporté, hors périmètre.

Quatre incréments, gates vertes à chaque étape (tsc, lint, `dotnet build`
0 warning, `dotnet test` 34, vitest 206 — 22 nouveaux, `next build`) :

1. `lib/compliance/violations.ts` — trois détecteurs purs, testés contre le
   **vrai** lockout kill-switch du 2026-09-15 (`lockout-mu2h6tvb-8qosw0`,
   requêté en base pour construire le fixture) : le trade EURUSDm de
   09:36:00 ressort bien en violation.
2. `lib/compliance/evaluate.ts` + `GET /api/risk/lockouts`
   (`RiskLockoutHistoryRepository`, nouveau — `RiskTodayRepository` ne
   couvre que « maintenant ») + colonne Violations sur `/journal`. Bug
   trouvé en écrivant l'intégration : `closed_trades.symbol` est le nom
   broker (`EURUSDm`), pas le canonique qu'attend `symbolMetadata` — le
   type `ComplianceTradeInput.symbol` est `SymbolCode | null`, et seul le
   contrôle de taille se désactive sur un symbole non résolu, jamais
   lockout/session avec lui.
3. `ComplianceBadge` dans `TopCommandBar` — fenêtre glissante de 7 jours,
   indépendante du filtre de `/journal`, même détecteurs.
4. Taille hors politique : déjà branchée depuis l'incrément 2 (conçue avec
   dès le départ) — rien à ajouter, seulement vérifié.

**Vérifié contre de vraies données.** `GET /api/risk/lockouts` appelé
directement contre la base réelle : retrouve le lockout kill-switch, et au
passage les 4 lignes « Daily loss guard » dupliquées à 73 ms d'intervalle du
2026-09-14 (artefact historique de l'ancien bug de course, corrigé le
2026-09-15 — sans conséquence ici). `ComplianceBadge` chargé dans le
navigateur intégré : rendu correct de son état « Conformité — » (aucun
compte connecté), aucune erreur console nouvelle. Même limite que T06 :
jamais vu rendu avec de vraies données à l'écran.

---

## 2026-09-16 (suite — **T06 livré**, journal auto-alimenté)

Choisi explicitement par l'utilisateur (« phase suivante » posée en question
ouverte après EA-06 : Vague 2/T06 préféré à EA-07 ou à la clôture de
Vague 1). Fiche écrite, trois décisions soumises et validées (« valide les
trois, enchaîne sur les incréments ») :

1. P&L réalisé par trade + calendrier P&L : oui, ce sont des faits sur des
   trades déjà pris. Expectancy/profit factor/taux de réussite/courbe
   d'équité : non dans ce tour — exactement le vocabulaire qu'[ADR 0011](../adr/0011-banc-de-replay.md)
   bannit pour le banc de replay, et ce que le charter écarte déjà comme KPI.
2. Aucune nouvelle table — vue de lecture pure sur `closed_trades`/
   `position_opens`/`trade_captures`/`setup_proposals` : ce que backlog.md
   décrivait comme « nouveau modèle de données à construire » existait déjà,
   éclaté sur quatre tables.
3. Lien Capture uniquement quand une ligne `trade_captures` existe —
   jamais un lien mort (deux trades du 2026-09-14 ont perdu leur capture de
   sortie pour de bon, voir le journal T05).

Quatre incréments, gates vertes à chaque étape (tsc, lint, `dotnet build`
0 warning, `dotnet test` 34, vitest 184, `next build`) :

1. `JournalRepository.GetTradesAsync` + `GET /api/journal/trades` —
   `LEFT JOIN` partout, pas l'`INNER JOIN` du précédent le plus proche
   (`SetupProposalRepository.GetClosedTradesAsync`) : un trade reste visible
   même sans `position_opens` ou sans capture.
2. `/journal` : table filtrable (dates, symbole côté client), lien Capture
   conditionnel.
3. Calendrier + ventilations (symbole, session, heure d'entrée, jour de la
   semaine), agrégées côté TypeScript depuis la même liste — aucun nouvel
   endpoint par vue.
4. Enrichissement EA-02 — trouvaille en cours de route : une fonction pure
   de rapprochement existait déjà, `lib/setup/reconciliation.ts::reconcile`
   (tolérance 5 min), déjà utilisée par `/setups`. Réutilisée telle quelle
   après avoir commencé à en écrire une seconde à 30 min — jetée avant
   d'aller plus loin.

**Vérifié contre de vraies données, au-delà des gates.** TimescaleDB
redémarrée (arrêtée depuis 6 h), backend relancé, `GET /api/journal/trades`
appelé directement contre les trades réels du 2026-09-14/15 (accountId
477029930) : jointures correctes, `entryPrice`/`stopLoss` bien `null` sur le
seul trade sans capture, et — trouvaille en vérifiant — **tous les autres
trades réels ont `stopLoss: 0`** (jamais posé pendant cette période
OBSERVE), donc la colonne R multiple est vide sur les données actuelles :
honnête, pas une régression. `GET /api/setup-proposals` ne renvoie que des
`blocked` (cohérent avec le taux d'accord EA-02 toujours à 0/595) : rien à
accrocher pour l'incrément 4 aujourd'hui, vérifié comme vide plutôt que
supposé.

**Non vérifié : le rendu dans un navigateur.** `/journal` chargé dans le
navigateur intégré — aucune erreur console, l'état de chargement s'affiche
correctement — mais aucun agent MT5 n'est connecté à ce backend fraîchement
relancé, donc `useCockpit().account` reste `null` indéfiniment (même
comportement que toute autre page du cockpit sans connexion live). Table,
calendrier et ventilations jamais vus rendus à l'écran avec des données
réelles.

---

## 2026-09-16 (**EA-06 livré** — résolution `UNKNOWN`, positions externes, surface cockpit)

Fiche écrite et deux décisions soumises la veille (« lance EA-06
maintenant ») ; validées telles que proposées ce jour (« valide les deux,
enchaîne sur les incréments ») : comportement par défaut `WARN` sur une
position externe (l'exposition est déjà comptée sans distinction via
`PositionsTotal()`, ce qui manque est l'attribution, pas une barrière de
plus), et logique de réconciliation dans l'agent MQL5 (seul endroit avec un
accès direct à `HistoryDealsGet`/`PositionsGet`, même raisonnement que
l'observer Python pour `scan_missed_round_trips`).

Quatre incréments, gates vertes à chaque étape :

1. **Wire** — `Mt5ReconciledMessage`/`Mt5PositionScannedMessage` dans
   `mt5-wire.ts` + miroirs C#. Un message par position, jamais un tableau
   (`JsonLite.mqh` ne lit que du plat).
2. **Résolution `UNKNOWN`** — `CommandStore.mqh` gagne
   `CommandStoreFindUnknown` (énumération, n'existait pas). L'agent cherche
   par `InpMagicNumber` + `"TradingOS "+commandId` dans le commentaire du
   deal/ordre, lit toujours `DEAL_POSITION_ID`, jamais un ticket — le piège
   du 2026-09-05 revérifié à la main. Déclenché sur le heartbeat et sur
   toute connexion. Écart assumé par rapport au brouillon de la fiche :
   `not_found` n'abandonne jamais (pas de plafond à 3 tentatives, pas de
   `RECONCILIATION_PENDING`) — détail dans le journal de la fiche.
3. **Positions externes** — `ScanOpenPositions`, `isExternal` sur magic
   number seul, `POSITION_IDENTIFIER` jamais un ticket. Corrigé au passage
   un commentaire d'EA-05 qui annonçait à tort qu'EA-06 exclurait les
   positions externes du compte `PositionsTotal()` — c'est l'inverse de la
   décision validée ; le compte n'a pas bougé.
4. **Persistance + cockpit** — `command_reconciliations`/`position_scans`
   (upsert, pas d'accumulation — `envelopes` porte déjà l'historique
   complet) ; `GET /api/execution/divergence` ; `/positions` sort de son
   placeholder (il réservait déjà ce texte à « reconciliation state »).
   Nommé « divergence », pas « réconciliation », pour ne pas percuter le
   sens qu'EA-02 donne déjà à ce mot (`SetupProposalRepository`).

Gates : MetaEditor 0/0 à chaque incrément MQL5, tsc, lint, `dotnet build`
(0 warning), `dotnet test` (34), vitest (184), `next build`.

**Deux limites assumées, pas cachées** (détail : journal de la fiche EA-06) :
la propagation du commentaire de commande jusqu'au deal MT5 est une
hypothèse jamais vérifiée en réel — `OrderSend` n'a encore jamais tourné ;
et le scénario « mort de l'agent entre `OrderSend` et l'accusé » n'a été
vérifié que par lecture du code (même méthode que l'incrément 6 d'EA-05),
jamais par un test exécuté — aucun harnais MQL5 n'existe dans ce dépôt.

Seul l'incrément 3 produit du trafic réel dès aujourd'hui (`PositionsTotal()`
ne dépend pas du mode) ; l'incrément 2 reste sans trafic tant qu'`OrderSend`
est inatteignable. `OrderSend` lui-même : vérifié inchangé après les 4
incréments (un seul site d'appel, `g_mode` toujours `const MODE_OBSERVE`).
`state.md` : plus de « prochaine action » construite — le projet passe en
observation jusqu'à ce que les préconditions d'EA-07 se remplissent par de
vrais trades.

---

## 2026-09-15 (suite — rendu T05 réparé, course de lockout corrigée, **EA-05 incrément 6 livré**)

**Rendu des captures, réparé et vérifié à l'écran.** Deux défauts, pas un.
(1) Le viewer demandait le timeframe déclaré par la capture — « M15 », hérité
de l'observer XAUUSD — pour un symbole qui n'a que du M1 en base. Corrigé
dans `app/(cockpit)/journal/[brokerPositionId]/page.tsx` : si le store n'a
rien au timeframe déclaré, il le rebâtit depuis le M1 avec `aggregateCandles`
(la fonction pure et testée d'EA-02). Le repli vit côté TypeScript et pas
dans le `/api/candles` en C# parce que l'ADR 0004 interdit de réimplémenter
le moteur d'analyse dans un autre langage. (2) Une fois les bougies là, elles
restaient invisibles : les marqueurs `SL 0` / `TP 0` — MT5 écrit 0 pour « pas
de stop posé », pas « stop à zéro » — tiraient `computePriceScale` de 0 à
1,1534 et écrasaient 24 bougies en une bande d'un pixel. `buildMarkers`
n'émet plus de ligne pour un niveau absent : une ligne absente se lit
correctement comme « aucun stop ». Vérifié sur la position 3230177984 :
24 bougies M15 agrégées depuis 361 M1, entrée, sortie, overlay order-block.
Premier rendu T05 jamais validé visuellement sur EURUSD.

**Course sur le registre de lockout, corrigée.** Les 4 lignes « Daily loss
guard » à 73 ms d'intervalle du 2026-09-14 : `detectNewLockout` est
correctement edge-triggered sur son entrée, mais l'appelant lui passait un
`activeLockout` périmé — le store n'apprend l'existence du lockout qu'au
retour de l'écho du hub, et les ticks continuent de déclencher des recalculs
pendant ce temps. Ajout d'un `lockoutPublishPending` dans
`signalr-client.ts`, remis à false dès que l'écho atterrit, donc il ne peut
jamais masquer un verrou réellement nouveau. Logique pure inchangée.

**EA-05 incrément 6 — livré, sur accord explicite et séparé.** L'utilisateur
l'a demandé nommément après que j'aie refusé de l'inclure dans une demande
générale de clôture la veille ; c'est le feu vert que la fiche attendait.

Le dépôt contient désormais **un** `OrderSend`, et un seul. Vérifié en lisant
le code, comme la fiche l'impose, pas en me croyant : `grep` sur tout le
dépôt → un seul site d'appel ; il est dans `ExecuteOrder` dont la première
instruction sort si le mode n'est pas `CONFIRM` ; `ExecuteOrder` n'a qu'un
appelant, lui-même derrière un test de mode ; et `g_mode` est déclaré une
fois en `const … = MODE_OBSERVE` et **jamais affecté nulle part**. Le chemin
est donc prouvablement mort dans ce build — écrire la voie et pouvoir
l'emprunter sont deux accords distincts, et le second (EA-07) n'est pas
demandé ni rempli.

Idempotence traitée à l'endroit qui compte : `UNKNOWN` écrit sur disque
**avant** l'appel broker, résultat réel réécrit après — un agent qui meurt
au milieu laisse `UNKNOWN`, et le rejeu retourne `DUPLICATE` sans jamais
renvoyer d'ordre. Un refus broker est un résultat définitif (`FAILED`), pas
une ambiguïté. Trouvé au passage : `tp` n'était parsé nulle part dans
`HandleOrderCommand` alors que le wire l'envoie — ajouté.

Corrections exigées par l'ADR 0010 faites dans la foulée : `README.md` et
`.claude/CLAUDE.md` ne prétendent plus qu'aucun appel de trade n'existe — ils
décrivent la barrière, et CLAUDE.md gagne une consigne explicite de ne pas
l'élargir sans accord séparé. `charter.md` n'a pas eu à bouger : son principe
6 (« aucun ordre n'est envoyé sans qu'un humain l'ait déclenché ») reste vrai.

Gates : `MetaEditor64.exe /compile` → **0 errors, 0 warnings** ; lint, tsc,
184 tests TS, `npm run build`, `py_compile`, `dotnet build` (0 warning),
`dotnet test` (34). Prochaine action passée à EA-06 dans `state.md`.

---

## 2026-09-15 (kill switch réel, correctif T05 confirmé, gap de rendu trouvé — Vague 1 toujours ouverte)

Reprise après redémarrage complet de session (docker/backend/observer/worker
tous tombés avec la session précédente) — toute la chaîne relancée et
revérifiée avant tout diagnostic, pas supposée repartie seule.

**Reset de minuit** : confirmé que le mécanisme est bien côté client, comme
prévu la veille. `dayAnchorStartsAtUtc` avait basculé côté serveur
(2026-09-15T00:00:00Z), mais le lockout *Daily loss guard* est resté marqué
actif jusqu'à la reconnexion du cockpit — personne n'était là au moment de
la bascule. Levé automatiquement (`next-day-reset`) à la reconnexion.

**Kill switch testé pour de vrai par l'utilisateur.** Cycle complet tracé en
base : verrouillage 09:34:44 UTC (`risk_lockouts`, raison « Kill switch
manuel ») → acquittement 09:37:15 (`kill_switch_acks`) → levée 09:37:18
(`cleared_by = kill-switch-ack`, seul chemin qui existe dans le code pour ce
type de lockout). Ferme la case correspondante de la checklist T02a/T02b —
la seule qui ne dépendait que de l'utilisateur.

**Trouvé en vérifiant la clôture de Vague 1** : une position EURUSDm a été
ouverte à 09:36:00 UTC — **pendant** la fenêtre du lockout kill-switch
(09:34:44 → 09:37:18), fermée 60 s plus tard à 09:37:00, avant même
l'acquittement. C'est exactement la situation que le critère de sortie
reformulé la veille interdit. Constat neutre, pas une remontrance : la vague
reste ouverte, et c'est le critère qui fonctionne, pas un échec à cacher.

**Correctif T05 (course entrée/sortie) confirmé en conditions réelles.** Le
même trade (60 s, plus rapide que les deux qui avaient échoué le
2026-09-14) a ses deux captures — entrée et sortie — vérifiées via l'API.
Le correctif tient en production, pas seulement aux gates.

**Trouvé en vérifiant le rendu, jamais fait avant** : `/journal/3230177984`
affiche « No candles in the captured window » sur les deux captures. Cause
identifiée : `candles` ne porte que du M1 pour EURUSDm/GBPUSDm (pipeline
EA-02) et que du M15 pour XAUUSDm (seul symbole que diffuse
`mt5_observer.py`). Le rendu de capture demande du M15 dans la fenêtre —
absent pour tout symbole hors XAUUSD, donc pour tout le périmètre réel de
S01 (EURUSD/GBPUSD). Les faits sont bien écrits ; seul le rendu échoue.
Non corrigé — décision de conception à prendre (agréger le M1 à la volée
côté rendu, ou persister le M15 depuis le worker EA-02), pas un correctif
d'une ligne. Détail dans le journal de `T05-captures-auto.md`.

**Précision trouvée sur la barrière EA-07** : T02a (kill switch, daily loss
guard) a tourné en réel plusieurs fois. **T02b — la pause temporisée de
30 min sur deux pertes consécutives — n'a elle jamais été déclenchée** :
un seul trade perdant est survenu à ce jour, jamais deux d'affilée
(`risk_lockouts` : zéro ligne avec `until` renseigné). La barrière d'EA-07
n'est donc que partiellement remplie, pas entièrement comme on aurait pu le
lire trop vite dans le state.md d'avant cette entrée.

**EA-02, état chiffré** : 595 évaluations à ce jour, **zéro** `proposed`.
Toutes bloquées avant la séquence S01 elle-même (fenêtre horaire, lockout,
ou biais H4/D1 non aligné). Le taux d'accord reste à l'état de pipeline
fonctionnel, pas de mesure — sans changement de fond depuis la veille.

**Explicitement pas touché, sur demande de « clôturer toutes les phases
ouvertes »** : EA-05 incrément 6 (`OrderSend`). Aucune formulation de
demande de clôture globale ne vaut accord explicite séparé pour celui-ci —
c'est la règle elle-même (ADR 0010, fiche EA-05) et elle ne se déduit pas.
Toujours pas donné.

`state.md` mis à jour en conséquence (bloque désormais sur trois points
précis plutôt qu'un vague « rien n'est vérifié ») ; `context/product/tools/T05-captures-auto.md`
complété (correctif confirmé + gap de rendu trouvé) ; `03_Suivi_Projet/Suivi.md`
resynchronisé dans la foulée.

---

## 2026-09-14 (suite — correctif calendrier EA-02, recadrage post-T01/T04)

Quatre tâches enchaînées après « à part attacher l'EA, que peut-on faire
pour avancer maintenant ».

**1. Correctif fail-closed du gate calendrier, worker EA-02.** Trouvé en
vérifiant ce qui bloquerait réellement `run-setup-detection.ts` une fois le
lockout levé : `upcomingReleases(client)` faisait un `SELECT` brut sur
`news_releases` et renvoyait `[]` si la table était vide — jamais `null`.
`isNewsBlackout(now, [], ...)` avec un tableau vide renvoie `false` (pas de
blackout). Résultat : la précondition calendrier **ne bloquait jamais rien**
dans ce worker, contrairement au vrai gate T03 côté backend .NET
(`NewsCalendarRepository.GetUpcomingOrNullAsync`, qui distingue correctement
« jamais synchronisé » de « synchronisé, rien à venir » via
`SELECT EXISTS(...)`). Corrigé en miroir exact de ce mécanisme :
`upcomingReleases` renvoie maintenant `null` si la table est vide, et
l'appelant bloque explicitement (`precondition_calendar`,
« FRED calendar never synced — fail-closed ») avant même d'appeler
`isNewsBlackout`. Pas de test dédié (le script fait de l'I/O Postgres directe,
même statut que le reste des composants socket/DB du dépôt). Effet non
observable en direct cette session : à l'heure du correctif (16h UTC), la
précondition de fenêtre horaire bloque déjà avant d'atteindre le calendrier —
se vérifiera à la prochaine fenêtre Londres ou NY AM.

**2. Recadrage T06/T07 post-retrait de T04.** La fiche d'origine de T06
dépendait explicitement du contexte du ticket T04 (setup déclaré, biais,
confiance, invalidation — capturés avant que le résultat ne biaise le
souvenir). Sans T04, ce contexte n'existe plus : T06 redevient un journal des
faits d'exécution (base + captures T05 + `setup_proposals` d'EA-02 en
approximation machine, jamais l'intention humaine), pas des intentions.
Conséquence en cascade sur T07 : sa taxonomie fermée comptait *« trade hors
plan »* et *« absence de ticket »* — toutes deux supposent un plan déclaré.
Redéfini vers ce qui reste mesurable sans déclaration : stop déplacé, taille
hors politique, trade pendant lockout, trade hors fenêtre. Écrit dans
`context/product/backlog.md` et `context/project/roadmap.md`.

**3. Critère de sortie de Vague 1 reformulé.** L'original (« dimensionner,
armer et journaliser via le cockpit ») n'a plus de sens sans T01/T04. Nouveau
critère, sur ce qui reste (T02/T03/T05, une couche passive) pendant une
séance réelle : kill switch déclenché et acquitté pour de vrai, capture
entrée+sortie sur chaque trade sans exception, aucune règle de risque active
contournée en tradant directement dans MT5. Décision prise par moi, à
l'instruction explicite de l'utilisateur (« enchaîne jusqu'à la fin ») —
signalée comme telle, pas illustrée comme si elle allait de soi. Noté
explicitement : la séance du jour même ne remplit pas ce critère (deux trades
EURUSD pendant un lockout actif), donc ne clôt pas la vague — le critère
fonctionne, il ne s'auto-valide pas complaisamment.

**4. `roadmap.md` nettoyé** : lignes T01/T04 marquées retirées, table Vague 2
mise à jour, `03_Suivi_Projet/Suivi.md` corrigé sur son unique mention de T04
(reste de la staleness de ce fichier hors périmètre — il datait du
2026-09-11, avant toute la séance EA-05 ; son propre en-tête dit que le dépôt
fait foi en cas de divergence).

Gates vertes (tsc, lint, 184 tests TS — inchangé, aucune logique pure
touchée). Worker EA-02 relancé sur le code à jour.

---

## 2026-09-14 (suite — retrait du pipeline Signal → RiskDecision → Command factice)

Trouvé en répondant à « à quoi sert l'interface Signals » : `signalr-client.ts`
(le client **réel**, pas mock) démarrait sans condition, à chaque connexion,
une boucle Phase 09 vieille d'avant le pivot — toutes les 30s, elle fabriquait
un faux `StrategySignal` à partir du **vrai** contexte de marché et du **vrai**
état de compte, le faisait juger par le **vrai** Risk Engine, et — si approuvé
— soumettait une **vraie** `PlaceOrderCommand` via `connection.invoke("SubmitCommand", ...)`,
le même chemin que l'agent EA-05 réel. Vérifié en base avant toute suppression :
309 lignes dans `strategy_signals`/`risk_decisions`, 0 dans `execution_commands`
— aucune n'avait encore atteint la soumission, mais rien ne l'empêchait
structurellement. Aucun risque financier dans tous les cas (EA-05 est
`OBSERVE` figé, pas d'`OrderSend`), mais de quoi polluer une vraie séance de
vérification EA-05 avec des rapports `SIMULATED` fantômes.

**Erreur évitée en creusant avant de couper** : la fiche EA-03 documente
`lib/execution/command-builder.ts::buildPlaceOrderCommand` comme *« seule
porte d'entrée d'une commande, dérivée d'une RiskDecision approuvée »* — ce
n'est pas un reliquat de la boucle factice, c'est le protocole réel qu'EA-05
consomme en aval. Conservés intacts : `command-builder.ts` (+ test),
`lib/domain/execution.ts`, `lib/domain/strategy.ts` (type dont
`buildPlaceOrderCommand` dépend), `lib/contracts/commands.ts`,
`CockpitHub.SubmitCommand`, et tout l'audit `CommandRow`/`AckRow`/`ReportRow`
(`execution_commands`, `command_acks`, `execution_reports` — ce dernier sert
la télémétrie EA-05 réelle, `execution.order.simulated` alimente les deux).

Retiré, précisément : la boucle elle-même (`startSignalLoop`/`runDecisionLoop`
+ `submitCommand`/`onAckTimeout`/`pendingAcks`, glue client-side propre à son
rythme de fake-submit, pas documentée comme protocole par EA-03) des deux
clients (réel et mock — sans UI pour l'afficher, le générateur mock devenait
lui aussi sans objet) ; `StrategySignal`/`RiskDecisionView`/`ExecutionCommandView`
(lecture-modèle dashboard, `signalId`-shaped, distincts du `StrategySignal`
domaine que `command-builder.ts` garde) ; les pages/composants `/signals`,
`signal-queue.tsx` (+ son point de montage sur Command Center) ; `SignalRow`/
`DecisionRow` et leurs tables `strategy_signals`/`risk_decisions` (`DROP
TABLE`-ées en local) ; les entrées `strategy.signal.created`/`risk.decision.made`
de la liste blanche `CockpitHub.PublishableTypes` et de `EventType`. Trouvé et
nettoyé au passage : `journal.ticket.created` traînait encore dans `envelope.ts`
depuis le retrait de T04 — oublié la première fois.

Gates vertes (lint, tsc, 184 tests TS — 202 au départ de la séance, T01/T04 et
ceci expliquent la baisse —, build, `dotnet build`, `dotnet test` 34).
Backend et cockpit relancés sur le code à jour.

---

## 2026-09-14 (retrait T01/T04, correctif T05, séance réelle EA-02)

Séance avec trading réel en parallèle (compte démo 477029930), pipeline
EA-02 tournant en continu. Trois choses faites, dans l'ordre où elles sont
arrivées :

**Correctif T05** — `TradeCaptureRepository.RecordExitAsync` no-opait
silencieusement sur deux trades EURUSDm réels (47 s et 2 min 13 de durée de
vie), alors que `closed_trades` les avait bien. Cause : `RecordEntryAsync`
et `RecordExitAsync` sont dispatchées fire-and-forget depuis
`GatewayBridgeService`, chacune sur sa propre connexion, sans garantie
d'ordre — sur un aller-retour assez rapide, l'exit peut chercher la ligne
'entry' avant que son insert ait committé. Corrigé par une relecture bornée
(5 tentatives, 200 ms d'écart) dans `FindEntryWithRetryAsync` — le cas
« aucune entrée n'existera jamais » (position antérieure au backend, ex. la
position backfillée le même jour) continue de no-oper exactement comme
avant, une fois le budget de tentatives épuisé. Gates vertes. Pas de test
dédié ajouté — même précédent que le reste des classes socket/DB de ce
fichier, vérifiées en intégration.

**Retrait T01 + T04** — décision explicite de l'utilisateur, pas la mienne :
panneau de sizing et ticket pré-trade supprimés du cockpit, ainsi que toute
la chaîne qui les portait (`lib/domain/ticket.ts`, le chemin
`journal.ticket.created` de bout en bout côté TS et C#, la table
`pretrade_tickets`). Détail complet dans le journal des fiches T01 et T04.
Rien d'autre n'en dépendait — vérifié par grep avant de couper, pas supposé.
Gates vertes après coup (lint, tsc, 193 tests TS, build, `dotnet build`/`test`
36). Conséquence non résolue dans cette entrée : le critère de sortie de la
Vague 1 (« séance 100% cockpit ») perd deux de ses trois outils — à
retrancher ou reformuler la prochaine fois que la clôture de vague est
rediscutée.

**Trading réel pendant la séance** — 5 puis plusieurs trades supplémentaires
pris directement dans MT5 (XAUUSDm et EURUSDm), aucun via le cockpit. Un
trade (position 3225412263, TP-gagnant) manqué par l'observer parce qu'il a
tourné entièrement avant que `mt5_observer.py` soit relancé en session
précédente — backfillé dans `closed_trades`/`position_opens` à partir de
`mt5.history_deals_get()`, valeurs identiques à ce que l'observer aurait
écrit (`sum_realized_pnl`/`weighted_exit_price` recalculés à la main). Un
lockout *Daily loss guard* s'est déclenché en réel (13:37:28) sur la perte
flottante d'une position XAUUSDm — confirmé qu'il n'existe aucun clear
manuel pour ce type de lockout (`acknowledgeLockout` est câblé en dur sur
`kill-switch-ack`), seulement `shouldAutoClearForNewDay` au prochain
rollover UTC, et seulement si le cockpit est ouvert à ce moment pour
l'évaluer. Aucun des trades du jour n'avait de stop-loss — le critère « R
cohérent » de la checklist T02a/T02b reste donc non vérifiable, pas par
manque de code mais par absence de stop sur les trades réels.

---

## 2026-09-12 (EA-05 — incréments 2–5 livrés, en attente avant l'exécution)

Agent MQL5. Cartographie avant code a trouvé un trou structurel que le
prompt de lancement ne nommait pas : aucun point d'écoute Gateway n'existait
pour un agent entrant (`Mt5ObserverClient` ne fait que dialer *vers*
l'observer Python). Trouvé aussi un conflit documentaire :
`context/realtime/mt5_agent_realtime_lifecycle.md` décrit une architecture
sidecar pré-pivot, obsolète, contredisant `mt5_wire_protocol.md`. Deux
décisions validées avec l'utilisateur : TCP brut (pas WSS) entre l'agent et
le Gateway, et le nouveau point d'écoute dans le périmètre de cette fiche.

Livré : `Mt5AgentServer.cs` (nouveau, jamais fusionné avec l'observer),
`CockpitHub`/`GatewayBridgeService`/`Program.cs` branchés,
`tools/mt5-execution-agent/TradingOsAgent.mq5` + deux includes (JSON plat
maison, persistance `commandId → résultat` sur disque), toutes les
barrières locales de `safety.md` sauf l'exécution elle-même. **Aucun
`OrderSend` dans le fichier.** Correction en route : `Mt5ExecutionMode`
portait encore `"live"` (vocabulaire pré-ADR 0010) — renommé `"confirm"`,
renommage pur vérifié sans effet de bord.

Nouvelle gate ajoutée : compilation MQL5 headless via `MetaEditor64.exe`
(trouvé installé localement), 0 erreur sur le premier essai.

Ouvert : incréments 2–5 vérifiés seulement par compilation au moment
d'écrire ce qui précède. **Mise à jour même session** — l'utilisateur a
testé les incréments 2 à 5 contre un vrai terminal, tout est vert (procédure
du README de l'outil suivie). L'incrément 6 (exécution) reste soumis à un
accord explicite séparé, distinct de cette vérification, conformément à
l'ADR 0010 — pas encore donné.

---

## 2026-09-12 (EA-04 — livré)

Profils de compte, modèle de coût, registre de symboles. Cartographie avant
code : `TradingAccount`/`AccountKind` (`lib/domain/account.ts`) existaient
déjà mais n'étaient utilisés nulle part ; `RiskProfile` demandé par le prompt
de lancement est le même concept que `RiskPolicy` existant. La porte de coût
d'EA-01 attendait déjà `costThreshold`/`commission` en paramètres — seul
`scripts/run-setup-detection.ts` les codait en dur.

Trois décisions validées avec l'utilisateur avant code : réutiliser
`AccountKind` plutôt qu'un second axe `AccountType`, `XAUUSDm` comme symbole
XAUUSD canonique (`XAUUSD247m` documenté à part), et une structure FTMO avec
placeholders `TODO(FTMO-rules)` documentés plutôt que des chiffres devinés —
le compte FTMO n'existe pas encore.

Livré : `lib/market/symbols/registry.ts` (canonique↔broker, réutilise
`SymbolMetadata`), `lib/accounts/{types,cost-model,ftmo,real,registry}.ts`,
`defaultRiskPolicy` étendu avec un paramètre `registry` optionnel (signature
compatible, les cinq appelants réels dont T01 sont inchangés puisque le
registre réel est vide), et le câblage réel dans
`scripts/run-setup-detection.ts`. T01 vérifié inchangé — cette fiche rend la
*policy* multi-compte, pas le *sizing* multi-symbole (hors périmètre,
assumé).

Ouvert : `ACCOUNT_PROFILES` reste vide tant qu'un compte FTMO ou réel n'est
pas confirmé ; les valeurs FTMO/real restent des placeholders à renseigner
depuis la source officielle avant d'enregistrer un compte.

---

## 2026-09-12 (EA-03 — livré)

Protocole d'exécution et machine à états, sans MQL5 ni réseau. Cartographie
avant code : le chemin `RiskDecision → Command → ACK → Report` existait déjà
au niveau wire, mais sans machine à états nommée, sans `UNKNOWN`, sans
`ACCOUNT_MISMATCH`, sans `protocolVersion` explicite sur la commande.

Décision d'architecture validée avec l'utilisateur : la machine à états (12
états, `transition()` pure) vit dans `lib/domain/execution-state.ts`, pas
dans `lib/contracts/execution/` — écart assumé au texte du prompt de
lancement, par cohérence avec l'ADR 0004. `lib/contracts/execution/` porte le
vocabulaire de rejet typé (`ACCOUNT_MISMATCH` en premier) et la règle
d'idempotence (`recordOrReplay`, testée : un rejeu ne ré-exécute jamais).
Trois documents `context/execution/{protocol,state-machine,safety}.md`
écrits. `CockpitHub.SubmitCommand` non branché — posé pour EA-05/EA-06.

Ouvert : le branchement réel (persistance de l'état par `commandId`,
vérification `ACCOUNT_MISMATCH` contre un agent réel, résolution
d'`UNKNOWN`) attend l'agent MQL5 (EA-05) et la réconciliation (EA-06).

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
