# État du projet

Dernière mise à jour : 2026-09-20. Instantané seulement — l'historique vit
dans `session-log.md` (ADR 0008) et dans le journal de chaque fiche d'outil.

## En une phrase

Poste de travail personnel pour trader intraday, sorti de la recherche
d'edge (ADR 0002). T01 et T04 ont été retirés le 2026-09-14 (décision
explicite) ; le critère de sortie de Vague 1 a été reformulé le même jour et
**n'est toujours pas rempli** — deux incidents réels de lockout contourné,
2026-09-15 puis 2026-09-14 (découvert seulement le 2026-09-17, voir « Ce qui
bloque »). Le lockout a été durci en réponse le 2026-09-17 (T02c) : alerte
temps réel dès qu'une position s'ouvre pendant un verrou actif, et accusé de
réception désormais obligatoire pour lever n'importe quel verrou non
chronométré (plus de levée silencieuse au lendemain) — ça prévient une
récidive, ça ne referme pas ce qui s'est déjà passé ; Vague 1 reste ouverte.
L'**agent d'exécution MT5** (ADR 0010) est construit jusqu'au mode
CONFIRM uniquement : Phase 0 et EA-01 à **EA-06 sont livrés**, un seul
`OrderSend` existe (EA-05 incrément 6), **structurellement inatteignable
hors `CONFIRM`** (`g_mode` figé à `OBSERVE`, jamais affecté) — il n'a donc
jamais tourné contre un broker. Ouvrir `CONFIRM` est EA-07, non démarré,
non demandé, et ses propres préconditions ne sont pas remplies. **Vague 2
est livrée** (T06 journal, T07 conformité, T15 serveur MCP, T08 revue
hebdomadaire) — son propre critère de sortie (taux de conformité affiché
en haut du cockpit) est rempli. **S01 s'exécute** depuis le 2026-09-18
(trois gates structurellement fermées ont été corrigées) mais n'a encore
rien proposé ; le pipeline est **à l'arrêt** au 2026-09-20 — voir « Ce qui
bloque ». Détail de chaque brique dans sa propre fiche
(`context/product/tools/`) et dans `session-log.md`, pas ici — ce fichier
reste un instantané.

## Ce qui existe et fonctionne

Validé en live contre le compte de démonstration Exness (XAUUSDm) jusqu'au
28 juillet 2026 : la chaîne temps réel, les contrats, la persistance, le
chemin d'exécution. **Ce que la Vague 1 a ajouté par-dessus (T01–T05) n'a
jamais tourné contre un vrai terminal** — voir « Ce qui bloque ».

