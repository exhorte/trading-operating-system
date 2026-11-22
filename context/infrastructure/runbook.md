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

- **Santé** : `GET http://127.0.0.1:8000/api/system/health` (le seul endpoint sans jeton) — base, journal d'audit, ticks, clients WebSocket, workers MT5, agents connectés, tâches de fond. Le reste de l'API exige le jeton **et** une Origin du cockpit (lectures comprises). Le schéma OpenAPI est à `/api/openapi.json` (avec jeton).
- **Workers MT5** (ADR 0037) : `mt5Workers` de la santé compte les processus worker lancés, terminés et vivants par ce cœur. Attendu : **1 vivant par compte connecté**, 1 de plus le temps d'une reconnexion ; sous Windows chaque worker est **2 processus** (le `python.exe` du venv, qui est un lanceur, et l'interpréteur réel qu'il démarre en enfant). `alive` qui monte et ne redescend pas = fuite. Vérifier à la main : `Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'mt5.worker' }`. Une annulation (échéance d'un job, arrêt) ou un délai dépassé termine le worker **et** ses enfants ; avant l'ADR 0037 une annulation les laissait vivants.
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
python -m trading_os live-report --minutes 60        # mesures live d'une fenêtre (spread, cadence des ticks, durées des commandes) depuis la base — ADR 0035, L1 ; --from/--to pour le passé ; page dans exports\live\
curl -H "Authorization: Bearer $TOKEN" -H "Origin: http://localhost:3000" http://127.0.0.1:8000/api/accounts/<id>/profile          # ADR 0036 : qui est ce compte (déclaré à côté d'observé), avec quelle confiance
curl … /api/accounts/<id>/effective-policy                                                                                            # chaque limite, toutes ses sources, celle qui l'emporte
curl … /api/accounts/<id>/provider-loss                                                                                               # planchers de perte du fournisseur (références de 00:00, équité, marge restante) — « unknown » bloque les entrées
# (le cœur en marche donne les mêmes mesures + le retard de réception et le lien agent : GET /api/system/live-metrics?minutes=60)
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

## Voir l'état et le plan de démarrage, sans rien lancer (ADR 0038, I1)

Depuis `04_code\python` (le paquet `trading_os` ne s'importe que de là tant que l'installation éditable du venv pointe vers `C:\Dev\…`, disparu) :

```powershell
.venv\Scripts\python.exe -m trading_os launcher status     # prérequis, base / cœur / cockpit, qui tient chaque port, processus possédés
.venv\Scripts\python.exe -m trading_os launcher plan       # ce qu'un démarrage ferait (--json pour une sortie lisible par un programme)
```

**Lecture seule** : ni l'une ni l'autre n'écrit un fichier, ne lance ni n'arrête quoi que ce soit. Une réponse `FOREIGN` veut dire qu'un processus qui n'est pas de ce dépôt tient le port : il est signalé, jamais touché, jamais pris pour le composant. Code de sortie : 0 rien de bloquant · 1 une étape du plan est bloquée · 2 la machine n'a pas pu être observée (le lanceur échoue fermé).

### Démarrer, arrêter, adopter (ADR 0038, I2)

```powershell
.venv\Scripts\python.exe -m trading_os launcher start                      # démarre ce qui manque, dans l'ordre, en attendant la santé réelle de chaque maillon
.venv\Scripts\python.exe -m trading_os launcher stop --dry-run             # dit ce qui serait arrêté, n'arrête rien, n'écrit rien
.venv\Scripts\python.exe -m trading_os launcher stop                       # arrête cockpit, puis cœur, puis la base si c'est le lanceur qui l'a démarrée
.venv\Scripts\python.exe -m trading_os launcher adopt core                 # fait d'un cœur lancé à la main un processus que le lanceur possède (idem : cockpit)
```

