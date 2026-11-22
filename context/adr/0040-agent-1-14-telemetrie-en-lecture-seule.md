# ADR 0040 — Agent 1.14 : télémétrie en lecture seule (graphique, instance, protocole, protections locales)

Date : 2026-11-07. Statut : **accepté le 2026-11-07** par Exhorte (« Oui, accepter ») — décision C7 du même jour (« Oui, valider » : accord pour **écrire** cet ADR). **Accepter l'ADR n'autorise pas à construire l'agent : la construction (code MQL5, compilation, déploiement, premier attachement) demande son accord explicite, au moment de la faire. Écrire l'ADR n'est pas construire l'agent** : aucune ligne de MQL5 ni de Python n'est modifiée par ce document, et la construction demande son accord explicite au moment de la faire. Prévu par l'ADR 0038 (A3, incrément I9) et par l'ADR 0039 (§ 5, § 7). **Ne touche ni au mode compilé `OBSERVE`, ni à l'unique `OrderSend`, ni à `ExecuteOrder`, ni à aucune entrée de l'agent, ni au Risk Engine.** N'amende aucun ADR.

## Contexte

L'audit du 2026-11-07 (`docs/architecture/MT5_DEPLOYMENT_AUDIT.md`, § 7 C7) établit ce que l'agent 1.13 ne dit pas dans son `agent.hello` :

