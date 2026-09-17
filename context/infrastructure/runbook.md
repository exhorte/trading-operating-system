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

À ajouter en Vague 1 : `FRED_API_KEY` pour T03 (voir la fiche). La clé va dans `.env.local`, jamais dans `.env.example` ni dans un commit.

## Ordre de démarrage complet

```
docker compose up -d --no-deps timescaledb backend   (ou dotnet run pour le backend, si Smart App Control le permet)
  → python tools/mt5-observer/mt5_observer.py         (Windows, MT5 ouvert)
    → npm run dev  avec NEXT_PUBLIC_REALTIME_SOURCE=backend
```

## Points de fragilité connus

- **Smart App Control (Windows) bloque `dotnet run`/`dotnet test`** sur cette machine depuis le 2026-09-17 — voir section 2 ci-dessus. Docker contourne le problème plutôt que de le résoudre (la politique reste active pour tout binaire .NET natif) ; `dotnet build` reste toujours utilisable pour vérifier la compilation.
- **Stall de l'observer** — observé une fois le 2026-07-28 à 14:03 sur une collecte longue. Si le problème revient, la piste retenue est la conteneurisation via `gmag11/MetaTrader5-Docker` (MIT), éventuellement avec `lucas-campagna/mt5linux`.
- **Fins de ligne** — le dépôt a été cloné avec des fins de ligne CRLF alors que l'index git est en LF, ce qui faisait apparaître 267 fichiers comme modifiés. Corrigé par `git config core.autocrlf true` dans ce clone. Si un `git status` affiche à nouveau tout le dépôt comme modifié, c'est ce réglage qu'il faut vérifier en premier — **surtout ne pas commiter la différence**.
