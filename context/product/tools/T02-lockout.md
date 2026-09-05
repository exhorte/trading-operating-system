# T02 — Lockout comportemental

Statut : **livré** (T02a et T02b livrés le 2026-09-05) · Vague 1 · Effort 1–2 j · Dépend de : rien

Découpé en deux incréments en cours de route — le plan initial (7 incréments,
4 à 6 jours) mélangeait quatre verrous qui ne demandent rien à l'observer
avec un seul qui a besoin de l'historique des deals MT5. Voir le journal.

## Problème

Le mode d'échec dominant de l'intraday n'est pas la mauvaise analyse : c'est la séquence deux pertes → trade hors plan pour se refaire → taille doublée. Aucun rappel écrit n'a jamais arrêté ça. Seul un système qui refuse l'ordre l'arrête.

## Comportement attendu

Des verrous durs, configurés à froid, appliqués à chaud :

| Verrou | Effet | Statut |
|---|---|---|
| Perte quotidienne maximale atteinte | Séance verrouillée jusqu'au lendemain | **livré (T02a)** |
| Nombre de trades maximum atteint | Séance verrouillée | **livré (T02a)** |
| Hors fenêtre de session autorisée | Refus | déjà livré avant T02 (`sessionGate`) |
| Kill switch manuel | Verrouille + bandeau manuel (pas de fermeture réelle) | **livré (T02a)** |
| Deux pertes consécutives | Pause forcée de 30 min, chrono affiché | **livré (T02b)** |

L'état de verrouillage **persiste** : recharger la page ne déverrouille rien. Chaque refus porte un motif lisible et est tracé.

## Ancrage dans le code

