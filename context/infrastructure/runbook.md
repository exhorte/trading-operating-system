# Runbook — reconstruire et démarrer l'environnement

Écrit le 2026-09-04, après le pivot. À exécuter **sur la machine Windows de l'utilisateur** : MT5 et le paquet Python `MetaTrader5` n'existent que là.

## 0. Vérification post-pivot — à faire en premier

La restructuration du 2026-09-04 a supprimé du code sans que les gates puissent être exécutées (ni `dotnet`, ni `docker`, ni `node_modules` sur le poste où elle a été faite). **Cette séquence est la première chose à lancer.**

```bash
cd 04_code
npm install
npm run lint
npx tsc --noEmit
npm test
npm run build
cd backend && dotnet build && dotnet test
```

Attendu : tout vert. Les tests supprimés avec `lib/backtest/` et `lib/strategy/` font mécaniquement baisser le compte de tests Vitest — c'est normal, ce n'est pas une régression.

En cas d'échec, l'état d'avant-pivot reste consultable dans le reflog git du clone local (aucune référence n'existe côté distant).

## 1. Base de données

```bash
docker compose up -d          # démarre tradingos-timescaledb
docker compose ps             # healthcheck doit être healthy
docker compose down           # arrêt (les données survivent dans le volume)
```

TimescaleDB écoute sur le port hôte **5433** (choisi pour ne pas entrer en conflit avec un PostgreSQL local). Le schéma est appliqué de façon idempotente au démarrage du backend.

**Nettoyage optionnel** — les tables de l'ancienne recherche existent encore dans la base locale. Elles ne sont plus dans `schema.sql` et ne seront plus recréées. Pour les supprimer :

```sql
DROP TABLE IF EXISTS holdout_attempts, holdout_verdicts,
                     backtest_rejections, backtest_trades, backtest_runs;
```

Sans risque : plus aucun code ne les lit. À faire une fois la vérification de l'étape 0 passée, pas avant.

## 2. Backend

**Option recommandée depuis le 2026-09-17 — Docker**, dans le même
`docker compose` que TimescaleDB :

```bash
docker compose up -d --no-deps --build backend    # première fois / après un changement de code
docker compose up -d --no-deps backend            # relance simple
docker logs -f tradingos-backend                  # logs
```

Pourquoi `--no-deps` : `timescaledb` tourne déjà sous un nom de projet
compose distinct (`trading_operating_system_algorithmique_default`, vérifié
via `docker inspect`, pas deviné) — `docker-compose.yml` pointe `default`
dessus en réseau externe pour que `backend` puisse résoudre `timescaledb`
par son nom, mais laisser compose gérer aussi `timescaledb` provoquerait un
conflit de nom de conteneur à chaque fois. `--no-deps` évite d'y toucher.

**Pourquoi Docker plutôt que `dotnet run` sur cette machine** : Smart App
Control (Windows) bloque le chargement de tout binaire .NET fraîchement
recompilé — `dotnet build` reste propre, mais `dotnet test`/`dotnet run`/le
`.exe` refusent de démarrer (`Microsoft-Windows-CodeIntegrity/Operational`,
« did not meet the Enterprise signing level requirements », refus
déterministe, pas une vérification en cours). Un conteneur Linux n'est pas
soumis à cette politique Windows.

**Option native** (fonctionne tant que Smart App Control ne bloque pas) :

```bash
cd backend
dotnet run --project src/TradingOs.Host
```

Les deux écoutent sur `http://localhost:5080`. Surface HTTP : `/health` et
`/api/audit/recent`. Hub SignalR : `/hub/cockpit`. (L'endpoint
`/api/backtests` a été retiré le 2026-09-04.)

