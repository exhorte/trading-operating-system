# ADR 0037 — Cycle de vie des workers MT5 : une annulation ne laisse jamais un worker vivant

Date : 2026-11-05. Statut : **accepté** — demande d'Exhorte du 2026-11-05 (« écris l'ADR, puis corrige la fuite de workers MT5 »), avec trois validations distinctes et une condition : **pas de passage à
`armed` ou `autonomous` tant que ce défaut n'est pas corrigé et validé**. **Ne touche à aucun garde-fou, à aucun chemin d'exécution, ni à l'agent MQL5** (compilé `OBSERVE`) ; Claude ne change aucun mode.

## Contexte

Le 2026-11-05, le superviseur du cœur a enregistré quatre incidents (`scheduler_stalled`, `mt5_disconnected`). L'analyse en lecture seule (événements du cœur, table `ticks`, journaux Windows, MT5 et base)
a établi ceci :

- Chaque série est une **reconnexion lancée par le superviseur** (`account.disconnected`, motif `reconnect`). Elle a duré 5 s, 36 s, puis **5 min 23 s** (12:38 → 12:43 UTC, neuf workers lancés) ; aucune
  cote n'a été enregistrée pendant 7 min 16 s. Le courtier n'a pas coupé (journal du terminal MT5 vide de toute perte de connexion), et Windows n'a rien signalé (ni veille, ni heure, ni réseau, ni disque).
- Après la panne, **huit paires de processus worker** (le `python.exe` du venv, qui est un lanceur, et l'interpréteur réel qu'il démarre en enfant) restaient **vivantes et inactives** — trente-cinq minutes
  plus tard. Aucun appel à `_kill()` n'avait été fait pour elles.
- Le mécanisme est dans le code. Le job `supervisor` a un délai de **30 s** (`runtime/engine.py`) ; un `initialize` MT5 peut en prendre **60** (`SLOW_CALLS`, `infrastructure/mt5/transport.py`). Quand le
  planificateur annule le job (`asyncio.wait_for`), l'annulation traverse `SubprocessTransport.call()`, qui ne gère que `TimeoutError` et les erreurs de pipe : **le worker n'est pas tué**. Puis
  `AccountService.connect()` ne nettoie que sur `TradingOsError` : le compte reste « en cours de connexion » (`_connecting`) et le client abandonné n'est jamais déconnecté.
- **Reproduit** avec la vraie classe `SubprocessTransport` et le backend simulé (aucun contact avec MT5) : après une annulation externe pendant un appel, le worker reste vivant (deux processus) et un
  thread de l'executor par défaut reste bloqué.

Ce qui **n'est pas établi** : ce qui a déclenché les coupures. Elles coïncident avec le lancement d'applications lourdes sur le poste (application Claude de bureau à 10:53, VS Code et ses extensions à 12:32)
et, pour la première, avec un `fsync` de la base à 6 s ; aucun historique de charge ne permet de le confirmer. Cet ADR n'en fait pas une hypothèse de travail.

## Décision

