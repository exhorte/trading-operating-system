# État du projet

Dernière mise à jour : 2026-11-01 (soir : connexion, base migrée, application lancée). Instantané seulement — l'historique vit dans `session-log.md` (ADR 0008) et dans le journal de chaque fiche d'outil. Réécrit le 2026-10-09 : l'ancien instantané décrivait la pile .NET/SignalR/observateur, qui n'existe plus. Le 2026-11-01 : vérification Git — `origin/main` **contient** la migration (PR #1 fusionnée sur GitHub, `44e797c`) ; seul le `main` **local** est en retard (`e53a4ac`, mise à jour en avance rapide possible). Le correctif du 2026-10-31 (« non fusionnée ») était lui-même périmé.

## En une phrase

Poste de travail personnel pour trader intraday, sorti de la recherche d'edge (ADR 0002) et désormais **Python-native** (ADR 0016) : un cœur Python (FastAPI, REST + un WebSocket) porte tout le métier, le cockpit Next.js n'affiche que ce qu'il sert, l'agent MQL5 reste l'exécutant local et le garde-fou. Le Gateway .NET, SignalR et l'observateur Python sont **supprimés**. Un seul `OrderSend` existe dans le dépôt (EA-05, `ExecuteOrder`), structurellement inatteignable hors `CONFIRM` — plafond de mode compilé à `OBSERVE` — : **aucun ordre n'a jamais été envoyé à un courtier**. La migration est faite et testée ; **rien n'a encore tourné contre un vrai terminal MT5, un vrai agent ou la vraie base `tradingos`** : le premier rattachement d'un compte réel reste à faire, par l'utilisateur, en `OBSERVE`.

## Ce qui existe et fonctionne

Vérifié avec un terminal **simulé**, des sockets réels sur la boucle locale, un PostgreSQL jetable et un Chrome headless contre le vrai cœur — pas avec un compte.

| Brique | Où | État |
|---|---|---|
| Cœur Python | `python/trading_os/` | `domain/` pur (comptes, marché et analyse ICT/SMC, stratégie S01, risque, exécution, positions, autonomie, journal), `services/`, `infrastructure/` (lecteur MT5 en processus enfant à liste blanche, lien agent, base, FRED), `api/`, `runtime/`, `cli/`, `mcp/`. 2197 tests (2026-11-01), `ruff` et `mypy --strict` propres. |
| API et flux | `api/`, `lib/api/generated.ts` | 59 opérations nommées, un WebSocket `/ws` (54 événements, instantané en première trame, file bornée par client). Jeton du cockpit **et** Origin sur chaque requête, lectures comprises. Les types du cockpit sont générés depuis les schémas du cœur ; un test échoue s'ils sont périmés. |
| Risk Engine | `domain/risk/`, `services/risk.py` | point de contrôle unique ; mêmes règles internes pour Exness et FTMO (plafonds contractuels du fournisseur en plus), verrous **persistants** levés par accusé, kill switch, dimensionnement avec les spécifications réelles du symbole (testé sur XAUUSD, EURUSD, GBPUSD, GBPJPY, BTCUSD). **ADR 0019 (2026-11-01)** : risque par trade dynamique (grille de performance vs capital initial, déclencheur 200 $, budgets jour/semaine/total restants — le minimum l'emporte), 15 trades/jour, 5 positions, perte hebdomadaire 10 %, arrêt à −5 %. Règles : `context/domain/risk_rules.md`. |
| Exécution | `domain/execution/`, `services/execution.py`, `services/senders.py`, `infrastructure/mt5/ea_link.py` | commande persistée **avant** tout envoi, idempotence aux deux bouts, états explicites (`UNKNOWN` ne se rejoue jamais), réconciliation avec MT5. Seul `OPEN` est envoyé : `MODIFY`, `CLOSE`, `PARTIAL_CLOSE`, `CANCEL` sont refusés à la soumission (`AGENT_CAPABILITY_MISSING`). |
| Autonomie | `domain/autonomy/`, `services/autonomy.py`, `services/readiness.py` | échelle OFF → OBSERVE → PAPER → CONFIRM → ARMED → AUTONOMOUS (+ HALTED), bail d'armement, readiness de 16 contrôles. **AUTONOMOUS est bloqué, volontairement** : aucune sortie S01 (dette TD-09) et capital de référence non fixé. |
| Stratégie S01 | `domain/strategy/s01/`, `services/strategy.py` | intégrée au cœur (plus de pipeline de trois processus) ; évalue à chaque clôture de bougie, écrit son verdict dans `setup_proposals`. **N'a encore rien proposé en réel** (dernière mesure : 2026-09-18, entonnoir bloqué à `range_location`). |
| Agent MQL5 | `tools/mt5-execution-agent/` | build **1.11** : refus `DEAD_MAN` (aucun ping du cœur depuis 30 s), capacité `dead_man`, `coreSilentMs`. Compile sans erreur ni avertissement ; **pas déployée** dans le terminal de l'utilisateur (à recompiler et rattacher). Un test lit sa source : un seul `OrderSend`, plafond `OBSERVE`, homme mort. |
| Cockpit | `app/`, `components/`, `lib/` | 12 écrans (ADR 0017), clair et sombre, bureau et mobile (les quatre combinaisons vérifiées) ; client typé, WebSocket, store pur. Vérifié dans un vrai navigateur : aucune erreur console, aucun débordement, contraste AA. Le dossier d'un trade est une page de **chiffres** (ADR 0018) : plus de capture graphique. |
| Base | `docker-compose.yml`, `python/…/migrations/` | un seul conteneur Docker (TimescaleDB, volume existant ; `127.0.0.1:5433` par défaut, `TRADINGOS_DB_PORT` pour un autre port — **5434 depuis le 2026-11-01**, 5433 étant pris par un autre projet). Migrations 0001–0004 (additives, sommes de contrôle), **appliquées à la vraie base le 2026-11-01 après sauvegarde** (l'ancienne table de suivi .NET est conservée sous `schema_migrations_dotnet`) ; les scripts destructeurs (`drop_legacy_tables`, `drop_capture_window`) restent manuels. |
| Démarrage | `scripts/start.ps1` | jetons, base, schéma, jeton de l'agent, cœur, cockpit ; `-Simulated` (terminal de démonstration), `-Plan` (ne fait rien). Vérifié en `-Plan` ; **jamais lancé pour de vrai** : il exige 3000, 8000 et 5433, pris par d'autres projets le 2026-11-01 — l'application a été lancée à la main sur 3001 / 8001 / 5434 (runbook). |
| Outils | `python -m trading_os …` | export/import de bougies, `list-symbols`, `spread-history`, `weekly-review`, `mcp` (lecture seule), `gen-types`. |

## Ce qui a été supprimé

Le 2026-09-04 : la recherche d'edge et la mémoire de la série 1 (`pivot-2026-09-04.md`). Le 2026-10-09 : le Gateway .NET (`backend/`), SignalR, l'observateur Python (`tools/mt5-observer`), l'exportateur de bougies et le worker S01 comme processus séparés, les scripts Node, le serveur MCP et la revue hebdomadaire en TypeScript, `scripts/start-live.ps1`, le service `backend` de Docker (conteneur et image compris), la chaîne `lib/{analysis,risk,setup,domain,contracts,execution,market,mock}` et le client SignalR du cockpit (leur logique vit dans le cœur Python), et la capture graphique (ADR 0018). Inventaire exact : `docs/architecture/python-native-migration-report.md`.

## Ce qui bloque, ou reste à décider

- **Le critère de sortie de la Vague 1 n'est pas rempli** : deux incidents réels de lockout contourné (2026-09-14, découvert le 09-17 ; 2026-09-15), six trades ouverts pendant un verrou actif. T02c (2026-09-17) a durci le verrou — alerte en direct, accusé obligatoire pour lever un verrou non chronométré — ; ça prévient la récidive, ça ne referme pas ce qui s'est passé. La pause de 30 min sur deux pertes consécutives (T02b) n'a jamais été déclenchée en réel.
- **EA-07 (CONFIRM) reste fermé** : conditions de sa fiche non remplies (T02b jamais déclenché en réel ; taux d'accord d'EA-02 inconnu, zéro proposition ; Vague 1 non close). Aucune consigne générale d'« avancer » ne vaut accord ; ADR 0013, 0014, 0015, EA-07, EA-08 sont accordés *incrément par incrément*, chacun dans son ADR ou sa fiche (`.claude/CLAUDE.md`).
- **Autonomie (ADR 0015, valeurs de limites amendées par l'ADR 0019 le 2026-11-01 : 15 trades, 5 positions, risque dynamique 0,1–1,5 %)** : limites du compte réel écrites par l'utilisateur — killzones de S01, arrêts à 20 R et à 50 trades — mais il manque le **capital de référence** et la mesure du spread du compte réel ; restent ouverts le plafond de stop à 7 pips et la demi-heure de Francfort (`02_Plan_Projet/regles-deduites-scalp-marco-2026-09-26.md`). `position_management_valid` échoue tant que S01 n'a pas de sortie (TD-09). L'entrée `LIMIT` de S01 n'est pas portée par le protocole de l'agent (marché seulement).
- **Formulaire de connexion (ADR 0013 I3, ADR 0020, ADR 0021, T13) construit le 2026-11-01** — sur Account, et à la place de tout écran vide ; **un seul compte connecté à la fois** (imposé par le cœur). La démo Exness est enregistrée et rattachée (capital 10 000 $, profil FTMO 2-Step), sans mot de passe, et ses données s'affichent ; le chemin **avec** mot de passe n'a pas été éprouvé contre un vrai courtier (il l'est à la main, par l'utilisateur). Stockage du mot de passe dans le coffre : pas proposé par le formulaire.
- **Le sort des tables héritées** (`db manual drop_legacy_tables`, et `drop_capture_window`) est une décision de l'utilisateur : rien ne les supprime tant qu'il ne l'a pas demandé. La migration est dans `origin/main` (PR #1) ; le `main` local n'a pas été mis à jour.

## Prochaine action

La migration est dans `origin/main` (PR #1, vérifié le 2026-11-01). À faire **par l'utilisateur**, dans l'ordre :

1. Mettre le `main` local à jour (`git switch main` puis `git pull --ff-only`) et décider du sort de `migrate.py` (modification non commitée, voir `HANDOFF.md` du vault).
2. **Premier essai réel, en `OBSERVE`** : sauvegarde `pg_dump -Fc` de la vraie base (la dernière connue est `backups/tradingos-2026-09-25-pre-rebind.dump`, hors dépôt, du 2026-09-25) ; `pwsh -File scripts\start.ps1 -Plan`, puis sans `-Plan` (le schéma 0001–0003 s'applique, additif) ; ouvrir MT5 connecté ; recompiler l'agent 1.11 et le rattacher (`tools/mt5-execution-agent/README.md`) ; enregistrer le compte dans Settings, écrire ses limites, cocher « Ces limites sont les miennes » ; `MT5_LIVE_TESTS=1 python -m pytest tests/integration/test_terminal_contract.py -m live_mt5` (lecture seule).
3. Laisser tourner S01 pendant les killzones (06:00–09:00 et 11:00–14:00 UTC en heure d'été) : c'est la seule façon de mesurer l'accord machine / trader (EA-02).
4. Seulement ensuite, les incréments I3 à I8 de l'étude (`02_Plan_Projet/etude-connexion-pilotage-agent-2026-09-25.md`), un à la fois, chacun après son ADR ou sa fiche, sur le cœur Python.

## Questions ouvertes

- Quel déclencheur pour le multi-compte ? Par défaut : le jour où un deuxième compte prop firm est ouvert.
- Le compte FTMO existe-t-il déjà ? Toute la modélisation de ses règles est urgente ou spéculative selon la réponse.
- Veut-on pousser un trade manuel par le même chemin d'exécution, pour qu'il soit journalisé identiquement ?
- Le cœur doit-il refuser d'armer un agent qui n'annonce pas la capacité `dead_man` (build < 1.11) ? Aujourd'hui il l'accepte et la documentation le dit.
- Y a-t-il un besoin de superviser le cœur lui-même (tâche planifiée Windows, service) ? Aujourd'hui sa fenêtre reste ouverte, rien ne le relance.
