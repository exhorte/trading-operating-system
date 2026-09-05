# T05 — Captures automatiques entrée / sortie

Statut : **livré** (2026-09-05) · Vague 1 · Effort 1–2 j · Valeur 4 · Dépend de : rien

## Problème

Les captures d'écran sont prises à la main, après coup, sur un graphique qui a déjà bougé. C'est la corvée qui fait abandonner les journaux.

## Comportement attendu

Sur événement de fill (entrée) et de clôture (sortie), le système capture l'état du graphique et l'attache au trade. Sans intervention.

## Décision d'architecture (tranchée avec l'utilisateur avant tout code)

**Rejetée en session** : l'idée initiale de la fiche — rendu ET déclencheur tous deux côté serveur (.NET) — parce qu'elle part d'une contrainte auto-imposée. Le déclencheur doit être serveur (fiable sans onglet cockpit ouvert), mais ça ne veut pas dire que le RENDU doit l'être : `lib/analysis/` est la source canonique de l'analyse en TypeScript (ADR 0004 — « le TypeScript fait foi, le C# suit »). Dessiner le graphique côté .NET aurait exigé soit de porter les détecteurs en C# (une seconde source de vérité, exactement ce que l'ADR interdit), soit de dessiner sans les niveaux (une capture vidée de son intérêt). Et le cockpit devra de toute façon savoir dessiner un graphique pour T06 — deux moteurs de rendu à écrire et à garder cohérents.

**Retenue : le serveur capture les faits, le cockpit fabrique l'image.**
À l'événement (`journal.position.opened` / `journal.trade_closed`), le Gateway
écrit une ligne **immuable** dans `trade_captures` : bornes exactes de la
fenêtre de bougies, prix d'entrée, stop, TP, prix de sortie, horodatages.
Rien d'autre — quelques nombres, jamais une image. Le graphique se rend en
TypeScript au moment où on le regarde (`components/journal/trade-chart.tsx`),
avec `analyzeMarketContext` sur cette fenêtre figée.

Pourquoi c'est meilleur que l'alternative « capture MT5 » de la fiche originale, et meilleur que « rendu + export côté serveur » :
- **Non-anticipation garantie plus solidement qu'une image** — la borne haute de la fenêtre est stockée et ne peut jamais être élargie ; une image, elle, pourrait avoir été mal rendue une fois sans qu'on le sache.
- **Reproductibilité totale** — les mêmes nombres, rejoués, donnent le même graphique.
- **Zéro nouvelle dépendance** — pas de SkiaSharp/ImageSharp côté .NET, pas de moteur de rendu dupliqué.
- **Le composant sert aussi T06** — `TradeChart` n'est pas un aller simple pour T05.

Prix à payer, assumé explicitement : aucune image n'existe tant que le
cockpit n'est pas ouvert pour la regarder (le rendu est paresseux, pas
anticipé), et l'allure du graphique peut changer si le composant évolue —
ce qui change le style, jamais ce qui était connu à l'instant capturé,
puisque les données sont figées. Un bouton « exporter en SVG/PNG » depuis le
composant, si un fichier portable devient utile un jour, coûtera une heure —
ne pas le construire maintenant.

**Candidat ADR** (à trancher à la clôture de la Vague 1, comme prévu par le
script de session) : « le serveur capture des faits immuables et bornés, le
cockpit rend » est un principe plus général que ce seul outil — il vaut
d'être écrit une fois dans `context/adr/` plutôt que de rester enterré ici.

## Trouvailles en cours de route qui ont changé le périmètre

1. **Le vrai événement de fill n'est pas celui que suggérait la fiche.**
   Les rapports SIMULATED de la boucle de décision transitoire (Phase 09,
   ADR 0010) ne sont pas des trades réels — ce sont T02a/T02b qu'il fallait
   utiliser : `journal.position.opened` (entrée) et `journal.trade_closed`
   (sortie), déjà la source de vérité du lockout.

