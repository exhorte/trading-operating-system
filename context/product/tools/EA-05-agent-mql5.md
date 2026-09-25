# EA-05 — Agent MQL5

Statut : **livré** (2026-09-15, incrément 6 compris) · Vague EA · Effort 3–5 j ·
Dépend de : EA-03 (protocole, machine à états), EA-04 (profils de compte)

**Le chemin d'exécution existe mais ne peut pas s'exécuter.** L'`OrderSend` est
écrit, unique dans le dépôt, et structurellement inatteignable hors `CONFIRM` ;
le mode est une constante de compilation figée à `OBSERVE`. Rendre `CONFIRM`
atteignable est EA-07, sous les conditions de sa propre fiche — pas un réglage
ici. Voir le journal du 2026-09-15.

**La première fois que ce dépôt contient du code capable de passer un ordre
réel.** Trois contraintes non négociables (ADR 0010) priment sur tout le
reste de cette fiche : l'agent ne décide rien ; le mode est une barrière
physique, pas un réglage ; jamais deux positions.

## Problème

Aucun agent d'exécution n'existe. Le protocole (EA-03) et les profils de
compte (EA-04) sont figés côté OS, mais rien ne les parle côté terminal MT5.
Sans agent, `CockpitHub.SubmitCommand` (déjà écrit) n'a personne à qui
envoyer une commande — il ne parle aujourd'hui qu'à l'observer Python
lecture-seule, jamais à un exécutant.

## Écart trouvé avant tout code (cartographie)

Lu en entier avant d'écrire quoi que ce soit : `context/adr/0010-execution-agent-mt5.md`,
`context/execution/{protocol,state-machine,safety}.md`, `tools/mt5-observer/README.md`
et `mt5_observer.py`, `backend/src/TradingOs.Gateway/{Mt5ObserverClient.cs,Mt5WireTranslator.cs}`,
`backend/src/TradingOs.Host/{Program.cs,CockpitHub.cs}`, `lib/contracts/mt5-wire.ts`,
`backend/src/TradingOs.Contracts/Mt5Wire.cs`, et — parce qu'ils portent le nom
« MT5 agent » et auraient pu être le point d'ancrage — `context/realtime/{mt5_agent_realtime_lifecycle.md,live_prototype.md,README.md}`.

### Ce qui existe déjà et qu'il ne faut pas dupliquer

| Brique | Fichier | État |
|---|---|---|
| Contrat de messages | `lib/contracts/mt5-wire.ts` + miroir `Mt5Wire.cs` | **Complet** pour tout ce qu'EA-05 doit émettre/recevoir : `agent.hello`, `agent.heartbeat`, `execution.order`, `execution.ack`, `execution.report`, etc. Rien à ajouter au niveau des formes de message. |
| Protocole et machine à états | `context/execution/{protocol,state-machine,safety}.md` (EA-03) | Le contrat métier (commandId/accountId/protocolVersion/expiresAt, `ACCOUNT_MISMATCH`, les 12 états) est figé. EA-05 l'implémente côté MQL5, ne le redéfinit pas. |
| Résolution de compte | `lib/accounts/` (EA-04) | Fournit les bornes (whitelist symboles, volume max, positions max, mode) que l'agent doit faire respecter localement — configuré côté OS, pas deviné côté agent. |
| Traduction wire → domaine | `Mt5WireTranslator.cs` | Pure, déjà exhaustive pour les messages existants. Transport-agnostique — **ne dépend d'aucune décision prise dans cette fiche** (WSS ou TCP brut, peu importe pour ce fichier). |
| Observer Python | `tools/mt5-observer/mt5_observer.py` | Lecture seule, validé en live, **à ne pas toucher** (ADR 0010 : « deux processus, deux responsabilités, jamais fusionnés »). |

### Ce qui n'existe nulle part, et que le prompt de lancement ne nomme pas explicitement

Le prompt de lancement cadre EA-05 comme « écrire l'agent MQL5,
`tools/mt5-execution-agent/TradingOsAgent.mq5` ». En lisant le code
d'ancrage réseau, j'ai trouvé un trou structurel que cette formulation ne
couvre pas :

