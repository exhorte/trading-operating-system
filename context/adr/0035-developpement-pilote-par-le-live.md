# ADR 0035 — Développement piloté par le marché réel et le courtier

Statut : accepté le 2026-11-03 — exigence prioritaire d'Exhorte (« données réelles dès maintenant, feedback court, amélioration continue, sécurité explicite et aucune validation fictive »). Cet ADR change la **méthode** de travail ; il ne retire, n'assouplit ni ne contourne aucun garde-fou (ADR 0007, 0014, 0015, 0033, 0034 inchangés).

## Contexte

Jusqu'ici le cœur a été vérifié avec un terminal simulé (`infrastructure/mt5/fake.py`), des tests unitaires et le mode `OBSERVE`. Le 2026-11-03 le cœur lit pourtant déjà **le vrai terminal MT5** de la démo Exness (ticks, bougies sur six échelles, spécifications des symboles, solde, positions, réconciliation), mais l'agent MQL5 n'est pas attaché : rien du chemin d'exécution n'a été éprouvé chez le courtier. Les mesures du jour sont dans `context/execution/live-baseline-2026-11-03.md`.

## Décision

### 1. La preuve est un fait observé au terminal ou au courtier

Chaque amélioration répond à trois questions écrites dans sa note : **quel problème réel** elle corrige, **quelle preuve** (journal, événement, tick, bougie clôturée, spread, latence, réponse ou rejet du courtier, position, réconciliation) montre qu'il existe, **comment** on vérifie la correction. La boucle est : observer → collecter → cause exacte → hypothèse → modifier le composant responsable → tester en conditions réelles → comparer avant/après avec une métrique → conserver, ajuster ou annuler → documenter.

Un comportement n'est dit **validé** que si une réponse réelle du terminal ou du courtier l'a confirmé ; sinon la fiche écrit « non vérifié sur le live ». Une commande envoyée n'est pas une commande exécutée ; un état inconnu se réconcilie avant toute nouvelle tentative (ADR 0034, inchangé).

### 2. `OBSERVE` n'est plus le mode de développement

`OBSERVE` reste le mode de **diagnostic et de récupération** (lecture seule, démarrage, après un incident). Le développement s'appuie sur les données live et, dès que les verrous ci-dessous sont levés par Exhorte, sur l'exécution sur la **démo** (réponses réelles du courtier). Les tests unitaires et les simulations restent utiles pour une fonction isolée ; ils ne remplacent pas une validation d'intégration live et ne sont pas un passage obligé avant chaque changement.

### 3. Une donnée manquante, obsolète ou incohérente est signalée et bloque ce qui en dépend

Rien n'est inventé, interpolé ni remplacé en silence. Le code le fait déjà pour le calendrier (échec fermé), les portes de risque (« n/a », jamais un passage fabriqué), la fraîcheur des cotes sur marché ouvert, la lecture du terminal. Les écarts restants sont listés dans la note de mesures (G1 à G4) et deviennent les incréments L1 à L3.

### 4. Les verrous de l'exécution sur la démo sont des gestes d'Exhorte, pas des obstacles à contourner

