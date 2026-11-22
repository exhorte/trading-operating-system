# ADR 0038 — Lanceur Trading OS et orchestration du terminal MT5 : préparer et observer, sans jamais autoriser

Statut : **accepté le 2026-11-06** par Exhorte (« Oui, accepté »), avec les choix A1 à A11 aux valeurs recommandées — mission « Trading OS — one-click launcher, MT5 auto-deployment & execution readiness », rédigé à sa demande à partir de l'audit `context/execution/launcher-mt5-integration-audit.md`. **Rien n'est construit à la date d'acceptation** ; le code avance par incréments (voir « Stratégie de migration »), un ADR fils avant l'agent 1.14 et avant les actions de processus du cockpit. Des essais sur la démo, des actions sur l'environnement (A10) et tout redémarrage du cœur ou de MT5 réels demandent **son accord au moment de les faire**. **N'amende aucun ADR ; respecte les invariants des ADR 0010, 0013, 0021, 0034, 0035, 0036 et 0037** (voir « Ce que cet ADR ne fait pas »). Ne touche ni au Risk Engine, ni au Guardian, ni aux modes d'autonomie, ni au chemin d'exécution, ni au mode compilé de l'agent.

## Contexte

L'application se lance aujourd'hui avec un seul script, `scripts/start.ps1` (base, schéma, jeton de l'agent, cœur, cockpit), puis à la main pour tout ce qui touche MT5. L'audit du 2026-11-06 (lecture seule du code et du poste) a établi :

- **Pas d'arrêt, pas de registre de processus, pas de journal de fichier.** Les fenêtres PowerShell sont le seul « propriétaire » du cœur et du cockpit. Un port occupé par un processus étranger est pris pour le nôtre (cockpit) ou n'est pas identifié.
- **Le piège du dossier courant a une cause racine** : le paquet `trading-os` du venv est installé en éditable vers `C:\Dev\trading-operating-system\04_code\python`, dossier disparu.
- **Rien pour MT5** : ni découverte, ni déploiement de l'EA (une jonction `MQL5\Experts\TradingOsAgent` → dépôt fait l'affaire), ni preset (le seul, `ea1.set`, date de 2026-09-26 et porte d'anciens noms d'entrées), ni configuration de démarrage, ni vérification d'attachement. Un seul terminal est installé, déjà ouvert, sans EA attaché ; un EA tiers est installé à côté du nôtre ; `[Experts] Enabled=0` dans `common.ini`.
- **Le cœur sait déjà presque tout ce que l'état « prêt » demande** : 16 contrôles de préparation et 6 conditions de démarrage (ADR 0034), un registre d'agents par login, un `agent.hello` riche (identité lue par l'EA, permissions, `attachedExperts`, `agentVersion`, `buildId`, `capabilities`), un heartbeat à 5 s, un superviseur à incidents, et `mt5Workers` depuis l'ADR 0037.
- **Ce que l'agent ne dit pas** : ni version de protocole (seulement l'enveloppe `"version":1`), ni symbole et période du graphique, ni chemin de données du terminal, ni état d'initialisation.
- **Trois faits MT5 qui bornent la conception**, non vérifiés ici : `/config:` pourrait **remplacer** `common.ini` pour la session ; la liste « Allow WebRequest » y est stockée sous forme codée, **invérifiable par lecture de fichier** ; `mt5.initialize` peut lancer le terminal lui-même (d'où le délai de 60 s de `SLOW_CALLS`).

## Décision

### 1. Principe et responsabilités

Le Trading OS décide, MT5 exécute, **le lanceur prépare et observe**. Il ne décide rien du trading. Il ne relève aucun mode, n'arme rien, ne rattache aucun compte, ne change jamais de compte, n'écrit ni identifiant ni permission de trading, ne clique pas le bouton Algo Trading.

| Responsable | De quoi |
|---|---|
| Lanceur (`trading_os.launcher`) | processus qu'il possède, état du démarrage, fichiers préparés pour MT5 (EA, preset, ini, jeton), lancement du terminal |
| Cœur | tout ce qui est décidé et observé : santé, identité, préparation, risque, exécution |
| Agent MQL5 | exécution et télémétrie, inchangé dans son rôle |
| Cockpit | afficher (System Center) ; un geste humain pour tout ce qui change un état |
| Exhorte | tout élargissement : mode, armement, compte, permission de trading, redémarrage d'un terminal |

### 2. Architecture (A1, A2, A6, A7, A8)

- **Logique en Python, enveloppe en PowerShell** *(A1 recommandé)*. `scripts/TradingOS-Start.ps1`, `TradingOS-Stop.ps1` et `Trading OS.bat` trouvent la racine, choisissent le Python du venv, fixent le dossier courant et appellent `python -m trading_os launcher start|stop|status|plan`. `start.ps1` reste en repli jusqu'à la validation (§ Migration).
- **Paquet `trading_os/launcher/`** : un **plan pur** (état observé → étapes, sans effet de bord), des **ports** (table de processus, Docker, HTTP, système de fichiers, horloge, registre Windows) avec une implémentation Windows et un faux de test chacun, un **registre de processus**, des **événements structurés**, la sous-commande CLI. Sous `launcher/mt5/` : `discovery`, `registry`, `deploy`, `preset`, `startup_ini`, `attach`, `terminal`.
- **Identification des processus sans nouvelle dépendance** *(A2 recommandé)* : `Get-CimInstance Win32_Process` et `Get-NetTCPConnection` via PowerShell. `psutil` n'est ajouté que si Exhorte le choisit.
- **État du lanceur dans des fichiers**, pas en base : il doit fonctionner **avant** la base. `04_code/var/launcher/` (`state.json`, `terminals.json`, `events-AAAAMMJJ.jsonl`, `logs/`, `backups/`), ajouté au `.gitignore`. Aucune migration.
- **Fenêtres du cœur et du cockpit masquées**, leur sortie redirigée vers `var/launcher/logs/` avec rotation *(A6 recommandé)* ; System Center les affiche.
- **Cockpit en `npm run dev`**, comme aujourd'hui *(A7 recommandé)* ; `next build` + `next start` pourra venir plus tard.
- **Aucun service Windows, aucune application Electron** : rien ne démontre qu'ils soient nécessaires.

### 3. Propriété et cycle de vie des processus

- Un processus est **possédé** s'il a été lancé par le lanceur. Le registre garde pour chacun : nom du composant, PID, **heure de création** (contre la réutilisation des PID), ligne de commande, dossier courant, fichier de journal, identifiant de corrélation du lancement.
- Un processus qui a notre signature (ligne de commande et dossier du dépôt) mais que le lanceur n'a pas lancé est **reconnu** (« adopté en lecture seule ») : il compte comme présent, il n'est ni dupliqué ni arrêté. Pour qu'un arrêt le vise, un geste humain explicite (`launcher adopt <composant>`) le fait passer à « possédé » après vérification de sa signature.
- Un processus **étranger** sur 3000, 8000 ou 9765 bloque **ce composant** (`LAUNCHER_PORT_FOREIGN_PROCESS`), jamais un kill.
- **Interdit** : arrêter un `terminal64.exe`, `python.exe`, `node.exe` ou `postgres.exe` parce qu'il écoute ou porte ce nom. Toute fin de processus passe par une entrée du registre ; un test d'architecture vérifie qu'aucun autre chemin de code n'appelle `taskkill`, `Stop-Process` ni `terminate`.
- Les **workers MT5** appartiennent au cœur (ADR 0037) : le lanceur ne les lance ni ne les tue ; il lit `mt5Workers` (un vivant attendu par compte connecté).

### 4. Démarrage idempotent

Ordre, chaque maillon attendant la **santé réelle** du précédent :

1. validation de l'environnement (venv, Node, Docker, ports, fichier `.env` présent — **sans en lire le contenu**, hors lecture de configuration par le lanceur lui-même) ;
2. Docker Desktop **accessible** — s'il est éteint, message clair, **le lanceur ne le lance pas** *(A11 recommandé)* ;
3. base : conteneur `tradingos-timescaledb` (nom exact), `healthy` (90 s) ; un autre conteneur sur 5433 bloque, comme aujourd'hui ;
4. schéma : `db migrate` (additif) ; **sauvegarde `pg_dump` avant toute migration en attente**, sinon rien ;
5. cœur : lancé **avec le dossier courant `04_code\python`** ; `GET /api/system/health` `ok`, base `up` (60 s) ;
6. cockpit : lancé s'il manque, réponse HTTP 200 sur 3000 (120 s, la compilation à la volée est lente) ;
7. préparation MT5 (§ 6 à 8) ;
8. lancement de MT5 **ou** redémarrage contrôlé confirmé ;
9. attente du `hello`, puis vérification (§ 10) ;
10. rapport final.

Règles : un composant déjà sain n'est ni relancé ni dupliqué (pas de second cœur, cockpit, PostgreSQL, worker ou agent pour le même compte). La base en échec empêche le cœur ; le cœur en échec empêche toute préparation MT5 qui suppose un cœur ; **MT5 en échec laisse le cœur et le cockpit en place**, signale `MT5_DISCONNECTED` et permet une nouvelle tentative ; un cockpit en échec ne bloque pas MT5. Tout échec écrit un diagnostic.

### 5. Arrêt propre

Ordre inverse des dépendances, **limité aux processus possédés** : cockpit → cœur → base. Le cœur reçoit d'abord une demande d'arrêt ordinaire (il termine ses workers, ADR 0037), puis, passé un délai, l'arbre du PID possédé est terminé. La base n'est arrêtée que si le lanceur l'a démarrée (ou sur `--include-database`). **MT5 et l'EA ne sont pas touchés** par défaut ; un arrêt du terminal est une option confirmée (§ 8). **L'arrêt de Trading OS n'est jamais une fermeture de positions** : aucune commande d'ordre n'est envoyée, jamais. Chaque étape est journalisée.

### 6. MT5 Terminal Manager (A5 pour le jeton)

- **Découverte** : registre Windows (désinstallation), raccourcis du menu Démarrer, dossiers connus (`C:\Program Files\MetaTrader 5*`), chemins déclarés par Exhorte, processus `terminal64.exe` en cours. **Aucune sélection automatique s'il y a plusieurs résultats.**
- **Registre** (`var/launcher/terminals.json`), une entrée par instance. L'identifiant d'instance est celui que MT5 donne à son dossier de données (le nom à 32 hexadécimaux, lié au chemin d'installation par `origin.txt`). Champs **observés**, jamais saisis : chemin d'installation, exécutable, dossier de données, mode portable ou non, version, courtier et serveur (lus par le cœur), login et devise (lus par l'EA), type de compte. Champs **déclarés** par Exhorte : le compte Trading OS associé, le symbole et la période du graphique de l'EA, le numéro magique, les symboles autorisés. L'écart entre observé et déclaré **bloque la préparation** et s'affiche, il ne se corrige pas tout seul.
- **Association explicite** compte Trading OS → instance de terminal → courtier, serveur et compte observés. Elle **resserre** : elle s'ajoute à l'identification de l'ADR 0036, ne la remplace pas ni ne l'assouplit. Elle se confronte à `Account.terminal_path` (le lien technique du cœur) ; une divergence bloque.
- **Jamais de changement automatique de compte.** Ni `/login`, ni `[Common] Login/Server/Password` ne sont écrits.
- **Multi-terminal** : chaque instance a son identifiant, son dossier, son état, son EA, son jeton, son compte, ses paramètres et ses journaux. Une installation = un dossier = un terminal (contrainte MetaQuotes). Un seul compte connecté à la fois reste vrai (ADR 0021). **Jeton** : le mécanisme actuel est conservé (fichier `MQL5\Files\tradingos_agent.token`, jamais une entrée), la même valeur est écrite pour **chaque terminal enregistré, même fermé** ; un jeton par instance est un ADR ultérieur du lien agent.

### 7. Déploiement de l'EA (A3, A4)

- **Compilation** : jamais automatique en production. Un script de compilation **sur une copie** (la procédure du runbook : MetaEditor, journal en UTF-16, `0 errors, 0 warnings`) écrit un **manifeste** (SHA-256 du `.ex5`, des sources et des `Include/`, version lue de `AGENT_VERSION`, version de MetaEditor, date). Le déploiement refuse un `.ex5` dont le manifeste ne concorde pas avec les sources.
- **Copie, jonction conservée** *(A4 recommandé)* : le seul `.ex5` est copié dans `MQL5\Experts\TradingOS\` (l'`Include/` ne sert qu'à la compilation). Copie atomique (fichier temporaire puis renommage), **vérification du hash après copie**, sauvegarde de l'ancienne version dans `var/launcher/backups/`, retour arrière en cas d'échec. La jonction existante `MQL5\Experts\TradingOsAgent` est **détectée, signalée et respectée** ; elle n'est pas supprimée sans accord.
- **Pas de remplacement sous un EA actif** : le déploiement exige l'EA détaché ou le terminal arrêté ; un fichier verrouillé est un échec explicite, pas un contournement.
- **Compatibilité** : le cœur compare `agentVersion`, `buildId`, `capabilities` et la version d'enveloppe à une **table de versions minimales versionnée** (donnée, avec sa date). Résultat hors table = `EA_PROTOCOL_INCOMPATIBLE`, état explicite, rien ne continue en silence. La table initiale exige seulement l'enveloppe `1` et un `agentVersion` non vide ; `dead_man` y figure comme **recommandé** (avertissement) en attendant la décision (5) du HANDOFF (refuser d'armer sans `dead_man`), que cet ADR ne tranche pas.
- **Agent 1.14, lecture seule** *(A3 recommandé, ADR séparé avant tout code)* : ajouter au hello des champs de télémétrie — version de protocole, symbole et période du graphique, identifiant d'instance du terminal, état d'initialisation. Le mode compilé `OBSERVE`, l'unique `OrderSend` et le test d'architecture ne changent pas. **Sans 1.14**, l'attachement au graphique attendu **ne se prouve pas** par l'EA : le rapport dit `CHART_UNVERIFIED` (avertissement) et n'invente rien.

### 8. Configuration de MT5 (R1 à R4)

- **Preset** `MQL5\Presets\TradingOS-<instance>.set`, généré **depuis les entrées lues dans le source** de l'agent ; un test échoue si une clé n'est pas une entrée déclarée. Valeurs : `InpCoreHost`/`InpCorePort` (réglages du cœur), `InpAccountId` (le login de l'association : l'agent refuse alors toute commande si le terminal change de compte), `InpMagicNumber` et `InpAllowedSymbolsCsv` (déclarés ; noms du courtier avec le suffixe du compte et le registre d'instruments), `InpMaxSpreadCsv` (plafonds de spread que l'utilisateur a écrits dans Settings ; absent = l'agent refuse tout ordre, échec fermé). **Le lanceur ne renseigne jamais `InpTradableLogins` ni `InpClosableLogins`** (vides = aucun ordre ne peut jamais partir). Il n'invente ni numéro magique ni plafond : une valeur déclarée manquante rend la préparation `PRESET_INCOMPLETE`. **Aucun jeton, aucun identifiant dans le `.set`** — règle de l'agent (« never an input ») qui prime sur l'idée de les y mettre.
- **Configuration de démarrage** : fichier `var/launcher/mt5/<instance>/startup.ini` contenant **uniquement** `[StartUp]` : `Expert=TradingOS\TradingOsAgent`, `Symbol`, `Period`, `ExpertParameters=<le .set>`. Symbole et période viennent de l'association déclarée (jamais `XAUUSD` par défaut : les noms sont ceux du courtier). **Jamais** `[Experts]`, `[Common]`, `Login`, `Password`. Ce qu'on ne sait pas : si `/config:` remplace ou complète `common.ini`. **Premier incrément MT5 = un essai contrôlé sur la démo** (voir « Validations »), avant toute construction qui en dépende ; **plan B** : pas de `/config`, un profil de graphiques préparé une fois par Exhorte, ou un attachement manuel documenté.
- **Permissions** : le lanceur **lit** (`Enabled`, `Account`, `Profile`, `AllowDllImport` dans `common.ini`, puis les quatre permissions du hello) et **n'écrit jamais**. Il n'active ni l'algo-trading, ni les permissions de trading. La permission affichée est celle que l'agent rapporte ; le fichier n'est qu'un indice avant le lancement.
- **WebRequest** : invérifiable par fichier (valeur codée) — le lanceur n'y touche pas. Détection par comportement : aucun `hello` dans le délai (90 s) **et** une erreur 4014 dans le journal des experts du jour (`MQL5\Logs\AAAAMMJJ.log`, UTF-16) ⇒ `MT5_WEBREQUEST_NOT_ALLOWED` avec la procédure (Outils → Options → Expert Advisors → URL autorisées → `127.0.0.1`). Sans trace dans le journal : `MT5_EA_NOT_REPORTING`, causes candidates listées.
- **Terminal déjà ouvert** (le cas actuel) : le lanceur **ne le tue pas, ne change pas son compte, n'attache pas un second EA, ne le redémarre pas sans confirmation**. Un redémarrage contrôlé est une opération explicite : (1) refus si le cœur voit des positions ou des ordres en attente, sauf accusé explicite ; (2) confirmation de l'utilisateur ; (3) demande de fermeture de la fenêtre principale (le terminal enregistre son profil), attente bornée, **jamais de kill** — s'il ne se ferme pas, le lanceur le dit et s'arrête ; (4) lancement avec `/config:`. Les positions restent chez le courtier pendant ce temps, avec leurs stops.
- **Ordre** : MT5 est préparé et lancé **avant** tout rattachement de compte, car `mt5.initialize` peut démarrer le terminal sans l'EA. Le lanceur ne rattache aucun compte ; « DÉMARRER LE SYSTÈME » reste le geste humain de l'ADR 0034.

### 9. États distincts

Trois énumérations **dérivées de faits observés**, jamais stockées comme vérité ; l'état d'un maillon ne dit rien du suivant.

| Famille | Valeurs |
|---|---|
| Terminal | `TERMINAL_STOPPED`, `TERMINAL_STARTING`, `TERMINAL_RUNNING`, `TERMINAL_CONNECTED` (connecté au courtier, lu par le cœur) |
| EA | `EA_NOT_DEPLOYED`, `EA_DEPLOYED`, `EA_NOT_REPORTING` (déployé, terminal en cours, aucun hello dans le délai), `EA_CONNECTED` (hello reçu, jeton accepté), `EA_DEGRADED` (identité en écart, heartbeat vieilli, avertissement), `EA_DISCONNECTED` (était connecté, plus de hello), `EA_PROTOCOL_INCOMPATIBLE` |
| Exécution | `EXECUTION_NOT_READY`, `EXECUTION_READY` (aucune autorisation), `EXECUTION_ARMED` et `EXECUTION_HALTED` (lus de l'échelle d'autonomie, jamais posés par le lanceur) |

`EA_ATTACHED` et `EA_INITIALIZING` ne sont **pas** observables séparément du hello tant que l'agent ne les annonce pas (agent 1.14) : le premier fait que l'EA produit est le hello. La présence du `.ex5` ne prouve jamais l'attachement.

### 10. Préparation d'exécution : `READY_NOT_ARMED`

Évaluation centralisée, **lecture** de `ReadinessReport` (16 contrôles + conditions de démarrage) et d'`AgentStatus`, sans second Risk Engine. Elle vit **dans le cœur** (modèles purs sous `domain/system/`, un service qui lit le collecteur de préparation et le registre d'agents), pas dans `launcher/` ; le lanceur la lit par HTTP. Elle couvre : base, cœur, API et lien agent (le « Gateway » .NET de la mission n'existe plus depuis l'ADR 0016), processus MT5, connexion au courtier, identité du compte, agent connecté, version compatible, heartbeat frais, jeton accepté, spécifications d'instruments complètes, limites chargées, aucun incident bloquant, permissions détectées. **Résultat** : `READY_NOT_ARMED` si tout est vert, agent connecté, compatible, identité `ok`, et mode ∈ {`OFF`, `OBSERVE`, `PAPER`, `CONFIRM`} ; jamais pour `ARMED`/`AUTONOMOUS` (affichés tels quels). Il fournit statut global, contrôles, **raisons de blocage**, avertissements, dernier succès, dernier échec, détails. **Échec fermé** : une information indispensable manquante ou périmée = bloqué avec le motif exact ; aucune valeur supposée, aucun ancien état réutilisé. La permission de trading est un contrôle **distinct** : « désactivée » ne devient jamais « prête ». Un EA tiers attaché au terminal rend le résultat bloqué *(A9 recommandé)*.

### 11. System Center dans le cockpit (A8)

Nouvelle page `/system`, dans le design « ExponentValue Monochrome » (ADR 0017), alimentée par `GET /api/system/center` (lecture ; types générés, jamais écrits à la main) : vue d'ensemble (base, cœur, API, lien agent, cockpit, MT5, agent), carte terminal, carte déploiement de l'EA (version installée et disponible, compatibilité, dernier déploiement), carte préparation d'exécution, événements récents. **Version 1 : les actions qui touchent des processus (démarrer, redémarrer MT5 ou le cœur, arrêter) sont des commandes du lanceur affichées et copiables**, pas des boutons : le cœur ne peut pas redémarrer le cœur, et ouvrir l'API aux processus élargirait une surface gardée par le seul jeton du cockpit. Une version 2 (geste humain confirmé qui lance la CLI détachée) demandera son propre ADR. Aucune action ne contourne le Risk Engine.

### 12. Observabilité

Événements JSONL structurés : horodatage UTC, composant, identifiant d'instance de terminal, identifiant de compte si connu, type, gravité, identifiant de corrélation, diagnostic. Types : `STARTUP_DATABASE_READY`, `STARTUP_CORE_READY`, `STARTUP_COCKPIT_READY`, `LAUNCHER_PORT_FOREIGN_PROCESS`, `MT5_TERMINAL_DISCOVERED`, `MT5_EA_DEPLOYED`, `MT5_PRESET_WRITTEN`, `MT5_TERMINAL_STARTED`, `MT5_RESTART_REQUESTED`, `MT5_EA_CONNECTED`, `MT5_ACCOUNT_MISMATCH`, `MT5_PROTOCOL_INCOMPATIBLE`, `MT5_WEBREQUEST_NOT_ALLOWED`, `MT5_EA_NOT_REPORTING`, `MT5_HEARTBEAT_TIMEOUT`, `EXECUTION_READINESS_BLOCKED`. Le masquage des secrets du cœur (`shared/logging/redaction`) s'applique ; **aucun secret** dans un événement, un `.set`, un `.ini` ni un fichier temporaire. Le lanceur lit ses réglages par la configuration du cœur (les secrets sont enregistrés pour le masquage) ; Claude ne lit jamais `.env`. La persistance en base des événements du lanceur est reportée (le lanceur tourne avant elle).

### 13. Gestion des erreurs

Chaque échec nomme son composant, sa cause probable et ce qui reste en place ; rien n'est retenté en boucle silencieuse ; une nouvelle tentative est un geste. Un échec de déploiement restaure la version sauvegardée. Un état inconnu est traité comme bloquant.

## Choix retenus (acceptés le 2026-11-06)

Exhorte a accepté l'ADR avec les valeurs de la colonne « Posé ici ». **A10** agit sur l'environnement (le venv) : son accord est redemandé au moment de l'exécuter. Les autres se changent par un ADR suivant.

| # | Choix | Posé ici | Alternative |
|---|---|---|---|
| A1 | logique du lanceur | Python + enveloppe PowerShell | PowerShell pur |
| A2 | identification des processus | CIM / `Get-NetTCPConnection` | `psutil` |
| A3 | agent 1.14 (télémétrie en lecture) | oui, ADR séparé | non, attachement inféré |
| A4 | installation de l'EA | copie + manifeste, jonction conservée | jonction seule |
| A5 | jeton | un jeton, écrit pour chaque terminal enregistré | un jeton par instance maintenant |
| A6 | fenêtres | masquées + journaux de fichier | visibles |
| A7 | cockpit | `next dev` | `next build` + `next start` |
| A8 | actions de System Center | commandes affichées | spawn confirmé par le cœur |
| A9 | EA tiers attaché | résultat bloqué | simple avertissement |
| A10 | installation éditable du venv | `pip install -e` depuis le dépôt actuel, **avec accord** | contournement par le dossier courant |
| A11 | Docker Desktop éteint | message, pas de lancement | le lancer |

**Valeurs posées par Claude, à relire** : délais (base 90 s, cœur 60 s, cockpit 120 s, `hello` 90 s, fermeture contrôlée de MT5 à définir), rotation des journaux, table de versions minimales de l'agent, refus de redémarrer un terminal qui a des positions ou des ordres en attente sauf accusé.

## Limites connues

- Rien de MT5 n'est vérifié sur ce poste : `/config` (R1), WebRequest (R2), lancement par le worker (R3), terminal déjà ouvert (R4), verrou du `.ex5` (R6), encodage et emplacement du `.set`. L'ADR 0035 s'applique : un fait est « vérifié » quand le terminal l'a montré, sinon « non vérifié sur le live ».
- Sans agent 1.14, ni le graphique ni l'instance ne sont prouvés par l'EA.
- Un seul jeton pour tous les terminaux jusqu'à un ADR du lien agent.
- Les actions de processus du cockpit sont absentes de la version 1.
- La causalité des coupures du cœur (validation 3 de l'ADR 0037) et le délai du job `supervisor` restent ouverts ; le lanceur n'en fait pas une hypothèse.
- Les tests automatiques n'utilisent aucun vrai MT5 ni ne tuent de vrai processus.

## Tests

Tout effet extérieur passe par un port avec un faux ; les tests échouent d'abord. Familles : lanceur (rien de lancé, tout lancé, base ou cœur ou cockpit indisponible, port étranger, lancement répété, arrêt propre, PID réutilisé, échec partiel), gestionnaire de terminaux (aucun, un, plusieurs, déjà lancé, dossier inaccessible, compte ou serveur incorrect, déconnecté, installation invalide), déploiement (absent, à jour, obsolète, hash faux, manifeste absent, preset invalide, protocole incompatible, interruption, retour arrière, jonction), attachement (hello correct, mauvais compte, WebRequest refusé, cœur absent, jeton invalide, heartbeat interrompu, reconnexion), préparation (chaque contrôle rouge, donnée manquante = bloqué, jamais prêt sous `ARMED`/`AUTONOMOUS`). **Tests d'architecture** : aucune écriture de `[Experts]`, `[Common]`, `Login`, `Password` ; `InpTradableLogins`/`InpClosableLogins` jamais renseignés ; aucun secret dans les événements, `.set` et `.ini` ; un seul `OrderSend` dans le dépôt ; `launcher/` n'importe ni exécution, ni risque, ni Guardian, ni positions ; aucun arrêt de processus hors registre. Non-régression : `pytest`, `vitest`, `ruff`, `mypy`, `gen-types --check`, `tsc`, `eslint`, `next build` **hors** `next dev`.

## Stratégie de migration

1. `start.ps1` **reste intact et fonctionnel** pendant tout le développement ; le lanceur reconnaît (adopte en lecture seule) ce qu'il a lancé.
2. Incréments (un ADR avant chaque code, ici ou dans un ADR fils) : I1 plan pur, ports, registre de processus, événements ; I2 démarrage et arrêt de base, cœur, cockpit ; I3 découverte et registre MT5 ; I4 script de compilation sur copie, manifeste, déploiement ; I5 preset et ini, **essai R1 sur la démo (accord requis)** ; I6 lancement ou redémarrage contrôlé, vérification de l'attachement, états ; I7 préparation d'exécution ; I8 `GET /api/system/center` et System Center ; I9 agent 1.14 si A3 ; I10 validation sur la démo, documentation (runbooks de démarrage, d'arrêt, de dépannage ; guides d'installation de l'EA, de configuration MT5, de gestion multi-terminal ; System Center), HANDOFF, `state.md`, `session-log.md`.
3. Après validation, `start.ps1` devient un renvoi vers `TradingOS-Start.ps1` ; il n'est supprimé qu'à la demande d'Exhorte.
4. Aucun changement de schéma de base. Aucune donnée existante n'est modifiée. La jonction `MQL5\Experts\TradingOsAgent`, `ea1.set` et `.env` ne sont ni touchés ni réutilisés.
5. L'installation éditable du venv (A10) est une action sur l'environnement, faite avec l'accord d'Exhorte, indépendante du reste.

## Ce que cet ADR ne fait pas

- Il **ne relève aucun mode**, n'arme rien, ne rend rien `AUTONOMOUS`. La condition d'Exhorte (pas d'`armed` ni d'`autonomous` avant les validations 1 et 2 de l'ADR 0037) est remplie ; relever un mode reste **sa** décision.
- Il **ne touche** ni au Risk Engine, ni au Guardian, ni au Position Manager, ni au chemin d'exécution, ni à l'unique `OrderSend`, ni au mode compilé `OBSERVE` de l'agent. L'agent 1.14 (A3) est un ADR séparé, en lecture seule.
- Il **ne rattache aucun compte**, ne change aucun compte, n'écrit aucun mot de passe (ADR 0013), n'active ni l'algo-trading ni une permission de trading.
- Il **ne duplique pas** l'ADR 0036 (il ajoute une contrainte d'association qui ne fait que resserrer, et n'assouplit aucune identification) ni l'ADR 0037 (le lanceur ne lance ni ne tue de workers ; il lit `mt5Workers`).
- Il **ne tranche pas** la décision (5) du HANDOFF (refuser d'armer sans `dead_man`), ni le délai du `supervisor`, ni la validation 3 de l'ADR 0037.
- Il **ne décide pas** du sort de l'EA tiers installé dans le terminal ; il le signale.

## Validations (distinctes)

1. **En simulation** : tests du lanceur, du gestionnaire de terminaux, du déploiement, de l'attachement et de la préparation avec des faux. Ne prouve rien chez MT5.
2. **Sur le poste, hors MT5** : démarrage, arrêt, relance répétée de la base, du cœur et du cockpit réels ; aucun doublon, aucun processus étranger touché. Un redémarrage du cœur réel demande l'accord d'Exhorte.
3. **Sur la démo Exness, par étapes, avec son accord** : (a) essai R1 (`/config` avec un ini minimal : la liste WebRequest et `Enabled` sont-ils conservés ?) ; (b) déploiement et preset ; (c) redémarrage contrôlé ; (d) attachement, identité, heartbeat ; (e) plusieurs démarrages, `mt5Workers.alive` conforme, aucun worker orphelin. Toujours `OBSERVE`, lecture seule, aucun ordre.

## Avancement

- **I1 — construit le 2026-11-06, lecture seule** : paquet `trading_os/launcher/` (modèles, ports, registre de processus, événements, plan pur, observateur, adaptateurs Windows en lecture seule, rapports, `python -m trading_os launcher plan|status`). Tests écrits avant le code (rouges, puis verts) ; **pytest complet : 3 058 passés, 15 ignorés** (2 920 + 138 nouveaux), `ruff`, `mypy`, `gen-types --check` propres ; deux règles cassées exprès (pid recyclé tenu pour le nôtre, composant étranger « gardé ») sont bien détectées. **Vérifié sur le poste réel, en lecture seule** : `status` et `plan` classent la base (conteneur reconnu), le cœur (pid reconnu, ports 8000 et 9765) et le cockpit (pid reconnu, HTTP 200), proposent « rien à faire » et n'écrivent rien (`var/` n'existe pas après les deux commandes). **Non vérifié** : tout ce qui touche MT5 (aucun code MT5 dans cet incrément) ; un processus **possédé** par le lanceur (il n'en a pas encore lancé) ; un port réellement tenu par un processus étranger sur ce poste (cas couvert par les tests seulement).
- **I2 — construit le 2026-11-06 (non commité)** : `launcher start | stop [--dry-run] [--include-database] | adopt`, verrou (`lock.py`), registre étendu aux conteneurs, `starter.py`, `stopper.py`, `adopt.py`, `actions.py` (lancement détaché, actions Docker, sauvegarde `pg_dump` + `docker cp`), `process_control.py` (**le seul module qui termine un processus**, imposé par un test d'architecture ; seul `stopper.py` lui passe un pid). Tests écrits avant le code ; monde simulé (`tests/unit/launcher/world.py`) ; quatre tests sur de **vrais processus factices** (arrêt poli, voisin épargné, arbre entier, non-chef de groupe) ; deux règles cassées exprès (pid recyclé tenu pour le nôtre, verrou périmé tenu pour vivant) détectées ; suite complète : 3 146 passés, 15 ignorés (2 920 + 226 tests du lanceur), puis 3 tests ajoutés : 229 tests ciblés du lanceur verts. **Mesuré** : la demande d'arrêt polie est un **Ctrl+Break envoyé au groupe du processus** (le cœur est lancé chef de son groupe ; uvicorn 0.54 le traite en arrêt ordonné) — Ctrl+C peut être désactivé et l'état se transmet, et un Ctrl+Break envoyé à toute la console tuait l'aide de son propre signal. Un processus **adopté** n'est pas chef de groupe : Windows refuse la demande polie, son arrêt est **forcé** et le rapport le dit. **Sur le poste réel** : `plan` et `stop --dry-run` lus ; un `start` réel sur l'application déjà en place n'a rien changé (une fois, la base a été signalée « Docker ne répond pas » à tort — `docker info` avait manqué son délai pendant qu'une suite de tests saturait le poste : échec fermé, rien fait ; corrigé par deux tentatives). **Non vérifié** : démarrage réel du cœur et du cockpit par le lanceur ; arrêt réel d'un processus qu'il possède ; arrêt poli du vrai cœur ; sauvegarde réelle `pg_dump` + `docker cp` ; `docker compose up` réel — tout cela demande d'arrêter l'application d'Exhorte (son accord).
- **Premier arrêt réel, le 2026-11-08, à la demande d'Exhorte** (`adopt cockpit`, `adopt core`, `stop --dry-run --include-database`, `stop --include-database`) : cockpit arrêté de force (arbre du processus), **cœur arrêté par la demande polie — il s'est terminé de lui-même bien qu'adopté**, base arrêtée (`docker stop`, code 0, données dans le volume). Ports libres, aucun worker ni processus du projet, `dossier-db-1` et MetaTrader 5 intacts, registre revenu vide, journal des événements écrit. **Corrige l'avancement de l'I2** : un processus adopté n'est pas toujours arrêté de force (le cœur ne l'a pas été) ; l'arrêt poli est tenté d'abord et le rapport dit s'il a fallu forcer. **Reste non éprouvé** : le démarrage réel du cœur et du cockpit par le lanceur, la sauvegarde `pg_dump` + `docker cp` réelle, `docker compose up`.
- Constat annexe, dans la logique de l'audit (D2) : lancé hors de `04_code\python`, `python -m trading_os` ne s'importe pas (installation éditable vers `C:\Dev\…`) ; les tests passent parce que `pytest` est lancé depuis `python\`. A10 reste à accorder.

## Conséquences

- Un point d'entrée unique et un arrêt propre, avec des composants reconnus plutôt que devinés.
- L'état « prêt non armé » devient une lecture honnête de ce que le cœur sait déjà, avec ses raisons de blocage, sans second contrôle de risque.
- Le déploiement de l'EA devient traçable (manifeste, hash, retour arrière) au lieu de dépendre d'une compilation manuelle sans lien avec ses sources.
- Coût : un paquet Python de plus à maintenir, un dossier `var/` ignoré par Git, des essais sur la démo qui demandent la présence d'Exhorte, et — sans l'agent 1.14 — une vérification d'attachement moins forte que celle que la mission demande.
- Risque résiduel principal : `/config` (R1). Tant qu'il n'est pas levé sur la démo, la partie « attachement automatique » de la mission reste une hypothèse, et le plan B (profil préparé une fois, attachement documenté) est le repli.
