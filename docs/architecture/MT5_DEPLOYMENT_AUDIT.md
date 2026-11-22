# Audit — Trading OS Launcher et MT5 Deployment Manager (Phase 0, 2026-11-07)

Phase 0 de la mission « Trading OS Launcher + MT5 Deployment Manager » (brief d'Exhorte, 2026-11-07). **Lecture seule : ce document est le seul fichier créé.** Aucun code, réglage, migration, ni processus modifié, redémarré ou tué ; aucun clic sur le cockpit ; aucun ordre ; `04_code/.env` et le jeton de l'agent n'ont pas été lus.

**Lu** : `scripts/start.ps1`, le paquet `python/trading_os/launcher/` (16 fichiers, 2 538 lignes), `app/config.py`, `runtime/engine.py`, `infrastructure/mt5/{transport,ea_link}.py`, `domain/providers/identity.py`, `domain/execution/state.py`, `domain/system/startup.py`, `services/{accounts,readiness,startup,reconciliation}.py`, l'agent `TradingOsAgent.mq5` (entrées, `SendHello`), `context/execution/protocol.md`, `components/shell/nav.ts`, l'ADR 0038 et l'audit du 2026-11-06.
**Exécuté (lecture seule)** : `launcher status`, `launcher plan` (depuis `python\` ; `var/launcher/` est resté vide), `GET /api/system/health`, `docker ps`, listes de ports et de processus (`Get-NetTCPConnection`, `Get-CimInstance`), lecture des seules clés non sensibles de `common.ini`.

Légende : **Lu** = dans le code · **Mesuré** = relevé sur ce poste le 2026-11-07 · **Non vérifié** = ni l'un ni l'autre.

Ce rapport **complète** `context/execution/launcher-mt5-integration-audit.md` (2026-11-06) sans le répéter : il le référence pour R1 à R15 et les possibilités natives de MetaTrader 5.

---

## 0. Synthèse

1. **Le brief recoupe à environ 80 % l'ADR 0038, déjà accepté le 2026-11-06, et dont I1 et I2 sont construits.** Lanceur Python (`launcher plan|status|start|stop|adopt`, 202 tests), registre de PID par pid + heure de création, verrou, journaux, arrêt limité aux processus possédés. Rien n'est commité. **Rien de MT5 n'est écrit** (I3 à I10).
2. **Le numéro d'ADR demandé (0038 = Deployment Manager, 0039 = Launcher) est pris** : 0038 est le lanceur *et* l'orchestration MT5. Numéros libres lors de l'audit : 0039, 0040 (rédigés depuis, voir § 15).
3. **Dix écarts entre le brief et l'architecture acceptée** exigent une décision avant tout code (§ 7). Les plus lourds : PowerShell modulaire contre Python (A1), machine à états stockée contre états dérivés, boutons du cockpit contre commandes affichées (A8), multi-comptes simultanés contre ADR 0021, et « produit confirmé » comme condition de `EA_READY`.
4. **`scripts/stop.ps1` et `scripts/doctor.ps1` n'existent pas.** `scripts/` contient `start.ps1` seul. Aucun `TradingOS.bat` non plus. L'arrêt existe côté Python (`launcher stop`) ; `doctor` n'existe nulle part.
5. **`ACCOUNT_IDENTITY_UNVERIFIED` n'existe pas dans le code** (0 occurrence). L'identité repose sur `Confidence` (5 niveaux) et `IdentityBlocker` (9 valeurs).
6. **Un produit déduit du seul suffixe reste exécutable** (§ 7, C6). Le code ne le marque jamais `CONFIRMED` (bonne règle), mais `executable = not blockers` (`identity.py:325`) l'accepte à `PROBABLE`. Si `EA_READY` exige un produit *confirmé*, **il ne sera jamais atteint sur la démo Exness** (aucune preuve indépendante possible, pages Exness en HTTP 403).
7. **MT5 est ouvert (pid 1872) et un worker du cœur y est rattaché** (`mt5Workers` 15 lancés / 14 terminés / 1 vivant). « Lancer MT5 » est donc ici un *redémarrage*, et fermer le terminal sous un worker attaché est le scénario R3 de l'audit précédent (le worker peut relancer MT5 **sans** l'EA).
8. **L'agent ne dit ni le graphique, ni la période, ni les plafonds locaux.** `hello.symbol` est le *premier symbole de la liste blanche* (`FirstAllowedSymbol()`), pas celui du graphique. « EA attaché au bon graphique » et « protections locales actives » ne se prouvent pas par l'EA sans un build 1.14 (A3, ADR séparé).
9. **Le travail I1 + I2 n'existe que dans l'arbre de travail** (6 fichiers modifiés, 5 chemins non suivis). Risque de perte ; aucun commit sans ton accord.

---

## 1. État réel du poste (Mesuré, 2026-11-07 ≈ 00:25 UTC)

| Élément | Constat |
|---|---|
| Ports (tous `127.0.0.1`) | **3000** cockpit `next dev` (pid 7900) · **8000** API et **9765** lien agent (pid 1668, cœur) · **5433** base (backend Docker, conteneur `tradingos-timescaledb`, healthy) · 5435 `dossier-db-1` (autre projet) · 3300 `next dev` du projet jobdom (autre projet). Concordent avec la doc. |
| Cœur | `python -m trading_os serve`, pid 1668 (lanceur du venv pid 16780). Santé `ok`, version 0.2.0, **0 signalement**, `agentsConnected` = **0**. |
| Workers MT5 | `mt5Workers` : 15 lancés, 14 terminés, **1 vivant** (paire pid 50048 + 4220) : la démo est rattachée. |
| Lanceur | `launcher status` : base, cœur, cockpit `HEALTHY` / `RECOGNIZED` ; **« processus possédés par le lanceur : aucun »**. `plan` : « rien à faire ». `var/launcher/` est vide : **le lanceur n'a encore rien écrit en réel.** |
| MT5 | une installation (`C:\Program Files\MetaTrader 5`), un terminal en cours (pid 1872, **sans argument**, donc ni `/config` ni `/portable`), un dossier de données `%APPDATA%\MetaQuotes\Terminal\D0E8209F…F075` (plus `Common`, `Community`). |
| EA | jonction `MQL5\Experts\TradingOsAgent` → `04_code\tools\mt5-execution-agent` ; `TradingOsAgent.ex5` 139 452 o (2026-11-03 14:42), version **1.13**, mode compilé `OBSERVE` ; **EA tiers** `Ultimate_ICT_Gold_Scalper_v4.0` installé. Aucun EA attaché (journal des experts : 190 o, dernier le 2026-11-01). |
| `MQL5\Presets` | **n'existe pas.** `MQL5\Files\tradingos_agent.token` : 43 o, 2026-11-06 16:30. |
| `common.ini` (clés non sensibles) | `Enabled=0`, `Account=1`, `Profile=1`, `AllowDllImport=1`, `WebRequest=1`. Inchangé depuis le 2026-11-06. |
| Outils | PowerShell **7.6.9** et **5.1** présents ; **Pester 3.4.0 seulement** (celui de Windows ; pas de Pester 5) ; politique d'exécution `LocalMachine=RemoteSigned` ; Node 24.15.0 ; Docker 29.4.3 ; pas de `psutil`. |
| Git (`04_code`) | `main` à `9dbc774` (poussée). Non commité : `.gitignore`, `context/adr/README.md`, `context/infrastructure/runbook.md`, `context/project/{state,session-log}.md`, `python/trading_os/cli/main.py` ; non suivis : ADR 0038, l'audit du 2026-11-06, `launcher/`, `tests/unit/launcher/`, `tests/architecture/test_launcher_invariants.py`. Remote : `https://github.com/exhorte/trading-operating-system.git`. |
| Tests | `tests/unit/launcher` 202 · `tests/architecture` 62 · `tests/integration` 46 · `tests/unit` 1 746 (fonctions `test_*` comptées ; les chiffres de suite complète du HANDOFF restent la référence : 3 146 passés / 15 ignorés après I2). |
| Piège confirmé | `python -m trading_os` ne s'importe que depuis `04_code\python` (venv éditable vers `C:\Dev\…`, A10 non accordé). Tout `.bat` ou `.ps1` doit fixer son dossier courant. |

---

## 2. Réponses aux dix vérifications demandées

| # | Question | Réponse (source) |
|---|---|---|
| 1 | Comment les services démarrent | Deux voies. `scripts/start.ps1` (fenêtres PowerShell, aucun PID gardé, aucun arrêt) ; `launcher start` (Python : base → schéma → cœur → cockpit, chaque maillon ré-observé et attendu jusqu'à sa santé, registre de PID, verrou, sortie dans `var/launcher/logs/`, sauvegarde `pg_dump` avant toute migration). **Le cœur et le cockpit actuels ont été lancés à la main** : le lanceur n'en possède aucun. (Lu + Mesuré) |
| 2 | Comment le cœur détecte MT5 | Il ne le détecte pas. Chaque compte porte un `terminal_path` **nullable** (`accounts.py:104`) passé à `mt5.initialize(path=…)` dans un **worker** (sous-processus, un par compte). Sans chemin, la bibliothèque `MetaTrader5` trouve ou lance le terminal elle-même. (Lu) |
| 3 | Comment la connexion est initialisée | `AccountService.connect` → client MT5 sur `SubprocessTransport` → `initialize` (délai **60 s**, `SLOW_CALLS`, `transport.py:31`) puis `login` si un mot de passe est fourni ; rattachement sans mot de passe = terminal déjà connecté. (Lu) |
| 4 | Comment les comptes sont identifiés | Login et serveur lus du terminal ; fournisseur et produit par signaux indépendants (`identity.py` : serveur, société du compte, société du terminal, suffixe, levier, mode) ; **un seul compte connecté à la fois** (ADR 0021). Pas de registre compte ↔ terminal ↔ dossier de données. (Lu) |
| 5 | Comment l'EA parle au cœur | TCP loopback `127.0.0.1:9765`, un JSON par ligne, l'EA se connecte **vers** le cœur ; `agent.hello` porte le jeton (lu dans `MQL5\Files`, comparaison à temps constant, **échec fermé** sans jeton) ; un enregistrement **par login**. (Lu) |
| 6 | Heartbeat | EA : toutes les 5 s (`InpHeartbeatSeconds`). Cœur : `control.ping` toutes les 5 s. Trois seuils distincts : **15 s** (fraîcheur de la préparation, `readiness.py:41`), **30 s** (chien de garde du cœur, `ea_silent_after_s`, `config.py:98`), **30 s** (dead-man de l'EA, `InpDeadManSeconds`, 5..600). (Lu) |
| 7 | Détection d'un EA déconnecté | Connexion silencieuse > 30 s : le chien de garde la ferme et un nouveau `hello` la remplace aussitôt ; la préparation passe rouge dès 15 s ; le superviseur ouvre un incident. Côté EA, plus de ping > 30 s : **nouveaux ordres refusés** (`DEAD_MAN`), les stops déjà chez le courtier restent. (Lu) |
| 8 | Commandes ↔ compte | Registre par login ; `send` vise l'agent du login ; sans agent : `AGENT_UNREACHABLE`, jamais un no-op silencieux (`ea_link.py:222`). Les `ack`, `report`, `reconciled` arrivent avec le login **de la connexion** qui les envoie. L'EA, si `InpAccountId` est renseigné et diffère du login observé, **refuse toute commande** (`identity: mismatch`). (Lu) |
| 9 | Réconciliation | Cœur : `ReconciliationService` toutes les 15 s (délai 90 s, `engine.py:163`) ; règle les commandes `UNKNOWN`/`RECONCILING` contre les données du courtier ; une position ouverte à la main = avertissement (`EXTERNAL_POSITION`). EA : réconcilie lui-même une commande `UNKNOWN` à chaque connexion (`execution.reconciled`), rejoue les rapports finaux récents. **`UNKNOWN` ne se rejoue jamais** : la table de `state.py` n'a aucune ligne `UNKNOWN → SENT` ou `UNKNOWN → EXECUTED` ; seule issue `UNKNOWN → RECONCILING → RECONCILED`. Les commandes en doute pèsent sur la préparation (`readiness.py:218`) et sur la condition de démarrage `no_unknown_commands` (`startup.py:597`). (Lu) |
| 10 | Erreurs de démarrage | `start.ps1` : message console + `exit 1`. Lanceur : rapport structuré + événements JSONL (**jamais écrits en réel**). Cœur : `GET /api/system/health` (`findings`), incidents du superviseur, table `events`. Aucun point unique ne les réunit pour MT5. (Lu + Mesuré) |

---

## 3. Architecture actuelle

```
 Windows (utilisateur)
 ┌──────────────────────────────────────────────────────────────────────────┐
 │ Docker ── tradingos-timescaledb            127.0.0.1:5433 (healthy)      │
 │ PowerShell « cœur »  python -m trading_os serve (uvicorn, pid 1668)      │
 │      ├─ API REST + WebSocket /ws           127.0.0.1:8000                │
 │      ├─ lien agent (TCP, un JSON par ligne) 127.0.0.1:9765               │
 │      └─ workers MT5 (1 par compte, enfants, lecture seule, ADR 0037)     │
 │ PowerShell « cockpit » npm run dev → next dev -H 127.0.0.1   :3000       │
 │ terminal64.exe (pid 1872, lancé à la main) ─ EA TradingOsAgent: NON attaché
 └──────────────────────────────────────────────────────────────────────────┘
 lecture : terminal ─► worker ─► cœur ─► base / WebSocket ─► cockpit
 ordres  : cœur ─► ea_link ─► agent ─► OrderSend (unique, inatteignable : mode compilé OBSERVE)
```

Le « MT5 Gateway » du brief **n'existe plus** (backend .NET retiré, ADR 0016) : son rôle est tenu par le lien agent `ea_link` et les workers. L'échelle d'autonomie réelle est `OFF → OBSERVE → PAPER → CONFIRM → ARMED → AUTONOMOUS` (+ `HALTED` atteignable de partout), `domain/autonomy/state.py:26`.

---

## 4. Fonctionnalités existantes (à réutiliser, pas à réécrire)

| Besoin du brief | Déjà là |
|---|---|
| Démarrage idempotent, détection des processus actifs, ports, santé réelle, registre de PID, arrêt limité au possédé, journaux | `launcher/` I1 + I2 (`observe`, `plan`, `starter`, `stopper`, `adopt`, `lock`, `process_control`, `events`) |
| Vérifier PostgreSQL | `starter.py` (conteneur nommé, `healthy`, deux tentatives de `docker info`) |
| Santé des composants | `GET /api/system/{health,status,readiness,startup,incidents,events,live-metrics}` |
| Identité du compte, du fournisseur, du produit | `identity.py` (ADR 0036) + `hello.identity` (`ok`/`mismatch`/`no_account`) |
| Heartbeat, dead-man, déconnexion | § 2, lignes 6 et 7 |
| Un EA par compte, jeton | `ea_link.py` |
| Permissions de trading (4) | `hello` / `heartbeat` : `terminalTradeAllowed`, `expertTradeAllowed`, `accountTradeExpert`, `accountTradeAllowed` |
| Compatibilité partielle | `agentVersion`, `buildId`, `capabilities` ; le cœur n'envoie `limit`/`modify`/`close`/`cancel` qu'à un agent qui les annonce |
| Réconciliation et idempotence | § 2, ligne 9 ; `commandId` = clé d'idempotence (`protocol.md`) |
| HALT : bloque les entrées, laisse les sorties | ADR 0033 (inchangé par cette mission) |
| Faux terminal pour les tests | `FakeMt5` ; `tests/unit/launcher/world.py` (monde simulé du lanceur) |
| Masquage des secrets dans les journaux | `shared/logging/redaction.py` |

**Conditions de `EA_READY` du brief → source réelle** :

| Condition du brief | Source aujourd'hui | Écart |
|---|---|---|
| Terminal démarré | aucune (le lanceur n'observe pas MT5) | à construire (I3/I6) |
| Connexion broker active | readiness `mt5_connected` | — |
| Compte correctement identifié | `hello.identity == ok` + readiness `correct_account` + identification `executable` | — |
| **Produit confirmé** | `product_confidence` | **voir C6** |
| EA chargé | un `hello` reçu | « attaché » et « initialisation » non observables séparément (1.14) |
| Version / protocole compatibles | `agentVersion`, `buildId`, `capabilities`, enveloppe `"version":1` | aucune table de versions minimales ; pas de `protocolVersion` |
| Symbole autorisé | readiness `symbols_available` ; liste blanche de l'EA (`InpAllowedSymbolsCsv`) | la liste de l'EA n'est pas rapportée au cœur |
| Paramètres validés | rien de côté cœur | le `.set` généré se teste côté lanceur ; les entrées *effectives* de l'EA ne sont pas rapportées (1.14) |
| Heartbeat reçu | readiness `heartbeat` (< 15 s) | — |
| Core / Risk Engine opérationnels | readiness `python_core`, `risk_engine` | — |
| Compte non bloqué | readiness `no_critical_incident`, `account_limits_configured` | à confirmer pour les verrous (lockouts) |
| Protections locales actives | partiel : capacité `dead_man`, `tradable`/`closable` | **plafonds de spread / volume / positions non rapportés** |
| Dead-man fonctionnel | capacité `dead_man` annoncée + `core_silent_ms` du heartbeat | « fonctionnel » ne se prouve qu'avec un ordre : on ne peut dire que « annoncé et ping reçu » |
| Réconciliation terminée | readiness `reconciliation` + `no_unknown_commands` | — |

---

## 5. Fonctionnalités manquantes

Déjà listées dans l'audit du 2026-11-06 § 4 (découverte MT5, registre, déploiement, preset, `[StartUp]`, lancement, attachement, System Center). **Ajouts propres au brief** :

1. `TradingOS.bat` et l'enveloppe PowerShell (n'existent pas) ; modes `Full | Infrastructure | MT5 | Status | Stop | Doctor`.
2. **`doctor`** : diagnostic en lecture seule qui explique *pourquoi* un terminal ou un EA ne fonctionne pas (aujourd'hui `plan` et `status` observent sans diagnostiquer).
3. **Machine à états de déploiement** avec transitions contrôlées et journalisées (`NOT_INSTALLED … EA_READY`, `EA_BLOCKED`, `EA_DISCONNECTED`, `EA_ERROR`).
4. **Verrou d'instance par terminal** (`lock.py` est un verrou global du lanceur).
5. **Identifiant de déploiement**, journal de déploiement, code d'erreur, étape en échec, action corrective suggérée.
6. **Code `ACCOUNT_IDENTITY_UNVERIFIED`** (alias des bloqueurs existants, § 7 C6).
7. **Table de versions minimales EA ↔ cœur** (`EA_PROTOCOL_INCOMPATIBLE`).
8. Politiques de déploiement et versions multiples de l'EA (architecture d'accueil seulement).
9. Page « MT5 & Execution Management » : le cockpit compte onze écrans (`app/(cockpit)/` : account, agents, analyse, demarrage, journal, market-context, positions, preflight, risk, settings, setups) et **aucun** n'est dédié à MT5 / au déploiement.

---

## 6. Scripts et modules réutilisables

| Fichier | Réutilisation |
|---|---|
| `scripts/start.ps1` | Repli conservé intact (ADR 0038, migration § 1). Sa logique de découverte des dossiers de données (`Get-Mt5DataFolders` : `terminal64` → `origin.txt`) est le point de départ de I3. |
| `launcher/observe.py`, `adapters.py`, `ports.py` | Observation par ports + faux ; à étendre à MT5 (I3) sans changer le patron. |
| `launcher/process_control.py` | Seul module qui termine un processus (imposé par test d'architecture). Le brief « ne tue pas arbitrairement MT5 » est déjà garanti par construction. |
| `launcher/lock.py` | Patron du futur verrou par terminal. |
| `tests/unit/launcher/world.py` | Monde simulé pour les tests de Full / Doctor / MT5 sans MT5 réel. |
| `tools/mt5-execution-agent/ea1.set` | **À ne pas réutiliser** : porte d'anciens noms (`InpGatewayHost`/`InpGatewayPort`) et n'a ni `InpDeadManSeconds` ni `InpPendingMaxMinutes`. |

**Entrées réelles de l'EA 1.13** (base du générateur de `.set`) : `InpCoreHost`, `InpCorePort`, `InpAccountId`, `InpMagicNumber` (obligatoire, > 0), `InpTradableLogins`, `InpClosableLogins`, `InpHeartbeatSeconds`, `InpMaxVolumePerOrder`, `InpMaxOpenPositions`, `InpMaxSpreadCsv`, `InpAllowedSymbolsCsv`, `InpMaxSlippagePoints`, `InpPendingMaxMinutes`, `InpReconciliationLookbackDays`, `InpReportReplayMinutes`, `InpDeadManSeconds`. **Il n'existe aucune entrée pour le symbole ou la période du graphique** (attributs du graphique → `[StartUp] Symbol/Period`), **ni pour le « mode de fonctionnement »** (constante de compilation `OBSERVE`, `TradingOsAgent.mq5:106`), **ni pour un identifiant de terminal**.

---

## 7. Conflits architecturaux (décisions demandées)

| # | Conflit | État actuel | Recommandation |
|---|---|---|---|
| **C1** | **Numérotation d'ADR.** Le brief nomme 0038 = Deployment Manager, 0039 = Launcher. | 0038 existe, **accepté**, et couvre lanceur *et* orchestration MT5. | Garder 0038 comme base. Nouveaux ADR : **0039** (machine à états de déploiement, registre, réconciliation d'attachement, `doctor`), **0040** (agent 1.14, lecture seule) ; l'ADR des actions de processus du cockpit prendra le numéro libre suivant. Ne pas réécrire 0038 sans ADR. |
| **C2** | **Technologie.** Le brief : modules `.psm1` (`InfrastructureManager`, `ProcessManager`, …). | ADR 0038 **A1 accepté** : logique en Python, enveloppe PowerShell. 2 538 lignes et 202 tests déjà écrits. **Pester 3.4.0 seulement** : un lanceur PowerShell pur serait peu testable (le brief demande des tests sérieux). | **Garder A1.** Les noms du brief deviennent des sous-modules Python (`InfrastructureManager` ≈ `starter`, `ProcessManager` ≈ `process_control`, `HealthCheckManager` ≈ `observe`, `LoggingManager` ≈ `events`, `MT5*Manager` ≈ `launcher/mt5/`). `TradingOS.bat` et `TradingOS.Launcher.ps1` = enveloppe mince. |
| **C3** | **Machine à états.** Le brief : une machine explicite, transitions contrôlées et journalisées. | ADR 0038 § 9 : trois énumérations **dérivées**, « jamais stockées comme vérité ». Or `DEPLOYING` et `TERMINAL_STARTING` sont des *opérations en cours* que le cœur ne peut pas déduire de ce qu'il observe. | **Hybride** : états *observés* dérivés (jamais figés) + états d'*opération* du lanceur persistés dans `var/launcher/terminals.json`, **plus un journal de transitions** (un événement à chaque changement, ancien état, nouvel état, cause). `EA_READY` reste une lecture, jamais une valeur posée. À écrire dans l'ADR 0039. |
| **C4** | **Actions du cockpit.** Le brief : boutons `DETECT`, `REGISTER`, `DEPLOY`, `LAUNCH MT5`, `VERIFY`, `RECONNECT`, `REDEPLOY`, `VIEW LOGS`. | ADR 0038 **A8** : v1 = commandes affichées, car ouvrir l'API aux processus élargit une surface protégée par le seul jeton du cockpit. | **Deux temps.** Lectures d'abord (`DETECT`, `VERIFY`, `VIEW LOGS` ne changent rien). Les actions qui touchent un processus ou un fichier MT5 (`DEPLOY`, `LAUNCH`, `REDEPLOY`, `RECONNECT`) = ADR séparé + geste humain confirmé. Avant tout code cockpit : lire `node_modules/next/dist/docs/` (AGENTS.md : ce Next.js n'est pas celui que l'on connaît). |
| **C5** | **Multi-comptes simultanés.** Le brief (Phase 3) : Exness, FTMO et réel, chacun avec son terminal. | **ADR 0021 : un seul compte connecté à la fois**, et c'est le « compte actif » que lisent Risk Engine, Guardian et Position Manager. `ea_link` sait enregistrer plusieurs logins, `AccountService` n'en connecte qu'un ; un seul jeton d'agent (A5). | Phase 3 livre le **registre multi-terminaux**, l'isolation des configurations et les verrous, **sans** connexion simultanée. L'exploitation de deux terminaux connectés en même temps exige un ADR qui remplace 0021 (hors de cette mission). |
| **C6** | **« Produit confirmé » et `ACCOUNT_IDENTITY_UNVERIFIED`.** | Un produit déduit du suffixe est `PROBABLE` (`identity.py:261`), jamais `CONFIRMED` sur le seul suffixe (règle du brief respectée). **Mais `executable = not blockers` (`:325`) : un produit `PROBABLE` est exécutable.** Pour la démo Exness, l'API affiche `CONFIRMED` à cause du **contrat FTMO déclaré et répété** (`:280`), pas d'une preuve du produit Exness (HANDOFF, § État actuel). `ACCOUNT_IDENTITY_UNVERIFIED` n'existe pas ; équivalents : `PROVIDER_NOT_IDENTIFIED`, `PROVIDER_AMBIGUOUS`, `PRODUCT_UNKNOWN`, `FACTS_MISSING`. | **À trancher par toi.** (a) `EA_READY` exige un produit indépendamment confirmé : plus sûr, mais **inatteignable sur la démo Exness**. (b) `EA_READY` accepte `PROBABLE` + un champ « produit déclaré par Exhorte » et affiche l'avertissement `PRODUCT_UNCONFIRMED`. (c) statu quo. Je recommande (b), qui ne fait que resserrer l'ADR 0036 ; `ACCOUNT_IDENTITY_UNVERIFIED` devient le nom d'un état *agrégé* des bloqueurs existants, sans nouveau chemin d'assouplissement. |
| **C7** | **Paramètres et preuves que l'EA ne fournit pas** (§ 6). | Pas d'entrée symbole/période, pas d'entrée mode, `hello.symbol` ≠ symbole du graphique, plafonds locaux non rapportés. | « Mode de fonctionnement » ne se règle pas par `.set` et **ne doit pas** (invariant). L'attachement au bon graphique et les protections locales actives se prouvent avec l'**agent 1.14, en lecture seule** (A3 recommandé, ADR séparé, `OBSERVE` et unique `OrderSend` inchangés). Sans 1.14 : `CHART_UNVERIFIED` et `PROTECTIONS_UNREPORTED` en avertissement honnête. Les symboles sont ceux du courtier (`XAUUSDm`, pas `XAUUSD` : ne pas copier l'exemple du brief). |
| **C8** | **Ordre de travail.** Le brief : tests en phase 7, cockpit en phase 6. | Règle du dépôt : **un ADR avant chaque code, tests écrits avant le code**. | Les tests accompagnent chaque phase (rouges d'abord). La « phase 7 » devient le passage final de non-régression et de sécurité. |
| **C9** | **Emplacement des documents.** Le brief : `docs/architecture/ADR…`, `docs/operations/…`. | ADR dans `context/adr/NNNN-…md` (index `README.md`) ; runbook `context/infrastructure/runbook.md` ; guides `context/execution/`. `docs/architecture/` ne contient que 4 fichiers de la migration Python-native. | Suivre la convention du dépôt pour ADR et runbooks ; **ce rapport reste à l'emplacement demandé** et renvoie vers eux. Les noms `MT5_DEPLOYMENT_GUIDE` / `MT5_TROUBLESHOOTING` deviennent des fichiers de `context/execution/`. |
| **C10** | **Travail non commité.** | I1 + I2 : 2 538 lignes + 202 tests, uniquement dans l'arbre de travail. | Te demander si tu veux un commit local (sans attribution, sans push). Je ne commite pas sans ton accord. |

---

## 8. Risques techniques

Les risques **R1 à R15** de l'audit du 2026-11-06 restent entiers et **non vérifiés sur la démo** (R1 `/config` remplace `common.ini`, R2 WebRequest invérifiable par fichier, R3 le worker lance MT5 sans EA, R4 terminal déjà ouvert, R6 verrou du `.ex5`). **Nouveaux** :

| # | Risque | Gravité | Contre-mesure |
|---|---|---|---|
| R16 | **Fermer MT5 sous un worker attaché** (cas actuel, `alive=1`) : incident `mt5_disconnected`, et le worker peut relancer MT5 sans l'EA. | élevée | Séquence imposée : (1) refus si positions ou ordres en attente chez le courtier ; (2) **toi** détaches le compte (geste du cockpit) ; (3) fermeture contrôlée confirmée, jamais un kill ; (4) lancement avec la configuration ; (5) `hello` attendu ; (6) **toi** rattaches. Le lanceur ne détache ni ne rattache aucun compte. |
| R17 | `EA_READY` inatteignable sur la démo si « produit confirmé » est strict (C6). | élevée (blocage fonctionnel) | Décision C6. |
| R18 | I1 + I2 perdus (non commités). | moyenne | Commit local sur ton accord. |
| R19 | Venv éditable cassé (A10) : le `.bat` lancé d'ailleurs échoue à importer `trading_os`. | moyenne | L'enveloppe fixe le dossier courant à `04_code\python` ; A10 reste un accord séparé. |
| R20 | Trois seuils de heartbeat distincts (15 / 30 / 30 s). « Timeout configuré » du brief ne désigne pas une seule valeur. | moyenne | Ne rien unifier sans preuve ; le diagnostic affiche *quel* seuil a sauté. |
| R21 | `next dev` fragile (cache `.next/dev`, 404 connus) : un « cockpit prêt » n'est qu'un HTTP 200. | faible | Santé = HTTP 200 + une route typée ; A7 inchangé. |
| R22 | Politique d'exécution `RemoteSigned` : un `.ps1` copié depuis le réseau (marque Zone.Identifier) serait bloqué. | faible | `TradingOS.bat` appelle `-NoProfile -ExecutionPolicy Bypass -File` (portée du processus seulement) ; ne modifie aucune politique. |
| R23 | Mode `Full` « propose ou applique » la configuration MT5 : ambigu. | moyenne | Défaut = **proposer** (plan lisible) ; appliquer exige un indicateur explicite et, pour un terminal ouvert, une confirmation. |
| R24 | Provenance de l'EA : `*.ex5` est ignoré par Git ; le `.ex5` (14:42) est postérieur aux sources (10:18) sans lien prouvé. | moyenne | Manifeste de compilation (hash du `.ex5`, des sources, version, MetaEditor) exigé avant tout déploiement (ADR 0038 § 7). |

---

## 9. Dépendances

Windows 11 · Docker Desktop 29.4.3 (conteneur `tradingos-timescaledb`, volume `trading_operating_system_algorithmique_tradingos-pgdata`) · venv Python 3.14 avec `MetaTrader5` 5.0.6231 et `pywin32` · Node 24.15.0 / Next 16.2.10 · MetaTrader 5 build 6230 + MetaEditor (compilation sur copie) · PowerShell 7.6.9 et 5.1 (`start.ps1` ouvre `powershell.exe`) · `.env` gitignoré (jamais lu par Claude) · droits utilisateur suffisants pour `%APPDATA%\MetaQuotes\Terminal\<id>` ; **aucun droit administrateur** (sauf `/portable` sous Program Files : exclu). Aucune nouvelle dépendance requise ; `psutil` seulement si tu le choisis (A2), Pester 5 seulement si un test PowerShell devenait nécessaire.

---

## 10. Modifications nécessaires

**À modifier** (déjà listé dans l'audit du 2026-11-06 § 8) : `.gitignore` (fait, non commité), `cli/main.py` (fait), `api/routes/system.py` + `api/schemas/system.py` (`GET /api/system/center`, lecture), `domain/system/` (états MT5 / agent, préparation), `components/shell/nav.ts`, runbook et index ADR, `lib/api/generated.ts` régénéré par `gen-types`. **Ajouts du brief** : sous-commande `launcher doctor` (lecture seule) ; alias de modes ; journal de transitions ; verrou par terminal ; table de versions minimales ; `tools/mt5-execution-agent/` seulement si 1.14 est accepté.

**À créer** : `TradingOS.bat`, `scripts/TradingOS.Launcher.ps1` (enveloppe) ; `launcher/mt5/{discovery,registry,deploy,preset,startup_ini,attach,terminal}.py` ; `launcher/doctor.py` ; ADR 0039 et ADR 0040 (agent 1.14) ; page `/system` + `lib/cockpit/system-center.ts` ; tests correspondants ; guides `context/execution/…`.

**À ne pas toucher** : Risk Engine, Guardian, Position Manager, chemin d'exécution, unique `OrderSend`, mode compilé `OBSERVE`, limites de risque, délais existants (`SLOW_CALLS`, 30 s du `supervisor`, 15/30/30 s), ports, `.env`, la jonction `MQL5\Experts\TradingOsAgent`, `common.ini`.

---

## 11. Architecture cible proposée

Principes inchangés : le Core décide, MT5 exécute, **le lanceur prépare et observe**, sans jamais autoriser. Il s'arrête à `EA_READY` ; `CONFIRM`/`ARMED`/`AUTONOMOUS` restent des gestes humains distincts.

```
TradingOS.bat ─► TradingOS.Launcher.ps1 (enveloppe mince : racine, venv, cwd = 04_code\python)
                    │
                    ▼   python -m trading_os launcher <mode>
   ┌────────────────┴───────────────────────────────────────────────┐
   │ Infrastructure (I1/I2, fait)        │ MT5 Manager (I3–I7, à faire) │
   │  observe · plan · starter · stopper │  discovery → registry         │
   │  adopt · lock · process_control     │  deploy (manifeste, hash)     │
   │  events (JSONL)                     │  preset (.set)  startup_ini   │
   │                                     │  terminal (lancement/arrêt)   │
   │                                     │  attach (hello, identité)     │
   └────────────────┬────────────────────┴──────────────┬───────────────┘
                    │ lecture HTTP seule                 │ fichiers de MT5 (jamais [Experts]/[Common])
                    ▼                                    ▼
          Core: readiness · identity · ea_link   MT5 + TradingOsAgent (OBSERVE)
                    ▼
          GET /api/system/center ─► page « MT5 & Execution Management » (lecture d'abord)
```

**Modes** : `Status` = `status` ; `Stop` = `stop` ; `Infrastructure` = `start` (base, cœur, cockpit) ; `MT5` = préparation MT5 ; `Full` = `Infrastructure` puis *plan* MT5 (appliqué seulement sur indicateur explicite) ; `Doctor` = nouveau, lecture seule, **sans modifier aucune configuration ni lancer d'ordre**.

**États** (C3) : *observés*, dérivés et jamais figés — `Terminal` (`STOPPED/STARTING/RUNNING/CONNECTED`), `EA` (`NOT_DEPLOYED/DEPLOYED/NOT_REPORTING/CONNECTED/DEGRADED/DISCONNECTED/PROTOCOL_INCOMPATIBLE`), `Execution` (`NOT_READY/READY/ARMED/HALTED`) ; *d'opération* du lanceur, persistés — `DEPLOYING`, `TERMINAL_STARTING`, `EA_LOADING`, `EA_VALIDATING` ; vue d'ensemble pour l'utilisateur : `NOT_INSTALLED → DEPLOYING → TERMINAL_STARTING → EA_LOADING → EA_CONNECTED → EA_VALIDATING → EA_READY`, avec `EA_BLOCKED` (motif exact), `EA_DISCONNECTED`, `EA_ERROR`. Chaque transition = un événement (terminal, compte, identifiant de déploiement, code, étape, action corrective). Les huit niveaux « MT5 démarré / connecté au courtier / EA attaché / EA communique / EA prêt / compte autorisé / ARMED / AUTONOMOUS » restent **huit lectures indépendantes**.

**Garde-fous du lanceur (tests d'architecture)** : aucune écriture de `[Experts]`, `[Common]`, `Login`, `Password`, `AllowLiveTrading` ; `InpTradableLogins` / `InpClosableLogins` jamais renseignés ; aucun secret dans `.set`, `.ini` ou événements ; aucun arrêt de processus hors registre ; un seul `OrderSend` dans le dépôt ; le lanceur n'importe ni exécution, ni risque, ni Guardian, ni positions.

---

## 12. Plan d'implémentation (numérotation du brief, § 13)

| Phase du brief | Contenu | Correspondance | Dépend de |
|---|---|---|---|
| 1 — Architecture cible et ADR | ADR 0039 : C1 à C10 tranchés, machine à états hybride, réconciliation d'attachement, `doctor`, table de versions | nouveau | tes réponses (§ 14) |
| 2 — Launcher | `TradingOS.bat` + enveloppe ; modes ; `doctor` ; **essai réel de I2** (arrête puis relance le vrai cœur : **ton accord**) ; A10 (accord séparé) | I1/I2 faits | ADR 0039 |
| 3 — MT5 Terminal Manager | découverte, registre observé/déclaré, association explicite, verrou par terminal, multi-terminaux **sans** connexion simultanée | I3 | 2 |
| 4 — MT5 Deployment Manager | script de compilation sur copie + manifeste, copie atomique, retour arrière, `.set` depuis les entrées lues dans le source, `startup.ini` `[StartUp]` seul ; **essai R1 sur la démo (accord)** | I4, I5 | 3 |
| 5 — États et réconciliation | lancement / redémarrage contrôlé (R16), attente du `hello`, états, `EA_READY`, table de versions ; 1.14 si accepté | I6, I7, I9 | 4 |
| 6 — Cockpit | `GET /api/system/center` + page en lecture ; actions de processus = ADR séparé | I8 | 5 |
| 7 — Tests et sécurité | accompagne chaque phase ; passage final : pytest complet (≈ 16 à 40 min, en arrière-plan), vitest, ruff, mypy, `gen-types --check`, tsc, eslint, `next build` hors `next dev` | — | — |
| 8 — Documentation | ADR, runbook, guides (`context/execution/`), HANDOFF / `state.md` / `session-log.md` | I10 | — |
| 9 — Validation OBSERVE réelle | démo Exness, par étapes (a : `/config` ; b : déploiement + preset ; c : redémarrage contrôlé ; d : `hello`, identité, heartbeat ; e : démarrages répétés, `mt5Workers.alive` conforme). **Aucun ordre, `OBSERVE`, avec ta présence et ton accord à chaque redémarrage.** | I10 | 8 |

Rien dans cette feuille de route ne modifie un mode, n'arme, ne rattache un compte, n'écrit un identifiant ou une permission, ne touche au Risk Engine ni à l'unique `OrderSend`.

---

## 13. Ce qui n'est pas vérifié

- Tout ce qui touche MT5 : `/config` remplace-t-il `common.ini` (R1) ; autorisation WebRequest (R2) ; lancement par le worker (R3) ; fermeture contrôlée d'un terminal ouvert (R4) ; verrou du `.ex5` (R6) ; encodage et emplacement exact du `.set` (`MQL5\Presets` n'existe pas).
- Le lanceur n'a **jamais** démarré, adopté ni arrêté un vrai processus : `var/launcher/` est vide.
- Les verrous (lockouts) comptent-ils dans la préparation ? (`no_critical_incident` et `account_limits_configured` lus, pas les lockouts.)
- Positions et ordres en attente actuels de la démo : non relus pour ce rapport (aucun appel authentifié).
- Contenu des événements JSONL, de `state.json` et des journaux du lanceur : jamais produits en réel.

---

## 14. Décisions demandées avant la Phase 1

1. **C1** — Garder l'ADR 0038 et ouvrir 0039 et 0040 (1.14) ? *(recommandé)*
2. **C2** — Garder Python + enveloppe PowerShell (A1) plutôt que des modules `.psm1` ? *(recommandé)*
3. **C3** — Machine à états hybride (observé dérivé + opération persistée + journal de transitions) ? *(recommandé)*
4. **C4** — Cockpit : lectures d'abord, actions de processus dans un ADR séparé ? *(recommandé)*
5. **C5** — Multi-terminaux : registre et isolation, **sans** connexion simultanée (ADR 0021 intact) ? *(recommandé)*
6. **C6** — Produit : option (b) (déclaration d'Exhorte + avertissement `PRODUCT_UNCONFIRMED`) ?
7. **C7** — Accord pour **écrire l'ADR** de l'agent 1.14 (lecture seule) ? *(l'écrire n'est pas le construire)*
8. **C10** — Commit local de I1 + I2 (sans attribution, sans push) ?
9. **Plus tard, séparément** : essai réel de I2, A10, essai `/config` sur la démo, tout redémarrage du cœur ou de MT5.

---

## 15. Suites (2026-11-07, après la validation d'Exhorte)

**Décisions enregistrées** (« Oui, valider ») : C1, C2, C3, C4, C5 et C7 aux valeurs recommandées. **Appliquées sans question** parce qu'elles ne font que suivre une règle existante du dépôt : C8 (tests écrits avant le code, un ADR avant chaque code) et C9 (ADR et runbooks dans `context/`). **C6 tranché ensuite : option (b)** (« Oui, option (b) », 2026-11-07) — pour `EA_READY`, un produit déduit du suffixe n'est vert que si Exhorte a déclaré le même produit (avertissement `PRODUCT_UNCONFIRMED`, jamais « confirmé ») ; sans déclaration `PRODUCT_UNDECLARED`, déclaration différente `PRODUCT_MISMATCH` ; `ACCOUNT_IDENTITY_UNVERIFIED` devient le code d'en-tête de ces rouges ; condition de préparation seulement, `identity.py` et le drapeau `executable` inchangés (ADR 0039 § 9). **Reste ouverte** : C10 (commit local de I1 + I2).

**Livrés (Phase 1, aucun code)** : `context/adr/0039-deploiement-mt5-machine-a-etats-registre-des-terminaux-et-doctor.md` (états, registre et isolation, réconciliation d'attachement, `doctor`, modes, compatibilité, cockpit en lecture) et `context/adr/0040-agent-1-14-telemetrie-en-lecture-seule.md` (l'écrire n'est pas le construire) ; deux lignes dans `context/adr/README.md`. Les deux ADR sont **proposés**, pas acceptés. L'ADR des actions de processus du cockpit prendra le numéro libre suivant, le moment venu.