Pour qu'une commande atteigne le courtier de la démo, il faut, **dans cet ordre de dépendance** : (a) l'agent MQL5 attaché à un graphique (sinon `kill_switch_available` et `heartbeat` bloquent) ; (b) l'agent compilé avec un mode au-dessus de `OBSERVE` — constante de compilation, **décision d'Exhorte** (ADR 0010, 0029, 0034) ; (c) le plafond du compte (`maxMode`, aujourd'hui `OBSERVE`) et `TRADING_MODE` du cœur relevés ; (d) les limites de risque **écrites par l'utilisateur** (`account_limits_configured`, ADR 0015) ; (e) la préparation verte, puis « DÉMARRER LE SYSTÈME » et, séparément, l'autorisation de l'automatique. Aucun garde-fou n'est désactivé « pour aller plus vite ». Le passage à un compte réel reste distinct, explicite et protégé (ADR 0015, bannière de compte réel, ADR 0034).

### 5. Ce qui ne change pas pour Claude

Claude ne déclenche pas lui-même d'ordre, d'armement ni d'autonomie, ni en démo ni en réel, et ne clique pas les boutons d'exécution (`.claude/CLAUDE.md`). Cet ADR **ne lève pas** cette règle : Claude collecte et lit les preuves en lecture seule, prépare les mesures, analyse les réponses du courtier après l'essai que fait Exhorte. Lever la règle pour la démo demanderait une décision explicite et séparée d'Exhorte, écrite ici ou dans un nouvel ADR.

## Incréments (ordre proposé, chacun avec son critère mesurable)

* **L1 — Mesures live permanentes (lecture seule).** Enregistrer : fréquence et âge des ticks par symbole, série et distribution du spread (min, médiane, p95, max par fenêtre), temps de réponse EA ↔ cœur, durées du cycle de vie des commandes (créée → envoyée → accusée → exécutée), codes de retour du courtier. Critère : un rapport avant/après produit sans geste, sur la démo, avec les chiffres du 2026-11-03 comme base.
  **Construit le 2026-11-03** : `GET /api/system/live-metrics?minutes=` (spread, cadence et retard de réception des cotes, état du lien agent, durées et codes de retour des commandes — en lecture seule) et `python -m trading_os live-report` (même mesure sur n'importe quelle fenêtre, depuis la base seule, page Markdown dans `exports/live/`). Ce qu'il **ne** mesure pas est écrit dans chaque réponse (`notMeasured`) : la latence au repos entre le cœur et l'agent — le battement de l'agent envoie `latencyMs = 0` en constante et le ping n'est pas renvoyé — donc seul l'aller-retour d'une commande (envoyée → accusée) est une mesure. Pour la mesurer au repos il faut un agent qui renvoie le ping avec un horodatage (**L1b**, changement de l'agent MQL5 : à recompiler et réattacher, geste d'Exhorte, accord séparé).
* **L2 — Ticks avec horodatage à la milliseconde.** Aujourd'hui un sondage à 1 Hz expose une seconde entière ; relire `time_msc` pour mesurer le vrai âge d'un tick et la variation fine du spread. Critère : âge d'un tick connu à ±100 ms.
* **L3 — Spécification et coûts réels.** Ajouter à la spécification du symbole ce que le courtier fournit (swap long/short, mode de remplissage, sessions de négociation) et comparer la commission configurée (`commissionPerLotRoundTrip`, aujourd'hui une valeur de réglage) à celle des transactions réelles (`commission` + `swap` des deals, déjà lus). Critère : aucun coût utilisé par une porte n'est une valeur par défaut non confirmée sans l'écrire.
* **L4 — Première exécution sur la démo (geste d'Exhorte).** Une position minimale, ouverte puis fermée depuis le cockpit avec l'agent compilé au-dessus de `OBSERVE` ; Claude relève ensuite : délais, `retcode`, glissement, commission, swap, réconciliation, disparition de la position du terminal. Critère : chaque ligne du protocole `context/execution/protocol.md` confirmée par une réponse réelle, ou marquée « non vérifié ».
* **L5 — Coupures et redémarrages.** Arrêter le cœur, fermer MT5, retirer l'agent, couper le réseau pendant qu'une commande est en vol ; vérifier qu'aucun envoi n'est rejoué et que la réconciliation tranche. Critère : zéro doublon, zéro état `UNKNOWN` laissé sans réconciliation.

## Conséquences

* Chaque note de session distingue ce qui est « vérifié sur le live » de ce qui ne l'est pas ; `state.md` et les fiches d'outil le reprennent.
* La suite de tests existante est conservée ; on n'y ajoute plus de simulation pour valider une intégration que la démo peut prouver.
* Reste à la charge d'Exhorte : compiler l'agent au-dessus de `OBSERVE`, relever les plafonds, écrire les limites, faire l'essai L4.
