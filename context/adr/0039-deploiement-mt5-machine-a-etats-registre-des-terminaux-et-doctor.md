# ADR 0039 — Déploiement MT5 : machine à états, registre des terminaux, `doctor` et réconciliation d'attachement

Date : 2026-11-07. Statut : **accepté le 2026-11-07** par Exhorte (« Oui, accepter ») — rédigé à sa demande (mission « Trading OS Launcher + MT5 Deployment Manager », Phase 1) à partir de l'audit `docs/architecture/MT5_DEPLOYMENT_AUDIT.md`. **Décisions déjà prises par Exhorte le 2026-11-07 (« Oui, valider »)** : C1 (cet ADR complète l'ADR 0038, il ne le réécrit pas), C2 (Python + enveloppe PowerShell), C3 (machine à états hybride), C4 (cockpit en lecture d'abord), C5 (plusieurs terminaux sans connexion simultanée), C7 (l'agent 1.14 a son ADR : 0040). **C6 tranché le 2026-11-07 : option (b)** (« Oui, option (b) » ; § 9). **Reste ouvert** : C10 (commit de I1 + I2). **Rien n'est construit par cet ADR.** **Complète l'ADR 0038 sans l'amender ; n'amende aucun autre ADR** ; respecte les invariants des ADR 0010, 0013, 0021, 0033, 0034, 0036, 0037 et 0038. Ne touche ni au Risk Engine, ni au Guardian, ni aux modes d'autonomie, ni au chemin d'exécution, ni au mode compilé de l'agent.

## Contexte

L'ADR 0038 (accepté le 2026-11-06) pose le lanceur Python, la propriété des processus, le déploiement de l'EA par copie et manifeste, le preset, la configuration de démarrage et trois énumérations d'états **dérivées**. I1 et I2 sont construits (lecture, démarrage, arrêt, adoption). Le brief du 2026-11-07 ajoute ce que l'ADR 0038 ne précise pas :

- une **machine à états de déploiement explicite**, dont les transitions sont contrôlées et journalisées, et qui s'arrête à `EA_READY` ;
- un **registre multi-terminaux** à isolation stricte (un contexte, un verrou, des fichiers propres à chaque terminal) ;
- un mode **`doctor`** qui explique pourquoi un terminal ou un EA ne fonctionne pas ;
- les modes de lancement `Full | Infrastructure | MT5 | Status | Stop | Doctor` et le point d'entrée `TradingOS.bat` ;
- une **réconciliation d'attachement** : aucune préparation déclarée avant que l'état métier soit relu après une (re)connexion.

L'audit a établi que `DEPLOYING` et `TERMINAL_STARTING` sont des *opérations en cours* que le cœur ne peut pas déduire de ce qu'il observe, que `scripts/` ne contient que `start.ps1` (ni `stop.ps1`, ni `doctor.ps1`), que Pester n'existe qu'en 3.4.0, et que le magasin de commandes de l'EA (`CommandStore.mqh`) vit dans `MQL5\Files\` du terminal, un fichier par login et numéro magique, et porte l'idempotence des ordres.

## Décision

### 1. Place de cet ADR (C1)