**Le Gateway n'a aujourd'hui aucun point d'écoute pour un agent entrant.**
`Mt5ObserverClient` (`backend/src/TradingOs.Gateway/Mt5ObserverClient.cs`) est
un **client** WebSocket : c'est le Gateway qui compose vers l'observer Python
(`ws://localhost:8765`, où l'observer est le serveur). `Program.cs` n'expose
que `/hub/cockpit` (SignalR, réservé au cockpit — ADR 0004) et une poignée
d'endpoints HTTP `/api/*`. **Rien n'écoute une connexion MQL5 entrante.**

Le docstring de `Mt5ObserverClient` le dit lui-même, en commentaire, depuis
la Vague 1 : *« The definitive MQL5 agent will invert this (agent dials the
gateway) […] only this class changes then »* — mais ce composant miroir
n'a jamais été écrit. **Construire ce point d'écoute côté Gateway est un
prérequis d'EA-05, pas une extension optionnelle** : sans lui, l'agent MQL5
n'a littéralement personne à qui se connecter. Je le mets dans le périmètre
de cette fiche (voir « Décisions à valider », point 2).

### Un conflit documentaire trouvé en cherchant le point d'ancrage réseau

`context/realtime/mt5_agent_realtime_lifecycle.md` (et, dans une moindre
mesure, `live_prototype.md`) décrit une architecture **différente** de celle
qu'EA-03/ADR 0010 posent : un **sidecar bridge** local (l'EA parle à un
processus tiers par pipe nommé/socket local, qui seul détient la connexion
WSS vers le Gateway). Trois signaux convergent pour dire que ce document est
**obsolète, pas juste une variante** :

1. Il référence « Phase 03 (ADR 0005) » — la gouvernance par phases
   numérotées n'existe plus depuis l'ADR 0006, et l'ADR 0005 actuel (« l'IA
   reste en lecture ») n'a aucun rapport avec un sidecar. Ce sont les
   anciens numéros, d'avant le pivot du 2026-09-04.
2. **Il n'est cité nulle part** dans la liste de lecture d'EA-05 fournie par
   le prompt de lancement, ni par aucun ADR post-pivot (0004, 0007, 0010).
   `context/realtime/mt5_wire_protocol.md` — le document que l'ADR 0004 cite
   et que le prompt de lancement fait lire — ne mentionne aucun sidecar : sa
   propre justification (« MQL5 has no maintained SignalR client […] Raw WSS
   + lean JSON keeps the agent simple ») suppose déjà une connexion
   directe EA↔Gateway.
3. **Personne ne l'a implémenté** : `tools/mt5-observer/` ne contient ni
   sidecar ni pipe nommé, seulement l'observer Python et son WebSocket
   direct.

Je recommande de traiter ce fichier comme un reliquat pré-pivot (à archiver
dans une passe de ménage documentaire ultérieure, hors périmètre de cette
fiche) et de **ne pas construire de sidecar**. À confirmer avec toi (point 1
ci-dessous) puisque ça touche à l'architecture réseau que je m'apprête à
coder des deux côtés.

## Décisions à valider avant d'implémenter

Deux points où l'arbitrage est le tien, parce qu'ils engagent une nouvelle
surface réseau des deux côtés (Gateway et MQL5) :

1. **Transport : WSS ou TCP brut ?** `mt5_wire_protocol.md` parle de « secure
   WebSocket (WSS) », mais la connexion **existante** Gateway↔observer
   (`Mt5ObserverClient`) tourne déjà en `ws://` **non chiffré**, en boucle
   locale — pas de TLS du tout, malgré ce que le nom du document laisse
   entendre. Implémenter un vrai client WebSocket (poignée de main HTTP
   Upgrade + trames RFC 6445 masquées) en MQL5 pur est un morceau de
   protocole non trivial, source d'erreurs, pour un bénéfice nul sur une
   connexion boucle locale entre deux processus de la même machine
   personnelle. Je propose un **socket TCP brut, JSON délimité par retour à
   la ligne**, même format de message (`lib/contracts/mt5-wire.ts` /
   `Mt5Wire.cs` inchangés — seul le cadrage/transport change, jamais le
   contrat), via les fonctions natives MQL5 `SocketCreate`/`SocketConnect`/
   `SocketSend`/`SocketReceive` (aucune DLL externe requise). Recommandé :
   **TCP brut**. Alternative : WSS complet, si tu préfères rester au plus
   près du texte de `mt5_wire_protocol.md` malgré le coût d'implémentation.
2. **Le point d'écoute côté Gateway fait-il partie d'EA-05 ?** Sans lui,
   l'agent MQL5 n'a personne à qui se connecter — je le considère comme un
   prérequis, pas une extension. Confirme que c'est bien dans le périmètre
   de cette fiche (un nouveau composant, ex. `Mt5AgentServer.cs`, parallèle à
   `Mt5ObserverClient` et jamais fusionné avec lui — ADR 0010).

