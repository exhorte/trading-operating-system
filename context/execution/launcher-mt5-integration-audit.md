# Audit — lanceur Trading OS, orchestration du terminal MT5 et déploiement de l'agent (Phase 0, 2026-11-06)

Phase 0 de la mission « Trading OS Launcher, MT5 auto-deployment & execution readiness » (Exhorte, 2026-11-06). **Lecture seule : aucun code, aucun réglage, aucun processus n'a été modifié, redémarré ou tué pour l'écrire ; ce document est le seul fichier créé.** Aucun clic sur un bouton du cockpit, aucun ordre, aucun accès à `04_code/.env`, aucune lecture du jeton de l'agent ni d'un identifiant.

Lu : `scripts/start.ps1`, `context/infrastructure/runbook.md`, `tools/mt5-execution-agent/` (README, `TradingOsAgent.mq5` : entrées, `OnInit`, `SendHello`, `SendHeartbeat`, `ReadCoreToken`), `python/trading_os/` (`app/config.py`, `infrastructure/mt5/{protocol,transport,wire,ea_link}.py`, `services/{readiness,startup,accounts}.py`, `domain/system/startup.py`, `domain/autonomy/readiness.py`, `api/routes/system.py`, `api/schemas/system.py`), `components/shell/nav.ts`, `app/(cockpit)/`, `package.json`, `.gitignore`, ADR 0010, 0034, 0036, 0037. Mesuré sur le poste, en lecture seule : processus et ports, Docker, installations et dossier de données MT5, `config\common.ini` (clés non sensibles seulement), profils de graphiques, empreintes et dates des fichiers de l'agent, import du paquet Python, `start.ps1 -Plan`. La page officielle MetaTrader 5 « Platform Start - For Advanced Users » a été lue par un sous-agent de lecture ; **ses affirmations ne sont pas éprouvées sur ce poste**.

Légende : **Lu** = dans le code ou la doc · **Mesuré** = relevé sur ce poste le 2026-11-06 · **Non vérifié** = ni l'un ni l'autre (à éprouver sur la démo, avec l'accord d'Exhorte).

## 0. Ce qu'il faut retenir

