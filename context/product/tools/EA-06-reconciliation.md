# EA-06 — Réconciliation

Statut : **livré** (4 incréments, 2026-09-16) · Vague EA · Effort 1–2 j ·
Dépend de : EA-03 (protocole, machine à états), EA-05 (agent MQL5,
incrément 6 — le premier `OrderSend` du dépôt)

« Ce qui distingue un vrai système d'exécution d'un EA. » (prompt de
lancement, `02_Plan_Projet/prompt-claude-code-vague-ea.md`)

## Problème

Depuis EA-05 incrément 6, un `OrderSend` existe — structurellement
inatteignable hors `CONFIRM` aujourd'hui, mais le jour où EA-07 l'ouvre, deux
trous devront déjà être bouchés :

1. **`UNKNOWN` n'a personne pour le résoudre.** La machine à états
   (`lib/domain/execution-state.ts`, EA-03) le documente comme état de
   première classe avec une seule sortie légale (`RECONCILED`), et
   `ExecuteOrder` (EA-05) écrit `commandId → UNKNOWN` avant l'appel broker —
   mais rien n'interroge jamais MT5 pour le faire avancer. Un agent qui meurt
   entre `OrderSend` et l'accusé laisse une position peut-être ouverte, peut-
   être pas, et le système ne le saura jamais tout seul.
2. **Les positions externes sont comptées, jamais distinguées.**
   `InpMaxOpenPositions` (EA-05) compte déjà *toutes* les positions du
   terminal via `PositionsTotal()` — prudent par défaut, mais aveugle : une
   position manuelle et une position du Trading OS pèsent pareil dans la
   barrière, et rien ne les étiquette différemment pour le journal ou une
   future mesure de conformité (T07).

## Écart trouvé avant tout code (cartographie)

Lu en entier avant d'écrire quoi que ce soit : `.claude/CLAUDE.md`,
`context/execution/{state-machine,protocol,safety}.md`,
`context/adr/0010-execution-agent-mt5.md`, `lib/domain/execution-state.ts`
(+ son test), `tools/mt5-execution-agent/TradingOsAgent.mq5` et
`Include/CommandStore.mqh` dans leur état post-incrément-6,
`backend/src/TradingOs.Gateway/Mt5AgentServer.cs`,
`backend/src/TradingOs.Persistence/schema.sql`, et — parce que le prompt de
lancement l'exige nommément — la revue T05 du 2026-09-05 dans
`session-log.md`.

### Ce qui existe déjà et qu'il ne faut pas dupliquer