- `lib/risk/gates.ts` — `maxTradesGate`, `consecutiveLossGate`, `sessionGate` **existent déjà** et sont inchangées. Elles restent de pures fonctions d'affichage (« combien utilisé sur combien autorisé ») ; ce qui manque était les compteurs réels et la persistance de la décision de verrouiller — livrés dans T02a via un mécanisme séparé (voir journal).
- `lib/risk/evaluate.ts` — `evaluateRiskState` inchangée. `RiskState.mode` qu'elle calcule est maintenant traité comme une proposition, pas un verdict final : `lib/risk/lockout.ts::applyActiveLockout` a le dernier mot.
- `lib/risk/lockout.ts` (nouveau, T02a) — `detectNewLockout`, `applyActiveLockout`, `shouldAutoClearForNewDay`. Le ledger (`risk_lockouts`) est la source de vérité pour « verrouillé maintenant », jamais re-dérivé du calcul live seul.
- `lockoutUntil` ajouté à `RiskStatus` (`lib/contracts/snapshots.ts`) et à sa projection — la trouvaille de T01 est résolue. `null` pour les verrous T02a (clairance manuelle/lendemain) ; peuplé par T02b pour la pause de 30 min.
- Le refus reste une `RiskDecision` refusée sur le chemin `RiskDecision → Command → ACK → Report` (ADR 0007), pas un `disabled` React — `applyActiveLockout` alimente `RiskState.mode`, qui alimente `evaluateSignalRisk`, inchangé.
- T02b — `tools/mt5-observer/mt5_observer.py::poll_positions/build_position_closed/sum_realized_pnl`, wire `Mt5PositionClosedMessage` (TS + C#), `Mt5ObserverClient` case → `journal.trade_closed` (Gateway-direct, comme `risk.day_anchor.resolved`), table `closed_trades`, `RiskTodayRepository.CountConsecutiveLosses`, `lib/risk/lockout.ts::detectConsecutiveLossPause/isLockoutExpired`, chrono dans `RiskStatusPanel`.

## Limite assumée

Tant que MT5 est ouvert à côté, le verrou est un ralentisseur, pas un mur. C'est suffisant : la friction de vingt secondes est exactement ce qui manque au revenge trade. Une version « mur » (déverrouillage différé de 24 h) est possible plus tard — ne pas la construire d'emblée.

## T02b — plan d'implémentation

Écrit le 2026-09-05 pour qu'une session à froid (post `/clear`) puisse
démarrer directement sans repasser par l'analyse. Toutes les décisions
ci-dessous sont déjà validées (voir journal) ; ce qui suit est le
« comment », pas un nouveau « si ». Lire quand même le journal T02a avant de
coder — les patterns (ledger stocké, `PublishEvent` vs Gateway direct,
`applyActiveLockout`) s'y expliquent, ici ils s'appliquent.

**1. Observer (`tools/mt5-observer/mt5_observer.py`)** — détection de
clôture : garder un `set[int]` des `brokerPositionId` déjà vus (comme le
faisait `positions_get()` avant, mais côté Python cette fois). Quand un
ticket connu disparaît de `positions_get()`, appeler
`mt5.history_deals_get(position=ticket)`. **Piège signalé en revue** : une
position peut avoir plusieurs deals de clôture (fermetures partielles) —
sommer `profit + commission + swap` sur **tous** les deals de ce
`position_id` (entrée comme sortie), jamais un seul deal isolé, sinon un
gagnant partiellement fermé qui finit négatif après swap est compté comme un
gain. Émettre un nouveau message wire `position.closed` : `brokerPositionId`,
`symbol`, `side`, `volume`, `realizedPnl` (la somme ci-dessus), `closedAt`
(epoch ms, `now_ms()`).

**2. Wire (`lib/contracts/mt5-wire.ts` + `backend/.../Mt5Wire.cs`)** —
nouveau type `Mt5PositionClosedMessage` (mirroir TS/C#, même convention que
`Mt5PositionSnapshot`). Ajouter `"position.closed"` à `Mt5MessageType`
(TS) et au `switch` de `Mt5WireParser.Parse` (C#).

**3. Gateway (`Mt5ObserverClient.Handle`)** — nouveau `case
Mt5PositionClosedMessage`, publié en direct comme `agent.snapshot.account`
(**pas** via `PublishEvent` — c'est un fait MT5 réel, seul l'observer peut
le connaître, même catégorie que `risk.day_anchor.resolved`). Type
d'événement : `journal.trade_closed` (cohérent avec le namespace `journal.`
déjà utilisé pour les tickets T04 et `journal.position.opened` de T02a).
Payload : `{accountId, brokerPositionId, symbol, side, volume, realizedPnl, closedAt}`.

**4. Persistance** — table `closed_trades` (`account_id`,
`broker_position_id` PK composite, `symbol`, `side`, `volume`,
`realized_pnl`, `closed_at`) ; `ClosedTradeRow` + case dans
`PersistenceMapper`/`PersistenceWriter`, `ON CONFLICT DO NOTHING`.
**Pas de scope par jour** : contrairement à `tradesToday`, la séquence de
pertes consécutives ne se réinitialise pas à minuit — deux pertes fin de
journée puis une à l'ouverture du lendemain restent trois pertes
consécutives. Compter la traîne de `realized_pnl < 0` triée par
`closed_at DESC` jusqu'à la première ligne non perdante, sans filtrer par ancre.

**5. `GET /api/risk/today`** — étendre `RiskTodaySummary`
(`RiskTodayRepository.cs`) avec `consecutiveLosses: int` et
`lastConsecutiveLossAt: string | null` (calculés depuis `closed_trades`
comme au point 4). Filtrer aussi `activeLockout` sur `until IS NULL OR until > now()`
— un verrou temporisé expiré ne doit plus apparaître comme actif à
l'hydratation (voir point 7).

**6. `lib/risk/lockout.ts`** — nouvelle fonction dédiée, ne pas surcharger
`detectNewLockout` (sémantique différente : celle-ci calcule un `until`) :
```ts
export function detectConsecutiveLossPause(
  state: RiskState,
  activeLockout: ActiveLockout | null,
  lastConsecutiveLossAt: UtcTimestamp | null,
  pauseMinutes: number,
): { reason: string; until: UtcTimestamp } | null
```
Édge-triggered comme `detectNewLockout` (ne republie pas à chaque
évaluation). `until = lastConsecutiveLossAt + pauseMinutes`. Tests : pause
posée à la 2e perte, pas republiée à la 3e tant que la pause court, pas
posée si `activeLockout` existe déjà pour une autre raison.

**7. `applyActiveLockout`** — actuellement traite tout `activeLockout` non
nul comme verrouillant sans condition. Ajouter le paramètre `now` et
traiter un verrou dont `until !== null && until <= now` comme expiré (état
retourné inchangé, pas `locked`). Dans ce cas, le client qui le détecte doit
aussi publier `risk.lockout.cleared` (`clearedBy: "pause-expired"`) pour que
le ledger ne reste pas avec une ligne stale — sinon un rechargement juste
après expiration relit une ligne « active » au sens de l'ancienne requête
(d'où le filtre déjà ajouté au point 5, en double sécurité).

**8. `lib/risk/gates.ts` / `evaluate.ts`** — inchangés : `consecutiveLossGate`
existe déjà et reste une fonction d'affichage pure ; `RiskEvaluationInput.consecutiveLosses`
reçoit maintenant la vraie valeur (plus jamais `null` une fois `/api/risk/today`
hydraté) au lieu d'être forcé à `null`.

**9. Client (`signalr-client.ts`)** — `onEvent` : `case "journal.trade_closed"`
→ re-hydrater via `hydrateRiskToday` (même pattern que `risk.day_anchor.resolved`,
pas de calcul de traîne dupliqué côté client). Dans `recomputeRisk()`,
appeler `detectConsecutiveLossPause` en plus de `detectNewLockout`, et passer
`now` à `applyActiveLockout`.

**10. Cockpit** — `RiskStatusPanel` affiche déjà `lockoutReason` ; ajouter
un chrono simple (`until - now`, `setInterval` 1s) quand `risk.lockoutUntil`
n'est pas `null` — c'est la seule pièce UI vraiment neuve de T02b, tout le
reste (bandeau, ledger) existe déjà depuis T02a.

**Vérification à ne pas sauter** : un test qui simule une position gagnante
fermée en deux deals partiels (un profitable, un légèrement perdant après
swap) et vérifie que la somme nette classe correctement gagnant/perdant —
c'est exactement le piège signalé en revue.

## Critère de réussite

Le nombre de trades pris hors fenêtre autorisée tombe à zéro sans effort de discipline conscient.

## Journal

- 2026-09-04 — fiche créée au moment du pivot. Rien de démarré.
- 2026-09-05 — plan initial (7 incréments) jugé trop large en revue : mélangeait
  quatre verrous ne nécessitant rien de l'observer avec un seul (pertes
  consécutives) qui a besoin de l'historique des deals MT5. Découpé en T02a
  (ce qui suit, livré) et T02b (deal history + verrou de pertes consécutives,
  à faire).

  **T02a — décisions et implémentation :**

  1. **Ancre de journée = minuit serveur, jamais 00:00 UTC.** C'est la
     frontière que le broker et une prop firm utilisent pour leur relevé
     quotidien ; s'en écarter rendrait l'outil incohérent avec l'arbitre
     réel. L'offset serveur est lu à chaque `agent.hello` en comparant
     l'horodatage d'un tick MT5 (qui encode l'heure serveur, pas l'UTC réel —
     particularité connue de l'API) à l'horloge UTC du poste
     (`resolve_server_utc_offset_minutes` dans `mt5_observer.py`), arrondi à
     30 min, jamais figé en dur — ça bouge avec l'heure d'été.
  2. **L'ancre elle-même est stockée comme instant UTC résolu**
     (`trading_day_anchors.starts_at_utc`), pas comme une règle recalculée à
     chaque lecture. Résolue par le Gateway (`TradingDayAnchor.cs`, pur,
     testé) à chaque `agent.hello` **et** toutes les 5 min
     (`GatewayBridgeService.DayAnchorRecheckLoopAsync`) pour couvrir un jour
     qui bascule sans reconnexion — sans ce deuxième mécanisme, une connexion
     ininterrompue de plus de 24 h aurait gardé l'ancre de la veille.
  3. **`tradesToday` ne nécessite aucun P&L** — un `brokerPositionId` vu pour
     la première fois est un trade ouvert, point. ~~Détecté côté client~~
     **mise à jour T05 (2026-09-05) : détection migrée côté Gateway** — voir
     `T05-captures-auto.md`. Le paragraphe qui suit décrit la conception T02a
     d'origine (détection client) ; elle a été remplacée, pas seulement
     complétée, parce qu'un trade manuel pris sans onglet cockpit ouvert ne
     déclenchait rien — ni le comptage ici, ni la capture d'entrée dont T05
     avait besoin. Compté depuis l'ancre (table `position_opens`, idempotente
     sur `(account_id, broker_position_id)`), inchangé.
     **Limite connue, toujours vraie après la migration T05** : le fil MT5 ne
     transporte pas l'heure réelle d'ouverture d'une position — `openedAt` est
     l'heure de détection (désormais côté Gateway), pas celle de MT5. Une
     position déjà ouverte avant l'ancre mais découverte pour la première fois
     aujourd'hui (ex. après une coupure prolongée) serait comptée à tort comme
     un trade du jour. Correction future : ajouter l'heure d'ouverture réelle
     au wire côté observer.

     *Conception T02a d'origine (historique)* : détecté côté client (le
     moteur de risque tournait dans le navigateur, pas encore porté au
     backend) en diffant les snapshots de positions, publié comme
     `journal.position.opened` via `PublishEvent`.
  4. **L'état verrouillé est stocké, jamais dérivé** — table `risk_lockouts`
     (motif, depuis, jusqu'à, effacé le/par). `detectNewLockout` publie une
     ligne au passage exact à `locked` (edge-triggered, pas à chaque
     évaluation) ; `applyActiveLockout` fait primer le ledger sur le calcul
     live à chaque rendu — un equity qui remonte tout seul ne rouvre pas un
     compte verrouillé. Perte quotidienne et trades max se lèvent
     automatiquement à la prochaine ancre de journée
     (`shouldAutoClearForNewDay`) ; le kill switch ne se lève **jamais**
     ainsi (voir 6).
  5. **Rattachement au trading manuel** : comme pour T04, aucun `commandId`
     n'existe pour ces faits — `journal.position.opened` et les événements
     de lockout sont publiés via `PublishEvent` (liste blanche étendue),
     même mécanisme que les tickets, pas un nouvel endpoint HTTP (ADR 0003).
  6. **Kill switch sans `close_all` simulé** — aucune commande de fermeture
     n'existe côté wire ni côté observer, et une réponse SIMULATED qui ne
     ferme rien de réel serait trompeuse. Le bouton « Emergency stop » (déjà
     présent, `disabled` depuis Phase 01) verrouille réellement le compte ;
     `KillSwitchBanner` reste affiché tant que le verrou est actif et exige
     un clic explicite (« J'ai fermé mes positions ») qui journalise
     l'accusé de réception (`kill_switch_acks`) **et** lève le verrou —
     c'est la seule façon dont ce verrou se lève, jamais par le lendemain.
  7. **`GET /api/risk/today`** (nouvel endpoint, surface secondaire ADR 0003) :
     hydrate un onglet qui vient de se connecter avec l'ancre, l'equity de
     début de journée, `tradesToday` et le verrou actif — sans ça, un
     rechargement afficherait des zéros avant que le premier événement temps
     réel n'arrive.
  8. **Mode mock** : `mockRiskContext` ne franchit jamais un vrai seuil de
     verrouillage (ses scénarios restent dans les gates d'entrée), donc seul
     le kill switch est démontrable en mock — le verrouillage automatique
     par seuil n'est exercé que par le chemin backend réel.

  Vérification manuelle non faite en session (pas d'extension Chrome
  connectée) : `/api/risk/today` et les quatre nouvelles tables confirmés via
  `curl`/`psql` réels contre un backend + TimescaleDB lancés pour l'occasion ;
  la boucle clic-sur-Emergency-stop → bandeau → accusé → déverrouillage n'a
  pas été observée dans un navigateur.

- 2026-09-05 — **T02b livré**, en suivant le plan ci-dessus point par point,
  aucune déviation :
  1. Observer : `poll_positions()` remplace `build_positions()` comme unique
     point d'appel `positions_get()` par tick — évite un second appel MT5
     redondant tout en détectant les fermetures (diff des tickets vus). Sur
     un compte déjà ouvert au démarrage, la première mesure établit la
     baseline sans jamais émettre de fermeture fantôme.
  2. `sum_realized_pnl` / `build_position_closed` extraites en fonctions
     pures, testées (`test_mt5_observer.py`, stdlib `unittest`, pas de
     nouvelle dépendance pytest) : un test reproduit exactement le piège
     signalé en revue (dernier deal partiel négatif après swap, somme nette
     positive) et vérifie la classification correcte. `python -m py_compile`
     reste le seul gate CI pour ce dossier ; `unittest` est un ajout local,
     pas encore branché à un pipeline.
  3. `journal.trade_closed` — publié direct par le Gateway (comme
     `risk.day_anchor.resolved`), **absent** de `PublishableTypes` dans
     `CockpitHub.cs` : confirmé en relisant le whitelist, aucune entrée
     ajoutée par erreur.
  4. `closed_trades` n'a pas de scope calendaire (contrairement à
     `position_opens`) — testé explicitement
     (`RiskTodayRepositoryTests.Does_not_reset_across_a_streak_that_spans_the_day_anchor`).
  5. `applyActiveLockout` prend désormais un `now` obligatoire (pas de valeur
     par défaut) — tout appelant qui l'oublierait ne compile pas ; les deux
     usages existants (`signalr-client.ts`, tests) mis à jour. Extrait aussi
     `isLockoutExpired` en fonction pure séparée, réutilisée par le client
     pour décider quand publier `risk.lockout.cleared` (`clearedBy:
     "pause-expired"`) — pas dupliquée dans `applyActiveLockout` lui-même.
  6. `detectConsecutiveLossPause` se déclenche sur `gate-consec-loss` blocked
     spécifiquement (pas sur `state.mode === "locked"` en général, qui
     mélangerait perte quotidienne/max trades) — sinon une perte quotidienne
     déclencherait à tort une pause chronométrée de 30 min au lieu d'un verrou
     manuel/lendemain.
  7. Chrono cockpit (`LockoutCountdown` dans `risk-status-panel.tsx`) :
     `setInterval` 1s local au composant, dérivé de `risk.lockoutUntil` —
     aucun nouvel état dans le store, la source de vérité reste le ledger.

  Vérification manuelle non faite en session (même contrainte qu'en T02a,
  pas d'extension Chrome connectée) : la chaîne complète clôture MT5 réelle →
  `position.closed` → `journal.trade_closed` → pause 30 min → chrono cockpit
  → expiration → déverrouillage n'a pas été observée de bout en bout contre
  un terminal MT5 réel. Couvert par unité (Python `unittest`, Vitest, xUnit)
  à chaque étage ; gates `npm run lint`, `npx tsc --noEmit`, `npm test`,
  `npm run build`, `dotnet build`, `dotnet test`, `python -m py_compile`
  tous verts au moment de la clôture.
