# ADR 0016 — Architecture Python-native : le cœur du Trading OS est un monolithe Python

Date : 2026-10-07. Statut : **accepté** — décision de l'utilisateur dans la
mission du 2026-10-07 (« DÉCISION ARCHITECTURALE DÉFINITIVE : Python devient le
cœur opérationnel, le frontend reste Next.js, MetaTrader 5 reste la passerelle,
l'EA reste un agent local d'exécution et de sécurité »). Les points marqués
**« à confirmer »** sont des interprétations de l'assistant, prises là où la
mission était ambiguë ; ils sont listés pour relecture.

Supersède, pour la pile : la section « Backend — .NET » et « Temps réel —
SignalR » de l'ADR 0003. Amende l'ADR 0004 (le TypeScript n'est plus le modèle
canonique : c'est le modèle Python), l'ADR 0013 (stockage opt-in des
identifiants, voir plus bas) et réalise le « Risk Engine côté serveur » exigé
par les ADR 0007 et 0015 (I6). N'amende pas l'ADR 0010 : le chemin d'exécution
est le même, seul l'émetteur change.

## Contexte

Le backend .NET (≈ 4 900 lignes) n'était qu'un **relais** : il traduisait les
messages de l'observateur Python et de l'agent MQL5 en enveloppes, les
diffusait par SignalR et les écrivait en base. La logique qui décide (Risk
Engine, verrous, contexte de marché, détection S01) vivait ailleurs :
en TypeScript, **dans l'onglet du navigateur** (`lib/risk`, `lib/analysis`,
`lib/setup`, évalués par `signalr-client.ts`) ou dans un worker Node lisant des
fichiers exportés par un script Python. Résultat : quatre langages, dix
processus lancés à la main, des contrats recopiés trois fois (TS, C#, SQL),
des traductions en cascade — et un Risk Engine sans autorité (« aucun ordre ne
l'oblige à avoir été consulté », audit du 2026-10-05, C-01/TD-02).

`docs/architecture/migration-map.md` (Phase 0) détaille l'état mesuré.

## Décision

**Un monolithe modulaire Python — un seul processus d'exploitation — porte tout
ce qui décide et tout ce qui orchestre. Le cockpit Next.js lui parle en REST et
en WebSocket ; MetaTrader 5 est atteint par l'API Python officielle ; l'EA
reste l'exécutant local.**

```
Next.js ──HTTP/WS──▶ FastAPI ─▶ Cœur Python (domaine, services, supervision)
                                   ├─ API Python MetaTrader5 (lecture) ─▶ MT5 ─▶ Exness | FTMO
                                   └─ lien TCP 9765 ─▶ EA (exécution locale, garde-fou) ─▶ MT5
```

1. **Python est le cœur** : comptes, données de marché, contexte, stratégie,
   Risk Engine, exécution, positions, réconciliation, journal, autonomie,
   supervision. Modules internes d'un même processus ; aucun microservice.
2. **.NET, SignalR, le Gateway et tous les ponts/traducteurs sont supprimés**
   (liste exacte dans `docs/architecture/python-native-migration-report.md`).
3. **Un seul modèle de données** : modèles pydantic → schéma OpenAPI/WebSocket →
   types TypeScript *générés*. Plus de miroirs écrits à la main.
4. **Le Risk Engine est le point de contrôle unique, côté serveur** : aucune
   commande n'est créée sans `RiskDecision` approuvée, liée à un `accountId`
   (ADR 0007 renforcé ; ADR 0015, I6).
5. **Le plafond de mode reste `OBSERVE` par défaut** (`TRADING_MODE`) et ne se
   relève que par un geste de l'utilisateur. L'autonomie ne s'active que si le
   rapport de « readiness » est vert.

### Interprétations (à confirmer)

- **L'exécution passe par l'EA, pas par `mt5.order_send()` depuis Python.**
  La mission cite `send_order/modify_position/close_position` pour le client
  MT5 et, ailleurs, fait de l'exécution une responsabilité de l'EA. Je retiens
  l'EA : (a) l'unique `OrderSend` du dépôt reste celui de `ExecuteOrder`,
  structurellement inatteignable (`g_mode_ceiling` = `const MODE_OBSERVE`) —
  aucun second chemin d'ordre n'est créé ; (b) un **homme mort** n'a de sens
  que si l'exécutant est un processus distinct du cerveau ; (c) les barrières
  locales (symboles, volume, stop obligatoire, spread, identité du compte)
  restent une dernière barrière que le cœur ne peut pas contourner. Le client
  MT5 du cœur ne contient **aucune** fonction d'ordre : son processus de
  lecture n'accepte qu'une liste blanche de fonctions en lecture seule.
  *Envoyer directement depuis Python serait un élargissement du chemin
  d'exécution qui demande un accord nommé (`.claude/CLAUDE.md`).*
- **Le cœur tourne sur l'hôte Windows, pas dans Docker.** Le paquet
  `MetaTrader5` est Windows-only et lié à un terminal local. Docker garde la
  base (TimescaleDB, volume existant inchangé) ; un conteneur du cœur n'aurait
  pas MT5.
- **Un processus de lecture MT5 par terminal.** Le module `MetaTrader5` est
  global au processus et bloquant ; un appel qui se bloque ne doit jamais
  figer le cœur (heartbeat, homme mort). Chaque terminal/compte connecté a
  donc un processus enfant à liste blanche, géré par le cœur. Le multi-comptes
  *simultané* exige un terminal par compte ; sur un seul terminal les comptes
  se succèdent, avec le refus de bascule de l'ADR 0013 (positions ouvertes,
  ordres en attente ou session armée).
- **Identifiants — opt-in, jamais par défaut.** Le comportement de l'ADR 0013
  reste le défaut : le terminal est déjà connecté, ou le mot de passe est
  fourni au `connect` et ne vit que le temps de l'appel (jamais stocké, journalisé,
  persisté, renvoyé). La mission demande en plus une abstraction `CredentialStore` :
  elle existe (`infrastructure/security/credentials.py`), avec un magasin
  *nul* par défaut et un magasin du coffre Windows activable explicitement
  (`CREDENTIAL_STORE=windows`). Jamais dans la base, les événements, les
  journaux, les exceptions ni le frontend ; le frontend ne les reçoit jamais.
  La règle de `.claude/CLAUDE.md` (« aucun mot de passe de compte n'est
  stocké… ») est réécrite en ce sens.