| Brique | Fichier | État |
|---|---|---|
| Machine à états, 12 états | `lib/domain/execution-state.ts` | Pure, testée, `UNKNOWN` de premier ordre, aucune sortie automatique. C'est la **narration** de ce qu'EA-06 doit faire respecter — elle ne fait rien toute seule (« no clock, no I/O, no persistence » — le commentaire du fichier le dit explicitement). |
| Isolation par magic number | `TradingOsAgent.mq5`, `context/execution/safety.md` | `InpMagicNumber` posé sur chaque `OrderSend` (`request.magic`). `safety.md` nomme déjà `EXTERNAL_POSITION` pour « une position sans ce magic number » — le vocabulaire est pris, pas à réinventer. |
| Trace du `commandId` sur l'ordre | `TradingOsAgent.mq5::ExecuteOrder` | `request.comment = "TradingOS " + commandId`. Hypothèse à vérifier en réel, pas garantie universelle : MT5/le broker propage généralement le commentaire de l'ordre au deal puis à la position, mais rien dans la doc MQL5 ne le garantit à 100 % pour toute combinaison de type de remplissage — **premier test à faire en réel, avant de fonder toute la résolution dessus**. |
| Persistance `commandId → résultat` | `Include/CommandStore.mqh` | Fichier plat, une ligne par écriture, dernière occurrence gagne. Porte déjà `UNKNOWN` comme statut possible depuis l'incrément 6. **Ce n'est pas la machine à 12 états** — c'est un état résumé (`SIMULATED`/`REJECTED`/`EXPIRED`/`FAILED`/`FILLED`/`PARTIALLY_FILLED`/`UNKNOWN`), suffisant pour l'idempotence, pas pour narrer une transition. EA-06 doit décider s'il a besoin de plus que ça (voir décision 2). |
| Le piège déjà payé une fois | `context/project/session-log.md`, 2026-09-05 (revue T05) | Deux bugs réels sur `mt5_observer.py`, corrigés depuis : (a) clé de position `ticket` au lieu de `identifier`/`POSITION_IDENTIFIER` — coïncident dans le cas courant, divergent sur une opération de service broker ; (b) un aller-retour plus court que l'intervalle de sondage est invisible à un diff de snapshots. Le second est **résolu côté observer** par `scan_missed_round_trips` (scanne les deals de sortie indépendamment du diff de positions) — la stratégie à porter ici, pas le code : MQL5 n'importe pas du Python. |
| Rien n'interroge jamais MT5 pour résoudre `UNKNOWN` | — | Confirmé par grep : aucune fonction de réconciliation nulle part dans le dépôt. |
| Aucune table de rapprochement | `backend/src/TradingOs.Persistence/schema.sql` | 14 tables, aucune ne porte un état de commande courant ni une notion de divergence. `execution_commands`/`command_acks`/`execution_reports` sont des journaux d'événements, jamais un état interrogeable par `commandId`. |
| Aucun type de message pour ça | `lib/contracts/mt5-wire.ts` / `Mt5Wire.cs` | Le wire agent↔gateway ne porte aujourd'hui aucun message de réconciliation ou de divergence. À étendre, jamais à contourner par un canal parallèle. |

## Décisions

Validées telles que proposées (« valide les deux, enchaîne sur les
incréments », 2026-09-16) — les deux choix où l'arbitrage revenait à
l'utilisateur, le premier parce que le prompt de lancement l'exige
nommément, le second parce qu'il engage l'architecture réseau et où vit la
logique.

1. **Comportement par défaut face à une position externe : `IGNORE`,
   `WARN`, ou `BLOCK_NEW_TRADES` ?**

   Je recommande **`WARN`**. Raisonnement : le risque numérique réel —
   l'exposition totale — est déjà compté prudemment aujourd'hui,
   `PositionsTotal()` (barrière `InpMaxOpenPositions`, EA-05) ne fait aucune
   différence entre une position du Trading OS et une position manuelle, et
   c'est le sens le plus sûr de l'erreur. Ce qui manque n'est donc pas une
   barrière numérique supplémentaire, c'est l'**attribution** : savoir
   laquelle est laquelle, pour le journal et pour une future mesure de
   conformité (T07). `WARN` ajoute cette visibilité — journalisée, comptée
   dans l'exposition (déjà fait), visible dans le cockpit — sans introduire
   un nouveau refus dont la justification n'est pas encore posée.
   `BLOCK_NEW_TRADES` bloquerait une commande du Trading OS à cause d'une
   position sans rapport avec elle, sur un dépôt où `CONFIRM` n'existe même
   pas encore (EA-07) — prématurément agressif comme *défaut*, même si ça
   reste une option de configuration légitime plus tard (ex. contrainte prop
   firm explicite). `IGNORE` reviendrait en arrière par rapport au
   comportement actuel, qui compte déjà tout : à écarter.