## Réalité opérationnelle : ce que je peux vérifier moi-même, ce qui t'attend

- **MetaEditor est installé** (`C:\Program Files\MetaTrader 5\MetaEditor64.exe`).
  Il supporte une compilation headless (`/compile:<fichier> /log:<fichier>`) —
  je peux donc l'ajouter comme **gate réelle** pour le `.mq5` (aucune gate
  MQL5 n'existe aujourd'hui dans `quality_gates.md`). Ça vérifie la syntaxe
  et les types, pas le comportement réseau ni l'exécution.
- **Ce que je ne peux pas vérifier moi-même** : faire tourner l'EA compilé
  contre le terminal MT5 réel (`terminal64.exe`), observer la connexion,
  le heartbeat, les accusés en conditions réelles. Le prompt de lancement le
  demande explicitement par incrément (« connexion et heartbeat d'abord […]
  l'exécution en dernier, et seulement une fois que tout le reste est
  vérifié en OBSERVE contre un compte de démonstration »). Ces vérifications
  sont pour toi, entre chaque incrément — je ne les invente pas, je te les
  demande.

## Les trois contraintes non négociables (ADR 0010), et comment chacune se traduit en code

1. **L'agent ne décide rien.** Aucune fonction MQL5 ne lit `lib/analysis/`
   ni ne calcule un signal. L'agent reçoit une commande déjà complète
   (symbole, sens, volume, SL, TP) et l'exécute ou la refuse — jamais
   « attendre un meilleur prix » ni « ajuster l'entrée ».
2. **Le mode est une barrière physique.** En `OBSERVE`/`PAPER`, le chemin de
   code qui appelle `OrderSend` doit être **structurellement inatteignable**
   — pas seulement derrière un `if`. Traduction MQL5 concrète : l'appel
   `OrderSend` n'existe que dans une fonction dont l'unique point d'entrée
   vérifie `mode == CONFIRM` en amont ET où le retour anticipé rend le reste
   de la fonction mort ; le critère de revue (« lis le code toi-même ») est
   : peut-on suivre un chemin d'exécution qui atteint `OrderSend` sans
   passer par ce test ? Doit être non. `AUTO` n'existe pas comme valeur du
   type mode (même discipline que `ExecutionMode` en TypeScript, EA-04).
3. **Jamais deux positions.** La correspondance `commandId → résultat`
   persiste **sur disque** (fichier local au terminal, ex. `Files/tradingos_commands.dat`),
   pas en mémoire — elle doit survivre à un redémarrage de l'EA ou du
   terminal. Une commande dont le `commandId` est déjà connu retourne le
   résultat mémorisé (`execution.ack` `DUPLICATE`) et **n'appelle jamais
   `OrderSend` une seconde fois**, quel que soit l'état de la machine à
   états au moment du rejeu (EA-03 : `UNKNOWN` ne rejoue jamais).

## Comportement attendu

`tools/mt5-execution-agent/TradingOsAgent.mq5`, responsabilités et rien
d'autre : `connect`, `heartbeat`, `receive`, `validate`, `execute`,
`acknowledge`, `report`, `reconcile` (partiel — la résolution complète
d'`UNKNOWN` est EA-06 ; l'agent expose ici ce qu'il faut pour qu'EA-06
puisse interroger).

Barrières locales (`context/execution/safety.md`, implémentées ici) :
whitelist de symboles, volume max, positions max, stop-loss obligatoire,
spread max au moment de l'exécution, kill switch local (fonctionne backend
injoignable), `accountId` de la commande ≠ compte du terminal → `REJECTED`
`ACCOUNT_MISMATCH`, magic number propre à l'environnement.

Contrainte FTMO dès l'écriture : orienté événement, pas tick — aucune
modification de stop déclenchée par une simple variation de prix.

`tools/mt5-execution-agent/README.md` : installation, paramètres, mode
d'emploi, procédure de vérification en OBSERVE.

## Ancrage dans le code

- `lib/contracts/mt5-wire.ts` / `Mt5Wire.cs` — non modifiés (sauf, si le
  point 1 choisit TCP brut, un commentaire documentant que le framing a
  changé, pas le contrat).
- `Mt5WireTranslator.cs` — réutilisé tel quel côté Gateway pour traduire les
  messages du nouveau point d'écoute ; c'est déjà transport-agnostique.
- `CockpitHub.SubmitCommand` — branché sur le nouveau point d'écoute au lieu
  de (ou en parallèle de) `Mt5ObserverClient.SendCommandAsync` pour l'envoi
  de commandes réelles ; **non réécrit**, juste reciblé.