1. **Une annulation termine le worker.** `SubprocessTransport.call()` tue le worker quand l'appel est annulé de l'extérieur (échéance d'un job, arrêt), avant de laisser l'annulation se propager, et à
   l'abri d'une seconde annulation. C'est la règle qui existe déjà pour le dépassement du délai : un appel dont la réponse ne sera jamais lue ne laisse pas de worker derrière lui.
   Laisser le worker vivre n'est pas une option sûre : le thread de l'executor qui attend sa réponse ne peut pas être annulé, il continue de lire le tube, et un worker bloqué dans un appel natif y garde
   ses enfants.
2. **Un worker se tue en entier.** Sous Windows, tuer le lanceur ne suffit pas : l'interpréteur réel, bloqué dans un appel natif, ne voit jamais le tube se fermer. Toute fin de worker (annulation, délai
   dépassé, fermeture, remplacement d'un worker mort) tue **l'arbre** (`taskkill /T /F`), puis `Popen.kill()` si le processus vit encore.
3. **`shutdown` ne démarre jamais de worker.** Sur un transport sans worker vivant, `call("shutdown")` ne fait rien : il n'y a rien à arrêter. Sans cela, le nettoyage qui suit un échec relançait un worker
   — deux processus — juste pour le fermer.
4. **`AccountService.connect()` nettoie sur annulation comme sur échec** : le compte sort de `_connecting`, le client de la tentative est déconnecté (à l'abri d'une seconde annulation), puis
   l'annulation est ré-élevée. Aucun état « en cours de connexion » ne survit à la tentative.
5. **Un compteur de cycle de vie, en lecture seule.** Le transport tient un registre (`WORKERS` : lancés, terminés, vivants) exposé dans `GET /api/system/health` sous `mt5Workers`. Valeur attendue : un
   worker vivant par compte connecté, un de plus pendant une reconnexion. Un écart durable est une fuite, visible sans outil extérieur. **Aucun garde-fou, aucun mode ne lit ce compteur** : c'est de la mesure,
   pour les validations 2 et 3.
6. **Condition posée par Exhorte.** Tant que les validations 1 et 2 ne sont pas faites, le plafond reste `OBSERVE` : pas d'`armed`, pas d'`autonomous`. Le cœur ne le change pas de lui-même et Claude ne le
   fait jamais ; la décision de relever un mode reste celle d'Exhorte (ADR 0015).

## Coût connu

Tuer le worker d'un appel annulé qui était **sain** oblige à rattacher le compte : le worker suivant démarre sans terminal initialisé, ses lectures échouent, et le superviseur relance la connexion (le même
chemin qu'après un dépassement de délai). Ce coût est jugé acceptable parce que les seules annulations qui atteignent le transport sont **l'échéance d'un job** (le cœur est déjà en difficulté) et **l'arrêt du
cœur** (le middleware de sécurité est de l'ASGI pur : une requête HTTP abandonnée n'annule rien).

## Laissé ouvert, volontairement

- **Le délai du job `supervisor` (30 s) contre `initialize` (60 s).** Une reconnexion plus lente que 30 s est coupée par son appelant avant que le transport ne renonce ; et `Supervisor.tick()` n'écrit ni
  incident ni santé pour le tour annulé (`collect → act → track_incidents → publish_health`, `act` attend la reconnexion) : c'est pourquoi des incidents ont été publiés plus d'une minute après leur
  ouverture. Deux voies : (A) lancer la reconnexion dans sa propre tâche, avec son échéance ; (B) relever le délai du job au-dessus de `initialize` (~90 s), au prix d'une détection plus lente d'un
  superviseur lui-même bloqué. **Non décidé ici** : l'effet réel de ce décalage sur la durée des coupures n'est pas mesuré. Après la validation 3.
- **Le déclencheur des coupures.** Voir ci-dessus.
- **La politique de reconnexion** (délais 5, 10, 20, 40, 60 s) : inchangée.

## Ce que cet ADR ne fait pas

- Il ne change ni le Risk Engine, ni la validation des ordres, ni l'agent, ni un mode, ni un plafond. Il n'envoie aucun ordre.
- Il ne remplace pas la politique d'« échec fermé » : un cœur qui ne lit plus MT5 refuse toujours d'agir.
- Il ne nettoie pas les processus déjà orphelins du cœur en marche : ils disparaissent au redémarrage contrôlé de la validation 2 (leurs tubes se ferment avec le cœur), ou sur ordre explicite d'Exhorte.

## Validations (trois, distinctes)

1. **Simulation.** Tests d'annulation sur la vraie classe de transport et le backend simulé : le worker et tout ce qu'il a lancé ont disparu après une annulation, après un dépassement de délai et après une
   fermeture ; `shutdown` ne lance rien ; un `connect()` annulé ne laisse ni compte « en cours de connexion » ni client ouvert ; le compteur revient à sa valeur de départ. Puis `ruff`, `mypy`, `gen-types
   --check` et la suite complète.
2. **Cœur réel, redémarrage contrôlé, sans ordre.** Après redémarrage, compte rattaché sans mot de passe : `mt5Workers.alive` = 1 et exactement une paire de processus worker ; plusieurs rattachements
   successifs ne font pas monter ce nombre. Aucun clic sur un bouton d'exécution, aucun mode relevé.
3. **Cause des coupures.** Seulement après collecte de métriques (compteur ci-dessus, incidents, trous de cotes, charge du poste pendant une période), et sans hypothèse retenue d'avance.

## Conséquences

- Tests : `tests/integration/test_mt5_worker_process.py` (annulation, délai, `shutdown`, compteur), `tests/unit/services/test_accounts_service.py` (`connect()` annulé), `tests/unit/api/test_system_routes.py`
  (le champ de santé).
- Types : `lib/api/generated.ts` régénéré (`gen-types`) ; aucun changement visible dans le cockpit.
- Documentation : runbook (processus worker attendus), état, journal de session, HANDOFF.
