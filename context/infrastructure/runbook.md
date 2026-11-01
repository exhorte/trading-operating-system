# Runbook — reconstruire et démarrer l'environnement

Réécrit le 2026-10-09 pour l'architecture Python-native (ADR 0016). À exécuter **sur la machine Windows de l'utilisateur** : MT5 et le paquet Python `MetaTrader5` n'existent que là, donc le cœur Python ne tourne pas dans un conteneur. Docker ne porte plus que la base.

```
cockpit Next.js (3000) ⇄ cœur Python (127.0.0.1:8000, un processus) ⇄ MT5 ⇄ courtier
                                   │  └── lien agent 127.0.0.1:9765 ── EA TradingOsAgent
                                   └── PostgreSQL/TimescaleDB (conteneur, 127.0.0.1:5433)
```

## 0. Une fois : installer

```powershell
cd 04_code\python
py -3.14 -m venv .venv                                   # Python ≥ 3.12 (développé en 3.14)
.venv\Scripts\python.exe -m pip install -e ".[dev]"      # ajouter ,mcp pour le serveur MCP
cd ..
npm install
```

Vérifier (tout doit être vert) :

```powershell
cd python
.venv\Scripts\python.exe -m pytest -q                    # unitaires, intégration, base jetable, architecture (~8 min)
.venv\Scripts\python.exe -m ruff check . ; .venv\Scripts\python.exe -m ruff format --check .
.venv\Scripts\python.exe -m mypy trading_os
cd ..
npm test ; npm run typecheck ; npm run lint ; npm run build
```

Les tests de base de données lancent leur **propre** cluster PostgreSQL jetable à partir des binaires installés (ou `TRADINGOS_TEST_DATABASE_URL`) : ils **échouent** s'il n'y en a pas et ne touchent jamais la base `tradingos`.

## 1. Base de données

```powershell
docker compose up -d timescaledb     # crée le conteneur tradingos-timescaledb s'il n'existe pas
docker start tradingos-timescaledb   # le relance (après un arrêt de Docker Desktop : sortie en code 255)
docker compose ps                    # healthcheck : healthy
```

TimescaleDB écoute sur le port hôte **5433**, sur `127.0.0.1` seulement. `docker-compose.yml` ne déclare que ce service.

**Le schéma s'applique par migrations numérotées**, jamais rejouées d'un bloc :

```powershell
python -m trading_os db status                      # appliquées / en attente / dérivées
python -m trading_os db migrate                     # applique les migrations en attente (additives)
python -m trading_os db manual <nom> --confirm <nom>   # UN script destructeur de migrations/manual/, geste humain
```

Une migration modifiée après son application est une erreur (somme de contrôle), pas une dérive silencieuse. Le cœur applique les migrations en attente au démarrage (`scripts\start.ps1` le fait aussi explicitement). Aucun script destructeur ne se lance seul : par exemple `drop_capture_window` (ADR 0018) et la suppression de la table `envelopes`.

**Le volume des données porte le nom d'un ancien projet compose** : `trading_operating_system_algorithmique_tradingos-pgdata`. `docker-compose.yml` le déclare `external` par son nom exact — sans ça, recréer le conteneur depuis `04_code` démarrerait sur le volume vide `04_code_tradingos-pgdata`, sans aucune erreur. **Sur une machine neuve** il n'existe pas : `docker volume create trading_operating_system_algorithmique_tradingos-pgdata` avant le premier `docker compose up`. **Avant toute recréation** : `pg_dump -Fc` copié hors du conteneur, nombre de lignes par table relevé avant/après.

## 2. Le cœur Python

```powershell
cd 04_code\python
.venv\Scripts\python.exe -m trading_os serve         # http://127.0.0.1:8000 — REST + WebSocket /ws + lien agent :9765
```

Configuration : variables d'environnement et `04_code/.env` (gitignoré) — `.env.example` les liste toutes, `python/trading_os/app/config.py` fait foi. Il faut au minimum `DATABASE_URL`, `TRADINGOS_COCKPIT_TOKEN` et `TRADINGOS_AGENT_TOKEN` ; `scripts\start.ps1` écrit ce qui manque.

- **Santé** : `GET http://127.0.0.1:8000/api/system/health` (le seul endpoint sans jeton) — base, journal d'audit, ticks, clients WebSocket, agents connectés, tâches de fond. Le reste de l'API exige le jeton **et** une Origin du cockpit (lectures comprises). Le schéma OpenAPI est à `/api/openapi.json` (avec jeton).
- **Plafond de mode** : `TRADING_MODE=OBSERVE` par défaut — rien n'est envoyé nulle part. Le relever est une décision de l'utilisateur, jamais d'un script.
- **Mode simulé** : `MT5_ENABLED=false` (ou `start.ps1 -Simulated`) — aucun terminal : un compte de démonstration en mémoire (deux positions ouvertes, un petit historique, des cotes qui bougent). C'est ce qui sert à regarder le cockpit sans courtier.
- **Journaux** : sur la console du cœur, masqués (jetons, mots de passe, clé FRED) ; jamais d'identifiant de compte de trading dans un message.
- **Clé FRED (T03)** — sans elle la porte calendrier échoue fermée en permanence et bloque toute entrée S01. `FRED_API_KEY` dans `04_code/.env`, jamais dans `docker-compose.yml` ni `.env.example`. Prise en compte au redémarrage du cœur. Vérification : `GET /api/market/calendar` renvoie des publications.