- `mt5_observer.py` — non touché.

## Découpage en incréments

Staged exactement comme le demande le prompt de lancement : chaque
incrément tourne en OBSERVE contre le compte de démonstration avant le
suivant, et je m'arrête avant l'incrément d'exécution sans ton accord
explicite.

1. **Décisions ci-dessus tranchées** (transport, périmètre du point
   d'écoute) — préalable à tout code.
2. **Connexion et heartbeat.** Côté Gateway : nouveau point d'écoute
   (`Mt5AgentServer` ou nom équivalent), accepte une connexion, lit
   `agent.hello`, répond, traite `agent.heartbeat`. Côté MQL5 : connexion,
   envoi de `agent.hello`, heartbeat périodique. Rien d'autre. **Vérification
   par toi** : l'EA compile, se connecte au Gateway, le heartbeat apparaît
   côté serveur, contre le compte de démonstration.
3. **Réception et accusés.** L'agent reçoit une commande de test (mode
   OBSERVE forcé), répond `execution.ack` puis `execution.report`
   `SIMULATED` — chemin déjà existant côté Gateway (`Mt5WireTranslator.ToCommandAck`/`ToExecutionReport`),
   juste alimenté par le nouveau transport. **Vérification par toi.**
4. **Validation locale.** Toutes les barrières de `safety.md`, y compris
   `ACCOUNT_MISMATCH` testé contre un second `accountId` réel (pas simulé) —
   toujours en mode OBSERVE, donc sans risque financier. **Vérification par
   toi.**
5. **Persistance `commandId → résultat`.** Sur disque, testée en tuant le
   processus de l'EA et en le relançant. **Vérification par toi.**
6. **Exécution — dernier incrément, sous ton accord explicite uniquement.**
   `OrderSend`, structurellement inatteignable hors `CONFIRM`. Avant d'y
   toucher, je m'arrête et attends ton feu vert.

## Critère de réussite

- Le chemin `OrderSend` est structurellement inaccessible hors `CONFIRM` —
  vérifié en lisant le code, pas en faisant confiance à la réponse.
- La correspondance `commandId → résultat` survit à un redémarrage de
  l'agent et du terminal — testé en tuant le processus.
- `ACCOUNT_MISMATCH` testé contre un vrai second compte, pas simulé.
- Le kill switch local fonctionne backend éteint.
- Aucune modification de stop déclenchée par un tick.
- Les incréments connexion/accusés/validation ont tourné en OBSERVE contre
  le compte de démonstration avant que l'exécution ne soit écrite.
- `README.md` et `charter.md` corrigés : « aucun appel de trade n'existe
  dans ce dépôt » devient faux et doit disparaître — **seulement une fois
  l'incrément d'exécution livré**, pas avant.
- Gates vertes : gates habituelles + nouvelle gate MetaEditor
  (`/compile`) pour le `.mq5`.

## Journal