2. **Où vit la logique de réconciliation, et qu'est-ce qui la déclenche ?**

   Je propose : **dans l'agent MQL5**, pas dans le Gateway ni dans un
   troisième processus. C'est le seul endroit avec un accès direct et
   immédiat à `PositionsGet`/`HistoryDealsGet` sans dépendre d'un aller-
   retour réseau — exactement pourquoi l'observer Python fait déjà son
   propre scan de déclarations plutôt que de demander au Gateway de le
   faire. Deux déclencheurs, pas un seul : (a) une passe périodique (même
   minuterie que le heartbeat, pas une nouvelle horloge) qui scanne les
   entrées `UNKNOWN` du `CommandStore` et cherche une position/deal portant
   le magic number de l'environnement **et** la trace `commandId` dans son
   commentaire ; (b) une passe systématique à la reconnexion, puisque
   c'est justement pendant une déconnexion qu'un `UNKNOWN` a le plus de
   chances de naître. Le résultat (trouvé-exécuté / trouvé-rejeté /
   introuvable) remonte au Gateway par un nouveau message wire
   (`execution.reconciled`, à ajouter à `mt5-wire.ts`/`Mt5Wire.cs` — extension
   additive, jamais un canal parallèle) plutôt que par un canal parallèle.
   Alternative : faire vivre la réconciliation côté Gateway, qui piloterait
   l'agent par des requêtes — plus proche de « le serveur décide », mais
   réintroduit une dépendance réseau exactement là où ADR 0010 a choisi
   l'inverse pour la validation locale.

   Paramètre à poser, pas à deviner en silence : **combien de tentatives
   avant d'abandonner et remonter à l'humain (`RECONCILIATION_PENDING` →
   escalade)**. Provisoire ici : 3 tentatives, espacées comme le cycle
   périodique choisi ci-dessus.

   **Changé en implémentant (incrément 2), à relire** : pas de plafond.
   `not_found` ne fait jamais abandonner — la recherche est rejouée à chaque
   heartbeat/reconnexion, indéfiniment, et repart d'elle-même si la fenêtre
   `InpReconciliationLookbackDays` finit par couvrir la trace. Aucun état
   `RECONCILIATION_PENDING` n'a été ajouté. Raison : un abandon au bout de 3
   tentatives ne change rien à la réalité — la position, si elle existe,
   reste non réconciliée — et il aurait fallu un second mécanisme rien que
   pour sortir de cet abandon plus tard. L'historique complet de chaque
   tentative (y compris chaque `not_found`) reste dans `envelopes` (l'audit
   trail générique) même si `command_reconciliations` (incrément 4) ne garde
   que la dernière. C'est le point de la fiche marqué « à poser, pas à
   deviner en silence » — posé ici, pas deviné, mais différemment de la
   valeur provisoire ci-dessus : à relire si un `UNKNOWN` réel reste
   introuvable de façon persistante une fois EA-07 vivant.

## Comportement attendu

1. **Résolution d'`UNKNOWN`.** Pour chaque entrée `UNKNOWN` du
   `CommandStore` : chercher une position ouverte ou un deal historique
   portant `InpMagicNumber` et dont le commentaire contient le `commandId`
   (`identifier`/`POSITION_IDENTIFIER` comme clé de position partout — jamais
   `ticket`, piège déjà payé). Trois issues seulement, jamais une quatrième :
   trouvé-et-exécuté, trouvé-et-rejeté, introuvable après N tentatives.
   **Aucun rejeu automatique dans aucun cas** — c'est la règle non
   négociable de l'ADR 0010, déjà testée au niveau de la machine à états
   (`execution-state.test.ts`) ; EA-06 ne fait que la faire respecter en
   pratique, jamais la contourner.

2. **Détection des positions externes.** Toute position sans
   `InpMagicNumber` est `EXTERNAL_POSITION` — jamais gérée comme une commande
   du Trading OS, comptée dans l'exposition (déjà le cas), comportement par
   défaut selon la décision 1 ci-dessus.

3. **Rapprochement périodique et visibilité.** Ce que le Trading OS croit
   détenir (le `CommandStore`, côté agent) contre ce que MT5 détient
   réellement. Toute divergence journalisée et visible côté cockpit — une
   divergence silencieuse est un défaut de cette fiche, pas un cas limite
   toléré.

4. **Le test exigé nommément par le prompt de lancement** : la mort du
   processus agent entre `OrderSend` et l'accusé — reproduite délibérément
   (pas juste un test unitaire de `transition()`, qui existe déjà), avec
   vérification que la résolution qui suit conclut correctement sans jamais
   raviver un second `OrderSend`.

