# Base de mesures live — 2026-11-03 (avant l'ADR 0035)

Mesures **réelles**, prises en lecture seule sur le cœur 0.2.0 branché au terminal MT5 de la démo Exness (serveur Exness-MT5Trial10, USD, hedging, levier 1:100, solde 10 000). Aucun ordre, aucune écriture. Le cœur et le cockpit tournaient depuis environ dix minutes ; l'agent MQL5 n'était **pas** attaché. Heure du relevé : 14:12–14:16 UTC (mardi). Sert de point de comparaison « avant » pour L1 à L5 (`context/adr/0035-developpement-pilote-par-le-live.md`).

## Ce que le cœur reçoit du terminal (vérifié)

| Mesure | Résultat |
|---|---|
| Terminal | lu à chaque cycle (« terminal read 0 s ago »), compte actif = compte connecté |
| Compte | solde = équité = 10 000 USD, marge 0, `tradeAllowed` et `tradeExpert` vrais |
| Réconciliation | lisible, 0 position, 0 divergence, cycle à ~15 s |
| Symboles suivis | `EURUSDm`, `XAUUSDm` |
| Spécification `EURUSDm` | 5 décimales, point 0,00001, valeur du tick 1, lot 0,01 à 200 (pas 0,01), niveaux de stop et de gel à 0 |
| Latence de l'API du cœur (30 appels, local) | 10–173 ms, moyenne 31 ms |

## Flux de cotes (30 s, un relevé par seconde)

| | `EURUSDm` | `XAUUSDm` |
|---|---|---|
| Horodatages distincts | 13 | 26 |
| Âge du dernier tick | 0,9 – 7,9 s (moyenne 3,1 s) | 0,7 – 2,6 s (moyenne 1,3 s) |
| Spread | 0,00008 constant (0,8 pip) | 0,24 constant |
| Plage du bid | 1,11865 – 1,11881 | 3949,04 – 3949,99 |

Limites de la mesure : l'horodatage exposé est à la seconde et le cœur sonde à 1 Hz, l'âge est donc connu à ±2 s ; sur 30 s le spread n'a pas varié.

## Bougies de `EURUSDm`

| Échelle | Dernière ouverture (UTC) | Trous dans les 60 dernières | Remarque |
|---|---|---|---|
| M1 | 14:13 | 0 | à jour |
| M5 | 14:10 | 0 | à jour |
| M15, H1 | 14:00 | 0 / 1 | à jour ; le trou H1 tombe sur le week-end |
| H4 | 12:00 | 2 | week-ends |
| D1 | 00:00 | 10 | week-ends et jours fériés ; non distingués d'une donnée manquante |

## Verrous de l'exécution sur la démo (état mesuré)

Préparation : **13 contrôles sur 16 verts**. Rouges : `kill_switch_available` et `heartbeat` (aucun agent d'exécution connecté), `account_limits_configured` (limites jamais écrites par l'utilisateur, ADR 0015). Plafond du compte `maxMode = OBSERVE` ; plafond du cœur `OBSERVE` ; agent compilé `OBSERVE` (constante). Mode courant `OBSERVE` depuis 13:31 UTC. Étape « Agent MQL5 » du démarrage : `FAILED`, « no execution agent is connected ».

## Écarts avec l'ADR 0035 (preuves)

* **G1 — Les ticks ne sont pas tous vus.** Sondage de `symbol_info_tick` à 1 Hz, heure à la seconde ; `time_msc` n'est lu que par l'outil `spread-history`. On ne voit ni chaque tick ni la variation fine du spread, et on ne peut pas dater un tick à moins de ~1–2 s.
* **G2 — Spécification incomplète.** Pas de swap long/short, pas de mode de remplissage, pas de sessions de négociation du courtier (les horaires viennent de `domain/market/hours.py`). La commission des portes de coût est un **réglage** (`commissionPerLotRoundTrip = 5`), pas une valeur lue du courtier ; la vraie commission n'apparaît qu'après une transaction (`commission` + `swap` des deals sont lus).
* **G3 — Latence EA ↔ cœur non mesurée.** Seul l'horodatage du dernier battement existe ; aucun temps d'aller-retour.
* **G4 — Délais de commande sans vue agrégée.** Chaque commande porte `created_at`, `sent_at`, `acknowledged_at`, `completed_at` ; rien ne les agrège (délai d'accusé, d'exécution, glissement entre prix demandé et prix obtenu).
* **G5 — Jours de marché fermé.** Les trous de bougies de week-end ne sont pas distingués d'un manque de données dans la lecture qu'on en fait ici (le code sait si un marché est ouvert, `domain/market/hours.py`).

## Mesures prises par L1 (le même jour, 14:37–14:42 UTC, cœur relancé sur le code de L1)

Fenêtre de 60 minutes. Stockées (`python -m trading_os live-report`, page `exports/live/live-20261103T143702Z.md`, hors Git) :

| | `EURUSDm` | `XAUUSDm` |
|---|---|---|
| Ticks stockés | 2 533 | 3 540 |
| Cadence observée | 42,2 / min | 59,0 / min |
| Spread min / médiane / p95 / max | 0,00008 partout | 0,24 / 0,24 / 0,24 / 0,26 |

Retard de réception des cotes, vu par le cœur (`GET /api/system/live-metrics`, environ 35 s après le redémarrage) : `EURUSDm` 18 cotes, médiane 1,28 s, p95 2,21 s ; `XAUUSDm` 33 cotes, médiane 0,40 s, p95 1,38 s.

Ce que ces chiffres prouvent : **l'or est observé à 59 cotes par minute, soit presque le plafond de 60 d'un sondage à 1 Hz** — le cœur ne voit qu'un tick par seconde au plus et en manque (G1 confirmé par un chiffre, c'est ce qui justifie L2). Les retards de réception (0,2 à 2,2 s) sont **dans la marge de ±2 s** de la mesure : ils ne disent pas la vraie latence. G3 est confirmé par le code de l'agent (`"latencyMs":0` en constante, `TradingOsAgent.mq5` ligne 735). Aucune commande dans la fenêtre : les réponses du courtier ne sont toujours pas mesurées.

## Contrat du terminal, joué contre le vrai terminal (14:50 UTC)

`MT5_LIVE_TESTS=1`, `pytest tests/integration/test_terminal_contract.py -m live_mt5` : **14 passés, 1 ignoré exprès, en 20 s**. Lecture seule : attache sans mot de passe, jamais d'ordre (un des tests prouve que `order_send`, `order_check` et `positions_close` sont inatteignables), jamais de changement de compte. Vérifié sur le vrai terminal : le compte et le serveur annoncés sont ceux de la démo ; un mauvais serveur est refusé, pas suivi ; la spécification d'un symbole est complète et cohérente ; un tick est une cote valide (ask ≥ bid) ; les bougies reviennent triées et bien formées ; positions et ordres sont des listes typées ; le détachement puis le rattachement fonctionne ; le dimensionnement calculé avec les propres chiffres du courtier ne dépasse jamais le risque, pour 1,5 / 1,0 / 0,3 / 0,2 / 0,1 %. Le cœur est resté en bonne santé pendant ce temps (aucun incident, aucune tâche en échec).

Non vérifié sur le live : tout le chemin d'exécution (agent, commandes, accusés, rejets, remplissages, fermeture globale, redémarrage avec une commande en vol).