### Outils en ligne de commande (lecture seule, aucun appel d'ordre)

```powershell
python -m trading_os list-symbols --help             # les symboles du courtier derrière un nom canonique
python -m trading_os export-history --symbol XAUUSDm --timeframe M1 --bars 1500 --out exports\xauusd_m1.jsonl
python -m trading_os import-candles exports\xauusd_m1.jsonl     # idempotent
python -m trading_os spread-history --help           # le spread par fenêtre New York, depuis les ticks du courtier
python -m trading_os weekly-review                   # revue hebdomadaire (Markdown) depuis le journal
python -m trading_os mcp                             # serveur MCP en lecture seule, sur stdio
python -m trading_os gen-types                       # régénère lib/api/generated.ts (un test échoue s'il est périmé)
```

Les exports (`exports/`) sont gitignorés : ce sont des données personnelles, jamais du code.

## 3. Le terminal MT5 et l'agent EA — Windows uniquement

Prérequis : terminal MT5 **ouvert et connecté** au compte voulu. Le cœur s'attache au terminal ; le mot de passe reste dans MT5 — **aucun identifiant de compte n'est demandé ni écrit nulle part** par `start.ps1`. Un compte se déclare dans le cockpit (Settings → « Enregistrer le compte », sans mot de passe), puis se rattache dans Account.

L'agent d'exécution (`tools/mt5-execution-agent`, EA-05) se compile avec MetaEditor et s'attache à **un** graphique ; son README donne les entrées, le jeton (`MQL5\Files\tradingos_agent.token`, copié par `start.ps1` dans chaque terminal ouvert), le prérequis `127.0.0.1` dans la liste WebRequest des options de l'EA, et la procédure de vérification. **Compilation sans effet de bord** :

```powershell
# sur une COPIE du dossier : MetaEditor écrit le .ex5 à côté de la source
MetaEditor64.exe /compile:"<copie>\TradingOsAgent.mq5" /log:"<copie>\compile.log"   # attendu : 0 errors, 0 warnings (code de sortie 1 = succès)
```

Une compilation ne recharge pas un EA déjà attaché : le retirer du graphique et le rattacher. Depuis le build 1.11 l'agent refuse tout nouvel ordre (`DEAD_MAN`) quand le cœur cesse de le pinguer ; un build plus ancien ne l'annonce pas (`capabilities`) — le recompiler.

**Installation par jonction** (2026-09-23) : `MQL5\Experts\TradingOsAgent` dans le dossier de données du terminal pointe vers `tools/mt5-execution-agent` — MT5 voit toujours la version compilée du dépôt. Retirer la jonction suffit à désinstaller.

## 4. Cockpit

```powershell
npm run dev            # http://127.0.0.1:3000 (lié à 127.0.0.1 seulement)
npm run build ; npm run start
```

Le cockpit lit `TRADINGOS_COCKPIT_TOKEN` dans `04_code/.env` **côté serveur** (jamais dans le bundle) et le remet à ses propres scripts par `/api/cockpit-token` ; `proxy.ts` refuse tout Host qui n'est pas `localhost`, `127.0.0.1` ou `[::1]`. `NEXT_PUBLIC_CORE_URL` ne sert que pour un cœur sur un autre port de la boucle locale (défaut `http://127.0.0.1:8000`).

Le menu du compte (en haut à droite) dit l'état du lien : connecté, reconnexion, périmé (plus de battement du cœur depuis 8 s), dégradé (le cœur signale un défaut), déconnecté — et le point rouge de la base ou d'un événement d'audit perdu. Jeton absent : le message dit de lancer `scripts\start.ps1`.

## 5. La stratégie S01

S01 n'est plus un pipeline de processus séparés : le `StrategyService` du cœur lit les bougies de MT5, évalue S01 à chaque clôture de bougie et écrit un verdict par symbole dans `setup_proposals` (l'étape où la séquence s'arrête, et pourquoi). Rien à lancer à côté. Les fenêtres utiles sont en heure de New York, DST-aware : killzone Londres 02:00–05:00 NY, killzone NY AM 07:00–10:00 NY — 06:00–09:00 et 11:00–14:00 UTC en heure d'été. Hors de ces fenêtres tout est `precondition_session_window` : c'est normal, pas une panne. Le cockpit les lit à `/setups`. L'entonnoir d'une killzone :

```sql
SELECT stage, count(*) FROM setup_proposals
WHERE event_at >= '<début de la killzone, UTC>' GROUP BY stage ORDER BY count(*) DESC;
```

## Ordre de démarrage complet

Depuis `04_code`, MT5 ouvert et connecté au compte voulu :