- 2026-09-12 — fiche créée avant tout code. Cartographie faite : le contrat
  de messages (EA-03) est complet et n'a rien à ajouter ; en revanche aucun
  point d'écoute Gateway n'existe pour un agent entrant — `Mt5ObserverClient`
  ne fait que dialer *vers* l'observer Python, jamais l'inverse. Trouvé un
  conflit documentaire : `context/realtime/mt5_agent_realtime_lifecycle.md`
  décrit une architecture sidecar pré-pivot (numérotation d'ADR obsolète,
  jamais implémentée, absente de la liste de lecture d'EA-05) qui contredit
  `mt5_wire_protocol.md`, actuellement cité par l'ADR 0004 — recommandé de
  la traiter comme reliquat, pas comme référence. Deux décisions soumises à
  l'utilisateur avant code, toutes deux validées : TCP brut plutôt que WSS
  complet, et le nouveau point d'écoute Gateway dans le périmètre de cette
  fiche. `MetaEditor64.exe` trouvé installé localement — une gate de
  compilation headless est proposée, comblant l'absence actuelle de toute
  gate MQL5.

- 2026-09-12 (suite) — **incréments 2 à 5 livrés côté code, en attente de
  vérification humaine contre le terminal réel avant l'incrément 6.**

  Correction trouvée en écrivant le mode de l'agent : `Mt5ExecutionMode`
  (`lib/contracts/mt5-wire.ts`) portait encore `"observe"|"paper"|"live"`,
  vocabulaire antérieur à l'ADR 0010 (qui nomme le troisième rang `CONFIRM`,
  pas `live` — parce que ce qui compte est la validation humaine par ordre,
  pas juste « compte réel »). Renommé en `"observe"|"paper"|"confirm"` :
  vérifié avant de renommer qu'aucun code ne branchait sur le littéral
  `"live"` (seulement des positions de type) — renommage pur, aucun
  comportement changé. `context/realtime/mt5_wire_protocol.md` mis à jour
  en cohérence.

  Côté Gateway (`backend/src/TradingOs.Gateway/Mt5AgentServer.cs`, nouveau) :
  serveur TCP dédié à l'agent d'exécution, jamais fusionné avec
  `Mt5ObserverClient` — même style d'événements (`EnvelopeReady`,
  `ConnectionChanged`), même réutilisation de `Mt5WireTranslator` (déjà pur
  et testé, agnostique du transport). Branché dans `GatewayBridgeService`
  (tourne en parallèle de l'observer) et `Program.cs`
  (`Cockpit:AgentPort`, défaut `9765`, exposé dans `/health`).
  `CockpitHub.SubmitCommand` reciblé sur `Mt5AgentServer` — le garde de mode
  lit maintenant `agentServer.Hello?.Mode` (le mode rapporté par l'agent
  d'exécution), plus celui de l'observer, qui n'a jamais eu vocation à le
  porter. `Mt5ObserverClient` et `mt5_observer.py` non touchés (diff vide).
  Comme `Mt5ObserverClient`, `Mt5AgentServer` n'a pas de test unitaire dédié
  — même précédent que le reste du dépôt pour les classes de socket,
  vérifiées en intégration contre un vrai terminal, pas en isolation.

  Côté MQL5 (`tools/mt5-execution-agent/`, nouveau) :
  `TradingOsAgent.mq5` + `Include/{JsonLite,CommandStore}.mqh`. Socket TCP
  brut (`SocketCreate`/`Connect`/`Send`/`Read`, natifs, aucune DLL), JSON par
  ligne via un scanner d'objets plats maison (MQL5 n'a pas de bibliothèque
  JSON — voir le commentaire d'en-tête de `JsonLite.mqh` sur la limite
  assumée : objets plats seulement). Persistance `commandId → résultat`
  sur disque (`Include/CommandStore.mqh`, `MQL5/Files/`, nommé par magic
  number), testée par relecture après écriture — la machine à états
  d'EA-03 n'est pas réimplémentée ici, seule sa règle d'idempotence l'est,
  au niveau attendu par ADR 0010 (rejeu → même résultat, jamais un second
  `OrderSend`… qui n'existe pas dans ce fichier). Barrières locales de
  `safety.md` implémentées : whitelist, volume max, positions max, stop
  obligatoire, spread max, `ACCOUNT_MISMATCH`. Mode figé à `OBSERVE` par une
  constante, pas une entrée — `control.set_mode` reçu est journalisé et
  ignoré (EA-07). **Aucun `OrderSend` dans ce fichier — grep-able, pas
  seulement documenté.**

  Limite assumée et documentée (README) : `agent.hello` ne porte qu'un seul
  champ `symbol` (héritage du prototype mono-symbole) ; cet agent peut
  whitelister plusieurs symboles mais n'en rapporte qu'un dans `hello` — les
  barrières locales s'appliquent quand même à tous les symboles autorisés.

  Gate MQL5 exécutée réellement (pas juste documentée) :
  `MetaEditor64.exe /compile` sur `TradingOsAgent.mq5` → **0 erreur,
  0 avertissement**. Ajoutée à `context/governance/quality_gates.md`.
  `.gitignore` étendu (`.ex5`, `compile.log`, le fichier de commandes
  persisté).

  Gates vertes par ailleurs : `npm run lint`, `npx tsc --noEmit`,
  `npm test` (202, inchangé — aucune logique pure nouvelle côté TS hors le
  renommage de type), `npm run build`, `dotnet build`, `dotnet test`
  (38, inchangé), `python -m py_compile` (inchangé), et la nouvelle gate
  MetaEditor.

  **Arrêt volontaire ici.** Les incréments 2 à 5 ne sont vérifiés que par la
  compilation — pas par un test contre le terminal réel, ce que seul
  l'utilisateur peut faire (procédure dans
  `tools/mt5-execution-agent/README.md`). Je n'écris pas l'incrément 6
  (exécution, `OrderSend`) sans un accord explicite séparé, conformément au
  prompt de lancement et à l'ADR 0010.

- 2026-09-12 (suite) — **incréments 2 à 5 vérifiés par l'utilisateur contre
  un vrai terminal, tout est vert.** Ceci confirme la connexion/heartbeat,
  la réception/accusés, la validation locale (dont `ACCOUNT_MISMATCH` contre
  un vrai second compte) et la persistance `commandId → résultat`. Ne
  remplace pas l'accord explicite distinct exigé avant l'incrément 6
  (exécution) — demandé, pas encore donné.

- 2026-09-15 — **incrément 6 livré, sur accord explicite et séparé de
  l'utilisateur** (demandé nommément : « réalise EA-05 incrément 6 jusqu'à la
  fin »). C'est la première fois que ce dépôt contient un appel d'exécution.

  **Ce qui a été écrit** : une seule fonction, `ExecuteOrder`, contenant le
  seul `OrderSend` du dépôt. `MqlTradeRequest` en `TRADE_ACTION_DEAL`,
  `ORDER_FILLING_IOC`, `deviation` = nouvel input `InpMaxSlippagePoints`,
  `magic` = `InpMagicNumber`, commentaire d'ordre portant le `commandId`.
  `SendReport` étendu pour porter un vrai remplissage (`brokerOrderId`,
  `brokerPositionId`, `filledVolume`, `averagePrice`, `brokerRetcode`) —
  paramètres par défaut à 0, sérialisés en `null`, donc les appels
  SIMULATED/REJECTED existants sont inchangés. `tp` était parsé nulle part
  dans `HandleOrderCommand` alors que le wire l'envoie (`Mt5WireTranslator.FlattenPlaceOrder`) :
  ajouté.

  **La barrière, vérifiée en lisant le code et pas en me croyant sur
  parole** — c'est le critère de revue que cette fiche impose :
  - `grep OrderSend` sur tout le dépôt (`.mq5/.mqh/.ts/.cs/.py`) → **un seul
    site d'appel**, ligne 483 de `TradingOsAgent.mq5` ; tout le reste est du
    commentaire ou de la doc.
  - Ce site est dans `ExecuteOrder`, dont la **première instruction** est
    `if(g_mode != MODE_CONFIRM) return;`.
  - `ExecuteOrder` n'a **qu'un seul appelant**, lui-même derrière un test de
    mode (défense en profondeur ; la barrière reste le test interne).
  - `g_mode` est déclaré une fois, `const ExecutionMode g_mode = MODE_OBSERVE;`,
    et **jamais affecté nulle part** — seulement lu (4 sites).
  - Donc : aucun chemin d'exécution n'atteint `OrderSend` dans ce build.
    Réponse à la question de revue de cette fiche : **non**.

  **Idempotence (« jamais deux positions »)** : `CommandStoreRecord(commandId,
  "UNKNOWN", ...)` est écrit sur disque **avant** l'appel broker, puis
  réécrit avec le résultat réel après. Un agent qui meurt entre les deux
  laisse `UNKNOWN` ; le rejeu de ce `commandId` retourne `DUPLICATE` depuis
  le store et n'appelle jamais `OrderSend` une seconde fois. Résoudre un
  `UNKNOWN` est la réconciliation d'EA-06, jamais une reprise depuis l'agent
  (EA-03 : `UNKNOWN` ne rejoue jamais). Un refus broker (`retcode` ≠ DONE /
  DONE_PARTIAL) est un résultat définitif, enregistré `FAILED` — rien n'est
  ouvert, pas d'ambiguïté à réconcilier.

  **Gate MQL5 réellement exécutée** : `MetaEditor64.exe /compile` →
  `Result: 0 errors, 0 warnings`. Gates TS/C# vertes par ailleurs (lint, tsc,
  184 tests, build, `dotnet build`/`test` 34). Corrections exigées par
  l'ADR 0010 faites dans la foulée : `README.md` et `.claude/CLAUDE.md` ne
  disent plus « aucun appel de trade n'existe dans ce dépôt » — ils décrivent
  la barrière à la place. `charter.md` n'avait pas besoin d'être touché : son
  principe 6 (« aucun ordre n'est envoyé sans qu'un humain l'ait déclenché »)
  reste vrai.

  **Non fait, volontairement** : rien qui rende `CONFIRM` atteignable. Pas
  d'input de mode, pas de `control.set_mode` implémenté, pas de seconde voie
  d'exécution. L'incrément 6 était d'écrire le chemin ; l'ouvrir est EA-07,
  sous les conditions de sa fiche (T02a/T02b vérifiés en réel — T02b ne l'est
  toujours pas — et taux d'accord d'EA-02 connu — toujours zéro proposition).

  **Jamais exécuté contre un broker, même en démo** : par construction, le
  mode ne le permet pas. Le critère de réussite « `ACCOUNT_MISMATCH` testé
  contre un vrai second compte » et « kill switch local backend éteint »
  restent hérités des incréments 2–5 ; les critères propres à l'exécution
  (un vrai fill, un vrai refus, un vrai `UNKNOWN` après crash) ne pourront
  être vérifiés qu'au moment d'EA-07, jamais avant.

- 2026-09-23 — **aucune trace de la vérification réelle du 2026-09-12 ;
  agent installé dans le terminal, à re-vérifier.** Trouvé en préparant
  l'environnement réel demandé par l'utilisateur (« rendre l'EA
  opérationnel »), vérifié avant d'être écrit :

  - **Terminal** (seule installation, `C:\Program Files\MetaTrader 5`,
    dossier de données `D0E8209F…`) : `TradingOsAgent` absent de
    `MQL5\Experts` ; aucun journal du terminal (2026-05-18 → 2026-09-18) ne
    montre son chargement — seuls deux EA tiers y ont tourné,
    `Ultimate_ICT_Gold_Scalper_v4.0` (2–10/07) et `K Trade Assistant MT5`
    (10/07). `metaeditor.log` ne montre que des compilations headless depuis
    le dépôt (12, 15, 16/09).
  - **Base** : depuis sa création (12/07), zéro ligne dans
    `execution_commands`, `command_acks`, `execution_reports`,
    `command_reconciliations`, `position_scans`, et zéro enveloppe
    `execution.*`. Les étapes 2 à 4 de la procédure du README en auraient
    laissé.

  L'entrée du 2026-09-12 (« vérifiés par l'utilisateur contre un vrai
  terminal, tout est vert ») consignait sa déclaration ; elle n'est
  corroborée ni côté terminal ni côté backend. Soit la vérification a eu lieu
  ailleurs (autre installation, depuis supprimée), soit elle n'a pas eu lieu —
  à refaire dans les deux cas, procédure du README, étapes 1 à 4. Aucune
  conséquence sur EA-07 (fermé, préconditions non remplies), mais ses
  préconditions supposent que cette base a tourné.

  **Fait ce jour, mode observe uniquement** : jonction
  `MQL5\Experts\TradingOsAgent` → `tools/mt5-execution-agent` (MT5 voit la
  version du dépôt ; retirer la jonction désinstalle) ; recompilation
  headless `0 errors, 0 warnings`. **Barrière relue dans le code avant
  installation** : un seul `OrderSend` (ligne 534, `ExecuteOrder`), précédé
  du garde `if(g_mode != MODE_CONFIRM)` (ligne 510) ; `g_mode` est une
  `const` à `MODE_OBSERVE` (ligne 64), jamais affectée ailleurs. Rien ne rend
  `CONFIRM` atteignable. L'attache sur un graphique et `InpAccountId` restent
  à l'utilisateur, dans MT5 — aucun identifiant ne passe par l'application.