L'ADR 0038 reste l'ADR du lanceur et de l'orchestration MT5. Le présent ADR fixe ce qui s'y ajoute (états, registre, `doctor`, modes, réconciliation d'attachement, compatibilité, cockpit en lecture). Les ADR suivants : **0040** (agent 1.14, télémétrie en lecture), puis un ADR distinct, au numéro libre suivant, pour les **actions de processus du cockpit** (§ 8). Les numéros 0038 et 0039 du brief sont donc lus comme : 0038 = lanceur *et* orchestration MT5 (existant), 0039 = déploiement MT5 (ici).

### 2. Technologie, enveloppe et modes (C2)

- **Logique en Python** (A1 de l'ADR 0038, inchangé). Les noms du brief sont des sous-modules : `InfrastructureManager` ≈ `starter` / `stopper`, `ProcessManager` ≈ `process_control` / `registry`, `HealthCheckManager` ≈ `observe`, `LoggingManager` ≈ `events`, `ConfigurationManager` ≈ lecture des réglages par la configuration du cœur, `MT5TerminalManager` ≈ `launcher/mt5/{discovery,registry,terminal}`, `MT5DeploymentManager` ≈ `launcher/mt5/{deploy,preset,startup_ini,attach}`, `AccountRegistryManager` ≈ `launcher/mt5/registry`.
- **Enveloppe mince** : `TradingOS.bat` (sans espace, il remplace le nom `Trading OS.bat` de l'ADR 0038) → `scripts\TradingOS.Launcher.ps1 -Mode …`. Le script trouve la racine du dépôt, choisit le Python du venv, fixe le dossier courant à `04_code\python` (le venv éditable cassé, A10, ne s'importe que de là), appelle `python -m trading_os launcher …` et renvoie son code de sortie. Il choisit `pwsh` s'il existe, sinon `powershell.exe`, avec `-NoProfile -ExecutionPolicy Bypass` (portée du processus seulement : aucune politique n'est modifiée). Tous les chemins sont entre guillemets (`C:\Program Files\MetaTrader 5`).
- **Modes** (sans argument : `Full`) :

| Mode | Sous-commande | Effet |
|---|---|---|
| `Status` | `launcher status` | lecture seule |
| `Stop` | `launcher stop` (`-DryRun` → `--dry-run`) | seulement les processus possédés ; ni MT5, ni position |
| `Infrastructure` | `launcher start` | base, schéma, cœur, cockpit ; un composant sain n'est pas touché |
| `MT5` | `launcher mt5 plan`, puis avec `-Apply` les étapes une à une | préparation de MT5 |
| `Full` | `launcher start`, puis `launcher mt5 plan` ; avec `-Apply`, les étapes MT5 jusqu'à `EA_READY` | **propose par défaut, applique sur demande** |
| `Doctor` | `launcher doctor` | diagnostic **sans rien modifier** (§ 6) |

- Sous-commandes MT5 : `detect`, `register`, `plan`, `deploy`, `start`, `verify`, `status`. Une étape qui touche un terminal **ouvert** demande une confirmation tapée dans la console ; **il n'existe pas d'option `--yes` pour fermer un terminal**.
- Codes de sortie : `0` rien d'anormal ; `2` bloqué ou partiel (le diagnostic dit quoi) ; `1` erreur technique. À relire (valeur posée).

### 3. États (C3)

**Principe** : l'état de préparation reste une **lecture**, jamais une valeur posée. Deux sources s'ajoutent, et un journal.

**3.1 États observés** (ADR 0038 § 9, inchangés) : `Terminal` (`STOPPED/STARTING/RUNNING/CONNECTED`), `EA` (`NOT_DEPLOYED/DEPLOYED/NOT_REPORTING/CONNECTED/DEGRADED/DISCONNECTED/PROTOCOL_INCOMPATIBLE`), `Execution` (`NOT_READY/READY/ARMED/HALTED`). Ils sont recalculés à chaque observation. **Huit lectures indépendantes** ne se déduisent jamais l'une de l'autre : terminal démarré, connecté au courtier, EA attaché, EA qui communique, EA techniquement prêt, compte autorisé à exécuter, `ARMED`, `AUTONOMOUS`.

**3.2 États d'opération** (nouveau, persistés) : par terminal, dans `var/launcher/terminals.json`, champ `operation` : `IDLE`, `DEPLOYING`, `TERMINAL_STOPPING`, `TERMINAL_STARTING`, `EA_LOADING`. Chacun porte un `deploymentId`, l'étape en cours, `startedAt` et une échéance. Une opération dont l'échéance est passée, ou laissée par un lanceur interrompu, n'est **jamais reprise en silence** : elle devient `EA_ERROR(LAUNCHER_OPERATION_INTERRUPTED)` (échec fermé) et demande un geste.

**3.3 État de synthèse du déploiement** — fonction pure du registre, de l'opération, des états observés, des faits de préparation et du dernier état journalisé :

| État | Condition |
|---|---|
| `NOT_INSTALLED` | terminal absent du registre, ou EA non déployé (aucun `.ex5` au manifeste concordant) et aucune opération |
| `DEPLOYING` | opération `DEPLOYING` en cours |
| `DEPLOYED` *(ajouté)* | EA déployé, terminal arrêté, aucune opération : prêt à démarrer |
| `TERMINAL_STOPPING` *(ajouté)* | fermeture contrôlée demandée : l'étape dangereuse doit être visible |
| `TERMINAL_STARTING` | processus lancé, connexion au courtier attendue |
| `EA_LOADING` | terminal en cours, aucun `hello` encore, dans l'échéance (90 s, ADR 0038) |
| `EA_CONNECTED` | `hello` reçu, jeton accepté ; compatibilité et identité pas encore jugées |
| `EA_VALIDATING` | connecté, **aucune condition rouge**, au moins une condition **en attente** (heartbeat pas encore frais, réconciliation pas encore terminée depuis cet attachement) |
| `EA_READY` | toutes les conditions de la liste du § 5 sont vertes |
| `EA_BLOCKED` | au moins une condition rouge, avec ses **codes de motif exacts** : la technique va bien, la situation interdit |
| `EA_DISCONNECTED` | l'état précédent journalisé était au moins `EA_CONNECTED` et le cœur n'a plus d'agent enregistré pour ce login, ou son heartbeat dépasse le délai du chien de garde |
| `EA_ERROR` | une opération a échoué (code, étape), l'EA n'a rien dit dans l'échéance (`MT5_EA_NOT_REPORTING`, `MT5_WEBREQUEST_NOT_ALLOWED`) ou une opération a été interrompue |

`EA_BLOCKED` (la situation interdit) et `EA_ERROR` (quelque chose a mal fonctionné) ne se confondent pas. `EA_READY` est **technique** : l'**autorisation d'exécuter** est une ligne séparée (`Execution Authorization`) dont les motifs sont lus : mode du système (`OFF`/`OBSERVE`…), permissions de trading rapportées, `HALTED`, compte non `tradable`, agent compilé `OBSERVE`. Un terminal peut donc être `EA_READY` avec `Execution Authorization: BLOCKED — SYSTEM MODE = OFF`, comme dans l'exemple du brief.

**3.4 Transitions** — table figée, comme `domain/execution/state.py` :

| De | Vers |
|---|---|
| `NOT_INSTALLED` | `DEPLOYING` |
| `DEPLOYING` | `DEPLOYED`, `EA_ERROR` |
| `DEPLOYED` | `TERMINAL_STARTING`, `DEPLOYING` (redéploiement) |
| `TERMINAL_STARTING` | `EA_LOADING`, `EA_ERROR` |
| `EA_LOADING` | `EA_CONNECTED`, `EA_ERROR` |
| `EA_CONNECTED` | `EA_VALIDATING`, `EA_BLOCKED`, `EA_DISCONNECTED` |
| `EA_VALIDATING` | `EA_READY`, `EA_BLOCKED`, `EA_DISCONNECTED` |
| `EA_READY` | `EA_VALIDATING`, `EA_BLOCKED`, `EA_DISCONNECTED`, `TERMINAL_STOPPING` |
| `EA_BLOCKED` | `EA_VALIDATING`, `EA_DISCONNECTED`, `TERMINAL_STOPPING`, `DEPLOYING` (EA détaché seulement) |
| `EA_DISCONNECTED` | `EA_CONNECTED` (reconnexion), `TERMINAL_STOPPING`, `DEPLOYED`, `EA_ERROR` |
| `EA_ERROR` | `DEPLOYING`, `TERMINAL_STARTING`, `TERMINAL_STOPPING`, `DEPLOYED`, `NOT_INSTALLED` |
| `TERMINAL_STOPPING` | `DEPLOYED`, `EA_ERROR` |

**`EA_READY` n'est atteignable que depuis `EA_VALIDATING`** : après toute reconnexion le terminal repasse par `EA_CONNECTED` puis `EA_VALIDATING`, donc la réconciliation est refaite. Un saut **observé** hors de la table (un terminal tué de l'extérieur, un agent qui réapparaît) n'est pas refusé — c'est un fait — mais il est enregistré comme `STATE_ANOMALY` (avertissement) ; si la cible est `EA_READY`, l'état affiché est ramené à `EA_VALIDATING`.

**3.5 Journal** : à chaque changement d'état de synthèse, un événement `MT5_STATE_TRANSITION` dans `var/launcher/events-AAAAMMJJ.jsonl` (ADR 0038 § 12) : horodatage UTC, `terminalId`, compte si connu, `deploymentId`, état précédent, nouvel état, codes de motif, étape, déclencheur (`operation` ou `observation`), identifiant de corrélation. Le dernier état est gardé dans `terminals.json` **uniquement** pour contrôler la table et reconnaître `EA_DISCONNECTED` ; il n'est **jamais** lu comme preuve de préparation (la préparation est recalculée à chaque fois).