**Différences de configuration entre les deux chemins** (voir
`docker-compose.yml` pour le détail complet) : le conteneur écoute en
interne sur `0.0.0.0` (`Cockpit__ListenUrl`) et l'agent EA-05 aussi
(`Cockpit__AgentBindAny=true`) — un conteneur ne peut pas router ses ports
publiés vers son propre loopback interne, contrairement à un process
natif. Le port publié côté hôte reste restreint à `127.0.0.1` dans les deux
cas (même posture « personnel, une seule machine » que le process natif).
`Cockpit__ObserverUrl` pointe `host.docker.internal` plutôt que `localhost`
— l'observer Python et MT5 restent natifs sur Windows, jamais
conteneurisés. `ConnectionStrings__TradingOs` utilise le port interne 5432
du réseau compose, pas le 5433 publié côté hôte.

## 3. Observer MT5 — Windows uniquement

Prérequis : terminal MT5 **ouvert et connecté** au compte de démonstration. L'observer s'attache au terminal déjà authentifié — **aucun identifiant n'est demandé ni accepté nulle part.**

```bash
cd tools/mt5-observer
pip install -r requirements.txt
python mt5_observer.py
```

Lecture seule, mode `observe`. Le script ne contient aucun appel de trade. Il diffuse sur `ws://localhost:8765`, que le gateway .NET consomme.

Détails et dépannage : `tools/mt5-observer/README.md`.

## 4. Cockpit

```bash
cp .env.example .env.local     # puis éditer
npm run dev                    # http://localhost:3000
```

Variables :

| Variable | Valeurs | Effet |
|---|---|---|
| `NEXT_PUBLIC_REALTIME_SOURCE` | `mock` (défaut) / `backend` | Source des données du cockpit |
| `NEXT_PUBLIC_BACKEND_HUB_URL` | `http://localhost:5080/hub/cockpit` | Hub SignalR, utilisé si `backend` |

`mock` suffit pour développer l'interface et pour la CI. `backend` exige que les étapes 1 à 3 tournent.

**Clé FRED (T03)** — sans elle la gate calendrier échoue fermé en permanence et bloque tout (`news_releases` vide ; 370 évaluations S01 sur 370 mortes le 2026-09-15). Elle se met dans **`04_code/.env`** (variable `FRED_API_KEY`, ignoré par git via `.env*`), que `docker compose` lit pour alimenter `Fred__ApiKey` du conteneur backend — **pas** dans `.env.local`, qui ne sert qu'au cockpit Next.js et que le conteneur ne voit jamais. Prise en compte : `docker compose up -d --no-deps --force-recreate backend`. Vérification : `SELECT count(*) FROM news_releases` > 0 et `GET /api/calendar/upcoming` renvoie des releases. Jamais dans `docker-compose.yml` ni dans `.env.example`, qui sont versionnés.

## 5. Pipeline de détection S01 (EA-02)

Indépendant de l'observer de la section 3 : **deux processus**, à lancer depuis
`04_code`, MT5 ouvert et connecté.

```bash
python tools/mt5-observer/export_m1_candles.py --symbols EURUSD GBPUSD --out-dir tools/mt5-observer
TRADINGOS_ACCOUNT_ID=477029930 npx tsx scripts/run-setup-detection.ts
```

L'exportateur réécrit toutes les 30 s, par symbole, `m1_*.jsonl` (1 500
bougies : le sweep et le déplacement), `h1_*`, `h4_*` et `d1_*.jsonl`
(500 / 300 / 300 bougies, **natives MT5**, pas agrégées — voir la fiche EA-02,
entrée du 2026-09-18) et `spread_*.json`. Le worker les lit toutes les 60 s,
évalue S01 et écrit un verdict par minute et par symbole dans
`setup_proposals` : l'étape où la séquence s'arrête, et pourquoi.

Fenêtres utiles, en heure de New York DST-aware (`lib/setup/preconditions.ts`) :
killzone Londres 02:00–05:00 NY, killzone NY AM 07:00–10:00 NY — soit
06:00–09:00 et 11:00–14:00 UTC en heure d'été. Hors de ces fenêtres tout est
`precondition_session_window` : c'est normal, pas une panne.