## Ancrage dans le code

- `lib/domain/execution-state.ts` — non modifié. C'est la narration ; EA-06
  la fait respecter, ne la réécrit pas.
- `Include/CommandStore.mqh` — étendu, pas réécrit : lecture des entrées
  `UNKNOWN` pour alimenter la résolution.
- `TradingOsAgent.mq5` — nouvelle logique de réconciliation (décision 2),
  aucune modification du chemin `ExecuteOrder` existant.
- `lib/contracts/mt5-wire.ts` / `Mt5Wire.cs` — extension additive pour porter
  le résultat de réconciliation et le signalement `EXTERNAL_POSITION`.
- `backend/src/TradingOs.Persistence/schema.sql` — nouvelle table de
  rapprochement (forme exacte à proposer une fois la décision 2 tranchée).
- `backend/src/TradingOs.Gateway/Mt5AgentServer.cs` — réception du nouveau
  message, jamais fusionné avec `Mt5ObserverClient` (ADR 0010, inchangé).
- Cockpit — surface de visibilité pour une divergence (composant à proposer
  dans le découpage en incréments, pas deviné ici).

## Découpage en incréments

À proposer précisément une fois les deux décisions tranchées — squelette
provisoire, cohérent avec la méthode déjà suivie pour EA-05 (chaque
incrément garde les gates vertes, rien ne s'exécute contre un vrai compte
avant vérification) :

1. Extension du wire (`execution.reconciled`, forme du signalement
   `EXTERNAL_POSITION`) + miroir C#.