| Brique | Où | État |
|---|---|---|
| Chaîne temps réel MT5 → cockpit | `tools/mt5-observer/`, `backend/src/TradingOs.Gateway/`, `backend/src/TradingOs.Host/` | Validée live. Observer Python lecture seule → gateway .NET → SignalR → cockpit. Le gateway .NET tourne **en conteneur Docker** depuis le 2026-09-17 (Smart App Control bloque le binaire natif — runbook §2) ; observer et MT5 restent natifs. |
| Contrats de domaine | `lib/domain/`, `lib/contracts/` | TypeScript portable, miroirs C# dans `TradingOs.Contracts`. |
| Moteur d'analyse | `lib/analysis/` | Swings, structure, liquidité, PD arrays, sessions, ATR. Pur, testé. Sert de source de niveaux — **pas de source de signal**. |
| Risk Engine | `lib/risk/` | Gates FTMO, sizing, lockout (ledger stocké, pause de 30 min sur pertes consécutives depuis T02b), gate calendrier FRED fail-closed depuis T03. Pur, testé. |
| Chemin d'exécution | `lib/execution/`, `lib/domain/execution-state.ts`, `CockpitHub`, `Mt5AgentServer` | `RiskDecision → Command → ACK → Report`, mode `observe`/SIMULATED. Protocole et machine à états figés (EA-03) : `commandId`/`accountId`/`protocolVersion`, `UNKNOWN` de premier ordre, `ACCOUNT_MISMATCH` typé. **Un seul `OrderSend` existe** (`tools/mt5-execution-agent/TradingOsAgent.mq5`, `ExecuteOrder`, EA-05 incrément 6) — première instruction de la fonction : sortie si le mode n'est pas `CONFIRM` ; `g_mode` est un `const` de compilation à `MODE_OBSERVE`, jamais affecté. Chemin prouvablement mort dans ce build. EA-06 (2026-09-16) ajoute la résolution d'`UNKNOWN` (sans trafic tant qu'`OrderSend` reste mort) et le signalement `EXTERNAL_POSITION` (`ScanOpenPositions`, réel dès aujourd'hui) — cockpit sur `/positions`. |
| Comptes et symboles | `lib/accounts/`, `lib/market/symbols/` | EA-04 : `defaultRiskPolicy` résout par compte (registre vide à ce jour — aucun compte FTMO/réel confirmé), registre canonique↔broker EURUSD/GBPUSD/XAUUSD. |
| Agent d'exécution MT5 | `tools/mt5-execution-agent/`, `backend/src/TradingOs.Gateway/Mt5AgentServer.cs` | EA-05 : connexion, heartbeat, réception, validation locale, persistance `commandId → résultat` sur disque — **vérifiés par l'utilisateur contre un vrai terminal** (2026-09-12). Mode figé à `OBSERVE` par construction. |
| Persistance | `backend/src/TradingOs.Persistence/`, `docker-compose.yml` | TimescaleDB port 5433, écriture non bloquante, audit JSONB. |
| Cockpit | `app/(cockpit)/`, `components/` | Coquille sombre et dense ; T01 (sizing) et T04 (ticket) retirés le 2026-09-14 (décision explicite), bandeau kill switch T02a, chrono de pause T02b, chip calendrier FRED T03, viewer de capture T05 (`/journal/[brokerPositionId]`). `/journal` (T06, 2026-09-16) : table filtrable + calendrier P&L + ventilations symbole/session/heure/jour, zéro nouvelle table (vue pure sur `closed_trades`/`position_opens`/`trade_captures`/`setup_proposals`) + colonne Violations (T07). `TopCommandBar` porte désormais `ComplianceBadge` (T07, taux de conformité hebdomadaire — la vraie tête de cockpit, charter.md principe 2), à la place où le P&L irait. `/positions` (EA-06) : divergence — positions externes, `UNKNOWN` résolus. `/preflight` (T09) : verdict `Armé`/`Pas armé` sur les 9 gates du Risk Engine, dont le gate de connexion ajouté par T09, qui lit l'état TCP de l'agent EA-05 (`Mt5AgentServer.IsConnected`) et non l'observer depuis le correctif du 2026-09-18. |
| Captures de trade | `lib/journal/`, `components/journal/`, `trade_captures` | T05 : faits immuables écrits par le Gateway (fenêtre, prix), rendu à la demande côté cockpit via `analyzeMarketContext` — jamais une image pré-rendue (ADR 0009). Écriture fiable même sur aller-retour rapide depuis le correctif du 2026-09-15. **Rendu cassé pour tout symbole hors XAUUSDm** (pas de M15 en base pour EURUSD/GBPUSD) — voir « Ce qui bloque ». |
| Outils standalone | `tools/mcp-server/`, `tools/weekly-review/`, `tools/shared/` | T15 (serveur MCP lecture seule, `npm run mcp`) et T08 (revue hebdomadaire Markdown, `npm run weekly-review`) : deux scripts `tsx` autonomes, toujours via l'API REST existante (`tools/shared/backend-client.ts`, jamais Postgres/MT5 en direct), important `lib/compliance/` plutôt que de le réécrire. |

## Ce qui a été supprimé le 2026-09-04

La recherche d'edge et la mémoire de la série 1, en entier. Liste exhaustive
et raisons : `context/project/pivot-2026-09-04.md`.

## Ce qui bloque

**Le critère de sortie de Vague 1 (reformulé le 2026-09-14) n'est pas
rempli — et c'est plus large qu'on ne le pensait.** Sur ses trois points :
le kill switch a été déclenché et acquitté pour de vrai (2026-09-15, cycle
complet vérifié dans `risk_lockouts` + `kill_switch_acks`) ; les captures
tiennent sur un aller-retour de 60 s (2026-09-15, voir T05) ; mais une
position EURUSDm a été ouverte à 09:36:00 UTC le 2026-09-15 pendant que le
lockout kill-switch était actif (09:34:44 → 09:37:18) — exactement ce que
le critère existe pour détecter. La vague reste ouverte.

**Second incident, découvert le 2026-09-17 en testant T15 — jamais
documenté avant ce jour.** `get_compliance_violations` (T15, réutilise T07)
interrogé sur toute la plage 2026-09-14/15 fait remonter **5 trades EURUSDm
ouverts pendant que la gate « Daily loss guard » était active**, du
2026-09-14 (`lockout-mu1af4l7-8lbceb`, verrouillé 13:37:28, jamais acquitté
— levée seulement le lendemain matin 08:54:25) : positions 3225706315
(13:49:49), 3225729956 (13:52:36), 3225966706 (14:19:50), 3226050174
(14:29:21), 3226089957 (14:35:04) — toutes après le déclenchement, toutes
avant la levée du lendemain. Vérifié à la main contre les horodatages bruts
avant d'être retenu (détail dans le journal de T15) : une position
XAUUSDm ouverte une seconde **avant** le déclenchement (3225577967,
13:36:35.861) n'est, à raison, pas comptée. Ni bug de T15 ni de T07 — un
fait réel sur des données réelles, invisible jusqu'ici parce que personne
n'avait encore posé cette question précise sur toute la plage plutôt que
sur un seul trade isolé. Le critère de sortie de Vague 1 était déjà non
rempli ; ceci ne change pas la conclusion, mais en révèle l'ampleur réelle
— six trades sur deux jours, pas un.

**Traité le 2026-09-17 (T02c)** : l'utilisateur a réagi à cet incident —
« On durcit le verrou, pas juste un ralentisseur », puis « Durcir sans
exécuter » face au choix réel entre renforcer la détection/friction ou
ouvrir EA-07 (refusé : préconditions non remplies, et circulaire — Vague 1
n'est pas close à cause de cet incident précis). Livré : alerte temps réel
(`journal.lockout_violated`, Gateway-direct) et accusé de réception
obligatoire pour tout verrou non chronométré (`shouldAutoClearForNewDay`
supprimée). Détail complet dans `T02-lockout.md`. **Ça ne ferme pas
Vague 1** — les six trades ont déjà eu lieu, le durcissement empêche
seulement une récidive du même genre. Vérifié : gates vertes (tsc, lint,
vitest 210/210, `dotnet build`, `next build`, `python -m py_compile`) et
mode mock (nouvelle config `cockpit-dev-mock`, port 3001) ; **`dotnet test` non
vérifiable ici (Smart App Control) et le chemin Gateway de l'alerte en
direct (`CheckLockoutViolationAsync`) jamais exercé en réel** — il faudrait
un vrai lockout actif et une position ouverte à la main ; seules les
bannières ont été vues, en mode mock.

**Blocage environnemental du 2026-09-17, résolu le même jour par
conteneurisation.** Smart App Control (Windows) est activé sur cette
machine et refuse de charger tout binaire .NET fraîchement recompilé —
confirmé par le journal Code Integrity (« did not meet the Enterprise
signing level requirements », refus déterministe). `dotnet build` reste
propre ; `dotnet run`/`dotnet test` natifs restent bloqués — mais **le
backend tourne maintenant en conteneur** (`docker compose up -d --no-deps
backend`, `context/infrastructure/runbook.md` section 2), ce qui contourne
le problème plutôt que de le résoudre côté Windows. Vérifié en direct de
bout en bout avec de vraies données (compte 477029930, observer connecté,
cockpit natif affichant les vraies valeurs) — détail dans `session-log.md`.
`dotnet test` reste le seul gate non vérifiable sur cette machine tant que
la politique Smart App Control n'est pas ajustée par l'utilisateur.

**S01/EA-02 : le détecteur s'exécute enfin, il n'a toujours rien proposé — et
ce n'est plus un défaut de câblage.** Jusqu'au 2026-09-18, aucune de ses
étapes 2 à 9 n'avait jamais pu tourner : trois gates structurellement
fermées — la gate calendrier sans données (`news_releases` vide depuis
toujours, aucune clé FRED : 370 évaluations sur 370 mortes le 2026-09-15),
l'exportateur écrivant dans un dossier que le worker ne lit pas, et H4/D1
agrégées depuis 25 h de M1 (2 bougies D1 là où `detectSwings` en exige 5,
donc un biais `neutral` inconditionnel). Les trois sont corrigées (fiche
EA-02, entrées du 2026-09-18 ; `session-log.md`). Observé depuis, en direct,
avec un seul worker :

- killzone de Londres du 2026-09-18 : l'entonnoir atteint `sweep` (étape
  4/9) ;
- killzone NY AM du 2026-09-18 (11:00→14:00 UTC) : **356 évaluations
  bloquées à `range_location`** (étape 2) sur EURUSDm et GBPUSDm — biais
  baissier, donc vente uniquement en zone prime, prix resté en zone décote
  toute la killzone ; aucun rejet `precondition_calendar`, la gate FRED ne
  bloque plus (15 releases en cache au 2026-09-18).

Le refus est compatible avec la règle de S01, mais **n'a pas été recoupé**
avec un recalcul indépendant du dealing range sur les bougies brutes :
« le marché n'a pas donné » est l'hypothèse la plus simple, pas une
vérification. Les étapes 5 à 9 n'ont jamais été atteintes, et **les seuils
de S01 (`c = 0,25`, 1:3, corps à 1,5 × ATR) n'ont toujours jamais été
exercés** — les régler resterait spéculatif.

**Le pipeline n'est pas supervisé, et il est à l'arrêt.** Exportateur et
worker sont deux processus manuels ; l'échantillon de séances que demande le
critère de réussite de S01 dépend d'eux. Au 2026-09-20 12:28 UTC (dimanche)
tout est tombé : conteneurs sortis en code 255 environ 12 h plus tôt (cause
non investiguée), MT5 fermé, plus aucun processus. Deux pièges d'outillage :
`TaskStop` ne tue que le shell, pas l'arbre `node`/`python` (quatre workers
en concurrence le 2026-09-18, la base affichant le verdict du plus rapide) ;
et après un redémarrage de session, un composant peut survivre pendant que
l'autre est mort (le worker a survécu, l'exportateur non). Toujours
vérifier, avant de lire un chiffre d'entonnoir :
`Get-CimInstance Win32_Process | ? { $_.CommandLine -like '*run-setup-detection*' }`
et que `event_at` avance. Démarrage : `context/infrastructure/runbook.md`,
section 5.