**Deux pièges qui ont coûté une session (2026-09-18)** :

- **`--out-dir` doit être `tools/mt5-observer`**, le dossier que lit le worker
  (`TRADINGOS_CANDLES_DIR`, défaut `tools/mt5-observer`). `--out-dir .`
  depuis `04_code` écrit une deuxième copie que personne ne lit, pendant que
  le worker continue d'évaluer un instantané figé. Symptôme :
  `setup_proposals.event_at` bloqué sur un vieil horodatage alors que
  `recorded_at` avance — la clé primaire `(symbol, event_at)` avale les
  écritures en silence.
- **Une seule instance de chaque, et vérifier les deux.** Un composant est une
  **chaîne** de processus (bash → npx → cmd → node pour le worker, ~8 lignes ;
  ~4 pour l'exportateur) : la lire par PID parent et heure de création, pas en
  comptant les lignes. `TaskStop` ne tue que le shell — arrêter par ligne de
  commande (`Stop-Process` sur ce même filtre). Et après un redémarrage de
  session, l'un peut survivre pendant que l'autre est mort.

```powershell
Get-CimInstance Win32_Process | ? { $_.CommandLine -like '*run-setup-detection*' -or $_.CommandLine -like '*export_m1_candles*' } |
  Select-Object ProcessId, ParentProcessId, Name, CreationDate
```

Lire l'entonnoir d'une killzone :

```sql
SELECT stage, count(*) FROM setup_proposals
WHERE event_at >= '<début de la killzone, UTC>' GROUP BY stage ORDER BY count(*) DESC;
```

Un « le détecteur ne propose rien » ne veut rien dire tant qu'on n'a pas
vérifié que les deux processus tournent et que `event_at` avance.

## Ordre de démarrage complet

```
docker compose up -d --no-deps timescaledb backend   (ou dotnet run pour le backend, si Smart App Control le permet)
  → python tools/mt5-observer/mt5_observer.py         (Windows, MT5 ouvert)
    → npm run dev  avec NEXT_PUBLIC_REALTIME_SOURCE=backend
      → exportateur + worker S01 (section 5), pour mesurer la stratégie
```

**Après un arrêt non propre** (redémarrage de la machine ou de Docker Desktop
— les conteneurs sortent en code 255, constaté le 2026-09-20) :
`docker start tradingos-timescaledb`, attendre `healthy`, puis
`docker compose up -d --no-deps backend`. MT5 est à rouvrir à la main ;
observer, exportateur et worker sont à relancer — **rien ne les supervise**.

## Points de fragilité connus

- **Smart App Control (Windows) bloque `dotnet run`/`dotnet test`** sur cette machine depuis le 2026-09-17 — voir section 2 ci-dessus. Docker contourne le problème plutôt que de le résoudre (la politique reste active pour tout binaire .NET natif) ; `dotnet build` reste toujours utilisable pour vérifier la compilation.
- **Rien ne supervise le pipeline S01** (exportateur + worker, section 5) : deux processus lancés à la main, qui ne survivent pas de façon prévisible à une fin de session ni à un redémarrage de la machine. Le critère de réussite de S01 mesure un échantillon de séances ; chaque arrêt silencieux en perd. Question ouverte dans `state.md`.
- **Stall de l'observer** — observé une fois le 2026-07-28 à 14:03 sur une collecte longue. Si le problème revient, la piste retenue est la conteneurisation via `gmag11/MetaTrader5-Docker` (MIT), éventuellement avec `lucas-campagna/mt5linux`.
- **Fins de ligne** — le dépôt a été cloné avec des fins de ligne CRLF alors que l'index git est en LF, ce qui faisait apparaître 267 fichiers comme modifiés. Corrigé par `git config core.autocrlf true` dans ce clone. Si un `git status` affiche à nouveau tout le dépôt comme modifié, c'est ce réglage qu'il faut vérifier en premier — **surtout ne pas commiter la différence**.