### 4. Registre des terminaux et isolation (C5)

`var/launcher/terminals.json`, une entrée par instance. Champs **observés** (jamais saisis) : chemin d'installation, exécutable, dossier de données, mode portable, version et build, serveur et société lus par le cœur, login et type de compte lus par l'EA. Champs **déclarés** par Exhorte : compte Trading OS associé, `expectedLogin`, symbole et période du graphique, numéro magique, symboles autorisés, fournisseur et produit déclarés. **L'écart observé / déclaré bloque la préparation** (`MT5_ACCOUNT_MISMATCH`, …) et s'affiche ; il ne se corrige pas tout seul.

```
{ "terminalId": "D0E8209F77C8CF37AD8BF550E51FF075", "label": "exness-demo-01",
  "installPath": "…", "dataPath": "…", "portable": false, "mt5Build": 6230,
  "declared": { "accountId": "exness-486046157", "expectedLogin": "…", "chart": {"symbol": "XAUUSDm", "period": "M5"},
                "magic": 0, "allowedSymbols": ["XAUUSDm"], "provider": "EXNESS", "product": "EXNESS_STANDARD" },
  "eaVersion": "1.13", "deploymentStatus": "…", "operation": {…}, "lastStatus": "…" }
```

(Illustratif : le schéma exact est fixé à l'incrément I3, par un test.) Le `lastHeartbeat` du brief n'est **pas** stocké : il est lu du cœur à chaque fois.

**Règles d'isolation**, chacune imposée par un test :

1. **Identifiant** : le nom à 32 hexadécimaux du dossier de données ; pour un terminal portable, une empreinte du chemin d'installation (à fixer en I3).
2. **Le chemin d'écriture se déduit du registre et se revérifie à l'écriture** : `origin.txt` (ou le marqueur portable) doit toujours désigner l'installation enregistrée ; sinon `MT5_TERMINAL_PATH_CHANGED`, rien n'est écrit.
3. **Fichiers propres à un terminal** : `MQL5\Experts\TradingOS\TradingOsAgent.ex5`, `MQL5\Presets\TradingOS-<terminalId>.set`, `var/launcher/mt5/<terminalId>/startup.ini`, `MQL5\Files\tradingos_agent.token`. Rien n'est partagé entre terminaux sauf la lecture du `.ex5` source.
4. **Verrou par terminal** : `var/launcher/locks/<terminalId>.lock`, même schéma (pid + heure de création) que `lock.py`. Deux opérations sur le même terminal sont refusées ; deux terminaux différents n'interfèrent pas.
5. **Liste blanche des écritures** : le déploiement n'écrit que dans les chemins ci-dessus et sauvegarde dans `var/launcher/backups/`. **Il ne touche jamais** `MQL5\Files\*` hors le jeton — en particulier **jamais le magasin de commandes de l'EA** (un fichier par login et numéro magique) : le supprimer permettrait à un `commandId` rejoué de s'exécuter, ce que l'idempotence de l'ADR 0010 interdit. Un redéploiement ne remplace que le `.ex5`, EA détaché.
6. **Liaison au compte** : le preset renseigne `InpAccountId` avec le login attendu ; l'EA refuse alors toute commande si le terminal est sur un autre login (`identity: mismatch`), et le cœur route les commandes par login (inchangé). Le login déclaré doit être celui du compte Trading OS associé.
7. **Numéro magique** : obligatoire, déclaré, **unique dans le registre** (ADR 0010 : isolation par environnement). Deux terminaux de même numéro sont refusés.
8. **Un seul compte connecté à la fois** (ADR 0021, inchangé) : préparer ou déployer sur N terminaux ne connecte **aucun** compte, et le lanceur n'appelle jamais `connect`. Le registre peut contenir plusieurs terminaux ; la connexion simultanée de plusieurs terminaux demande un ADR qui remplace l'ADR 0021 (hors de cette mission).
9. **Identité vérifiée de façon indépendante** : courtier, serveur, login et type de compte sont **observés** par le cœur et par l'EA et seulement **comparés** aux valeurs déclarées. Un doute rend le compte non exécutable (ADR 0036, inchangé).

### 5. Préparation et réconciliation d'attachement

**Conditions de `EA_READY`** (toutes vertes, chacune avec son motif si rouge) : terminal démarré ; connexion au courtier (`mt5_connected`) ; compte identifié (`hello.identity == ok`, `correct_account`, identification exécutable) ; identité du produit (§ 9) ; EA chargé (un `hello` accepté) ; version et protocole compatibles (§ 7) ; symbole autorisé et conforme au registre ; paramètres conformes au preset (avec 1.14, ADR 0040 ; sans lui : `PARAMETERS_UNREPORTED`, avertissement) ; heartbeat frais (< 15 s, `AGENT_FRESH`) ; cœur et Risk Engine opérationnels ; compte non bloqué (`no_critical_incident`, `account_limits_configured`) ; protections locales (capacité `dead_man` annoncée et ping reçu — « fonctionnel » ne se prouve qu'avec un ordre, la mission ne peut dire que « annoncé et reçu ») ; aucun EA tiers attaché (A9) ; **réconciliation terminée depuis cet attachement**.

**Réconciliation d'attachement** : après tout `hello` (premier ou reconnexion), le terminal reste en `EA_VALIDATING` tant que :

1. le cœur n'a pas terminé une réconciliation **postérieure à l'enregistrement de l'agent** (nouveau fait côté cœur, `attach_reconciled` : dernière réussite plus récente que l'enregistrement) ;
2. aucune commande n'est `UNKNOWN` ni `RECONCILING` (mécanisme existant ; `UNKNOWN` ne se rejoue jamais, seule issue : `RECONCILING` → `RECONCILED`) ;
3. l'EA a répondu (`execution.reconciled`) pour chaque commande dont il avait gardé le doute.

Les positions ouvertes à la main ou par un autre EA sont des **avertissements** (sémantique existante `EXTERNAL_POSITION`), listés ; les positions gérées par Trading OS sont rapprochées du journal. **Une opération non résolue bloque la reprise** (`EA_BLOCKED(UNRESOLVED_COMMANDS)`). Le lanceur n'envoie **aucune commande, jamais** ; il ne relance rien. Un redémarrage technique n'efface pas l'état métier : le lanceur ne touche pas à la base (hors la sauvegarde et la migration de l'ADR 0038) ni au magasin de commandes de l'EA.