- **Port 9765 conservé** pour le lien EA : c'est le défaut de l'entrée
  `InpGatewayPort` et celui des préréglages `.set` de l'utilisateur ; le
  changer casserait l'agent déjà installé pour un gain nul. Le port 5080
  (ancienne API) et 8765 (observateur) disparaissent ; l'API est sur 8000.
- **Cet ADR vit dans `context/adr/`** (convention du dépôt, lue au début de
  chaque session) et non dans `docs/adr/` comme la mission l'écrivait.

## Conséquences

- `backend/`, `lib/realtime/signalr-client.ts`, l'observateur WebSocket,
  l'exportateur JSONL, le worker Node S01, les scripts de démarrage actuels et
  le harnais `dev-submit-command.ts` sont supprimés quand leurs consommateurs
  ont migré (phases 3 à 7 ; garde-fous dans la migration-map).
- **`.claude/CLAUDE.md`** : « Un **appel d'exécution** existe… » reste vrai
  (rien n'est ajouté) ; la règle des identifiants est réécrite (ci-dessus) ;
  la mention du Risk Engine « dans le navigateur » disparaît.
- **ADR 0013/0014/0015.** Leur conception tient : connexion sans stockage par
  défaut, armement sous bail renouvelé **côté serveur** (le cœur renouvelle,
  l'EA se coupe au silence), plafond de mode, limites par compte. Ce qui
  change est *qui* l'implémente : Python. Les accords nommés restent
  attachés à leurs incréments ; cet ADR n'en crée aucun nouveau.
- **Rien ne s'active seul.** À la livraison, le plafond est `OBSERVE`, l'EA
  est compilé `OBSERVE`, la readiness d'AUTONOMOUS échoue (la gestion de
  sortie de S01 n'existe pas, le capital de référence n'est pas fixé). Passer
  au-dessus est un geste de l'utilisateur, jamais de l'assistant.
- **Persistance.** Une commande est écrite `PENDING` *avant* d'être envoyée ;
  base indisponible = refus (échec fermé). Seuls les ticks passent par une
  file bornée. Le schéma existant reste valide ; les ajouts sont additifs ; la
  suppression de l'ancienne table `envelopes` est un script manuel séparé.
- **Dette assumée** : multi-comptes simultanés nécessitant plusieurs
  terminaux ; sorties de S01 et classement des retours courtier ambigus de
  l'EA (F03/F04/F05 de l'audit) restent à traiter avant tout ordre réel ;
  `account-analysis` reste calculé dans le cockpit (présentation, pas une
  gate).
- **Vérification.** Tests unitaires, d'intégration (sockets réels, base
  jetable) et de contrat ; recherche globale prouvant l'absence de dépendance
  fonctionnelle à .NET/SignalR/Gateway ; rapport final
  (`docs/architecture/python-native-migration-report.md`).
