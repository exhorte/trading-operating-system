# ADR 0041 — Retirer le mode PAPER et l'issue SIMULATED ; OBSERVE reste l'état « aucun ordre »

Date : 2026-11-13. Statut : **accepté** — demandé par Exhorte le 2026-11-13 (« supprimer complètement le mode OBSERVE et tout système de simulation de l'application »), puis **périmètre précisé par lui** à la question posée : « **Retirer PAPER et SIMULATED, garder OBSERVE** » (les deux autres options proposées — tout retirer, OBSERVE compris ; ne rien retirer — ont été écartées). **Ne touche ni au mode compilé `OBSERVE` de l'agent, ni à l'unique `OrderSend`, ni au Risk Engine, ni au Guardian, ni aux limites : aucun chemin d'exécution n'est ouvert.** Amende l'ADR 0015 (échelle des modes), l'ADR 0027 (critères de passage) et l'ADR 0034 (cibles de « Démarrer le système »).

## Contexte

Le dépôt connaît deux sortes de simulation d'ordre :

- le mode **PAPER** (barreau de l'échelle `OFF → OBSERVE → PAPER → CONFIRM → ARMED → AUTONOMOUS`) : un remplissage simulé au prix courant, en processus, jamais chez MetaTrader (`PaperSender`, `ExecutionRoute.PAPER`) ;
- l'issue **SIMULATED** d'une commande : validée de bout en bout puis enregistrée comme « simulée », soit localement (OFF, OBSERVE, PAPER : rien ne part), soit par un agent compilé `OBSERVE` qui répond `SIMULATED`.

Exhorte ne veut plus d'exécution simulée : **un ordre part pour de vrai, ou il est refusé**. Il garde `OBSERVE` comme état « aucun ordre » de repli et de diagnostic (ADR 0035) : c'est le verrou qui rend l'unique `OrderSend` inatteignable, et il n'est pas retiré.

Faits mesurés (2026-11-13, vraie base) : 0 commande, 0 événement contenant PAPER ou SIMULATED — rien à migrer. Aucun ordre n'a jamais été envoyé.

## Décision

Deux incréments, tests d'abord, chacun laissant les gates vertes.

### Incrément 1 — PAPER

- L'échelle devient `OFF → OBSERVE → CONFIRM → ARMED → AUTONOMOUS` (+ `HALTED`). `AutonomyMode.PAPER`, `ExecutionRoute.PAPER`, `PaperSender`, `PlanMode.PAPER` et la cible `PAPER` de « Démarrer le système » disparaissent ; le démarrage monte à `OBSERVE` ou `CONFIRM` au plus, jamais plus haut.
- Les critères de passage (ADR 0027) perdent le barreau PAPER : `OBSERVE → CONFIRM` porte les critères des deux anciens passages qui ne parlaient pas d'ordres simulés ; le critère « N ordres simulés » est retiré, non remplacé par une valeur supposée.
- Un mode `PAPER` lu dans une configuration ancienne est **refusé avec un message qui dit quoi faire** (jamais accepté en silence, jamais traduit en autre mode).
- Cockpit : plus de libellé PAPER ; types régénérés.

### Incrément 2 — SIMULATED

- `CommandState.SIMULATED`, les événements `SIMULATED_LOCALLY` et `REPORT_SIMULATED`, `CloseAllItemStatus.SIMULATED`, la mesure « simulées » de `live_metrics`, le statut `SIMULATED` du protocole fil sont retirés.
- Une intention en `OFF`, `OBSERVE` ou `HALTED` **n'est plus enregistrée comme simulée** : elle est refusée avec le code `MODE_NOT_PERMITTING` (déjà en place, réutilisé : « le mode ne permet aucun ordre » ; le nom `MODE_NO_ORDERS` envisagé au départ n'est pas créé), enregistrée comme **refusée** (jamais `PENDING`, jamais « faite »). La décision du Risk Engine et l'évaluation de la stratégie restent enregistrées comme aujourd'hui (c'est ce que montre « Pourquoi pas de trade ? »).
- L'agent compilé `OBSERVE` répond désormais par un **refus typé** (`AGENT_OBSERVE`) au lieu de `SIMULATED` : agent **1.15**, compilé sur copie, mode compilé et unique `OrderSend` inchangés. Le refus vient **après** la validation locale et **avant** l'acquittement (acquittement `REJECTED`, raison `AGENT_OBSERVE: … order NOT sent`).
- « FERMER TOUTES LES POSITIONS » : un agent compilé `OBSERVE` produit un refus par position (`AGENT_OBSERVE`), et le rapport dit que rien n'a été fermé — plus de « simulé » ; l'action « agent » (`ENABLE_AGENT`) est proposée dès qu'un refus porte ce code.
- **Compatibilité d'un agent avant 1.15** (le 1.14 déployé répond encore `ACCEPTED` puis `SIMULATED`) : le fil (`wire.py`, `ExecutionReport`) lit ce rapport comme ce qu'il est — un `FAILED` codé `AGENT_OBSERVE` avec « order NOT sent » (refus définitif, jamais `UNKNOWN`, jamais un remplissage). Sans cela le rapport serait silencieusement ignoré et la commande resterait `ACKNOWLEDGED`. Cette lecture s'enlève quand tous les agents sont en 1.15.
- Les durées des commandes (`live_metrics`) ne comptent plus que les commandes **envoyées** (`sent_at`) : un refus à la porte n'a pas de réponse du courtier à chronométrer.

## Ce qui ne change pas

- `OBSERVE` (état, constante compilée de l'agent, `g_mode` et `g_mode_ceiling`), l'unique `OrderSend`, `ExecuteOrder` et son contrôle de mode en première instruction ; le Risk Engine, le Guardian, le Position Manager, les limites, `HALTED` et les sorties humaines (ADR 0033).
- Les **faux terminaux des tests** (`FakeMt5`, le terminal de démonstration `MT5_ENABLED=false` et `start.ps1 -Simulated`) et le **banc de validation** (`validate`, ADR 0026) : ce ne sont pas des exécutions d'ordres ; la suite et le banc en dépendent. Leur retrait demanderait un ADR à part.
- Claude ne déclenche aucun ordre, armement ou mode.

## Tests

Écrits avant le code : l'échelle n'a plus de PAPER (énumération, échelle, route, plan, cibles de démarrage, API) ; aucun module ne définit de remplissage simulé ; l'API refuse `PAPER` comme cible ; un mode `PAPER` ancien est refusé avec un message ; en incrément 2, une intention en `OFF`, `OBSERVE` ou `HALTED` est refusée avec `MODE_NOT_PERMITTING` et aucune commande n'est envoyée, aucun état `SIMULATED` n'existe (`test_no_simulated_outcome.py`), l'agent 1.15 n'a plus de réponse `SIMULATED`, plus de `MODE_PAPER`, refuse avec `AGENT_OBSERVE` avant d'acquitter et documente ce refus (`test_agent_no_simulation.py`, source MQL5), et un agent 1.14 qui dit encore `SIMULATED` est lu comme un refus définitif.

## Conséquences

- Une seule façon pour un ordre d'exister : il part chez le courtier, ou il est refusé avec un code. Plus de chiffre « simulé » qui ressemble à une preuve.
- Perte assumée : la répétition d'ordres en PAPER et le rejeu « validé de bout en bout, rien n'est parti » (utiles pour mesurer sans risque) ; la mesure sans risque passe par `OBSERVE` (évaluations enregistrées), le banc de validation et le script `TradingOsRequestCheck` (`OrderCheck` seulement, démo seulement).
- Coût : un refactor large (cœur, agent, cockpit, ~35 fichiers de tests) ; l'agent 1.15 est un build de plus à compiler, déployer et attacher (gestes d'Exhorte).

## Avancement

**2026-11-13 — incréments 1 et 2 construits, non commités** (avec le reste du lanceur : décision C10 d'Exhorte).

- **Incrément 1 (PAPER)** : fait — énumérations, route, `PaperSender`, `PlanMode`, cibles de démarrage, critères de passage, `TRADING_MODE=PAPER` refusé avec message, cockpit, types.
- **Incrément 2 (SIMULATED)** : fait — état, événements, statut de fermeture globale, compteur de mesures, statut du fil ; refus `MODE_NOT_PERMITTING` à la porte du cœur ; agent **1.15** (`AGENT_OBSERVE` avant l'acquittement) **compilé sur copie : 0 erreur, 0 avertissement, OBSERVE compilé, un seul `OrderSend`** ; **non déployé** (le 1.14 reste dans le terminal d'Exhorte, lu par le cœur comme un refus définitif).
- **Vérifié** : suite Python complète (`--ignore-glob="*(1)*"`, copies `(1)` écartées de l'import des modules) = 3 834 passés, 15 ignorés ; 5 échecs au premier passage, tous corrigés et rejoués verts (3 tests d'API que j'avais mis sur OBSERVE où le Risk Engine n'approuve rien, deux tests du contrat OpenAPI qui ignoraient les routes du System Center de l'I8 — opération renommée `system_terminal_registry` —, l'attente du test de plafond bas au démarrage, désormais retenue par `mode_authorized`) ; `mypy` 272 fichiers propres ; `ruff` lint et format propres ; `gen-types --check` à jour ; `tsc` sans erreur hors copies `(1)` ; `eslint` propre sur les fichiers touchés ; `vitest` 297 passés.
- **Non vérifié sur le live** : l'agent 1.15 n'a jamais tourné dans MetaTrader ; le refus `AGENT_OBSERVE` n'est éprouvé que par le source (tests d'architecture) et par des réponses jouées à la main dans les tests.
- **Mesuré avant d'agir** : la vraie base n'a aucune commande ni aucune occurrence de `PAPER`/`SIMULATED` ; le `.env` ne fixe pas `TRADING_MODE`. Limite assumée : une autre base portant d'anciennes lignes `SIMULATED` ne se relirait pas (pas de lecture tolérante écrite).
- **À Exhorte** : redémarrer le cœur (qui tourne encore avec l'ancien code en mémoire), décider du déploiement du 1.15, puis retirer la lecture de compatibilité de `wire.py` quand tous les agents seront en 1.15.