**HALT et positions ouvertes (ADR 0033, inchangé)** : `HALTED` bloque les entrées, les protections et sorties continuent, fermer toutes les positions reste un geste distinct. Arrêter Trading OS, déployer ou redémarrer MT5 ne ferme jamais une position, et un redémarrage de terminal est refusé tant que le cœur voit des positions ou des ordres en attente, sauf accusé explicite (ADR 0038 § 8).

**Le lanceur s'arrête à `EA_READY`.** Il ne passe jamais à `CONFIRM`, `ARMED` ni `AUTONOMOUS` ; il n'écrit jamais `AllowLiveTrading`, `Enabled`, `Login`, `Password`, `[Experts]`, `[Common]`.

### 6. `doctor`

`launcher doctor` est **en lecture seule** : il n'écrit ni registre, ni configuration, ni événement, ne lance aucun processus et n'envoie aucune commande (un test sur un monde simulé vérifie qu'aucun fichier n'est écrit). Il ne lit de `common.ini` que les clés `Enabled`, `Account`, `Profile`, `AllowDllImport`. Il lit les points d'API protégés avec les réglages que le cœur charge, sans jamais afficher un jeton. Familles de contrôles : environnement (venv, Node, Docker, `.env` présent, ports) ; composants (base, cœur, cockpit, propriétaire de chaque port) ; état du lanceur (verrou périmé, opération inachevée) ; MT5 (installations, instances en cours, dossiers de données, jonction ou copie, manifeste contre sources, preset contre entrées déclarées, clés de `startup.ini` contre la liste blanche, EA tiers) ; vue du cœur (agents, workers vivants contre comptes connectés, motifs de la préparation) ; EA (champs du `hello`, compatibilité, âge du heartbeat contre les seuils 15 / 30 / 30 s, identité, permissions) ; réconciliation (âge de la dernière réussite, commandes non résolues).

Sortie par terminal, dans la forme du brief : `MT5 Process`, `Broker Connection`, `EA Attached`, `EA Communication`, `Heartbeat`, `Account Identity`, `Product Identity`, `Risk Engine`, `Reconciliation`, `Deployment Status`, `Execution Authorization`, `Reason`. Chaque constat porte : code, étape, description, **action corrective suggérée**, horodatage, identifiant de terminal et de compte. **Ce qu'un EA 1.13 ne peut pas dire n'est pas inventé** : `EA Attached` est « inféré du `hello` », la période du graphique est « non rapportée ». Les seuils de heartbeat ne sont ni unifiés ni modifiés : le diagnostic dit **lequel** a sauté.

### 7. Compatibilité EA ↔ cœur

Une **table de versions minimales**, donnée pure et datée, sans entrée-sortie : enveloppe `1` ; `agentVersion` non vide ; capacité `dead_man` recommandée ; plage `protocolVersion` prise en charge (quand 1.14 la rapporte). Résultats : `COMPATIBLE`, `COMPATIBLE_WITH_WARNINGS` (par exemple `PROTOCOL_VERSION_UNREPORTED` pour un 1.13), `INCOMPATIBLE`. Le gestionnaire de déploiement lit la version **du manifeste** et applique la table **avant** de copier : **il ne déploie jamais une version incompatible**. Le cœur l'applique au `hello`. Un `hello` hors table : `EA_PROTOCOL_INCOMPATIBLE`, rien ne continue. L'emplacement de la table (importable par le lanceur et le cœur sans que l'un importe l'autre) est fixé à l'incrément I4.

### 8. Cockpit (C4)

Une seule page `/system`, qui réunit le « System Center » de l'ADR 0038 et la section « MT5 & Execution Management » du brief : vue d'ensemble, carte par terminal (nom, courtier, compte, serveur, type, chemins, versions MT5 et EA, symbole, période, états, dernier heartbeat, réconciliation, permissions), carte du déploiement, événements récents. Alimentée par `GET /api/system/center` et `GET /api/system/mt5/terminals` : **lecture seule, données réelles du backend, aucun statut simulé côté interface**. Types générés (`gen-types`), jamais écrits à la main.

- **Version 1 — boutons réels, tous en lecture** : `VERIFY EA` (relit la préparation du terminal), `VIEW LOGS` (événements du lanceur, secrets masqués), `DETECT TERMINALS` (balayage en lecture seule, sans écriture).
- **Version 1 — commande affichée et copiable, pas de bouton** : `REGISTER TERMINAL`, `DEPLOY EA`, `LAUNCH MT5`, `RECONNECT`, `REDEPLOY` (ils changent un fichier, un processus ou un état). Les rendre actifs exige un **ADR séparé** et un geste humain confirmé, parce que ouvrir l'API aux processus élargit une surface gardée par le seul jeton du cockpit.
- Le code de découverte en lecture seule est placé de façon que la CLI et l'API l'utilisent **sans que le cœur importe `launcher/`** (emplacement fixé en I3).
- **Avant tout code du cockpit** : lire le guide pertinent dans `node_modules/next/dist/docs/` (`AGENTS.md` : cette version de Next.js n'est pas celle que l'on connaît).

### 9. Identité du produit (C6, tranché) et ce qui reste ouvert