```powershell
pwsh -File scripts\start.ps1               # jetons, base, schéma, jeton de l'agent, cœur, cockpit
pwsh -File scripts\start.ps1 -Simulated    # sans MT5 : terminal de démonstration en mémoire
pwsh -File scripts\start.ps1 -Plan         # dit ce que chaque étape ferait, n'écrit rien, ne lance rien
```

Le script s'arrête avec un message clair à la première étape qui manque : Docker, port 5433 pris par un autre conteneur (il ne l'arrête jamais lui-même), base `healthy`, environnement Python absent, migration en échec, cœur muet, base du cœur injoignable. Il ne fait **jamais** : se connecter à un courtier, demander ou stocker un identifiant, ouvrir MT5, attacher l'agent, relever le plafond de mode, armer quoi que ce soit.

À la main :

```
docker start tradingos-timescaledb → python -m trading_os db migrate → python -m trading_os serve → npm run dev
```

**Après un arrêt non propre** (redémarrage de la machine ou de Docker Desktop — les conteneurs sortent en code 255) : `docker start tradingos-timescaledb`, attendre `healthy`, relancer le cœur. Le cœur survit à une panne de base (il refuse alors toute commande : échec fermé) et le superviseur ouvre un incident ; MT5 est à rouvrir à la main, l'agent se reconnecte seul. **Rien ne redémarre le cœur** : sa fenêtre reste ouverte, c'est tout.

## Points de fragilité connus

- **Ports 3000, 8000 ou 5433 pris par d'autres projets** (constaté le 2026-11-01 : `jobart-frontend-1`, `jobart-backend-1`, `dossier-db-1`) : `start.ps1` s'arrête sans y toucher. Sans les arrêter, l'application tourne sur des ports libres — la base est recréée sans toucher au volume (`docker rm tradingos-timescaledb`, **jamais** `-v`), puis, depuis `04_code` :
  ```powershell
  $env:TRADINGOS_DB_PORT = "5434"; docker compose up -d timescaledb
  # depuis python\ — le cœur (lit .env pour les jetons) et le schéma :
  $env:DATABASE_URL = "postgresql://tradingos:tradingos_dev@127.0.0.1:5434/tradingos"
  $env:ALLOWED_ORIGINS = "http://localhost:3001,http://127.0.0.1:3001"
  .venv\Scripts\python.exe -m trading_os db migrate
  .venv\Scripts\python.exe -m trading_os serve --port 8001
  # depuis 04_code — le cockpit :
  $env:NEXT_PUBLIC_CORE_URL = "http://127.0.0.1:8001"; npm run dev -- -p 3001
  ```
  Sauvegarde avant la première migration : `docker exec tradingos-timescaledb pg_dump -Fc -U tradingos -f /tmp/tradingos.dump tradingos`, puis `docker cp` vers `exports/backups/` (le dump est logique : une restauration passe par la procédure TimescaleDB `timescaledb_pre_restore()`). `start.ps1` attend 5433 : pour revenir aux ports par défaut, libérer les trois ports puis recréer la base sans `TRADINGOS_DB_PORT`.
- **Port 5433 partagé avec un autre projet** (constaté le 2026-09-23) : le conteneur `e-commerce-db-1` publiait aussi `5433`. Il a été déplacé sur `127.0.0.1:55432` ; si l'autre projet revient sur 5433, `start.ps1` le détecte et s'arrête sans y toucher — c'est au trader de choisir lequel tourne.
- **Un seul `next dev` par dossier** (Next 16) : le second s'arrête sur « Another next dev server is already running ».
- **404 partout sauf `/` après l'ajout de `proxy.ts`** (vu une fois, cache `.next/dev` d'avant) : arrêter `next dev`, supprimer `.next/dev`, relancer. Idem si `tsc`/`next build` échouent sur `.next/dev/types/validator.ts` (fichier généré corrompu par deux régénérations concurrentes) : `rm -rf .next/dev/types`.
- **Un cockpit ouvert dans un onglet caché ne se peint pas** : React n'y révèle pas le contenu diffusé en flux, la page reste sur « Chargement de l'écran… » alors que le serveur répond. Ce n'est pas une panne — la vérifier dans un onglet visible (ou un Chrome headless).
- **Fins de ligne** — le dépôt a été cloné avec des fins de ligne CRLF alors que l'index git est en LF. `git config core.autocrlf true` dans ce clone ; si un `git status` affiche à nouveau tout le dépôt comme modifié, c'est ce réglage qu'il faut vérifier en premier — **surtout ne pas commiter la différence**.
- **Les jetons ne se relisent qu'au démarrage** : un jeton ajouté à `.env` n'est pas vu par un cœur déjà lancé (le relancer) ; un cockpit déjà ouvert relit `.env` seul.
- **Rien n'a encore tourné contre un vrai MT5 depuis la migration** : le cœur, le lien agent et le cockpit ont été vérifiés avec un terminal simulé et des sockets réels, pas avec un compte. Le premier rattachement d'un vrai compte est un essai à faire par l'utilisateur, en `OBSERVE`.