- 2026-09-24 — **première connexion réelle, étape 1 du README passée —
  après correction d'un bug de framing présent depuis le premier commit.**
  Terminal Exness démo, `EURUSDm`, mode `OBSERVE`. Trois obstacles
  successifs, chacun lu dans les journaux de MT5, les logs de la Gateway et
  la base avant d'être traité :

  1. **Refus au démarrage** (13:09 et 13:17, heure locale) : presets à
     `InpMagicNumber=0` — la garde d'`OnInit` a fait son travail. Preset
     `ea1.set` à 1001 ensuite.
  2. **`SocketConnect` en 4014** (`ERR_FUNCTION_NOT_ALLOWED`) : la liste
     « Allow WebRequest for listed URL » du terminal était vide
     (`config\common.ini`, `WebRequestUrl=`). Refus avant tout accès
     réseau — la Gateway écoutait bien (une adresse autorisée sans serveur
     aurait donné 5272). `127.0.0.1` ajouté par l'utilisateur (réglage de
     sécurité du terminal) ; pris à chaud par les instances déjà lancées.
     Écrit dans le README (prérequis 4).
  3. **Connexion TCP établie, aucun message lu.** `SendRawLine` appelait
     `StringToCharArray(…, 0, StringLen(withNewline), CP_UTF8)` : avec un
     compte explicite, aucun 0 final n'est copié (doc MQL5 : seul le compte
     par défaut `-1` le copie), donc `written - 1` retirait le `\n`. La
     Gateway lit ligne par ligne (`ReadLineAsync`) : `hello` et heartbeats
     s'empilaient sans jamais former une ligne — aucun « MT5 execution agent
     connected », aucun heartbeat `mt5-execution-agent-1001` en base, malgré
     deux connexions TCP ouvertes. Correctif : compte `-1` (copie et compte
     le 0, en octets UTF-8). Ce code date de `0a7af59` (2026-09-12) :
     **aucune version de cet agent n'avait jamais pu être lue par la
     Gateway** — la vérification consignée le 2026-09-12 ne pouvait pas
     passer l'étape 1, ce qui confirme l'entrée du 2026-09-23.

  **Vérifié après réattache** (une compilation headless ne recharge pas un
  EA déjà attaché — README mis à jour) : `/health` `agentConnected: true` ;
  log Gateway « MT5 execution agent connected » (16:10:03 UTC) ; une
  enveloppe `agent.connected` pour `mt5-execution-agent-1001` ;
  `agent.heartbeat` à 12/min, soit une instance à 5 s ; une seule connexion
  TCP. Tables d'exécution toujours vides — aucune commande envoyée, aucune
  position ouverte : **étapes 2 à 4 restent à faire.**

  Deux instances ont tourné ensemble un moment (XAUUSDm et EURUSDm, même
  preset) ; celle de XAUUSDm a été retirée. Côté Gateway,
  `_writersByAccountId` est indexé par compte et le `finally` de
  `HandleClientAsync` désinscrit par clé sans vérifier que c'est sa propre
  connexion : deux instances, ou une reconnexion rapide, font afficher
  l'agent déconnecté alors qu'il ne l'est pas — non corrigé, tâche proposée
  à part. README : une instance par terminal.

  **Barrière relue dans le code après correctif** : un seul `OrderSend`
  (ligne 538, `ExecuteOrder`), garde `if(g_mode != MODE_CONFIRM)` en
  première instruction (ligne 514), `g_mode` `const` à `MODE_OBSERVE`
  (ligne 64), jamais affectée. Gate MetaEditor : `0 errors, 0 warnings`.