2. Résolution `UNKNOWN` côté agent — recherche par magic number + trace
   `commandId`, les trois issues, jamais de rejeu. Test unitaire du pire cas
   (mort entre `OrderSend` et l'accusé) à ce stade.
3. Détection des positions externes + comportement par défaut (décision 1).
4. Table de rapprochement + endpoint de lecture + surface cockpit pour une
   divergence visible.

## Journal

- 2026-09-15 — fiche créée avant tout code, sur lancement explicite de
  l'utilisateur (« lance EA-06 maintenant »). Cartographie faite : la
  machine à états (EA-03) est prête et pure, ne pilote rien elle-même ;
  aucune résolution d'`UNKNOWN` n'existe nulle part ; le vocabulaire
  `EXTERNAL_POSITION` est déjà posé dans `safety.md` mais rien ne
  l'implémente ; le piège du 2026-09-05 (identifiant de position, aller-
  retour invisible) est identifié comme devant se reposer ici en pire —
  une mauvaise clé réconcilierait une commande avec la mauvaise position.
  Deux décisions soumises à l'utilisateur avant code : comportement par
  défaut sur position externe (recommandation `WARN`, raisonnement ci-
  dessus) et localisation de la logique de réconciliation (recommandation :
  dans l'agent, pas le Gateway). **Arrêt ici, en attente de validation** —
  conformément au prompt de lancement (« Écris la fiche EA-06 avant de
  coder, puis attends ma validation »).

- 2026-09-16 — les deux décisions validées telles que proposées (« valide
  les deux, enchaîne sur les incréments »). Les 4 incréments implémentés
  dans la foulée, gates vertes à chaque étape (tsc, lint, `dotnet build`,
  `dotnet test` 34/34, vitest 184/184, `next build`, compilation MetaEditor
  0 erreur/0 avertissement à chaque incrément MQL5) :

  1. **Wire** : `Mt5ReconciledMessage`/`Mt5PositionScannedMessage` ajoutés à
     `mt5-wire.ts` et miroirs C# (`Execution.cs`, enregistrés dans
     `Mt5WireParser.Parse`). `brokerRetcode` toujours `null` sur
     `execution.reconciled` — l'historique MT5 ne porte jamais le retcode
     d'origine, jamais fabriqué.
  2. **Résolution `UNKNOWN`** : `CommandStore.mqh` étendu avec
     `CommandStoreFindUnknown` (énumération — n'existait pas, seul le
     point-lookup existait). `TradingOsAgent.mq5::ReconcileUnknownCommands`
     cherche par `InpMagicNumber` + `"TradingOS " + commandId` dans
     `DEAL_COMMENT`/`ORDER_COMMENT`, lit toujours `DEAL_POSITION_ID` — jamais
     un ticket. Déclenchée sur le heartbeat et sur toute connexion (y
     compris la première après un redémarrage), comme décidé. Écrit
     `FILLED`/`FAILED` dans `CommandStore` (pas un nouveau vocabulaire — le
     chemin de rejeu `HandleOrderCommand` doit rester un statut valide de
     `Mt5ReportMessage`), et envoie `execution.reconciled` séparément pour
     porter la distinction « reconstruit après coup » jusqu'au cockpit.
     Changement par rapport au brouillon : voir la note sur le plafond de
     tentatives ci-dessus. **Deux limites non résolues, à charge d'EA-07** :
     (a) la propagation du commentaire jusqu'au deal (`request.comment` →
     `DEAL_COMMENT`) reste l'hypothèse que la fiche demandait de vérifier en
     réel en premier — impossible ici, `OrderSend` n'a encore jamais tourné,
     donc jamais vérifiée contre un vrai broker ; (b) « test unitaire du pire
     cas » n'a pas pu être un test exécutable — aucun harnais MQL5 n'existe
     dans ce dépôt et je n'ai aucun moyen d'exécuter du MQL5 hors du
     terminal. Ce qui a été fait à la place : vérification structurelle
     (mêmes grep/traçage d'appel que EA-05 incrément 6 — magic number,
     jamais de ticket, une seule fenêtre `HistorySelect`, aucun rejeu
     possible) + compilation propre. Ce n'est pas équivalent à observer un
     vrai crash-recovery.
  3. **Positions externes** : `TradingOsAgent.mq5::ScanOpenPositions`, une
     position par message (contrainte `JsonLite.mqh`, jamais de tableau),
     `POSITION_IDENTIFIER` jamais `POSITION_TICKET`. `isExternal` sur
     magic number seul. `InpMaxOpenPositions` : commentaire corrigé (il
     annonçait à tort qu'EA-06 exclurait les positions externes du compte —
     l'inverse de la décision validée ; le compte reste inchangé,
     volontairement). Contrairement à l'incrément 2, **ce chemin tourne
     réellement dès que l'agent est déployé** — `PositionsTotal()` ne dépend
     pas du mode `CONFIRM`.
  4. **Persistance + surface cockpit** : `command_reconciliations` et
     `position_scans` (schema.sql) — upsert par clé naturelle, pas
     d'accumulation, l'audit complet reste dans `envelopes`. Chemin complet
     câblé : `Mt5AgentServer.Handle` → `Mt5WireTranslator` →
     `PersistenceMapper`/`PersistenceWriter` → nouveau
     `ExecutionDivergenceRepository` → `GET /api/execution/divergence` →
     `/positions` (le cockpit avait déjà réservé cette page à « pending
     commands, broker errors, and reconciliation state » — texte du
     placeholder d'avant EA-06). Nom délibérément « divergence », pas
     « réconciliation » : EA-02 porte déjà un concept distinct sous ce nom
     (`SetupProposalRepository`, rapprochement setup-vs-trade) — même mot,
     fonctionnalité sans rapport, à ne pas confondre en relisant l'un ou
     l'autre plus tard.

  **Vérifié** : un seul `OrderSend` dans le dépôt, toujours derrière la
  garde `MODE_CONFIRM`, `g_mode` toujours un `const` `MODE_OBSERVE` jamais
  affecté — les 4 incréments n'y touchent pas (grep refait après coup).
  **Non vérifié, honnêtement** : rien de tout ceci n'a encore tourné contre
  un vrai `UNKNOWN` réel, puisqu'aucun n'a jamais existé (`ExecuteOrder`
  reste inatteignable). Seul l'incrément 3 (scan de positions) produit du
  trafic réel dès aujourd'hui.