- **le graphique** : `hello.symbol` vaut `FirstAllowedSymbol()` (le premier symbole de la liste blanche), **pas** `_Symbol` ; la période n'est dite nulle part. « L'EA est attaché au graphique attendu » ne se prouve donc pas par l'EA ;
- **l'instance de terminal** : rien ne relie un `hello` au dossier de données qui l'a produit (le registre de l'ADR 0039 en a besoin pour ne pas mélanger deux terminaux) ;
- **la version du protocole** : seulement l'enveloppe `"version":1`, `agentVersion` et `buildId` ;
- **les protections locales** : les plafonds de volume, de positions, de spread, de glissement, la liste blanche complète (le `hello` n'en porte qu'un symbole) et les délais *effectifs* (après écrêtage, par exemple `InpDeadManSeconds` lu 30 s s'il est hors de 5..600) ne sont pas rapportés. Le cœur ne peut pas dire « paramètres conformes au preset » ni « protections actives ».

Sans cela, la préparation (ADR 0039 § 5) reste honnête mais faible : `CHART_UNVERIFIED`, `PARAMETERS_UNREPORTED`, `PROTECTIONS_UNREPORTED` en avertissements.

Faits utiles : le modèle `WireMessage` du cœur est `extra="ignore"` et tous les champs « agent d'exécution » de `AgentHello` sont optionnels (`wire.py:40`, `:68`) ; le lien lit des lignes de 1 MiB au plus (`ea_link.py:43`) ; l'agent refuse de s'initialiser (`INIT_FAILED`) seulement si le numéro magique est invalide, et reste chargé en refusant toute commande si l'identité diverge (`TradingOsAgent.mq5:29`, `:152`).

## Décision

### 1. Champs ajoutés (tous optionnels, tous en lecture)

Ajoutés à `agent.hello`, et rapportés de nouveau à chaque `hello` (donc après tout redémarrage de l'EA ou changement de graphique) :

| Champ | Contenu | Source dans l'agent |
|---|---|---|
| `protocolVersion` | entier ; **1** = le jeu de messages des ADR 0010, 0029 et 0033 ; il n'augmente que pour un changement **incompatible** | constante |
| `chart` | `{ "symbol": …, "period": … }` du graphique sur lequel l'EA tourne ; `period` en libellé MT5 (`"M5"`) | `_Symbol`, `_Period` |
| `instanceId` | dernier segment du dossier de données du terminal (le nom à 32 hexadécimaux) ; **jamais le chemin complet** (il contient le nom d'utilisateur Windows) | `TERMINAL_DATA_PATH` |
| `terminalBuild` | numéro de build du terminal | `TERMINAL_BUILD` |
| `initState` | `READY` ou `DEGRADED` ; `DEGRADED` est accompagné de `initIssues` (codes, par exemple `SYMBOL_NOT_AVAILABLE:XAUUSDm`) | `OnInit` |
| `localProtections` | écho des valeurs **effectives** chargées : `maxVolumePerOrder`, `maxOpenPositions`, `maxSlippagePoints`, `maxSpread` (carte symbole → plafond), `allowedSymbols` (liste complète), `deadManSeconds`, `pendingMaxMinutes` | entrées, après écrêtage |

`agent.heartbeat` n'ajoute rien : le graphique et l'instance ne changent pas sans un nouveau `hello` (réinitialisation de l'EA).

**Jamais rapportés** : le jeton, tout mot de passe, tout identifiant autre que ceux déjà présents, le numéro magique (déjà dérivé dans `agentId`), les listes `InpTradableLogins` / `InpClosableLogins` (le `hello` porte déjà `tradable` / `closable`).

### 2. Ce qui ne change pas (invariants)

- `g_mode` et `g_mode_ceiling` restent des constantes de compilation à `MODE_OBSERVE`.
- Un seul `OrderSend` dans le dépôt, dans `ExecuteOrder`, derrière le contrôle de mode qui en est la première instruction.
- **Aucune entrée n'est ajoutée ni retirée** ; le preset de l'ADR 0039 ne gagne aucune clé.
- Aucune nouvelle commande, aucun nouveau chemin d'ordre, aucun changement du magasin de commandes ni de la réconciliation.
- Le test d'architecture `tests/architecture/test_execution_agent.py` passe **sans modification de ses assertions** ; une assertion est *ajoutée* : le constructeur du `hello` n'émet que les champs de la table du § 1 et le champ `token` existant.

### 3. Côté cœur

- `AgentHello` gagne les champs du § 1, tous optionnels (un 1.13 qui ne les envoie pas donne `None`) ; `AgentStatus` les expose en lecture ; les schémas OpenAPI et `lib/api/generated.ts` sont régénérés par `gen-types` (jamais à la main).
- **Aucun refus nouveau à la connexion** : un `hello` sans ces champs reste accepté (compatible avec un 1.13).
- Les comparaisons se font dans la préparation de l'ADR 0039, en **lecture** : `chart` contre le registre (`CHART_MISMATCH`), `allowedSymbols` contre le registre (`ALLOWED_SYMBOLS_MISMATCH`), `localProtections` contre le preset généré (`PROTECTION_MISMATCH`), `instanceId` contre le terminal enregistré (`MT5_INSTANCE_MISMATCH`), `initState == DEGRADED` (`EA_INIT_DEGRADED`). Chacune est un **motif de blocage** de `EA_READY`, jamais une action.
- Un champ non rapporté reste un **avertissement** (`CHART_UNVERIFIED`, `PARAMETERS_UNREPORTED`, `PROTECTIONS_UNREPORTED`), jamais rempli par une valeur supposée.

### 4. Version et diffusion

- `AGENT_VERSION` passe à `1.14` ; `capabilities` est inchangé (rien de nouveau n'est exécutable) ; la table de versions de l'ADR 0039 (§ 7) accepte `1.13` en `COMPATIBLE_WITH_WARNINGS` et `1.14` en `COMPATIBLE`.
- Compilation **sur une copie** (procédure du runbook : MetaEditor, journal UTF-16, `0 errors, 0 warnings`), avec manifeste (ADR 0038 § 7). `*.ex5` reste ignoré par Git.
- Déploiement par le gestionnaire de l'ADR 0039, EA détaché. **Le premier attachement à un graphique reste un geste d'Exhorte.** Aucune compilation ni aucun déploiement n'est fait sans son accord.
- Retour arrière : le `.ex5` 1.13 sauvegardé reste valide ; rien ne dépend du 1.14 pour fonctionner.

## Non vérifié (à confirmer à la construction)

- Les noms et le comportement exacts des fonctions MQL5 (`TERMINAL_DATA_PATH`, `TERMINAL_BUILD`, conversion de `_Period` en libellé) : à confirmer à la compilation sur copie, pas supposés ici.
- Le dernier segment de `TERMINAL_DATA_PATH` d'un terminal **portable** n'est pas un identifiant à 32 hexadécimaux ; la règle d'identifiant du registre (ADR 0039 § 4, point 1) doit en tenir compte.
- Qu'un changement de période du graphique réinitialise bien l'EA et provoque un nouveau `hello` : comportement attendu de MetaTrader, **à éprouver sur la démo**.
- Taille du `hello` enrichi : très en deçà de 1 MiB, mais à mesurer.
- Rien n'est « vérifié » tant que le terminal n'a pas montré les champs dans `GET /api/agents` (ADR 0035).

## Tests

Écrits avant le code. **Python** : un faux agent envoie un `hello` 1.14 complet, un 1.13 sans les champs, un 1.14 `DEGRADED`, un `chart` divergent du registre ; chaque cas donne le bon motif ou le bon avertissement ; `extra="ignore"` n'est pas relâché ; aucun champ secret n'apparaît dans `AgentStatus` ni dans l'API. **MQL5** (test structurel, comme `test_execution_agent.py`) : constructeur du `hello` limité aux champs de la table, aucun `OrderSend` supplémentaire, `g_mode` toujours `const … = MODE_OBSERVE`. **Compilation** sur copie : 0 erreur, 0 avertissement. **Réel** (par Exhorte, sur la démo, `OBSERVE`) : attacher l'agent à un graphique, lire `chart`, `instanceId`, `localProtections` dans l'API, changer la période et voir le nouveau `hello`.

## Ce que cet ADR ne fait pas

- Il **n'autorise** ni un ordre, ni un mode, ni une permission ; il n'ajoute aucune commande ni aucun chemin d'exécution ; il ne change aucune entrée ni le preset.
- Il **ne construit rien** et n'attache rien : le code, la compilation, le déploiement et le premier attachement attendent l'accord d'Exhorte.
- Il **ne règle pas** l'identité du produit (C6, tranché dans l'ADR 0039 § 9 : l'agent ne rapporte aucun produit), ni la décision (5) du HANDOFF (refuser d'armer sans `dead_man`).

## Avancement

- **Construit le 2026-11-12, sur la consigne d'Exhorte (« lance les étapes suivantes jusqu'à I10, sans me demander de valider quoi que ce soit »)** — accord pris comme l'accord de construire, de compiler et de déployer ; **le premier attachement n'a pas eu lieu**.
- **MQL5** (`tools/mt5-execution-agent/TradingOsAgent.mq5`) : `AGENT_VERSION` et `#property version` à `1.14`, `PROTOCOL_VERSION 1`, sept champs ajoutés au `hello` (`protocolVersion`, `chart`, `instanceId`, `terminalBuild`, `initState`, `initIssues`, `localProtections`) par des fonctions qui ne font que lire (`PeriodLabel`, `InstanceId`, `ResolveInitState`, `InitIssuesJson`, `AllowedSymbolsJson`, `MaxSpreadJson`, `LocalProtectionsJson`). Aucune entrée ajoutée ni retirée, `g_mode` et `g_mode_ceiling` toujours des constantes à `MODE_OBSERVE`, un seul `OrderSend`. Une initialisation `DEGRADED` (symbole absent chez le courtier, liste vide) est rapportée et **ne décharge jamais** l'agent.
- **Compilation** sur une copie par `launcher mt5 build` avec le MetaEditor réel (5.0.0.6230) : **0 erreur, 0 avertissement**, `.ex5` de 156 458 octets, manifeste dans `var/launcher/mt5/builds/1.14-78149c2b/`. Les fonctions définies plus bas dans le fichier (`DeadManSeconds`, `PendingMaxMinutes`) sont appelées avant leur définition sans problème.
- **Cœur** : `AgentHello`, `AgentStatus` et `build_status` portent les champs, tous optionnels (un 1.13 est accepté comme avant, `extra="ignore"` n'est pas relâché) ; `shared/ea_readiness.py` en tire `CHART_MISMATCH`, `PARAMETERS_MISMATCH`, `EA_INIT_DEGRADED`, `MT5_INSTANCE_MISMATCH` (rouges) et lève les avertissements `CHART_UNVERIFIED`, `PARAMETERS_UNREPORTED`, `PROTOCOL_VERSION_UNREPORTED` quand l'agent les rapporte ; `shared/agent_compat.py` accepte 1.13 avec avertissement et 1.14 sans. Types TypeScript régénérés (`gen-types`).
- **Tests** : `tests/architecture/test_agent_telemetry.py` (6 tests : version, champs du `hello` = anciens + table du § 1, aucun secret ni numéro magique ni liste de logins, aucune fonction de télémétrie ne peut passer ni changer d'ordre, aucune entrée ajoutée, initialisation dégradée non fatale) et les 36 tests de `test_execution_agent.py` **sans modification de leurs assertions** ; `tests/unit/infrastructure/test_agent_hello_telemetry.py` (7 tests : 1.13 sans champs, 1.14 complet, dégradé, partiel, clés inconnues ignorées, aucun champ secret, un `instanceId` n'est pas un chemin).
- **Déploiement réel (2026-11-12)** : le `.ex5` 1.14 a été déployé par `launcher mt5 deploy` dans le terminal d'Exhorte **à travers la jonction existante** (il remplace le `.ex5` 1.13 du 2026-11-03, sauvegardé dans `var/launcher/backups/D0E8209F…/`). **Non attaché à un graphique ; aucun `hello` 1.14 n'a encore été vu par le cœur.**
- **Non vérifié** (ADR 0035 : rien n'est « vérifié » tant que le terminal n'a pas montré les champs dans l'API) : les fonctions MQL5 `TERMINAL_DATA_PATH`, `TERMINAL_BUILD` et la conversion de `_Period` ont été **compilées** mais pas **exécutées** ; le changement de période qui réinitialise l'EA et provoque un nouveau `hello` ; la taille réelle du `hello` ; le dernier segment du dossier de données d'un terminal portable.

## Conséquences

- « L'EA est attaché au graphique attendu », « les paramètres sont conformes » et « les protections locales sont celles du preset » deviennent des **observations de l'EA**, pas des inférences, et `EA_READY` peut le dire.
- Le registre multi-terminaux de l'ADR 0039 peut vérifier qu'un `hello` vient bien du terminal enregistré.
- Coût : un build de plus à compiler, déployer et attacher (gestes d'Exhorte) ; un 1.13 déjà attaché continue de fonctionner avec des avertissements jusqu'à la mise à jour.