- 2026-09-25 — **côté Gateway, trois défauts qui auraient cassé les étapes
  2 et 3 du README, corrigés avant qu'elles tournent** (incrément I0 de
  l'étude `02_Plan_Projet/etude-connexion-pilotage-agent-2026-09-25.md`).
  `.mq5` inchangé, barrière inchangée.

  1. **BOM devant la première commande.** `new StreamWriter(stream,
     Encoding.UTF8)` sur un `NetworkStream` écrit EF BB BF avant sa première
     ligne. Prouvé par un test à rebours : avec l'ancien encodage, la ligne
     reçue commence par `239, 187, 191` ; corrigé
     (`UTF8Encoding(false)`).
  2. **Registre global.** Une connexion qui se fermait retirait
     l'inscription du compte par sa clé, même si un autre agent l'avait
     prise entre-temps ; le mode lu par `SubmitCommand` était celui du
     dernier `hello`, quel que soit le compte. Désormais :
     - une inscription par compte, retirée seulement par sa propre
       connexion ;
     - un second agent vivant sur le même compte est refusé, et sa
       connexion est fermée ;
     - une connexion muette plus de 30 s (`Cockpit:AgentStaleSeconds`) est
       fermée par un watchdog, et un nouveau `hello` la remplace aussitôt ;
       sans ça, un terminal planté aurait laissé l'agent « connecté » pour
       toujours ;
     - la garde de `SubmitCommand` lit l'agent du compte visé.
  3. **Rapports.** Tout rapport non SIMULATED partait typé « commande
     rejetée ». Le mapper lisait alors un `ack` absent, plantait, et le
     writer prenait ce plantage pour une panne de base (`db: down`,
     événement perdu). Maintenant :
     - FILLED, PARTIALLY_FILLED, FAILED et SUBMITTED ont leurs types
       (`lib/contracts/events.ts` les déclarait déjà ; le miroir C# ne les
       avait pas) ;
     - un rejet se mappe qu'il porte un accusé ou un rapport ;
     - une charge illisible est comptée à part (`unmapped` sur `/health`)
       sans marquer la base en panne ;
     - `dbError` s'efface à la première écriture réussie.

  Tests : `dotnet test` 75/75, dont 17 nouveaux (sockets en boucle locale
  pour le registre et le framing), trois passages stables. **Non vérifié en
  réel** : le conteneur backend n'a pas été reconstruit (geste Docker laissé
  à l'utilisateur). **Resté ouvert** : comment le cockpit affiche un rapport
  REJECTED reçu sous `execution.command.rejected` (le store attend un
  accusé) — lecture de `lib/realtime/store.ts` pas faite dans cette session.