1. **Il n'existe qu'un lanceur partiel** (`scripts/start.ps1`) : base, schéma, jeton de l'agent, cœur, cockpit. Il n'a ni arrêt, ni registre de PID, ni journal de fichier, ni identification du propriétaire d'un port, ni rien pour MT5 ou l'agent.
2. **Cause racine du piège de `start.ps1` (Mesuré)** : le paquet `trading-os` du venv est installé en mode éditable vers `C:\Dev\trading-operating-system\04_code\python`, **dossier qui n'existe plus**. `import trading_os` échoue donc depuis `04_code` et ne marche que depuis `04_code\python`. Une réinstallation éditable depuis le dépôt actuel le corrige sans toucher au code (action sur le venv : à autoriser).
3. **Le cœur sait déjà presque tout ce qu'un état « prêt » demande** : 16 contrôles de préparation + 6 conditions de démarrage (ADR 0034), un registre d'agents (un par login), un `agent.hello` riche (identité observée par l'EA, permissions, `attachedExperts`, version, capacités), un `heartbeat` à 5 s, un superviseur à incidents. **Ne pas le dupliquer** : l'état « prêt non armé » est une lecture de ce qui existe.
4. **Ce que l'agent ne dit pas aujourd'hui** : ni symbole ni période du graphique, ni chemin de données du terminal, ni état d'initialisation, ni version de protocole (seulement `"version":1` d'enveloppe, `agentVersion`, `buildId`, `capabilities`). Prouver l'attachement « au graphique configuré » (§10.4 de la mission) demande soit un build 1.14 de l'agent (accord et ADR séparés), soit une inférence moins forte.
5. **Risque n° 1 sur MT5** : `terminal64.exe /config:<ini>` pourrait **remplacer** `common.ini` pour la session. Or ce fichier porte la liste « Allow WebRequest » (codée, illisible hors MT5) et `[Experts] Enabled=0`. Un ini mal conçu pourrait faire perdre l'autorisation du cœur à l'EA (erreur 4014) ou changer la permission d'algo-trading. **Non vérifié ; à éprouver d'abord.**
6. **Le worker du cœur peut lancer MT5 lui-même** (`mt5.initialize` peut démarrer le terminal, d'où `SLOW_CALLS = 60 s`). Si un compte est rattaché avant que le lanceur n'ait démarré MT5 avec sa configuration, le terminal démarrera **sans** EA. L'ordre du lanceur compte : préparer et lancer MT5 avant tout rattachement. **Lu (commentaire du code) ; non vérifié ici.**
7. **Un seul MT5 est installé** (`C:\Program Files\MetaTrader 5`, non portable) et il est **déjà ouvert**, lancé à la main. Aucun EA n'y est attaché. Un EA tiers (`Ultimate_ICT_Gold_Scalper_v4.0`) est installé à côté du nôtre.
8. **Rien dans la mission n'exige de toucher au Risk Engine, aux modes d'autonomie ni au mode compilé de l'agent.** Toutes les phases peuvent se faire sans les élargir.

## 1. Architecture actuelle

```
        Windows (utilisateur)
 ┌─────────────────────────────────────────────────────────────────────────┐
 │ Docker Desktop ── conteneur tradingos-timescaledb  127.0.0.1:5433       │
 │ PowerShell « coeur »   python -m trading_os serve (uvicorn)             │
 │        ├─ API REST + WebSocket /ws                127.0.0.1:8000        │
 │        ├─ lien agent (TCP, un JSON par ligne)      127.0.0.1:9765       │
 │        └─ workers MT5 (1 par compte, enfants, lecture seule, ADR 0037)  │
 │ PowerShell « cockpit » npm run dev (Next 16, -H 127.0.0.1)  :3000       │
 │ terminal64.exe (MT5, lancé à la main) ──► EA TradingOsAgent (si attaché)│
 └─────────────────────────────────────────────────────────────────────────┘
 lecture : terminal ─► worker ─► cœur ─► base / WebSocket ─► cockpit
 ordres  : cœur ─► ea_link (TCP) ─► agent ─► OrderSend (une seule fois, inatteignable : mode compilé OBSERVE)
```

| Élément | Fait établi | Source |
|---|---|---|
| Ports | cockpit 3000, cœur 8000, lien agent 9765, base 5433 ; tous à l'écoute sur 127.0.0.1 après la relance de ce matin | Mesuré |
| Jetons | `TRADINGOS_COCKPIT_TOKEN` et `TRADINGOS_AGENT_TOKEN` dans `.env` (jamais lu) ; **un seul jeton d'agent pour tous les terminaux**, copié par `start.ps1` dans `MQL5\Files\tradingos_agent.token` | Lu |
| Lien agent | `agent.hello` doit porter le jeton (comparaison à temps constant, échec fermé s'il manque) ; **un agent par login**, un second est refusé ; chien de garde 30 s ; `control.ping` toutes les 5 s | Lu (`ea_link.py`) |
| Hello (champs) | `agentId` (dérivé du numéro magique), `accountId` (login observé), `broker`, `server`, `currency`, `leverage`, `tradeMode`, `marginMode`, `fifoClose`, 4 permissions de trading, `identity` (`ok`/`mismatch`/`no_account`), `expectedAccountId`, `mode`, `modeCeiling`, `agentVersion`, `buildId`, `capabilities`, `halted`, `attachedExperts` | Lu (`wire.py`, `SendHello`) |
| Instance unique | l'EA se retire s'il en existe déjà un dans le terminal ; le cœur refuse un second hello pour le même login | Lu |
| Préparation | `ReadinessFacts` : `python_core`, `database`, `mt5_connected`, `correct_account`, `symbols_available`, `risk_engine`, `sizing_valid`, `reconciliation`, `kill_switch_available`, `heartbeat`, `supervisor`, `execution_engine`, `strategy_valid`, `position_management`, `no_critical_incident`, `account_limits_configured` (16) ; ADR 0034 : + 6 conditions propres au démarrage (22) | Lu |
| Démarrage dans le cœur | `StartupService` **vérifie** treize étapes, lit le terminal, réconcilie, connecte le compte sélectionné **sans mot de passe**, monte `OFF → OBSERVE` ; il **n'est pas un lanceur** (son en-tête le dit) et ne peut pas démarrer un cœur qui n'écoute pas | Lu |
| Santé | `GET /api/system/{health,status,readiness,startup,incidents,live-metrics,events}` ; `mt5Workers` {spawned, ended, alive} depuis l'ADR 0037 | Lu + Mesuré |
| Terminal ↔ compte | `Account.terminal_path` (nullable) est passé à `mt5.initialize(path=…)` ; un seul compte connecté à la fois (ADR 0021) ; identification fournisseur par signaux indépendants (ADR 0036) | Lu |
| Cockpit | 13 écrans (`nav.ts`), dont Démarrage, Account, Agents & Audit, Settings ; WebSocket + store pur + REST typé (`lib/api/generated.ts`, généré depuis le cœur) | Lu |
| Secrets dans les journaux | `shared/logging/redaction.py` masque les secrets enregistrés au chargement de la configuration | Lu |

## 2. Scripts et procédures existants

Un seul script : `04_code/scripts/start.ps1` (16,5 Ko, 2026-11-03). Aucun script d'arrêt, de compilation, de déploiement de l'EA ni de découverte de terminal. La compilation est manuelle (MetaEditor, sur une **copie**), l'installation de l'EA est une **jonction** (`MQL5\Experts\TradingOsAgent` → `04_code\tools\mt5-execution-agent`, Mesuré).

`start.ps1`, étape par étape, et ses limites :

| Étape | Ce qu'il fait | Limite constatée |
|---|---|---|
| 0 Jetons | écrit `TRADINGOS_*_TOKEN` et `DATABASE_URL` dans `.env` s'ils manquent (valeurs jamais affichées) | correct ; n'écrit rien en `-Plan` |
| 1 Base | `docker info`, refuse si un autre conteneur tient 5433, `docker start` ou `compose up`, attend `healthy` (90 s) | échoue si Docker Desktop est éteint (aucune tentative de le lancer) ; `-Plan` dit « démarrerait » même si le conteneur tourne déjà |
| 2 Schéma | `python -m trading_os db migrate` | dépend du `cwd` (cf. D2) ; migrations additives seulement |
| 3 Jeton | copie le jeton dans `MQL5\Files` de chaque terminal **ouvert** (processus `terminal64` → `origin.txt`) | rien pour un terminal fermé ni pour une installation non ouverte ; aucune découverte ; un seul jeton pour tous |
| 4 Cœur | ouvre une fenêtre PowerShell `-NoExit`, attend `/api/system/health` (60 s) | **cwd = `04_code`** (D2) ; aucun PID gardé ; journal = console seulement |
| 5 Cockpit | ouvre une fenêtre `npm run dev` si rien n'écoute sur 3000 | **n'identifie pas le propriétaire du port** (« quelque chose écoute déjà … laissé tel quel ») ; n'attend ni ne contrôle la santé du cockpit |
| Bilan | dit si un agent est connecté, rappelle la procédure d'attache | informatif seulement |

Défauts à corriger ou à encadrer :

- **D1** Aucun registre de processus : ni PID, ni heure de création, ni ligne de commande ; **aucun arrêt**. Les fenêtres sont le seul « propriétaire ».
- **D2** Cause racine mesurée : `pip list` montre `trading-os 0.2.0` éditable vers `C:\Dev\trading-operating-system\04_code\python` (absent) ; `import trading_os` échoue depuis `04_code`, réussit depuis `04_code\python`. Le contournement documenté (ouvrir le cœur depuis `python\`) masque le défaut.
- **D3** Port 3000 (et 8000, 9765) : un processus étranger serait pris pour le nôtre ; aucune identification (processus, ligne de commande, dossier courant).
- **D4** Pas de journal de fichier, pas de rotation, pas d'identifiant de corrélation, pas d'événement structuré pour le lancement.
- **D5** Jeton de l'agent écrit seulement pour les terminaux ouverts ; **un jeton global** (la mission demande un jeton par instance).
- **D6** Aucune préparation MT5/EA : ni lancement, ni déploiement, ni preset, ni configuration de démarrage, ni vérification d'attachement.
- **D7** Cockpit en `npm run dev` : compilation à la volée, 404 connus après un cache `.next/dev` périmé, une seule instance par dossier, `next build` déconseillé en parallèle.
- **D8** Aucun test automatisé de `start.ps1` : la recherche de `start.ps1`, `Get-Mt5DataFolders` et `tradingos_agent.token` dans `python/tests` ne donne **aucune occurrence**. Le lien agent, lui, est testé sur de vrais sockets (`tests/integration/test_ea_link.py`, jeton compris).
- **D9** Les documents se contredisent sur la compilation dans le dépôt : le HANDOFF dit « jamais dans le dossier du dépôt », la mémoire du projet dit que `*.ex5` est ignoré par Git (vrai : `.gitignore:50`) et le `.ex5` a été compilé dans le dépôt le 2026-11-03 à la demande d'Exhorte.

## 3. Fonctionnalités déjà disponibles et réutilisables

| Besoin de la mission | Déjà là | Réutilisation |
|---|---|---|
| Démarrer la base et attendre sa santé | `start.ps1` étape 1 | porter la logique, ajouter l'identification du conteneur (nom exact) |
| Santé du cœur | `/api/system/health` (+ `mt5Workers`, `findings`) | telle quelle |
| Identité du compte | `identity` du hello (login lu **par l'EA**), `correct_account`, identification fournisseur (ADR 0036) | telle quelle ; l'association explicite compte ↔ terminal vient s'y ajouter |
| Un seul agent par compte | registre `ea_link` par login | telle quelle |
| Heartbeat frais | `AGENT_FRESH = 15 s` dans `readiness.py` | telle quelle |
| Jeton valide | refus à `agent.hello` avec raison journalisée (sans citer le jeton) | telle quelle |
| Compatibilité | `agentVersion`, `buildId`, `capabilities` ; le cœur n'envoie `limit`/`modify`/`close`/`cancel` qu'à un agent qui les annonce | à compléter (cf. §4) |
| Permissions de trading | 4 permissions dans hello/heartbeat (`terminal_trade_allowed`, `expert_trade_allowed`, `account_trade_expert`, `account_trade_allowed`) | telles quelles pour « permission : désactivée » |
| Spécifications d'instruments complètes | `InstrumentSpecification` avec `missing` (ADR 0036) | telle quelle |
| Incidents bloquants | `no_critical_incident`, superviseur | tel quel |
| Limites chargées | `account_limits_configured` | tel quel |
| Traçabilité | table d'événements avec `correlation_id`, masquage des secrets | réutiliser pour les événements du lanceur une fois le cœur levé |
| Faux terminal | `FakeMt5` (742 lignes) | tests du lanceur et du gestionnaire de terminaux sans MT5 réel |
| Mesures live | `GET /api/system/live-metrics`, `python -m trading_os live-report` | inchangées |

## 4. Fonctionnalités manquantes

1. Lanceur unique, idempotent, avec registre de PID, journaux de fichier et arrêt propre (D1, D3, D4).
2. Découverte des installations MT5 (registre Windows, raccourcis, dossiers connus, processus), **registre persistant** séparant ce qui est **observé** de ce qui est **déclaré**, et **association explicite** compte ↔ terminal ↔ dossier de données ↔ EA (aujourd'hui seulement `terminal_path` nullable).
3. Gestionnaire de déploiement de l'EA : manifeste (SHA-256, version, taille, date, empreinte des sources), copie atomique, sauvegarde, vérification du hash, retour arrière. Aujourd'hui : jonction, sans manifeste.
4. Générateur de preset `.set` aux entrées **exactes** de l'agent 1.13 ; le seul précédent, `ea1.set` (2026-09-26, gitignoré), porte les anciens noms `InpGatewayHost`/`InpGatewayPort` et n'a pas `InpDeadManSeconds`, `InpPendingMaxMinutes`, etc.
5. Générateur de configuration de démarrage (`[StartUp]`), lancement ou redémarrage contrôlé, vérification de l'attachement.
6. États distincts : terminal (arrêté, démarrage, en cours, connecté), EA (non déployé, déployé, attaché, initialisation, connecté, dégradé, déconnecté, **protocole incompatible**), exécution (non prête, prête, **armée**, arrêtée). Aujourd'hui : `StartupStageState` (STOPPED/STARTING/READY/RUNNING/DEGRADED/FAILED/HALTED) par étape, et `AgentStatus`.
7. Télémétrie de l'agent absente du hello : **version de protocole**, **symbole et période du graphique**, **chemin de données du terminal** (ou son identifiant d'instance), **état d'initialisation**. Sans eux, « EA attaché au graphique attendu » ne se prouve pas par l'EA.
8. Détection de l'autorisation WebRequest : **impossible par lecture de fichier** (cf. R2) ; seulement par comportement.
9. Évaluation « READY_NOT_ARMED » avec raisons de blocage, avertissements, dernier succès et dernier échec ; **System Center** dans le cockpit ; actions (Démarrer, Connecter MT5, Redémarrer MT5, Redémarrer le cœur, Arrêter).
10. Tests du lanceur, du gestionnaire de terminaux, du déploiement et de l'attachement (§14 de la mission).

### État réel du poste (Mesuré, 2026-11-06)

| Fait | Valeur |
|---|---|
| Installations MT5 | **une** : `C:\Program Files\MetaTrader 5` (registre : « MetaTrader 5 », version 5.00 ; `terminal64.exe` et MetaEditor 5.0.0.6230) ; un raccourci du menu Démarrer, sans argument |
| Terminal en cours | **oui**, un processus, lancé sans argument (non portable) |
| Dossier de données | un seul : `%APPDATA%\MetaQuotes\Terminal\D0E8209F…F075`, `origin.txt` = l'installation ci-dessus ; les dossiers `Common` et `Community` n'ont pas d'`origin.txt` |
| Installation de l'EA | jonction `MQL5\Experts\TradingOsAgent` → `04_code\tools\mt5-execution-agent` ; **EA tiers** `Ultimate_ICT_Gold_Scalper_v4.0` (`.mq5` et `.ex5`) dans `MQL5\Experts` |
| `MQL5\Presets` | **n'existe pas** |
| Jeton de l'agent | présent dans `MQL5\Files` (43 octets, écrit ce matin) ; contenu non lu |
| `config\common.ini` | `[Experts]` : `Enabled=0` (permission d'algo-trading globale **désactivée** dans le fichier), `Account=1`, `Profile=1`, `AllowDllImport=1`, `WebRequest=1`, `WebRequestUrl=` valeur codée (**illisible**) |
| Graphiques du profil `Default` | 3 (`EURUSDm`, `GBPUSDm`, `XAUUSDm`), **aucun EA attaché** ; le profil date du 2026-09-25 |
| Journal des experts | `MQL5\Logs\20261101.log` (190 octets) : l'agent n'a pas été attaché depuis |
| Fichiers de l'agent | `TradingOsAgent.ex5` 139 452 octets, 2026-11-03 14:42 ; sources 2026-11-03 10:18 ; `compile.log` du 2026-09-26 (périmé) ; aucun manifeste liant le `.ex5` à ses sources |
| Paquets du venv | `MetaTrader5` 5.0.6231, `pywin32` 312 ; **pas de `psutil`** |
| Cœur / cockpit / base | tournent (relance de ce matin) ; 0 agent, 0 worker MT5, aucun compte rattaché |

### Possibilités natives de MetaTrader 5 (page officielle, lue par un sous-agent ; non éprouvées ici)

| Mécanisme | Ce que dit la page | Utilisable ici ? |
|---|---|---|
| `terminal64.exe /config:<ini>` | lance avec un fichier de configuration alternatif (défaut : `common.ini`) ; le fichier est utilisé en **lecture seule** | **Oui, à éprouver** (R1) |
| `[StartUp]` | `Expert`, `Symbol`, `Period` (H1 si absent), `Template`, `ExpertParameters` (nom d'un `.set`), `Script`, `ScriptParameters`, `ShutdownTerminal` (scripts seulement) ; sans `Symbol`, l'EA va sur le premier graphique du profil ; sans `Expert`, aucun EA ; l'EA tourne sur un graphique ouvert pour l'occasion, non sauvegardé à la fermeture | **Oui** : `Expert=TradingOsAgent\TradingOsAgent` (chemin tel que MT5 le voit par la jonction) |
| Emplacement du `.set` | `MQL5\presets` du dossier de données (la page écrit aussi `Presets`) ; sans lui, valeurs par défaut | **Oui** ; le dossier est à créer ; encodage du `.set` non précisé (**Non vérifié**) |
| `[Experts]` | `AllowLiveTrading`, `AllowDllImport`, `Enabled`, `Account`, `Profile` | **Ne jamais écrire** (permissions de trading) ; observer seulement |
| `[Common]` | `Login`, `Server`, `Password`, … | **Ne jamais écrire** (aucun identifiant, aucun changement de compte) |
| `/profile:<nom>`, `/login:`, `/portable` | profil existant ; compte ; mode portable (droits administrateur sous Program Files) | `/login` exclu (change de compte) ; `/portable` exclu ; `/profile` possible mais sans création documentée de profil |
| Terminal déjà lancé | **non précisé par la page** | traiter comme **non pris en charge** : redémarrage contrôlé et confirmé |
| Plusieurs instances | deux copies ne peuvent pas tourner depuis le même dossier ; plusieurs dossiers d'installation pour plusieurs terminaux | cohérent avec la contrainte MetaQuotes de la mission |
| WebRequest / URL autorisées | **non précisé par la page** ; réglage dans Outils → Options → Expert Advisors ; le README de l'agent le requiert pour `127.0.0.1` | détection par comportement seulement (R2) |

## 5. Dépendances

Windows 10/11 ; Docker Desktop (conteneur `tradingos-timescaledb`, volume `trading_operating_system_algorithmique_tradingos-pgdata`) ; venv Python 3.14 avec `MetaTrader5` (Windows seulement) ; Node/npm (Next 16.2.10) ; MetaTrader 5 5.0.0.6230 et MetaEditor (compilation) ; Windows PowerShell 5.1 (`start.ps1` appelle `powershell.exe`) ou PowerShell 7 ; `.env` gitignoré (jamais lu par Claude) ; droits utilisateur suffisants pour écrire dans `%APPDATA%\MetaQuotes\Terminal\<id>` ; **aucun droit administrateur requis**, sauf `/portable` sous Program Files (exclu). Nouvelle dépendance éventuelle : `psutil` (identification des processus) — décision d'Exhorte, sinon `Get-CimInstance` via PowerShell.

## 6. Risques techniques

| # | Risque | Gravité | Contre-mesure | État |
|---|---|---|---|---|
| R1 | `/config:` remplace `common.ini` pour la session : perte de la liste WebRequest (codée) ou d'un réglage `[Experts]` | élevée | n'écrire que `[StartUp]` ; ne jamais écrire `[Experts]` ni `[Common]` ; **essai sur la démo** avec redémarrage confirmé, puis contrôle de la liste WebRequest (par le hello) et de `Enabled` ; plan B : ne pas utiliser `/config` et attacher par profil ou par geste manuel | **Non vérifié** |
| R2 | Autorisation WebRequest invérifiable hors MT5 (valeur codée) | élevée | déduire de l'absence de `hello` après l'attache + erreur 4014 dans `MQL5\Logs` (UTF-16) ; l'EA n'imprime que le **premier** échec ; documenter la procédure ; ne jamais écrire dans `common.ini` | Lu + Mesuré |
| R3 | Le worker lance MT5 sans EA si un compte est rattaché avant le lanceur | élevée | préparer et lancer MT5 **avant** tout rattachement ; le lanceur ne rattache aucun compte ; « DÉMARRER LE SYSTÈME » reste un geste humain | Lu (code), non vérifié |
| R4 | Terminal déjà ouvert (cas actuel) | élevée | jamais `taskkill` ; fermeture contrôlée = demande de fermeture de la fenêtre principale (le terminal enregistre son profil), après confirmation explicite ; ne pas posséder = ne pas fermer sans accord | Non vérifié |
| R5 | Algo-trading armé par un bouton arme **tous** les EA, y compris le tiers | élevée | le lanceur n'écrit jamais `Enabled` ni ne clique le bouton ; `attachedExperts` est déjà publié par l'agent ; EA tiers attaché = avertissement (ou blocage, à décider) | Lu |
| R6 | Jonction : pas de remplacement atomique ni de retour arrière ; un EA attaché garde l'ancien code en mémoire ; le `.ex5` peut être verrouillé | moyenne | déploiement par copie + manifeste (le dossier `MQL5\Experts\TradingOS\` de la mission) ; respecter et détecter la jonction existante ; ne pas la supprimer sans accord ; remplacer seulement EA détaché | Non vérifié (verrou) |
| R7 | Pas de version de protocole ; un agent ancien est accepté | moyenne | compatibilité par `agentVersion` + `buildId` + `capabilities` ; `EA_PROTOCOL_INCOMPATIBLE` = écart avec une table de versions minimales du cœur ; `protocolVersion` explicite = build 1.14 | Lu |
| R8 | Le hello ne dit ni graphique, ni instance, ni initialisation | moyenne | build 1.14 en **lecture seule** (champs de télémétrie, mode `OBSERVE` inchangé, un seul `OrderSend` inchangé, test d'architecture inchangé) **ou** inférence (worker : `terminal_info().data_path` ; profil `.chr`) | Décision d'Exhorte |
| R9 | Un jeton d'agent pour tous les terminaux | moyenne | conserver pour la v1 (un seul terminal) ; jeton par instance = évolution du lien agent, ADR séparé | Lu |
| R10 | Identification de propriétaire : PID réutilisés, processus étrangers sur nos ports | moyenne | registre `{nom, pid, heure de création, ligne de commande, dossier}` ; reconnaître sans posséder (« adopté ») ; **ne jamais tuer** un processus non possédé | À construire |
| R11 | `.set` : entrées inconnues ou renommées, encodage | moyenne | générer depuis la liste **lue dans le source** (`input …`) ; test qui compare le preset aux entrées déclarées ; jamais de jeton dans le `.set` (règle du projet : « Never an input ») ; ne pas reprendre `ea1.set` | Lu |
| R12 | Aucune compilation reproductible : `.ex5` sans manifeste, staleness indémontrable | moyenne | script de compilation **sur copie** (procédure du runbook) qui écrit un manifeste (hash `.ex5`, hash des sources, version) ; le déploiement refuse un `.ex5` sans manifeste concordant ; pas de compilation automatique en production | À construire |
| R13 | Fenêtres masquées = journaux invisibles | faible | redirection vers des fichiers (`var/launcher/…`), rotation, affichage dans System Center | À construire |
| R14 | Docker Desktop éteint ; base lente à `healthy` | faible | message clair ; démarrage de Docker Desktop seulement si Exhorte le décide | Décision |
| R15 | Les tests ne peuvent pas lancer un vrai MT5 | faible | ports + faux (`FakeMt5`, faux table de processus, faux Docker, faux HTTP) ; validation réelle seulement sur la démo, par étapes, avec accord | — |

## 7. Architecture proposée

**Principe** : le Trading OS décide, MT5 exécute, le lanceur **prépare et observe**. Il ne décide rien du trading, ne relève aucun mode, n'arme rien, ne rattache aucun compte, n'écrit ni identifiant ni permission.

**Logique en Python, enveloppe en PowerShell** (recommandé, à confirmer) :

- `scripts/TradingOS-Start.ps1`, `TradingOS-Stop.ps1` et `Trading OS.bat` (ou `.lnk`) : trouvent la racine, choisissent le Python du venv, fixent le dossier courant, appellent `python -m trading_os launcher start|stop|status|plan`. Rien d'autre.
- `python/trading_os/launcher/` : un **plan pur** (état observé → étapes, testable sans effet de bord), des **ports** (table de processus, Docker, HTTP, système de fichiers, horloge) avec implémentations Windows et faux de test, un **registre de PID** (`var/launcher/state.json`, avec heure de création pour résister à la réutilisation des PID), des **événements structurés** (`var/launcher/events-AAAAMMJJ.jsonl` : horodatage UTC, composant, instance de terminal, compte si connu, type, gravité, identifiant de corrélation, diagnostic ; jamais de secret), la sous-commande CLI.
- Sous `launcher/mt5/` : `discovery` (registre Windows, raccourcis, dossiers connus, chemins déclarés, processus), `registry` (installation, exécutable, dossier de données, identifiant d'instance, **observé** : courtier, serveur, login, devise, type ; **déclaré** : compte Trading OS, symbole, période ; l'écart bloque), `deploy` (manifeste, copie atomique, sauvegarde, vérification, retour arrière), `preset` (aux entrées lues dans le source), `startup_ini` (`[StartUp]` seulement), `attach` (vérification par les signaux de l'EA), `terminal` (lancement, fermeture contrôlée).
- **États** : trois énumérations dérivées des faits, jamais stockées comme vérité (`TerminalState`, `AgentState`, `ExecutionReadiness`) ; `EXECUTION_READY` ne veut **jamais** dire « autorisé ». **READY_NOT_ARMED** = les 16 contrôles + les conditions propres vertes, agent connecté, compatible, identité `ok`, mode ∈ {`OFF`, `OBSERVE`, `PAPER`, `CONFIRM`} et jamais `ARMED`/`AUTONOMOUS`. Calculé par une **lecture** de `ReadinessReport` et `AgentStatus` — pas un second Risk Engine. Toute information manquante rend le résultat **bloqué**, avec le motif exact (échec fermé, jamais d'ancien état réutilisé).
- **Cœur et cockpit** : le cœur lit en lecture seule le registre MT5 et l'état du lanceur (`GET /api/system/center`), le cockpit affiche une page **System Center** (vue d'ensemble, carte terminal, carte déploiement de l'EA, carte préparation d'exécution, événements récents) dans le design « ExponentValue Monochrome » (ADR 0017). **Actions qui touchent des processus** : le cœur ne peut pas redémarrer le cœur, et ouvrir l'API aux processus élargit la surface protégée par le seul jeton du cockpit. **Version 1** : le cockpit affiche la commande du lanceur à lancer ; **version 2** (ADR séparé, après décision) : geste humain confirmé qui lance la CLI détachée.
- **Ordre de démarrage** : validation de l'environnement → Docker → base (`healthy`) → schéma → cœur (`/health`) → cockpit (HTTP 200) → préparation MT5 (découverte, registre, déploiement, preset, ini, jeton) → lancement de MT5 **ou** redémarrage contrôlé confirmé → attente du `hello` → vérification (identité, protocole, heartbeat, permissions) → rapport. L'échec d'un maillon n'entraîne que ce qui en dépend : base KO → pas de cœur ; cœur KO → pas de MT5 configuré ; MT5 KO → le cœur et le cockpit restent, `MT5_DISCONNECTED`, nouvelle tentative possible.
- **Arrêt** : ordre inverse (EA/MT5 non touchés sauf accord → cockpit → cœur → base), uniquement les processus que le lanceur **possède** ; il ne ferme jamais une position ; l'arrêt de Trading OS n'est pas l'arrêt de MT5.
- **Multi-terminal** : chaque instance a son identifiant, son dossier, son état, son EA, son compte, ses paramètres, ses journaux ; une installation = un dossier = un terminal (contrainte MetaQuotes) ; un seul compte connecté à la fois reste vrai tant que l'ADR 0021 tient.
- **Déploiement de l'EA** : copie du seul `.ex5` (l'`Include/` ne sert qu'à la compilation) dans `MQL5\Experts\TradingOS\` + manifeste ; jonction existante respectée et signalée ; remplacement seulement EA détaché.

### Choix d'architecture à trancher par Exhorte (recommandation en gras)

| # | Question | Options |
|---|---|---|
| A1 | Où vit la logique du lanceur ? | **Python + enveloppe PowerShell** (tests `pytest`/`mypy`/`ruff`, faux existants) · PowerShell pur (réutilise `start.ps1`, peu testable ; disponibilité de Pester **non vérifiée**) |
| A2 | Identification des processus | `psutil` (nouvelle dépendance) · **`Get-CimInstance` via PowerShell, sans dépendance** |
| A3 | Agent 1.14 (télémétrie en lecture : version de protocole, graphique, instance, initialisation) | **Oui, après ADR** (le mode compilé `OBSERVE` et l'unique `OrderSend` ne changent pas) · Non (attachement inféré) |
| A4 | Installation de l'EA | **Copie + manifeste, jonction conservée** · jonction seule |
| A5 | Jeton d'agent | **Un jeton, par terminal enregistré, même fermé** (v1) · jeton par instance maintenant |
| A6 | Fenêtres du cœur et du cockpit | **Masquées + journaux de fichier + System Center** · visibles comme aujourd'hui |
| A7 | Cockpit lancé par le lanceur | **`next dev` (comme aujourd'hui)** · `next build` + `next start` (plus stable, rebuild à gérer) |
| A8 | Actions de System Center sur les processus | **v1 : commande affichée** · v2 : spawn confirmé par le cœur (ADR séparé) |
| A9 | EA tiers attaché au terminal | **avertissement bloquant pour `READY`** · simple avertissement |
| A10 | Réparer l'installation éditable du venv (D2) | **oui, `pip install -e` depuis le dépôt actuel, avec ton accord** · contourner par le dossier courant |
| A11 | Docker Desktop éteint | **message clair, ne pas le lancer** · le lancer |

## 8. Fichiers à modifier

| Fichier | Changement |
|---|---|
| `.gitignore` | ignorer `/var/` (registre, états, journaux du lanceur, sauvegardes de l'EA) |
| `scripts/start.ps1` | conservé tel quel au début ; devient l'enveloppe du lanceur ou reste en repli ; corriger le dossier courant du cœur (D2) seulement si A10 est refusé |
| `python/trading_os/cli/main.py` | sous-commande `launcher` |
| `python/trading_os/api/routes/system.py`, `api/schemas/system.py` | `GET /api/system/center` (lecture) |
| `python/trading_os/app/container.py` | lecture de l'état du lanceur et du registre MT5 |
| `python/trading_os/domain/system/startup.py` | étapes « terminal MT5 » et « agent » plus fines, sans changer les 13 étapes existantes |
| `lib/api/generated.ts` | régénéré (`gen-types`), jamais à la main |
| `components/shell/nav.ts` | entrée System Center |
| `context/infrastructure/runbook.md`, `context/adr/README.md` | démarrage, arrêt, dépannage, nouvelle ligne d'ADR |
| `python/pyproject.toml` | `psutil` **seulement si A2 le retient** |
| `tools/mt5-execution-agent/` | **seulement si A3 est accepté** (build 1.14, README, test d'architecture inchangé dans son principe) |

## 9. Fichiers à créer

| Fichier | Rôle |
|---|---|
| `context/adr/0038-lanceur-trading-os-et-orchestration-du-terminal-mt5.md` | l'ADR de la Phase 1 (prochain numéro libre : 0038) |
| `scripts/TradingOS-Start.ps1`, `TradingOS-Stop.ps1`, `Trading OS.bat` | point d'entrée et arrêt |
| `python/trading_os/launcher/…` (plan, ports, registre de PID, événements, CLI) et `…/mt5/…` (discovery, registry, deploy, preset, startup_ini, attach, terminal) | logique |
| `python/tests/unit/launcher/…`, `python/tests/integration/launcher/…` | tests (§10) |
| `app/(cockpit)/system/page.tsx`, `components/cockpit/system-*.tsx`, `lib/cockpit/system-center.ts` (+ tests `vitest`) | System Center |
| `context/execution/{runbook-arret,runbook-depannage,guide-installation-ea,guide-configuration-mt5,guide-multi-terminal,system-center}.md` | documentation, écrite **après** validation de chaque incrément |

## 10. Plan de tests

Technique : tout ce qui touche un effet extérieur passe par un **port** avec un faux (processus, Docker, HTTP, fichiers dans un dossier temporaire, `FakeMt5`). **Aucun test automatique ne lance un vrai MT5 ni ne tue un processus réel.** Les tests doivent échouer d'abord.

| Famille | Cas (extraits de la mission §14) |
|---|---|
| Lanceur | rien de lancé · tout déjà lancé (aucun doublon) · base indisponible (le cœur ne démarre pas) · cœur indisponible (MT5 non configuré) · cockpit indisponible · port tenu par un étranger (refus, **aucun kill**) · lancement répété · arrêt propre (seulement les processus possédés) · redémarrage après arrêt · échec partiel · PID réutilisé |
| Gestionnaire de terminaux | aucun MT5 · une installation · plusieurs (jamais de choix automatique) · terminal déjà lancé · dossier de données inaccessible · compte ou serveur incorrect · terminal déconnecté · installation invalide |
| Déploiement | EA absent · à jour · obsolète · hash faux · manifeste absent · preset absent ou invalide (comparé aux `input` du source) · protocole incompatible · déploiement interrompu · retour arrière · jonction existante respectée |
| Attachement | hello reçu avec la bonne identité · mauvais compte · mauvais symbole ou période (si A3) · EA non initialisé · WebRequest non autorisé (aucun hello + 4014) · cœur indisponible · jeton invalide · heartbeat interrompu · reconnexion |
| Préparation | chaque contrôle rouge → motif exact ; donnée absente → bloqué ; `READY_NOT_ARMED` jamais atteint si `ARMED`/`AUTONOMOUS` ; aucune permission de trading n'est écrite par le lanceur (test d'architecture : le code ne contient aucune écriture `[Experts]`, `[Common]`, `Login`, `Password`) |
| Sécurité (architecture) | aucun secret dans les événements ni les `.set` ni les `.ini` ; l'unique `OrderSend` inchangé ; aucune commande `taskkill` sans PID possédé |
| Non-régression | `pytest` (≈ 18 min, en arrière-plan), `vitest`, `ruff check` + `format --check`, `mypy trading_os`, `gen-types --check`, `tsc --noEmit`, `eslint`, `next build` **hors** `next dev` (runbook : `.next/dev/types`) |

## 11. Critères de validation

| Critère | Preuve attendue | Qui |
|---|---|---|
| Un seul fichier démarre Trading OS ; ordre respecté ; lancement répété sans doublon ; arrêt propre | tests du lanceur + essai réel base/cœur/cockpit | Claude (avec accord pour tout redémarrage du cœur réel) |
| Terminal détecté, bon dossier de données, EA déployé, preset et ini générés | tests + lecture du poste | Claude |
| MT5 démarré avec la configuration, EA attaché, identité vérifiée, EA communique avec le cœur | **essai sur la démo Exness, redémarrage contrôlé accordé par Exhorte**, plusieurs démarrages, aucun worker orphelin (`mt5Workers.alive`), aucun ordre, `OBSERVE` | Exhorte autorise ; Claude lit |
| Le cockpit affiche l'état réel, les blocages sont expliqués, `READY_NOT_ARMED` est identifiable | tests `vitest` + lecture dans un navigateur visible | Claude |
| Aucun ordre, aucun compte changé, aucun mode relevé, aucun secret exposé, aucun garde-fou contourné | tests d'architecture + journaux relus | Claude |

**Réserve** : rien n'est « validé » tant que la preuve n'a pas été obtenue sur la démo ; une validation en simulation est dite telle. Les cases R1, R2, R3, R4 et R6 restent **Non vérifiées** jusqu'à cet essai.

## 12. Plan d'implémentation proposé (un ADR avant chaque code)

| Incrément | Contenu | Dépend de |
|---|---|---|
| I0 | ADR 0038 (cet audit en entrée) ; réponses à A1–A11 | — |
| I1 | plan pur, ports, registre de PID, événements structurés, CLI `plan`/`status` ; tests | I0 |
| I2 | démarrage idempotent base/cœur/cockpit, arrêt propre, santé réelle de chaque composant | I1 |
| I3 | découverte et registre MT5 (observé/déclaré), association explicite | I1 |
| I4 | script de compilation sur copie + manifeste ; gestionnaire de déploiement (copie atomique, retour arrière) | I3 |
| I5 | générateur de preset et d'ini `[StartUp]` ; **essai R1 sur la démo, accord requis** | I4 |
| I6 | lancement / redémarrage contrôlé de MT5, vérification de l'attachement, états distincts | I5 |
| I7 | préparation d'exécution (`READY_NOT_ARMED`) | I6 |
| I8 | `GET /api/system/center` et System Center | I7 |
| I9 | (si A3) build 1.14 de l'agent : télémétrie en lecture | ADR séparé |
| I10 | validation sur la démo, documentation finale, HANDOFF / state / session-log | tout |

Ce que cette mission ne fait **pas** : relever un mode, armer, rattacher un compte, écrire un identifiant, activer l'algo-trading, toucher au Risk Engine, au Guardian, aux ordres, à l'unique `OrderSend`, ni envoyer quoi que ce soit à un courtier.