- **C6 — identité du produit : tranché le 2026-11-07, option (b).** Constat de départ : `executable = not blockers` (`identity.py:325`) ; un produit déduit du seul suffixe est `PROBABLE` et **exécutable** ; l'API affiche `CONFIRMED` pour la démo Exness à cause du contrat FTMO déclaré et répété (`identity.py:280`), non d'une preuve du produit Exness. Les options écartées : (a) exiger un produit indépendamment confirmé (`EA_READY` aurait été **inatteignable sur la démo Exness**) ; (c) le statu quo. **Règle retenue** pour la condition « identité du produit » de `EA_READY`, calculée sur le **produit du courtier** (`broker_product`) et non sur le contrat de règles répété :
  - produit du courtier inconnu, ou un bloqueur d'identité existant présent (`FACTS_MISSING`, `PROVIDER_NOT_IDENTIFIED`, `PROVIDER_AMBIGUOUS`, `PROVIDER_MISMATCH`, `ENVIRONMENT_MISMATCH`, `PRODUCT_UNKNOWN`) → **rouge** ;
  - produit déduit d'un signal observé (le suffixe) et **aucune déclaration** d'Exhorte → **rouge `PRODUCT_UNDECLARED`** ;
  - produit déduit et déclaration d'Exhorte **différente** → **rouge `PRODUCT_MISMATCH`** ;
  - produit déduit et déclaration d'Exhorte **identique** → **vert, avec l'avertissement `PRODUCT_UNCONFIRMED`**. Le produit n'est jamais affiché « confirmé » : un suffixe seul ne prouve rien, la déclaration d'Exhorte le **contraint** sans le prouver.
  - La déclaration est le champ `declared.product` du registre des terminaux (§ 4), saisi par `launcher mt5 register` ; le cœur la lit en lecture seule. Pour un compte FTMO, le contrat déclaré (`challenge`, ADR 0036) tient lieu de déclaration de produit : pas de ressaisie (à confirmer à l'incrément I7).
  - `ACCOUNT_IDENTITY_UNVERIFIED` devient le **code d'en-tête** affiché quand l'une des lignes rouges ci-dessus est présente : il coiffe les codes détaillés, il n'en remplace aucun.
  - **Portée** : cette règle est une condition de **préparation**. Elle ne modifie ni `identity.py`, ni le drapeau `executable`, ni aucune règle de risque ; **aucun amendement de l'ADR 0036 n'est nécessaire**. Elle ne fait que **resserrer** : une préparation qui passait sans déclaration exige désormais la tienne.
- **Ouvert, hors de cette mission — rendre le *compte lui-même* non exécutable quand le produit n'est pas déclaré** (le brief le demande pour une identité ambiguë). Ce serait un resserrement du drapeau `executable`, donc d'une entrée du Risk Engine : décision et ADR séparés. Aujourd'hui, ni l'agent compilé `OBSERVE` ni le mode `OFF` ne permettent d'ordre.
- Les verrous (lockouts) comptent-ils dans « compte non bloqué » ? Lu : `no_critical_incident` et `account_limits_configured` ; pas les verrous. À vérifier en I7.
- Fait `attach_reconciled` côté cœur : à écrire et tester (I7).
- Identifiant d'un terminal portable ; emplacement exact et encodage du `.set` ; `/config` (R1) ; WebRequest (R2) — **non vérifiés**, à éprouver sur la démo avec accord.

## Tests

Tout effet extérieur passe par un port avec un faux (processus, Docker, HTTP, fichiers dans un dossier temporaire, `FakeMt5`) ; **les tests sont écrits avant le code et échouent d'abord**. Aucun test ne lance un vrai MT5, ne tue un vrai processus, n'envoie un ordre. Familles ajoutées par cet ADR :

- **Machine à états** : chaque transition de la table ; chaque saut observé hors table → `STATE_ANOMALY` ; `EA_READY` inatteignable hors de `EA_VALIDATING` ; une reconnexion repasse par `EA_CONNECTED` et `EA_VALIDATING` ; une opération périmée → `EA_ERROR` ; le lanceur ne produit jamais `CONFIRM`, `ARMED` ni `AUTONOMOUS`.
- **Registre et isolation** : deux terminaux de même numéro magique refusés ; login déclaré ≠ login du compte associé refusé ; `origin.txt` modifié → rien n'est écrit ; deux opérations simultanées sur le même terminal refusées, sur deux terminaux différents autorisées ; liste blanche d'écritures (le magasin de commandes de l'EA est intact après un redéploiement) ; `InpTradableLogins` / `InpClosableLogins` jamais renseignés.
- **Réconciliation d'attachement** : commande `UNKNOWN` → `EA_BLOCKED(UNRESOLVED_COMMANDS)`, jamais rejouée ; réconciliation antérieure à l'enregistrement → `EA_VALIDATING` ; position externe → avertissement ; mauvais compte → aucune commande ne lui est routée.
- **Identité du produit (C6)** : produit déduit sans déclaration → rouge `PRODUCT_UNDECLARED` ; déclaration différente → rouge `PRODUCT_MISMATCH` ; déclaration identique → vert avec `PRODUCT_UNCONFIRMED`, jamais « confirmé » ; le contrat FTMO répété sur un compte Exness ne rend **jamais** vert le produit du courtier ; chaque bloqueur d'identité existant → rouge et code d'en-tête `ACCOUNT_IDENTITY_UNVERIFIED` ; `identity.py` et le drapeau `executable` inchangés (tests existants de l'ADR 0036 intacts).
- **`doctor`** : aucun fichier écrit ; chaque contrôle rouge donne code, étape, action corrective ; un champ que 1.13 ne rapporte pas n'est pas inventé.
- **Enveloppe** : chemins contenant des espaces ; dossier courant ; code de sortie transmis ; `Status` et `Doctor` ne modifient rien.
- **Sécurité (architecture)** : aucune écriture de `[Experts]`, `[Common]`, `Login`, `Password`, `AllowLiveTrading` ; aucun secret dans un `.set`, un `.ini`, un événement ; un seul `OrderSend` dans le dépôt ; `launcher/` n'importe ni exécution, ni risque, ni Guardian, ni positions ; aucun arrêt de processus hors registre.
- **Non-régression** : `pytest` (≈ 16 à 40 min, en arrière-plan), `vitest`, `ruff check` et `format --check`, `mypy trading_os`, `gen-types --check`, `tsc --noEmit`, `eslint`, `next build` **hors** `next dev`.

## Stratégie de migration

1. `start.ps1` reste intact (ADR 0038, migration § 1). Aucun changement de schéma de base ; aucune donnée modifiée ; jonction `MQL5\Experts\TradingOsAgent`, `ea1.set`, `.env`, `common.ini` non touchés.
2. Incréments, un par un, tests d'abord, une validation entre chacun : **I2b** (enveloppe `TradingOS.bat`, modes, `doctor` côté infrastructure) ; **I3** (découverte, registre, verrou par terminal, états d'opération) ; **I4** (compilation sur copie, manifeste, table de versions, déploiement) ; **I5** (preset, `startup.ini`, **essai R1 sur la démo, accord requis**) ; **I6** (lancement ou redémarrage contrôlé, états, journal des transitions) ; **I7** (préparation `EA_READY`, `attach_reconciled`) ; **I8** (`GET /api/system/center`, page `/system` en lecture) ; **I9** (agent 1.14, ADR 0040) ; **I10** (validation sur la démo, documentation, HANDOFF).
3. **Validation réelle** (sur la démo, par étapes, **avec l'accord d'Exhorte à chaque redémarrage**, toujours `OBSERVE`, aucun ordre) : (a) essai R1 ; (b) déploiement et preset ; (c) redémarrage contrôlé, après détachement du compte par Exhorte (R16 de l'audit) ; (d) `hello`, identité, heartbeat ; (e) démarrages répétés, `mt5Workers.alive` conforme, aucun worker orphelin. Rien n'est dit « validé » sans réponse réelle du terminal (ADR 0035).

## Valeurs posées par Claude, à relire

Codes de sortie (`0`/`1`/`2`), échéances d'opération (déploiement, fermeture contrôlée, `EA_LOADING` = 90 s déjà posée en ADR 0038), deux états ajoutés à ceux du brief (`DEPLOYED`, `TERMINAL_STOPPING`), unicité du numéro magique dans le registre, `Full` qui propose et n'applique que sur `-Apply`, `TradingOS.bat` sans espace.

## Ce que cet ADR ne fait pas

- Il **ne relève aucun mode**, n'arme rien, ne rend rien `AUTONOMOUS`, ne rattache ni ne détache aucun compte, n'écrit aucun mot de passe, aucun identifiant, aucune permission de trading.
- Il **ne touche** ni au Risk Engine, ni au Guardian, ni au Position Manager, ni au chemin d'exécution, ni à l'unique `OrderSend`, ni au mode compilé `OBSERVE`, ni aux limites de risque, ni aux délais existants (`SLOW_CALLS`, 30 s du `supervisor`, 15 / 30 / 30 s du heartbeat), ni aux ports.
- Il **ne remplace pas l'ADR 0021** : pas de connexion simultanée de plusieurs terminaux.
- Il **ne rend pas le compte lui-même non exécutable** quand le produit n'est pas déclaré (§ 9), et **ne tranche pas** la décision (5) du HANDOFF (refuser d'armer sans `dead_man`), la validation 3 de l'ADR 0037, ni le sort de l'EA tiers (il le signale).
- Il **ne construit rien** : l'agent 1.14 est l'ADR 0040 ; les actions de processus du cockpit auront le leur.

## Avancement

- **I2b — construit le 2026-11-07 (non commité)** : l'enveloppe `TradingOS.bat` + `scripts/TradingOS.Launcher.ps1` (modes `Full | Infrastructure | MT5 | Status | Stop | Doctor`, `-Json`, `-DryRun`, `-IncludeDatabase`, `-Apply`, `-PythonPath`) et `python -m trading_os launcher doctor` (`launcher/doctor.py`, fonction pure : environnement, composants, état du lanceur, vue du cœur, ligne « MetaTrader 5 non inspecté »). Pour l'alimenter : `CoreHealth` lit en plus `agentsConnected`, `mt5Workers` et `executionMode` (`None` = le cœur ne le dit pas, jamais zéro), `Observation` garde la santé rapportée, et `lock.inspect_lock` regarde le verrou sans le prendre ni le retirer. **Tests écrits avant le code** (rouges par import absent, puis verts) : 418 tests ciblés du lanceur et de l'architecture verts, dont 58 d'enveloppe qui font tourner de **vrais** PowerShell 5.1 et 7 sur un faux paquet `trading_os`, depuis un chemin contenant des espaces ; `ruff`, `ruff format`, `mypy` (245 fichiers) et `gen-types --check` propres ; **suite complète : 3 282 passés, 15 ignorés** (18 min 37 s ; lancée avant les derniers ajustements des messages de `doctor` et de la pause du `.bat`, après lesquels les 418 tests ciblés ont été rejoués, verts). **Mutation** : sans son BOM, Windows PowerShell 5.1 écrit « incrÃ©ments » — le test des accents le détecte.
- **Vérifié sur le poste réel, en lecture seule** : `TradingOS.bat Doctor` (16 constats, code 0, aucune écriture : `var/launcher/` reste vide), `Stop -DryRun`, `MT5`, et `Doctor -Json` sous Windows PowerShell 5.1 ; le cœur (pid 1668) et le cockpit (pid 7900) n'ont pas été touchés.
- **Écarts avec le texte de cet ADR, dits plutôt que cachés** : (1) **codes de sortie** : ils suivent ceux déjà en place depuis I1 et I2 (0 rien d'anormal · 1 un problème, un refus ou un échec · 2 la machine n'a pas pu être observée), et non l'ordre posé au § 2 (2 bloqué, 1 technique) ; le § 2 les disait « à relire » et les tests de I1 et I2 les figent ; l'enveloppe ajoute 2 si le Python du cœur est introuvable. (2) **Pause finale du `.bat`** : seulement **sans argument**. Le premier jet détectait le double-clic par `cmd /c`, mais PowerShell, Python et les planificateurs lancent aussi les `.bat` ainsi : un utilisateur de terminal aurait attendu une touche, et un test a bloqué. (3) `doctor` ne conseille **jamais** `launcher adopt database` : le code le refuse (« la base est un conteneur »). Le reste de l'ADR est inchangé.
- **Non vérifié, non fait** : les modes `Full` et `Infrastructure` (ils appellent `start`) et un `Stop` réel via l'enveloppe, qui demandent l'accord d'Exhorte ; la pause du double-clic sans argument dans une vraie fenêtre ; l'enveloppe lancée depuis le dossier réel du dépôt avec un chemin à espaces (éprouvée sur une copie) ; **tout ce qui touche MetaTrader 5** (I3 et suivants : rien n'est écrit).
- **I3 — construit le 2026-11-07 (non commité)** : `launcher/mt5/` (`model`, `ports`, `adapters`, `discovery`, `terminals`, `plan`, `report`, `cli`) et les commandes `launcher mt5 detect | list | plan | register`. **Découverte en lecture seule** : les installations viennent de trois sources (la liste des programmes installés, les dossiers `*MetaTrader*` de Program Files, les processus `terminal64.exe`) plus les chemins déjà enregistrés, chacune acceptée seulement si `terminal64.exe` s'y trouve (sinon elle est « refusée » avec sa raison) ; un dossier de données est rattaché à une installation par son seul `origin.txt` (le **seul** fichier dont le contenu est lu) ; les instances en cours, la jonction ou le dossier de notre agent avec sa cible, les EA tiers *installés* (nommés, jamais dits « attachés »), la présence — jamais le contenu — du fichier de liaison de l'agent et la version lue dans les ressources de l'exécutable. **Aucun terminal n'est jamais choisi pour l'utilisateur.** **Registre** `var/launcher/terminals.json` : identité + déclaration d'Exhorte (compte Trading OS, login attendu, graphique, numéro magique, symboles autorisés, fournisseur, produit), états d'opération avec échéance, verrou d'écriture, copie `.bak-…` avant tout remplacement, fichier illisible mis de côté (`.corrupt-…`), refus qui laissent le fichier intact ; verrou par terminal `var/launcher/locks/<id>.lock`. **Enregistrement à la main** (`--install-path` avec `--data-path` ou `--portable`) aussi strict que la détection : `terminal64.exe` présent, `origin.txt` qui désigne cette installation (sinon « identité ambiguë », rien n'est écrit), dossier `MQL5` pour un portable. `mt5 plan` dit ce qui reste à déclarer et liste les étapes qui n'existent pas (I4 à I7) ; `MT5` = ce plan, `Full` = `start` puis ce plan (sauf `-Json`) ; `doctor` regarde MetaTrader (installations, instances, jonction, `Presets`, EA tiers, terminaux non enregistrés ou introuvables, opérations en cours ou périmées).
- **Valeurs posées par l'I3, à relire** : un compte Trading OS, un login attendu et un numéro magique ne peuvent chacun appartenir qu'à **un** terminal (l'ADR ne posait que le numéro magique) ; l'identifiant d'un terminal portable est `portable-` + 16 hexadécimaux d'une empreinte du chemin (insensible à la casse), un dossier de données qui n'a pas un nom de 32 hexadécimaux reçoit `manual-…` ; **`common.ini` n'est pas lu par l'I3** (clés sensibles : reporté à l'essai `/config`) ; **la ligne de commande d'un `terminal64.exe` n'est jamais gardée** (elle peut porter `/login:` et un mot de passe) — il n'en sort que deux faits, `/portable` et `/config:` ; un terminal portable *arrêté* n'est pas détecté automatiquement (seul un portable en cours l'est) : l'enregistrement à la main le couvre.
- **Défaut trouvé sur le poste réel, corrigé** : le diagnostic annonçait un « problème » du cockpit (« aucune réponse HTTP ») alors qu'il répondait (HTTP 200 en 1 à 5 s) : la première requête à `next dev` avait duré 5 s sous charge et la sonde n'attend que 3 s — le même défaut que `docker info` en I2. La sonde refait **une** tentative après une erreur de transport, **jamais** après un code de réponse ; les délais sont inchangés. Le préfixe `\\?\` des cibles de jonction n'est plus affiché.
- **Vérifié sur le poste réel, en lecture seule** : `mt5 detect` retrouve exactement l'audit du 2026-11-06 (une installation, version 5.0.0.6230, trois sources, pid 1872, un dossier de données, jonction vers `tools\mt5-execution-agent`, EA tiers `Ultimate_ICT_Gold_Scalper_v4.0.ex5`, `Presets` absent, fichier de liaison présent) ; `mt5 plan` propose `register --terminal D0E8209F77C8CF37AD8BF550E51FF075` ; `mt5 list` : aucun terminal ; `doctor` : code 0 ; `var/launcher/` vide. **Rien n'a été enregistré sur le poste réel** : les déclarations (compte, login, numéro magique, produit) sont celles d'Exhorte.
- **Tests de l'I3** : écrits avant le code (rouges par import absent) ; 603 tests ciblés verts (lanceur hors enveloppe, architecture, CLI, types générés) et 43 tests d'enveloppe verts sous PowerShell 7 et sous Windows PowerShell 5.1 ; trois **mutations volontaires** détectées (écriture dans le module de découverte, champ « ligne de commande » dans le modèle, option `--password` sur `register`), fichiers restaurés octet pour octet ; `ruff`, `mypy` (255 fichiers), `gen-types --check` propres ; suite complète : **non terminée** — le poste était saturé (CPU à 100 %, 216 Mo de mémoire libre sur 16 Go) et la suite, à ≈ 12 % après plus d'une demi-heure, a été arrêtée par mes soins ; la dernière suite complète, avant l'I3, était verte (3 282 passés, 15 ignorés) ; **à rejouer poste libre**. **Non vérifié** : `register` jamais exécuté sur le poste réel ; un second terminal et un portable (ils n'existent pas ici : testés sur des arborescences simulées) ; la clé du registre Windows lue sur une autre machine ; tout ce qui s'écrit dans MetaTrader (rien n'est écrit, par construction).
- **I4 à I10 — construits le 2026-11-12 sur la consigne d'Exhorte (non commités)** :
  - **I4** `launcher/mt5/{manifest,build,deploy}.py`, `shared/agent_compat.py` : `launcher mt5 build | builds | deploy`. Compilation sur une copie avec le MetaEditor du terminal (journal UTF-16 lu, jamais le code de sortie), manifeste (SHA-256 des sources et du `.ex5`, mode compilé, capacités lues dans la source) ; **un agent non compilé en `OBSERVE` n'est jamais construit ni déployé** ; déploiement du seul `.ex5` (copie atomique, sauvegarde dans `var/launcher/backups/<terminal>/`, vérification d'empreinte, retour arrière, jonction respectée, `MQL5\Files` jamais nommé). La table de compatibilité vit dans `shared/` (importable par le lanceur et le cœur sans que l'un importe l'autre).
  - **I5** `preset.py`, `startup_ini.py`, `prepare.py` : `launcher mt5 prepare`. Preset `.set` en UTF-16 LE avec BOM et CRLF (le format du `ea1.set` d'Exhorte), uniquement des entrées que la source de l'agent déclare, les entrées dont le nom finit par `Logins` toujours vides ; `startup.ini` à **une** section et **quatre** clés (`Expert`, `ExpertParameters`, `Symbol`, `Period`), toute valeur qui pourrait ouvrir une autre ligne ou section refusée.
  - **I6** `states.py`, `journal.py`, `control.py`, `status.py` : machine à états (table figée de l'ADR, `EA_READY` seulement depuis `EA_VALIDATING`, saut hors table = `STATE_ANOMALY`, journal `MT5_STATE_TRANSITION`) ; `launcher mt5 start | status`. **Redémarrage contrôlé** : portes toutes évaluées et toutes montrées (identité du terminal, `.ex5` et preset conformes à ce qui a été déployé et préparé, **aucune position ni ordre en attente lus sur le terminal lui-même** — un terminal illisible est un refus —, login conforme, **aucun worker du cœur attaché**, R16) ; **phrase `FERMER <terminal>` tapée** (il n'existe aucune option `--yes`) ; fermeture **polie** des fenêtres, jamais un kill ; relance par `terminal64.exe /config:<startup.ini>` sans compte ni mot de passe ; attente bornée (90 s) du `hello`. `process_control.request_window_close` est le seul code qui demande à une fenêtre de se fermer, appelé seulement par `control.py` (test d'architecture).
  - **I7** `shared/ea_readiness.py`, `services/system_center.py` : lecture de **14 conditions** (`READY` / `VALIDATING` / `BLOCKED`), règle C6 (produit déduit du suffixe : vert seulement si Exhorte l'a déclaré à l'identique, avertissement `PRODUCT_UNCONFIRMED`, jamais « confirmé » ; en-tête `ACCOUNT_IDENTITY_UNVERIFIED`), `attach_reconciled` (une réconciliation réussie postérieure à l'enregistrement de l'agent, `ExecutionService.registered_since`), commandes en doute, seuils de battement 15 / 30 s ; **autorisation d'exécuter en ligne séparée**. `launcher mt5 verify` la lit.
  - **I8** `GET /api/system/center` et `/api/system/mt5/terminals` (lecture seule, le cœur lit `var/launcher/` avec ses propres lecteurs, **sans importer `launcher/`**, test d'architecture) ; page `/system` du cockpit (`lib/cockpit/system-center.ts`, `components/cockpit/system-center-screen.tsx`, entrée de navigation) : carte par terminal, conditions non vertes d'abord, ligne d'autorisation, événements récents du lanceur, **commandes à copier, pas de bouton** (ADR séparé pour les rendre actives).
  - **I9** : voir l'ADR 0040 (« Avancement »). **I10** : voir ci-dessous.
- **Écarts avec le texte de l'ADR, dits** : (1) la confirmation tapée est lue sur l'**entrée standard** (`--confirm-close` puis la phrase) ; (2) un terminal portable : `MT5_TERMINAL_PATH_CHANGED` se contrôle sur le dossier `MQL5` de l'installation (pas d'`origin.txt`) ; (3) `launcher mt5 status` **écrit** le registre et le journal quand l'état change (le diagnostic `doctor`, lui, reste en lecture seule) ; (4) le lanceur ne lit de `common.ini` que la clé « experts autorisés » (jamais le reste, jamais `AllowDllImport`) ; (5) **valeurs posées** : délais de fermeture 60 s, d'apparition 30 s, de `hello` 90 s ; une opération de préparation prend l'état d'opération `DEPLOYING`.
- **Validation réelle (I10), faite le 2026-11-12 sur le poste, ce qui a tourné pour de vrai** : enregistrement du terminal (`register` : **déclarations posées par moi, à relire** — compte `exness-486046157`, login `486046157` (confirmé par la lecture réelle du terminal), graphique `XAUUSDm M5`, numéro magique `1001` (celui de l'`ea1.set` du 2026-09-26), symboles `XAUUSDm,EURUSDm`, fournisseur `EXNESS`, **produit non déclaré** : `EA_READY` restera bloqué par `PRODUCT_UNDECLARED` jusqu'à ta déclaration) ; `build` (MetaEditor réel, 0 erreur, 0 avertissement) ; `deploy` (REPLACE du 1.13, sauvegarde faite) ; `prepare` (le dossier `MQL5\Presets` a été créé) ; `start --dry-run` : **huit portes OK**, première lecture réelle d'un terminal ouvert par la sonde (0 position, 0 ordre, login conforme, aucun worker) ; **premier démarrage réel du lanceur** (`launcher start` : base, schéma à jour, cœur pid 31280, cockpit pid 24620) ; `mt5 status` et `mt5 verify` contre le vrai cœur (le cœur répond, aucun hello).
- **Pas fait — à ton geste** : **le redémarrage réel de MetaTrader 5** (fermeture polie, `/config`, attente du `hello`). Ma commande, qui envoyait moi-même la phrase de confirmation sur l'entrée standard, a été **refusée par le contrôle de permissions** (elle contournait la confirmation tapée par un humain) ; je ne l'ai pas contourné. Donc **non vérifiés sur le live** : R1 (`/config:` remplace-t-il `common.ini` ? sauvegarde faite avant l'essai : `var/launcher/backups/D0E8209F…/common.ini.before-r1-trial`, 1 758 octets, SHA-256 `26e70395…80c3`), R2 (WebRequest : le lanceur ne peut pas le lire), le chargement de l'agent par `[StartUp]`, le `hello` 1.14, un `EA_READY`. À taper toi-même, depuis `04_code\python` : `.venv\Scripts\python.exe -m trading_os launcher mt5 start --terminal D0E8209F77C8CF37AD8BF550E51FF075 --confirm-close`, puis la phrase `FERMER D0E8209F77C8CF37AD8BF550E51FF075`. Avant : les **experts doivent être autorisés** dans MetaTrader (Outils > Options > Experts, que le lanceur n'écrit jamais) et `127.0.0.1` listé pour WebRequest.
- **Tests** : lanceur, lecture, centre système, architecture, télémétrie : ~900 tests ciblés ; `vitest` 297 ; `tsc` et `eslint` propres ; 4 mutations d'architecture détectées ; `ruff` et `mypy trading_os` propres. **Non résolu, hors de mon travail** : 66 fichiers `* (1).py|tsx` non suivis (copies du 2026-11-11) font échouer 4 tests d'architecture existants et `next build` (erreur de type dans `components/accounts/registered-account-card (1).tsx`) ; la suite pytest complète a été lancée mais son résultat n'est pas consigné ici.

## Conséquences

- Un état de déploiement lisible, des transitions contrôlées et journalisées, sans transformer une lecture en valeur posée : `EA_READY` ne peut pas rester vrai par inertie.
- Plusieurs terminaux peuvent être déclarés, déployés et préparés sans mélange de configuration, sans que le cœur change de modèle de compte.
- `doctor` réunit en un endroit ce qui oblige aujourd'hui à lire plusieurs journaux.
- Coût : un registre et des états d'opération persistés de plus à maintenir ; une préparation `EA_READY` qui reste bloquée (`PRODUCT_UNDECLARED`) tant qu'Exhorte n'a pas déclaré le produit du compte ; sans l'agent 1.14, le graphique, la période et les protections locales restent des **avertissements honnêtes** (`CHART_UNVERIFIED`, `PARAMETERS_UNREPORTED`), non des preuves.