2. **`journal.position.opened` était détecté côté navigateur (T02a)** — un
   trade manuel pris sans onglet cockpit ouvert ne déclenchait rien, ni le
   comptage `tradesToday`, ni (pour T05) la capture d'entrée. Corrigé en
   migrant la détection côté Gateway, sur le même schéma que la fermeture
   (T02b) : `mt5_observer.py::poll_positions` calcule maintenant les deux
   côtés d'un seul diff (`diff_position_ids`), avec une fonction
   `seed_known_positions` dédiée à la toute première lecture pour ne jamais
   déclencher d'ouverture ou de fermeture fantôme au démarrage. Nouveau
   message `position.opened` sur le wire, payload `journal.position.opened`
   enrichi (symbole, côté, volume, prix, sl, tp — plus seulement l'id) pour
   rester auto-porteur en cas de relecture d'audit. Retiré de la liste
   blanche `PublishEvent` du hub (Gateway-only désormais, comme
   `risk.day_anchor.resolved`). Le client ne compte plus localement : il se
   ré-hydrate depuis `/api/risk/today` sur l'événement, comme pour les
   clôtures.

3. **`journal.trade_closed` n'avait pas de prix de sortie.** Ajouté
   (`exitPrice`, moyenne pondérée par volume sur tous les deals de sortie —
   même risque de piège que `sum_realized_pnl` en T02b si on prenait un seul
   deal). Colonne ajoutée à `closed_trades` au passage.

## Ancrage dans le code

- `tools/mt5-observer/mt5_observer.py` — `seed_known_positions`,
  `poll_positions`/`diff_position_ids` (pur, testé), `build_position_opened`,
  `weighted_exit_price` (pur, testé).
- Wire (TS + C#) — `Mt5PositionOpenedMessage`, `exitPrice` sur
  `Mt5PositionClosedMessage`.
- `backend/src/TradingOs.Gateway/Mt5ObserverClient.cs` — case
  `Mt5PositionOpenedMessage`, direct comme `position.closed`.
- `backend/src/TradingOs.Host/GatewayBridgeService.cs` — sur
  `journal.position.opened`/`journal.trade_closed`, écrit en plus une ligne
  `trade_captures` via `TradeCaptureRepository` (hors pipeline
  `PersistenceWriter` — un envelope ne mappe pas naturellement vers deux
  tables, et l'écriture de la ligne 'exit' a besoin de relire la ligne
  'entry' d'abord).
- `backend/src/TradingOs.Persistence/TradeCaptureRepository.cs`,
  `CandleRepository.cs` (première lecture par plage sur `candles`, la
  diffusion temps réel n'en avait jamais eu besoin).
- `GET /api/captures/{brokerPositionId}`, `GET /api/candles` — surface HTTP
  secondaire (ADR 0003), même famille que `/api/risk/today`.
- `lib/journal/chart-scale.ts` (pur, testé) + `components/journal/trade-chart.tsx`
  (SVG, consomme `analyzeMarketContext`) + `app/(cockpit)/journal/[brokerPositionId]/page.tsx`
  (viewer minimal par lien direct) + lien « Capture » dans `positions-table.tsx`.

## Limite de périmètre assumée : ce n'est pas T06

`/journal` reste le stub T06 (« dense, filterable trade audit table »). T05
livre le pipeline de faits immuables + le composant de rendu réutilisable +
un viewer minimal par lien direct (`/journal/[brokerPositionId]`) — pas de
liste, pas de filtre, pas de table. Parcourir/découvrir les trades passés
reste le travail de T06 (qui dépend de T04 et T05 dans la roadmap).

## Défauts trouvés en revue et corrigés (2026-09-05, après livraison initiale)

Deux défauts qui auraient corrompu les données dès la première séance réelle
— trouvés en revue, corrigés avant tout usage réel :

1. **Mauvais identifiant utilisé comme clé.** Le code diffait sur `p.ticket`
   et appelait `mt5.history_deals_get(position=ticket)`. Or dans MT5, c'est
   `POSITION_IDENTIFIER` (`TradePosition.identifier`, égal à
   `TradeDeal.position_id`) qui « ne change pas pendant toute la vie de la
   position » ; le ticket correspond à l'ordre d'ouverture et peut être
   réécrit par des opérations de service côté broker. Tant que les deux
   coïncident (le cas courant, ce qui rendait le bug invisible), tout
   marche ; le jour où ils divergent sur une position vivante, le diff voit
   un ticket disparaître et un autre apparaître : fausse clôture, fausse
   ouverture, `tradesToday` incrémenté à tort, capture d'entrée sur un trade
   qui n'a pas commencé, entrée parasite dans la série de pertes
   consécutives. Corrigé : `identifier` partout où une position est clé
   (`_map_position`, `build_position_opened`, `seed_known_positions`,
   `poll_positions`), y compris pour `history_deals_get(position=...)`.
   Test de non-régression : une position dont `identifier` et `ticket`
   divergent délibérément, qui vérifie que `brokerPositionId` suit
   `identifier`.

2. **Un trade ouvert et fermé entre deux sondages était invisible.** Le
   sondage tourne à 2 s ; `closed_ids` sort de
   `diff_position_ids(_known, current)` — un ticket/identifiant jamais entré
   dans `_known` ne peut pas en sortir. Un stop touché immédiatement en
   conditions rapides, ou un scalp très court, ne produisait ni `opened` ni
   `closed` : pas de capture, pas de comptage, pas de trace dans la série de
   pertes — précisément les trades qui pèsent le plus sur les métriques de
   discipline. Corrigé par `scan_missed_round_trips` : à chaque poll, en plus
   du diff de snapshots, un balayage des deals de sortie récents (fenêtre
   glissante depuis le dernier poll) repère tout `position_id` fermé qui
   n'était ni dans `_known_position_ids` ni dans les positions actuelles, et
   reconstruit `opened`+`closed` à partir du seul historique de deals
   (`build_position_opened_from_deal`). `stopLoss`/`takeProfit` valent `0.0`
   dans ce cas précis — MT5 ne stocke pas ces champs sur un deal, et `0.0`
   est la convention MT5 elle-même pour « pas de stop », pas une valeur
   inventée ; sur un graphique XAUUSD rendu (~4000), c'est visuellement
   impossible à confondre avec un vrai niveau.

Tests ajoutés : 7 nouveaux (identifiant vs ticket sur `build_position_opened`,
`_map_position` et `poll_positions` bout en bout avec `mt5.positions_get`
mocké ; `build_position_opened_from_deal` ; trois cas pour
`scan_missed_round_trips` — reconstruction réelle, positions déjà couvertes
par le diff normal, fenêtre de balayage vide). Total observer : 17 tests
(`python -m unittest`), tous stdlib (`unittest.mock`, pas de nouvelle
dépendance).

## Limite héritée, inchangée

`openedAt`/`closedAt` restent l'heure de détection, pas l'heure réelle MT5
(le wire ne l'a jamais transportée — limite documentée depuis T02a). La
fenêtre de capture d'entrée en hérite : sa borne haute est l'instant où le
Gateway a vu la position pour la première fois, pas forcément le tick exact
du fill.

## Critère de réussite

Plus une seule capture prise à la main.

## Journal

- 2026-09-04 — fiche créée au moment du pivot. Rien de démarré.
- 2026-09-05 — **livré**. Décision d'architecture rediscutée et inversée par
  rapport à la fiche initiale (voir section dédiée ci-dessus) : le rendu est
  client, pas serveur — seuls les faits sont serveur. Migration de
  `journal.position.opened` vers une détection Gateway (corrige un vrai bug
  T02a en même temps qu'elle sert T05). Ajout de `exitPrice` à
  `journal.trade_closed`/`closed_trades`.

  Gates tous verts : `npm run lint`, `npx tsc --noEmit`, `npm test` (107
  tests, dont 6 nouveaux sur `chart-scale.ts`), `npm run build`,
  `dotnet build`, `dotnet test` (38 tests, inchangé — pas de nouveau test
  ajouté côté C# pour ce tour : `TradeCaptureRepository`/`CandleRepository`
  sont de la glue DB non testée en unitaire, même convention que
  `RiskTodayRepository`/`NewsCalendarRepository`), `python -m unittest`
  (10 tests, dont 6 nouveaux sur le diff ouverture/fermeture et le prix de
  sortie pondéré).

  Non vérifié en session : la chaîne complète contre un terminal MT5 réel
  (pas d'extension Chrome connectée, même limite qu'en T02/T03) — en
  particulier, la boucle réelle position ouverte → ligne `trade_captures`
  'entry' → position fermée → ligne 'exit' → rendu dans
  `/journal/[brokerPositionId]` n'a été validée que par lecture de code et
  les tests unitaires des maillons individuels, jamais de bout en bout en
  live.

- 2026-09-05 (revue) — deux défauts trouvés en revue et corrigés avant tout
  usage réel, voir section dédiée ci-dessus : mauvais identifiant utilisé
  comme clé (`ticket` au lieu de `identifier`/`POSITION_IDENTIFIER`), et un
  trade ouvert-et-fermé entre deux sondages de 2 s totalement invisible au
  diff de snapshots. Observer : 10 → 17 tests (`python -m unittest`, stdlib
  `unittest.mock`, aucune nouvelle dépendance). `python -m py_compile`
  toujours vert ; aucun changement côté TS/C#, `brokerPositionId` reste une
  string opaque pour ces couches — seule la valeur produite par l'observer a
  changé. Toujours non vérifié contre un terminal MT5 réel.