**T02a/T02b, précision utile pour EA-07** : le kill switch et la gate
« Daily loss guard » ont tous deux tourné en réel plusieurs fois (verrouillage
→ acquittement/reset → levée, tracé en base). **La pause de 30 min sur deux
pertes consécutives (T02b, la gate temporisée spécifique) n'a elle jamais
été déclenchée** — un seul trade perdant est survenu jusqu'ici, jamais deux
d'affilée (`risk_lockouts` : zéro ligne avec `until` renseigné). La barrière
d'EA-07 (« T02a/T02b vérifiés en réel ») n'est donc que partiellement remplie.

*(Corrigé le 2026-09-15 — le rendu T05 hors XAUUSD : le viewer rebâtit
désormais le timeframe de la capture depuis le M1 avec l'agrégation d'EA-02,
et n'affiche plus de ligne pour un SL/TP à 0, qui écrasait l'échelle de prix.
Vérifié à l'écran sur la position 3230177984.)*

Friction héritée du 28 juillet 2026 : l'observer a calé une fois (14:03) sur
une collecte longue. Piste si ça revient : `gmag11/MetaTrader5-Docker`.

## Prochaine action

**T10 — brief pré-séance automatique (Vague 3)**, suite pré-autorisée
(« Vague 3 — T09/T10, puis T19 »). Pas encore commencé : les sessions du
2026-09-17/18 sont parties dans des corrections trouvées en vérifiant contre
du réel (voir `session-log.md`), pas dans de nouveaux outils.

**Ce qui conditionne la mesure de S01 : que le pipeline EA-02 tourne pendant
les killzones.** Il est à l'arrêt (voir « Ce qui bloque »). Prochaines
fenêtres, heure d'été : Londres 02:00–05:00 NY = **06:00–09:00 UTC**, NY AM
07:00–10:00 NY = **11:00–14:00 UTC** — la première, lundi 2026-09-21, une
fois les marchés rouverts dimanche soir. Redémarrage : runbook, section 5.

**Leçon à retenir de la période** : le mode `mock`
(`NEXT_PUBLIC_REALTIME_SOURCE=mock`, port séparé, config `cockpit-dev-mock`)
débloque le rendu des pages sans backend ni agent MT5, mais il **ne vérifie
pas le câblage** — la vérification d'origine de T09, faite en mock, ne
pouvait pas voir que `connectionGate` lisait l'observer. Tout chemin de risque
se vérifie contre le vrai backend. Vues à l'écran avec de vraies données
depuis le 2026-09-18 : `/journal` (T06/T07, correct) et `/preflight` (T09,
après correctif) ; T08 (Markdown) et T15 (MCP) ne sont pas des pages, ils ont
été vérifiés autrement.

Après T10 : T19 (pré-autorisé), puis choix explicite de l'utilisateur.
T11/T12 (multi-compte, prop firm) restent hors périmètre tant qu'un deuxième
compte prop firm n'existe pas.

Le track EA reste en pause. EA-01 à EA-06 sont livrés ; EA-06 (2026-09-16) a
fermé les deux trous que l'incrément 6 d'EA-05 avait laissés ouverts
(résolution `UNKNOWN`, attribution `EXTERNAL_POSITION`) — voir sa fiche pour
deux limites assumées et non encore vérifiées en conditions réelles : la
propagation du commentaire de commande jusqu'au deal MT5 (hypothèse jamais
testée, `OrderSend` n'ayant encore jamais tourné), et le scénario de mort
agent entre `OrderSend` et l'accusé (vérifié par lecture du code, pas par un
test exécuté — aucun harnais MQL5 n'existe ici). Les conditions d'EA-07 se
remplissent par de vrais trades, pas par du code — voir « Ce qui reste
fermé » ci-dessous.

**Ce qui reste fermé, et ne s'ouvre pas par déduction** : rendre `CONFIRM`
atteignable (EA-07). Pas d'input de mode, pas de `control.set_mode`, pas de
seconde voie d'exécution — aucune consigne générale d'« avancer » ou de
« clôturer » ne vaut accord pour ça. Les conditions de sa fiche ne sont de
toute façon pas remplies : (a) T02b — la pause 30 min sur deux pertes
consécutives — n'a jamais été déclenchée en réel ; (b) le taux d'accord
d'EA-02 est toujours inconnu — zéro proposition ; depuis le 2026-09-18 ce
n'est plus un défaut de câblage qui l'explique, et l'entonnoir n'a jamais
dépassé l'étape 4/9 (voir « Ce qui bloque ») ;
(c) la Vague 1 n'est pas close (un trade a été ouvert pendant un lockout
actif le 2026-09-15).

## Questions ouvertes

- Quel déclencheur pour le multi-compte ? Par défaut : le jour où un deuxième compte prop firm est ouvert.
- Le compte FTMO existe-t-il déjà ? Toute la modélisation de ses règles est urgente ou spéculative selon la réponse.
- Veut-on pousser un trade manuel par le même chemin d'exécution, pour qu'il soit journalisé identiquement ?
- Faut-il superviser le pipeline EA-02 (exportateur + worker) — tâche planifiée Windows, ou service ? Aujourd'hui deux processus lancés à la main : le critère de réussite de S01 mesure un échantillon de séances, et chaque arrêt silencieux (redémarrage de la machine, fin de session) en perd une partie sans que personne le voie.