- **`start`** : base (`docker start`, ou `docker compose up -d timescaledb` si le conteneur n'existe pas ; le volume reste externe), schéma (`db status` ; **sauvegarde `pg_dump` vers `exports/backups/` avant toute migration en attente**, jamais de migration sans elle ni par-dessus un schéma dérivé), cœur (depuis `04_code\python`, fenêtre masquée, sortie dans `var/launcher/logs/core-*.log`), cockpit (`npm run dev`, `cockpit-*.log`). Chaque maillon est ré-observé juste avant d'être démarré : ce qui est déjà sain n'est ni relancé ni dupliqué. Un maillon en échec bloque ceux qui en dépendent, et eux seuls. Ce qu'il lance est écrit dans `var/launcher/state.json` **avant** d'être attendu. Il n'arme rien, ne rattache aucun compte, ne touche pas à MT5 : après un démarrage, rattacher la démo reste un geste à toi.
- **`stop`** : seulement ce que le registre dit que le lanceur a démarré, vérifié par pid **et** heure de création (un pid recyclé n'est pas à lui). Le cœur reçoit d'abord un Ctrl+Break (uvicorn s'arrête en ordre et termine ses workers, ADR 0037), puis, après 30 s, l'arbre est terminé. Un cœur ou un cockpit lancé à la main est signalé « pas à moi » : fermer sa fenêtre, ou `adopt` puis `stop` — **l'arrêt poli est tenté d'abord ; si le processus ne le prend pas, l'arrêt est forcé et le rapport le dit** (mesuré le 2026-11-08 : le cœur adopté s'est arrêté par la demande polie, le cockpit a dû être arrêté de force). La base n'est arrêtée que si le lanceur l'a démarrée (ou avec `--include-database`), et jamais sous un cœur qui tourne encore. MetaTrader 5 et son agent ne sont pas touchés, aucune position n'est fermée, aucun ordre n'est envoyé. Après l'arrêt du cœur, un worker MT5 resté seul est signalé, pas tué.
- **Verrou** : `var/launcher/launcher.lock` empêche deux lanceurs à la fois ; un verrou dont le propriétaire a disparu (ou dont le pid a été recyclé) est remplacé. Journal des événements : `var/launcher/events-AAAAMMJJ.jsonl`. Le dossier `var/` est ignoré par Git.
- **Codes de sortie** : 0 fait · 1 une étape bloquée, refusée ou en échec (ou un autre lanceur tourne) · 2 observation impossible.
- `scripts\start.ps1` reste en repli, inchangé.

### `TradingOS.bat`, les modes et `doctor` (ADR 0039, I2b)

Un seul point d'entrée, depuis n'importe quel dossier (double-clic, ou un terminal) : `04_code\TradingOS.bat [Mode] [options]`. Il lance `scripts\TradingOS.Launcher.ps1` (PowerShell 7 s'il existe, sinon Windows PowerShell 5.1 ; `-ExecutionPolicy Bypass` vaut pour ce processus seulement, aucune politique n'est modifiée), qui fixe le dossier courant à `04_code\python` (le venv éditable cassé, A10, ne s'importe que de là) et appelle `python -m trading_os launcher …`. Rien d'autre, sauf **une étape avant `Full` et `Infrastructure`** (décision d'Exhorte du 2026-11-22, ADR 0038 A11) : `scripts\TradingOS.Docker.ps1` lance Docker Desktop s'il ne répond pas et attend son moteur (180 s au plus ; jamais avant `Status`, `Stop`, `Doctor` ni `MT5` ; `TRADINGOS_NODOCKERSTART=1` l'évite ; un échec n'arrête rien, le lanceur dit lui-même que Docker ne répond pas). L'enveloppe ne lit pas `.env`, ne touche à aucun conteneur, ne termine aucun processus, ne touche pas à MT5.

```powershell
.\TradingOS.bat Status                  # launcher status  — lecture seule
.\TradingOS.bat Doctor                  # launcher doctor  — lecture seule, explique et ne répare rien
.\TradingOS.bat Doctor -Json            # idem, sortie JSON (aucun autre texte)
.\TradingOS.bat Stop -DryRun            # launcher stop --dry-run — dit ce qui serait arrêté
.\TradingOS.bat Infrastructure          # launcher start  — démarre ce qui manque (base, schéma, cœur, cockpit)
.\TradingOS.bat                         # = Full : l'infrastructure, puis le plan de préparation de MetaTrader 5 (lecture seule)
```

| Mode | Sous-commande | Aujourd'hui |
|---|---|---|
| `Status` | `launcher status` | lecture seule |
| `Doctor` | `launcher doctor` | lecture seule, **sans verrou, sans écriture** |
| `Stop` (`-DryRun`, `-IncludeDatabase`) | `launcher stop` | seulement ce que le lanceur a démarré ou adopté |
| `Infrastructure` | `launcher start` | base, schéma (avec sauvegarde avant toute migration), cœur, cockpit |
| `Full` (défaut) | `launcher start`, puis `launcher mt5 plan` si le démarrage a réussi | le plan MT5 est en lecture seule ; avec `-Json`, seule l'infrastructure est rapportée (une note va sur la sortie d'erreur) |
| `MT5` | `launcher mt5 plan` | détecte les terminaux, dit ce qui est enregistré et ce qui reste à faire ; lecture seule |

`-Apply` est accepté mais **sans effet** : le déploiement, le preset et le lancement de MetaTrader 5 n'existent pas encore (I4 à I7). `-DryRun` et `-IncludeDatabase` n'ont de sens que pour `Stop` (ignorés ailleurs, avec une note). Variable `TRADINGOS_NOPAUSE=1` : le `.bat` n'attend pas une touche à la fin (sinon, lancé par double-clic, il garde la fenêtre ouverte). **Codes de sortie** : ceux du lanceur — 0 rien d'anormal · 1 un problème, un refus ou un échec · 2 la machine n'a pas pu être observée (le script ajoute : 2 si le Python du cœur est introuvable).

**`doctor`** explique ce que le lanceur sait observer et quoi faire : l'environnement (Docker, Python du cœur, présence de `.env` — jamais son contenu —, npm), les composants (état, propriétaire de chaque port, base / cœur / cockpit), l'état du lanceur (verrou périmé ou tenu, registre illisible, processus possédés) et la santé que le cœur déclare (statut, signalements, agents EA connectés, workers MT5 contre « un compte à la fois »). Chaque constat porte un code, une gravité (`OK`, `INFO`, `ATTENTION`, `PROBLÈME`, `?`), une explication et, pour tout problème ou avertissement, une action. Seul un `PROBLÈME` donne le code de sortie 1. **Côté MetaTrader 5 il dit ce qui est trouvé** (installations, instances, jonction de l'agent, dossier `Presets`, EA tiers installés, terminaux non enregistrés ou introuvables, opérations en cours ou périmées) **mais pas l'état de l'EA, du preset ni du graphique : ils ne sont pas encore inspectés** (une ligne « ? » le dit) — il n'invente aucun état. Un cœur qui ne rapporte pas ses agents ou ses workers n'est pas accusé (« non rapporté », pas zéro).

### Trouver, enregistrer et planifier les terminaux MetaTrader 5 (ADR 0039, I3)

```powershell
.venv\Scripts\python.exe -m trading_os launcher mt5 detect          # installations, dossiers de données, instances en cours — lecture seule (--json)
.venv\Scripts\python.exe -m trading_os launcher mt5 list            # terminaux enregistrés et ce qui reste à déclarer — lecture seule
.venv\Scripts\python.exe -m trading_os launcher mt5 plan            # ce que la préparation ferait ensuite — lecture seule (= TradingOS.bat MT5)
.venv\Scripts\python.exe -m trading_os launcher mt5 register --terminal <identifiant> [--label …] [--account-id …] [--expected-login …] `
    [--symbol … --period …] [--magic …] [--allowed-symbols a,b] [--provider …] [--product …]
.venv\Scripts\python.exe -m trading_os launcher mt5 register --install-path <dossier> --data-path <dossier>   # à la main, quand la détection échoue
.venv\Scripts\python.exe -m trading_os launcher mt5 register --install-path <dossier> --portable             # terminal portable : données dans son dossier
```

- **Détection** : trois sources (liste des programmes installés, dossiers `*MetaTrader*` de Program Files, processus `terminal64.exe`) plus les chemins déjà enregistrés ; un chemin n'est cru que si `terminal64.exe` y est. Un dossier de données est rattaché à une installation par son seul `origin.txt` (`Common` et `Community` n'en ont pas : ce ne sont pas des terminaux). **Plusieurs terminaux : tous listés, aucun choisi** — le choix se fait avec `--terminal`. Un terminal portable *arrêté* n'est pas détecté automatiquement : `--portable`.
- **Ce qui n'est jamais lu ni gardé** : le contenu de `common.ini` (non lu dans cet incrément), le fichier de liaison de l'agent (sa présence seulement), la ligne de commande d'un `terminal64.exe` (elle peut porter `/login:` et un mot de passe : il n'en sort que `/portable` et `/config:`).
- **`register`** n'écrit qu'**un** fichier, le sien : `var/launcher/terminals.json` (plus un événement). Rien dans un dossier de MetaTrader. Il ne demande ni mot de passe ni jeton — aucune option n'en existe. Une déclaration est vérifiée : numéro magique de 1 à 2 147 483 647, login en chiffres, période parmi `M1 … MN1`, symboles aux noms du courtier, symbole du graphique dans la liste des symboles autorisés. **Un numéro magique, un compte Trading OS et un login attendu ne peuvent appartenir qu'à un seul terminal.** Re-enregistrer un terminal ne change que ce qui est donné ; l'ancien fichier est gardé en `terminals.json.bak-…`, un fichier illisible en `terminals.json.corrupt-…`. Un enregistrement à la main est refusé si `origin.txt` ne désigne pas l'installation donnée (« identité ambiguë »).
- **Codes de sortie** : 0 fait · 1 refusé ou en échec (déclaration invalide, terminal inconnu, registre tenu par un autre lanceur) · 2 la machine n'a pas pu être lue.

## Démarrer et arrêter depuis le cockpit (ADR 0034)

`start.ps1` (ou les commandes à la main ci-dessus) lance l'application : base, cœur, cockpit. Rien d'autre. Depuis le cockpit :

- **Command Center → « DÉMARRER LE SYSTÈME »** (ou l'écran **Démarrage**) : vérifie treize étapes, force une lecture du terminal et une réconciliation, connecte le compte sélectionné **sans mot de passe** s'il ne l'est pas, puis monte `OFF → OBSERVE`. Ne monte jamais au-dessus de `CONFIRM` ; n'envoie aucun ordre. Si une étape bloquante échoue (base, terminal, compte), le système reste `OFF` et dit laquelle.
- **Écran Démarrage → « AUTORISER LE TRADING AUTOMATIQUE »** : geste séparé, un échelon, vingt-deux conditions vertes à cet instant ; un compte réel exige une case cochée. Un redémarrage du cœur retombe **toujours** à `OFF`.
- **« FERMER TOUTES LES POSITIONS »** (Command Center, Positions) : prévisualisation, confirmation explicite, un `CLOSE` par position, suivi en direct, réconciliation, rapport. Marche dans tous les modes, `HALTED` compris. Tant que l'agent est compilé `OBSERVE`, il refuse (`AGENT_OBSERVE`) et rien n'est fermé chez le courtier : le cockpit le dit.
- **Arrêts** : « Arrêter les nouvelles entrées » (→ `OBSERVE`), « Arrêter les moteurs de stratégie » (→ `OFF`), arrêt d'urgence (barre latérale : `HALTED`, ne ferme rien). Quatre gestes distincts : `autonomy-modes.md`.

Ces boutons ne se cliquent pas pendant le développement par Claude (`.claude/CLAUDE.md`) : l'essai sur la démo est fait par l'utilisateur.

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
- **Vérifié sur le vrai terminal (2026-11-03, démo Exness)** : l'attache sans mot de passe, la lecture du compte, des spécifications, des ticks, des bougies, des positions et des ordres, le refus d'un mauvais serveur, le détachement puis le rattachement, l'inaccessibilité des fonctions d'ordre, le dimensionnement avec les chiffres du courtier (14 tests de contrat, `MT5_LIVE_TESTS=1`), et la lecture continue du flux par le cœur (mesures L1). **Jamais vérifié chez un courtier** : l'agent, les commandes, les accusés, les remplissages, la réconciliation avec des positions réelles, la reconnexion après coupure.

## Préparer, déployer et lancer l'agent dans MetaTrader 5 (ADR 0039, I4 à I10)

Tout se lance depuis `04_code\python` (`.venv\Scripts\python.exe -m trading_os launcher mt5 …`) ou par `TradingOS.bat MT5`. **Aucune de ces commandes ne prend un mot de passe ou un jeton, aucune ne rattache ni ne détache un compte, aucune ne relève un mode ; le lanceur s'arrête à l'attachement de l'agent** (jamais `CONFIRM`, `ARMED` ni `AUTONOMOUS`).

| Étape | Commande | Ce qui est écrit |
|---|---|---|
| Trouver | `mt5 detect`, `mt5 plan` | rien |
| Enregistrer | `mt5 register --terminal ID --account-id … --expected-login … --symbol … --period … --magic … --allowed-symbols … --provider … --product …` | `var/launcher/terminals.json` ; **le produit est ta déclaration** : sans lui, `EA_READY` reste bloqué `PRODUCT_UNDECLARED` |
| Compiler | `mt5 build --terminal ID` | une copie de travail (supprimée), puis `var/launcher/mt5/builds/<version>-<empreinte>/` (`.ex5`, manifeste, journal) ; refuse un agent non compilé en `OBSERVE` |
| Déployer | `mt5 deploy --terminal ID [--dry-run]` | le seul `.ex5` de l'agent (à travers la jonction existante), l'ancien est gardé dans `var/launcher/backups/<terminal>/` ; échoue proprement si le fichier est utilisé (détacher l'agent ou fermer le terminal) |
| Préparer | `mt5 prepare --terminal ID [--dry-run]` | `MQL5\Presets\TradingOS-<terminal>.set` et `var/launcher/mt5/<terminal>/startup.ini` |
| Lancer | `mt5 start --terminal ID --dry-run`, puis `mt5 start --terminal ID [--confirm-close]` | rien dans MetaTrader : il le lance (ou, s'il est ouvert, le ferme **poliment** puis le relance) avec `/config:` ; **avec le pilote (ADR 0043)** : détacher d'abord le compte dans le cockpit (ce geste met aussi le pilote en pause) — les portes `CORE_WORKER_DETACHED` et `AUTOPILOT_PAUSED` le vérifient ; après le `hello` de l'agent, rattacher le compte et « démarrer le système » (ou redémarrer le cœur) relance le pilote |
| Lire | `mt5 status`, `mt5 verify --terminal ID`, page **System Center** (`/system`) | `status` journalise un changement d'état ; le reste est en lecture seule |

**Fermer un terminal ouvert** : `start --dry-run` montre huit portes (identité du terminal, agent déployé conforme, preset préparé conforme, **0 position, 0 ordre en attente** lus sur le terminal, login conforme, **aucun worker du cœur attaché**). Si une seule est rouge, rien n'est fermé. Pour passer : `start --confirm-close`, puis **taper** `FERMER <identifiant du terminal>` — il n'y a pas d'option `--yes`, et la phrase est la tienne. Détacher le compte du cœur avant (Settings) si un worker y est attaché (R16 : un worker qui trouve MetaTrader fermé le relance sans l'agent).

**Avant de lancer** : les experts doivent être autorisés dans MetaTrader (Outils > Options > Experts — le lanceur n'écrit jamais ce réglage) et `127.0.0.1` listé pour WebRequest (il ne peut pas le lire). Sans cela, `start` se termine en `EA_ERROR(MT5_EA_NOT_REPORTING)` avec ce qu'il a pu établir (`MT5_EXPERTS_DISABLED` quand `common.ini` le dit).

**Retour arrière** : le `.ex5` précédent est dans `var/launcher/backups/<terminal>/` ; pour revenir à l'agent 1.13, copier ce fichier à la place de `tools\mt5-execution-agent\TradingOsAgent.ex5` (agent détaché). `common.ini` n'est jamais modifié par le lanceur ; sa copie de précaution avant l'essai `/config` est `var/launcher/backups/<terminal>/common.ini.before-r1-trial`.
