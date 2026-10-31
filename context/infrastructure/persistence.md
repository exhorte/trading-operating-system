# Persistance

Réécrit le 2026-10-09 (ADR 0016, ADR 0011). PostgreSQL + TimescaleDB, un conteneur Docker (`tradingos-timescaledb`, volume existant, `127.0.0.1:5433`). Le cœur y écrit en **SQL explicite** (psycopg 3 asynchrone, `python/trading_os/infrastructure/database/`), sans ORM. Démarrage et sauvegarde : `context/infrastructure/runbook.md` § 1.

## Garanties

| Donnée | Garantie |
|---|---|
| commandes d'exécution, décisions de risque, verrous, états d'autonomie, comptes et leurs limites | écrites **avant d'agir**, dans la même transaction que le changement d'état ; base indisponible ⇒ refus (échec fermé), rien n'est envoyé |
| journal d'audit (`events`) | écriture durable ; **un seul** traitement par événement (identifiant unique, `ON CONFLICT DO NOTHING`) ; un événement perdu est compté et signalé (`audit.lost` de la santé) |
| ticks | file bornée + écriture par lots ; perte tolérée et **comptée** (`ticks.dropped`) ; horodatage = heure du tick |
| faits de capture T05 | chiffres seulement (ADR 0018), immuables : une ligne par position et par type, jamais modifiée |
| secrets | **aucune** colonne de mot de passe, de jeton ou de clé ; un test lit `information_schema` pour que cela reste vrai |

## Schéma, par migrations

Les migrations sont des fichiers `migrations/NNNN_nom.sql`, appliquées dans l'ordre, chacune dans sa transaction, enregistrées dans `schema_migrations` avec une somme de contrôle : **une migration modifiée après son application est une erreur**, pas une dérive silencieuse. Elles sont additives. `python -m trading_os db status | migrate`.

| Migration | Contenu |
|---|---|
| `0001_baseline` | le schéma tel que l'ancien backend l'avait créé (compatible avec les tables existantes, idempotent) : séries (`candles`, `ticks`, `news_releases`), `setup_proposals`, `risk_decisions`, `risk_lockouts`, `kill_switch_acks`, `trading_day_anchors`, positions (`position_opens`, `position_scans`, `closed_trades`), commandes et accusés/rapports hérités, `account_settings` |
| `0002_core` | `accounts` et `account_rule_versions` (les limites par compte, versionnées, en ajout seul), `trade_intents`, commandes avec leur cycle de vie (`execution_commands`, `command_transitions`, `command_reconciliations`), `events`, `incidents`, `system_state` ; l'ancienne `execution_commands` est **renommée** `legacy_execution_commands`, ses lignes intactes |
| `0003_captures_are_data` | `trade_captures` : la fenêtre de graphique devient optionnelle (ADR 0018) |

Tables à séries chronologiques : `candles`, `ticks` (hypertables TimescaleDB quand l'extension est présente ; une base PostgreSQL simple fonctionne aussi, c'est ce qu'utilisent les tests).

## Scripts manuels — jamais lancés par le migrateur

`migrations/manual/`, un geste humain : `python -m trading_os db manual <nom> --confirm <nom>`.

| Script | Effet |
|---|---|
| `drop_legacy_tables` | supprime ce que le cœur Python a remplacé et ne lit plus : `envelopes` (l'ancien journal JSONB), `legacy_execution_commands`, `account_settings` (les limites par firme). **Une décision sur l'historique, pas sur le fonctionnement** : exporter d'abord ce qu'on veut garder (`pg_dump -t envelopes -t legacy_execution_commands -t account_settings`). |
| `drop_capture_window` | supprime la colonne de fenêtre de graphique de `trade_captures` (ADR 0018). |

## Quelques requêtes

```sql
SELECT type, count(*) FROM events GROUP BY type ORDER BY 2 DESC;                       -- ce que le journal d'audit a vu
SELECT * FROM risk_decisions ORDER BY decided_at DESC LIMIT 10;
SELECT command_id, state, reject_code, created_at FROM execution_commands ORDER BY created_at DESC LIMIT 10;
SELECT stage, count(*) FROM setup_proposals WHERE event_at >= now() - interval '1 day' GROUP BY stage ORDER BY 2 DESC;
SELECT time_bucket('1 hour', open_time) AS h, count(*) FROM candles GROUP BY h ORDER BY h DESC LIMIT 24;
```

(`docker exec -it tradingos-timescaledb psql -U tradingos -d tradingos`)

## Quand la base est en panne

Le cœur reste debout et le dit (`GET /api/system/health` : `database.up = false`, dernière erreur). Il **refuse toute commande** (rien ne peut être persisté avant d'agir), le superviseur ouvre un incident, les ticks sont comptés comme perdus. À la reprise l'écriture repart seule ; ce qui a été perdu n'est pas rejoué.

## Pas encore

Interface de rejeu, politiques de rétention et de compression des séries, sauvegardes automatiques.
