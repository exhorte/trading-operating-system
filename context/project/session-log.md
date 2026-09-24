# Journal de session

Append-only, la plus récente en haut. Une entrée par session, courte — le
détail vit dans la fiche de chaque outil (`context/product/tools/*.md`) et
dans `git log`. Voir ADR 0008 pour ce que ce fichier est et n'est pas.

---

## 2026-09-24, suite (**EA-05 connecté pour la première fois** — bug de framing corrigé)

Demandes : relancer la base TradingOS et arrêter `e-commerce-db-1` ;
expliquer l'erreur 4014 à l'attache de l'agent ; vérifier sa connexion,
corriger, recompiler ; commit + push.

**Base** : `e-commerce-db-1` arrêté (code 0), `tradingos-timescaledb`
relancé, sain en 6 s. Arrêté depuis 11:19 UTC (3 h 33), le backend s'est
reconnecté seul. `PersistenceWriter` a perdu 1362 événements en un seul bloc
au début de la coupure (11:19–11:28 UTC : données de marché et snapshots —
aucune position ouverte, aucun trade ce jour-là) ; les ~9 000 suivants,
restés en file, ont été écrits.

**EA-05, trois obstacles successifs, détail dans sa fiche** : presets à
`InpMagicNumber=0` (refus attendu) ; `SocketConnect` en 4014 — liste
d'adresses autorisées de MT5 vide, `127.0.0.1` ajouté par l'utilisateur ;
puis connexion TCP établie sans qu'un seul message soit lu : `SendRawLine`
retirait le `\n` de chaque ligne, depuis le premier commit de l'agent
(2026-09-12). Corrigé ; après réattache, **étape 1 du README passée pour la
première fois, avec traces** (agent reconnu par la Gateway, heartbeats en
base). Ce bug rendait impossible la vérification consignée le 2026-09-12 —
le constat « non corroborée » du 2026-09-23 est confirmé.

**Trouvé, non corrigé (tâches proposées à part)** : `/health.dbError` n'est
jamais effacé après rétablissement ; `Mt5AgentServer` désinscrit un agent
par clé de compte sans vérifier que c'est sa connexion (deux instances — le
cas s'est produit — ou reconnexion rapide ⇒ agent affiché déconnecté).

Docs : README de l'agent (prérequis 4014, une instance par terminal,
recompilation ⇒ réattacher, étape 1 corrigée — l'EA n'affiche que son
premier échec, un onglet Experts muet ne prouve rien), runbook (bascule du
port 5433, perte au début d'une coupure de base).

Gates : MetaEditor `0 errors, 0 warnings`. Seul le `.mq5` a changé côté code
— gates TS/C#/Python non relancées, rien de leur périmètre n'a bougé.

## 2026-09-24 (**refonte visuelle du cockpit sur shadcn/ui — ADR 0012** ; T12 commité)

Demande : améliorer le dashboard d'après une maquette
(`05_screenchot/dashboar.jpg`) — icônes modernes et lisibles, Settings en
bas de la barre latérale, cartes qui remplissent l'espace, barre du haut
réduite au seul compte, palette discrète, bibliothèque shadcn/ui.

**T12 d'abord commité** (`1e8b19b`, sur accord) pour que la refonte ait son
propre commit. **Décision de l'utilisateur** : l'arrêt d'urgence va en bas
de la barre latérale (options : barre latérale / menu du compte / Command
Center seul).

**Livré** : shadcn/ui installé par sa CLI (jamais `init`, qui aurait réécrit
les jetons) ; jetons renommés dans 40 fichiers (`muted`/`accent`
entraient en conflit avec shadcn) ; `Card` → `Panel` dans 27 fichiers ;
nouvelle coque (barre latérale repliable, en-tête titre + compte) ; Command
Center, Pré-vol et Positions recomposés ; champs, boutons et barres au
format shadcn. **Rien de sécurité n'a été retiré, tout a été placé** :
conformité (T07) en tête du Command Center, publication/blackout (T03) et
arrêt d'urgence (T02a) en bas de la barre latérale sur tout écran, liaison
et persistance sur la pastille du compte. ADR 0012 amende l'ADR 0003
(dépendances front, densité).

**Défaut trouvé en vérifiant, corrigé** : `useJournalWindow` transformait un
refus (503) en historique vide — donc 100 % de conformité affichés base
arrêtée, contraire à son propre contrat. Vu à l'écran : la base TradingOS a
été arrêtée en cours de session (arrêt propre, code 0) au profit de
`e-commerce-db-1` — pas par moi ; la vérification a continué en mock, et les
états d'échec ont pu être vus pour de vrai.

Gates : `tsc`, `eslint`, `next build` propres ; 303 tests Vitest. Lenteur de
la machine notée (build 2 min 40 ; hydratation en dev jusqu'à 30 s).

---

## 2026-09-23 (**T12 incrément 2 — écrans Account et Settings ; environnement réel préparé ; l'agent EA-05 n'a jamais tourné dans le terminal**)

Demandes : « la partie connexion aux comptes propfirm ou FTMO et celui d'un
broker ou Exness à travers deux nouvelles interfaces Account et Settings »,
puis en cours de route « met en place l'environnement pour recevoir mes
données réelles des deux côtés pour se connecter et rendre l'EA
opérationnel ». Fiches : T12 (incrément 2), EA-05 (entrée du jour).

**Frontières posées avant tout code** : « connexion » ne sera jamais un
formulaire d'identifiants (ADR 0003, `.claude/CLAUDE.md`) ; « EA
opérationnel » = agent EA-05 connecté en mode observe — rendre `CONFIRM`
atteignable reste EA-07, pas déduit d'une demande générale.

**Account & Settings.** La décision T12 n°6 (configuration par commit,
tranchée à l'ingénierie) est révisée par l'utilisateur : les *faits* d'un
compte — challenge FTMO, capital de référence Exness, reconnaissance du
broker — s'éditent dans Settings, sous un verrou anti-tilt décidé par le
backend au moment d'écrire (immédiat seulement si aucune séance n'est en
cours, sur aucun compte ; sinon au prochain jour de trading). Les *règles*
restent dans le code. Vérifié en réel : écriture reportée, annulation,
diffusion d'un onglet à l'autre, refus 400/404/409 ; données de test
supprimées ensuite. Deux défauts vus à l'écran, corrigés.

**Une affirmation de ma propre fiche, corrigée dans la session** : « aucune
course » sur l'ancre du jour était faux — l'ancre venait de la base, écrite
de façon asynchrone. Elle vient maintenant de l'événement et ne recule jamais
au sein d'un compte (`nextDayAnchor`, testé). Le même mécanisme touche
probablement T02a (compteur de trades lu contre l'ancre de la veille à minuit
serveur → faux verrou « max trades » possible) : plausible, **non vérifié**,
signalé à part.

**Environnement réel** : `scripts/start-live.ps1` (base, backend, observer
sur le symbole du terminal détecté par `probe_terminal.py`, cockpit ; S01 en
option) — exécuté jusqu'à l'étape MT5, fermé. Agent EA-05 installé par
jonction dans le terminal, recompilé 0/0, barrière relue dans le code.

**Trouvé en le préparant — inconfortable, vérifié deux fois** :
`TradingOsAgent` n'a jamais été chargé dans ce terminal (journaux MT5 du
18/05 au 18/09 : seuls deux EA tiers, en juillet), et la base n'a aucune
trace du chemin d'exécution depuis sa création (0 commande, accusé, rapport,
scan). La vérification réelle d'EA-05 du 2026-09-12, consignée sur
déclaration, n'est pas corroborée : à refaire.

**Machine** : Smart App Control désactivé — `dotnet test` passe en natif ;
`e-commerce-db-1` (autre projet) partage le port 5433 avec TradingOS —
arrêté pour la vérification, le choix de celui qui tourne revient à
l'utilisateur.

Gates : `tsc`, `eslint`, `next build` propres ; **303 tests** Vitest (+34) ;
`dotnet build` 0/0, **`dotnet test` 58/58** (+24) ; Python 23/23 (+6) ;
MetaEditor 0/0. Non commité.

---

## 2026-09-21 (**T12 incrément 1 — profils FTMO / Exness, et une faille du Risk Engine corrigée**)

Demande : « une configuration interne de connexion propfirm FTMO ou un compte
direct Exness ». Fiche : `context/product/tools/T12-prop-firm-control-center.md`.

**Ce que « connexion » veut dire ici, établi avant tout code** : l'observer
appelle `mt5.initialize()` sans identifiant et suit le terminal que le trader
a ouvert. Aucun mot de passe broker n'a sa place dans l'application — ni
utile, ni permis (`.claude/CLAUDE.md`). Le cockpit reconnaît la firme au nom
du broker que MT5 transmet ; aucun numéro de compte n'entre dans le code.

**Faille trouvée en lisant le code, pas en la cherchant** : la perte max
était mesurée depuis le solde au moment où le cockpit s'était connecté,
remis à zéro à chaque resynchro. Chez FTMO elle se mesure depuis la taille du
challenge, fixe. Sur 10 000 $, −600 $ le jour 1 puis cockpit rouvert : le
gate autorisait un plancher à 8 460 $ au lieu de 9 000 $. Corrigé dans
`recomputeRisk` ; la perte journalière n'avait pas ce défaut (ancre T02a).
C'est la règle qui a clôturé le challenge 511333949 — compte jamais relié à
ce système, l'outil n'y est pour rien, mais il ne l'aurait pas empêché.

Trois décisions validées : un compte à la fois (le multi-compte simultané
reste T11) ; gabarit FTMO 2-Step 10 000 $, règles **sourcées par les exports
MetriX de l'utilisateur** (EA-04 les avait laissées en `TODO` faute de
source) ; Exness en direct à 5 %/10 %, choix de l'utilisateur contre une
recommandation à 3 %/8 %, appliqué tel quel.

**Vérifié contre FTMO lui-même** : les quatre journées réelles de 511333949
(« Résumé quotidien ») redonnent exactement les quatre verdicts de FTMO. Deux
autres trous bouchés au passage : les trades `XAUUSD` (nommage FTMO)
sautaient en silence le contrôle de taille ; le mock se disait « 100k » face
à un challenge configuré à 10 000 $.

**Non vu à l'écran** : le tableau des objectifs rempli — backend et base à
l'arrêt toute la session (`Exited (255)`, non relancés sans accord). Vus :
les états « non reconnu » et FTMO de `/comptes`, et le Command Center.

Gates : `tsc`, `eslint`, `next build` propres, **269 tests** (+22). Non
commité.

---

## 2026-09-20 (suite — **écran « Analyse de compte » livré** : le modèle FTMO adapté, discipline en tête, sans conseil)

Enchaîné sur la refonte d'architecture ci-dessous, sur demande directe
(« fait l'écran analyse de compte »). `/analyse`, neuvième écran.

**Une tension de fiche levée explicitement, pas contournée.** La fiche T08
(Décision 1) a écarté une page cockpit pour la revue hebdomadaire : « un
document qui se lit une fois et se garde… ce serait un second /journal ».
Cet écran est un autre objet, et la distinction est écrite dans
`information_architecture.md` : T08 rend **une semaine dans un fichier**,
`/analyse` lit **n'importe quelle plage à l'écran**, et calcule surtout des
dimensions que T08 n'a jamais eues — durée de trade, taille de position,
jour d'ouverture *contre* jour de fermeture, heure d'entrée, sens. Pas de
table de trades : sur ce point la fiche avait raison, `/journal` la porte
déjà.

**Trois écarts délibérés avec le modèle FTMO**, tous tenus par du code :
discipline avant P&L dans l'ordre de lecture (ADR 0001) ; **aucun conseil**
— FTMO clôt ses blocs par « focus only on those particular trades that
turned out successful for you », soit la sélection a posteriori qui a mis
fin à la recherche d'edge (ADR 0002), et un test interdit ce registre
(`narrative.test.ts`, « never gives trading advice ») ; aucune table de
trades.

**Ce qui a été mutualisé plutôt que recopié** — c'était la troisième copie
dans chaque cas : `lib/journal/types.ts` (forme d'un trade clôturé, T08 y
est branché), `lib/journal/use-journal-window.ts` (couple trades +
lockouts), `lib/compliance/summarize.ts` (chiffres de conformité, purs),
`lib/compliance/labels.ts`. `useComplianceRate` n'est plus qu'une politique
de fenêtre glissante par-dessus.

**Vérifié contre les vraies données, pas seulement en tests.** Les fonctions
pures exécutées sur le compte 477029930 (2026-06-01 → 2026-09-21) : 9
trades, +$25,27 net, 33 % de conformité, 6 `LOCKOUT_ACTIVE` — les quatre
recoupent exactement T08 et `state.md`. Et **chaque ventilation somme au
même net** : durée (−0,90 + 53,45 − 27,28), taille (0,30 + 52,25 − 27,28),
sens (53,20 − 27,93) = +25,27. T08 relancé après le déplacement de type :
fichier régénéré identique à la référence du 2026-09-17.

**Préversion mock alignée sur un compte réel, dans la foulée et sur demande.**
Le mock servait `account-001`, qui n'existe dans aucune base : `/journal`,
`/positions`, `/analyse` et le badge de conformité y étaient vides en
permanence. `lib/mock/initial-snapshot.ts` lit désormais
`NEXT_PUBLIC_MOCK_ACCOUNT_ID`, défaut `"account-001"`.

**Variable d'environnement et pas constante, délibérément** :
`.claude/CLAUDE.md` pose « Aucun identifiant de compte n'est jamais demandé,
stocké ou partagé », et le coder en dur l'aurait poussé sur le remote.
`.env*` est gitignoré, `.env.example` documente la variable sans valeur. Quand
elle est renseignée, le libellé du compte passe à « Compte réel — flux
simulé » : l'equity et les positions restent scriptées, seul le côté journal
devient réel, et le mélange doit rester visible.

**Ce que l'activation a révélé immédiatement** : `/risk` est passé de « 100 %
conforme, 0 verrou » à **33 % hors cadre, 6 trades non conformes sur 9, et
cinq verrous réels** — kill switch du 2026-09-15 (3 min, acquitté) et quatre
« Daily loss guard » du 2026-09-14 (19 h 17, acquittés). La trace exacte des
deux incidents de Vague 1, affichée sans qu'on la cherche. Un écran de
discipline qui affiche 100 % parce qu'il n'a rien à lire est pire qu'un écran
vide.

**Le rendu peuplé de `/analyse` est donc vérifié** : les nombres à l'écran
sont identiques à ceux calculés hors-écran (9 trades, +$25,27, 56 % de
réussite, rapport 1.49 ; ventilations durée/taille/sens sommant toutes à
+25,27).

Gates : `tsc` clean, `eslint` clean, **247 tests verts** (+29).

---

## 2026-09-20 (**refonte de l'architecture d'information du cockpit** — le Command Center passe de ~104 valeurs à ~25, trois écrans vides sont remplis, deux sont supprimés)

Session d'interface, déclenchée par une remarque de l'utilisateur : « le
command center semble très chargé, trop d'information, difficile de se fixer
ou trouver une information directement ».

**Diagnostic chiffré avant de toucher quoi que ce soit** : ~104 valeurs
distinctes dans un viewport, et surtout quatre horizons de temps mélangés
(maintenant / aujourd'hui / ce mois / structure de marché) sans qu'aucune
question ne soit posée. En parallèle, cinq des dix entrées de navigation
étaient des placeholders « not built yet ».

**Règle retenue, validée par l'utilisateur : un écran, une question.** Le
détail et la cartographie complète sont dans le nouveau
`context/frontend/information_architecture.md` — ce fichier ne le répète pas.

- **Command Center** : ligne de verdict « Armé / Pas armé » en tête, quatre
  KPI au lieu de huit (les quatre retirés étaient des composantes d'une même
  question, désormais la tuile « Marge avant verrou »), positions ouvertes.
- **Trois écrans vides remplis** avec ce qui en sortait : `/market-context`,
  `/risk` (renommé « Risque & Discipline »), `/agents` (« Agents & Audit »).
  Rien n'a été perdu dans le déplacement.
- **Deux écrans supprimés** : `/settings` (rien à configurer) et `/replay`
  (attend le pipeline analytics). `PnlCalendar` supprimé aussi — `/journal`
  a déjà un `MonthCalendar` plus riche, alimenté par la base.

**Trois surfaces de données trouvées sans aucun écran**, en cartographiant
les endpoints backend contre leurs consommateurs front : `/api/audit/recent`
(zéro consommateur — la piste d'audit d'un système qui se revendique
auditable vivait derrière `curl`), l'historique des lockouts, et le
calendrier FRED réduit à un chip. Les trois ont servi à donner du contenu
propre aux écrans receveurs.

**Deux duplications supprimées** : la règle « armé / pas armé » (deux copies)
vit maintenant dans `lib/cockpit/verdict.ts`, pur et testé (8 tests) ; le
calcul du taux de conformité T07 dans `lib/compliance/use-compliance-rate.ts`,
un fetch pour le badge et la nouvelle jauge.

**Un bug backend trouvé en vérifiant, pas en cherchant** : `Cockpit:DashboardOrigin`
n'acceptait qu'une seule origine (`http://localhost:3000`), donc **tout panneau
adossé à HTTP était cassé sur le port 3001** — le preview mock déclaré dans
`.claude/launch.json`. Journal, positions et badge de conformité y échouaient
en CORS opaque, ce qu'on lisait depuis des semaines comme « pas de données ».
La config accepte désormais une liste ; `docker-compose.yml` déclare 3000 et
3001. Conteneur reconstruit, en-tête vérifié.

**Analyse des modèles de référence** (`05_screenchot/`, demandée en début de
session) dans `context/frontend/visual_reference_ftmo_journal.md` : le journal
type TradeZella, et les deux exports FTMO (Analyse de compte, Account MetriX).
Le MetriX est le plus proche de notre produit — sa jauge de discipline est
l'ancêtre direct de `DisciplineGauge`, re-pointée sur le taux de conformité
T07 plutôt que sur le P&L.

Vérifié : `tsc` clean, `eslint` clean, 218 tests verts, les huit écrans
rendus à l'écran sur le port 3001. **Non vérifié** : `dotnet test` reste
bloqué par Smart App Control (runbook §2) — le changement C# est couvert par
`dotnet build` et par la vérification de l'en-tête CORS en direct.

---

## 2026-09-20 (**bilan de la killzone NY AM du 18/09** — S01 refuse pour une raison de marché ; tout est à l'arrêt)

Suite du 2026-09-18, après `1210fae` (poussé : correctif `connectionGate` +
pipeline S01 débloqué, voir les deux entrées ci-dessous).

**Relance du pipeline après un redémarrage de session.** État trouvé : un
worker survivant — une seule chaîne de processus, pas de doublon — mais
l'exportateur mort, donc un worker qui relisait depuis ~8 min un instantané
figé. Tout ce qui portait `run-setup-detection` arrêté, puis exportateur et
worker relancés ; vérifié par l'heure de création et le PID parent de
chaque chaîne (une instance de chaque). C'est l'envers du piège noté plus
bas (`TaskStop` ne tue pas l'arbre) : ce que la fin d'une session laisse
vivant est imprévisible, un composant peut survivre pendant que l'autre est
mort.

**Killzone NY AM du 2026-09-18 (11:00→14:00 UTC), un seul worker : 356
évaluations, toutes bloquées à `range_location`** (étape 2/9), sur EURUSDm
et GBPUSDm — « price is discount, need premium for a sell » : biais baissier,
donc vente uniquement au-dessus de l'équilibre du dealing range 1H, et le
prix est resté en dessous toute la killzone. Aucun rejet
`precondition_calendar` : la gate FRED, débloquée le matin même, ne bloque
plus. La killzone de Londres du même jour avait atteint `sweep` (étape 4/9),
donc franchi l'étape 2 à ce moment-là.

**Ce que ça établit, et ce que ça n'établit pas.** Le refus est compatible
avec la règle de S01 ; « le marché n'a pas donné le retracement » est
l'hypothèse la plus simple, **pas une vérification** — je ne l'ai pas
recoupée avec un recalcul indépendant du dealing range sur les bougies H1
brutes. Les étapes 5 à 9 (déplacement/MSS, entrée, stop, portes de coût et
de R:R, sorties) n'ont toujours jamais été atteintes ; les seuils de S01
(`c = 0,25`, 1:3, corps 1,5 × ATR) restent posés, pas mesurés.

**Fausse alerte de mon propre moniteur, corrigée.** Il annonçait « dernière
évaluation il y a 702 min » alors que le pipeline était sain (`event_at` à
1-2 min) : `${latest_event% *}` ne retirait pas un suffixe de fuseau mais
**l'heure**, ne laissant que la date — donc « depuis minuit ». Le format
réel de Postgres (`2026-09-18 11:41:00+00`) se lit directement avec
`date -d`. À retenir : tester l'arithmétique d'une alerte sur la vraie
sortie de la source, pas sur le format qu'on croit recevoir.

**État constaté le 2026-09-20 à 12:28 UTC (dimanche, marchés fermés) : tout
est à l'arrêt.** Les deux conteneurs sont sortis en code 255 environ 12 h
plus tôt (arrêt non propre de Docker Desktop ou de la machine, cause non
investiguée), MT5 est fermé, plus aucun observer, exportateur ou worker.
Git propre sur `1210fae`. Rien n'a été relancé : marchés fermés, et MT5
demande une ouverture manuelle.

Fichiers de suivi mis à jour dans le même passage : `state.md`, fiche EA-02,
index des fiches, `roadmap.md` (note T09), `runbook.md` (emplacement de la
clé FRED corrigé, nouvelle section 5 « Pipeline de détection S01 », ordre de
redémarrage après arrêt non propre), `03_Suivi_Projet/Suivi.md`. Rien de
committé. **Question ouverte, ajoutée à `state.md`** : superviser le
pipeline EA-02 ? Le critère de réussite de S01 mesure un échantillon de
séances, et chaque arrêt silencieux en perd.

---

## 2026-09-18 (suite — **S01 s'exécute enfin** : trois gates structurellement fermées, trouvées et corrigées)

Demande initiale : « analyser la stratégie de l'EA, trouver les faiblesses
dans ses prises de position, optimiser ses gains ». Deux corrections de
cadrage avant tout diagnostic. D'abord, **l'EA n'a pas de stratégie** :
`TradingOsAgent.mq5` est un exécutant (connexion, heartbeat, validation,
accusé), son `OrderSend` reste mort. La stratégie, c'est S01, détectée par
EA-01/EA-02. Ensuite, « optimiser les gains » est fermé par ADR 0001 (le KPI
est la conformité, pas le P&L) et ADR 0002 — dit une fois, sans y revenir,
et la suite a montré qu'il n'y avait de toute façon rien à régler.

**Le détecteur n'avait jamais rien proposé, et aucune des trois causes
n'était la stratégie.** Détail complet dans `state.md` (« Ce qui bloque ») :
gate calendrier sans données (370 évaluations sur 370 tuées le 15/09),
exportateur écrivant dans un dossier que personne ne lit (instantané figé
depuis trois jours), et surtout **H4/D1 agrégées depuis 25 h de M1 → 2
bougies D1**, alors que `dailyBias` a besoin d'au moins 5 bougies par
timeframe pour un seul swing : le bras D1 renvoyait `neutral`
inconditionnellement, l'étape 1 était infranchissable quoi que fasse le
marché. Le commentaire de l'exportateur affirmait le contraire sans que
personne ne l'ait mesuré.

Correctif retenu par l'utilisateur parmi deux options : **bougies natives
MT5** (H1/H4/D1, 500/300/300) plutôt qu'augmenter `--bars` — plus juste, la
journée D1 étant celle du broker et non un bucket UTC (même distinction que
l'ancre T02a). Révise la décision « agrège M1 → H1/H4/D1 » de la fiche
EA-02.

**Résultat vérifié en direct** : l'entonnoir passe de « jamais démarré » à
`sweep`, étape 4/9 — biais H4/D1 validé, dealing range H1 ancré, liquidité
cartographiée, et le refus porte désormais sur une condition de marché.
Premier refus légitime de l'histoire du projet.

**Deux erreurs de ma part dans cette session, corrigées et notées** : (1)
j'ai affirmé que les killzones étaient en UTC fixe — faux,
`lib/setup/preconditions.ts` fait bien du NY DST-aware via `Intl` ; j'avais
déduit au lieu de lire. (2) J'ai lancé l'exportateur avec le mauvais
`--out-dir`, en suivant ma propre note mémoire qui était fausse — note
corrigée. **Piège d'outillage** : `TaskStop` ne tue que le shell, pas
l'arbre `node`/`python` ; quatre workers ont tourné en concurrence sur la
même clé primaire, la base affichant le verdict du plus rapide et non celui
du code courant. Tout chiffre d'entonnoir lu avant le nettoyage est à jeter.

Gates : `tsc`, `lint`, `py_compile` verts. Rien de committé.

---

## 2026-09-18 (**bug de `connectionGate` corrigé** — le gate lisait l'observer, pas l'agent d'exécution)

« Phase suivante » : T10 était la suite sans réserve, mais avant de l'ouvrir
j'ai saisi l'occasion notée dans `state.md` — vérifier enfin à l'écran, avec
le vrai backend (possible depuis sa conteneurisation), les pages jamais vues
rendues avec de vraies données. `/journal` (T06/T07) est correct : les 6
violations de lockout, les P&L exacts, les ventilations, les liens Capture.

**Mais `/preflight` affichait « Execution agent — connected » alors que
`/health` répondait `agentConnected: false`** et qu'aucun agent EA-05 n'était
connecté — seul l'observer Python tournait. Cause confirmée en lisant le
code : le tableau `agents` envoyé au cockpit n'est alimenté **que** par le
hello de l'observer (`Mt5ObserverClient` appelle `SetHello` ;
`Mt5AgentServer` ne touche jamais `GatewayState`), et `recomputeRisk()`
dérivait `agentConnected` de ce tableau. Le gate répondait donc « le flux de
marché est up », lu comme « un ordre peut atteindre MT5 ». Pas seulement
cosmétique : ce booléen alimente `evaluateRiskState`, donc le Risk Engine
lui-même. Sans conséquence live tant qu'`OrderSend` reste fermé, mais
c'était exactement la fausse confiance que T09 existait pour supprimer.

Le mock l'avait masqué (`mockAgents()` fabrique un agent « connected ») —
la vérification d'origine de T09, faite en mode mock, ne pouvait pas voir le
câblage réel. Leçon qui vaut au-delà de ce bug : le mode mock débloque le
rendu, il ne vérifie pas le câblage.

Correctif et détail complet dans la fiche T09 (entrée 2026-09-18) :
`Mt5AgentServer.IsConnected` devient une donnée de premier ordre
(`CockpitSnapshotDto.ExecutionAgentConnected` + nouvel événement
`execution.agent.connection` diffusé depuis un `ConnectionChanged` qui
n'était que loggé), `executionAgentConnected` dans le store en fail-closed,
et deux libellés qui présentaient l'observer comme un agent d'exécution
corrigés (`AgentHealthPanel`, tuile KPI).

**Vérifié contre le vrai backend, pas en mock** : `/preflight` affiche
désormais « no agent connected » et 3 points bloquants au lieu de 2,
l'observer toujours connecté et les autres gates sur de vraies valeurs.
Gates vertes (tsc, lint, vitest 210/210, `dotnet build` 0/0, `next build`) ;
`dotnet test` toujours bloqué par Smart App Control.

T10 n'est pas commencé — cette correction a pris la place de la phase.

---

## 2026-09-17 (suite — **backend conteneurisé**, contourne le blocage Smart App Control)

Demande explicite (« mets le backend dans Docker ») après le backend resté
down à la fin de l'entrée précédente. Périmètre confirmé avant de coder :
« le backend » = `TradingOs.Host` (+ Gateway/Persistence/Contracts, ses
dépendances de projet) — l'observer Python et MT5 restent natifs sur
Windows, jamais conteneurisés (MT5 ne tourne pas dans un conteneur Linux).

Deux pièges réseau trouvés en lisant le code avant d'écrire le Dockerfile,
tous deux corrigés avant le premier `docker compose up` :

1. **`Mt5AgentServer` liait `IPAddress.Loopback` en dur** et `Program.cs`
   appelait `app.Run("http://localhost:5080")` en dur — dans un conteneur,
   le loopback interne n'est joignable par aucun port publié (Docker route
   vers l'interface du conteneur, pas vers son 127.0.0.1). Nouveau
   paramètre optionnel sur `Mt5AgentServer` (`bindAddress`, défaut
   `IPAddress.Loopback` — inchangé pour le run natif) et `Cockpit:ListenUrl`
   / `Cockpit:AgentBindAny` (nouvelles clés de config, défauts identiques au
   comportement natif). Seul `docker-compose.yml` les bascule à `0.0.0.0` /
   `true` ; le port publié côté hôte reste restreint à `127.0.0.1` dans les
   deux cas, même posture qu'avant.
2. **Conflit de réseau Docker** : `tradingos-timescaledb` tournait déjà sous
   un nom de projet compose différent
   (`trading_operating_system_algorithmique_default`, confirmé par
   `docker inspect`, pas deviné), pas celui que ce dossier (`04_code`)
   aurait produit par défaut. `docker-compose.yml` pointe désormais
   `networks.default` dessus en réseau externe — `backend` peut résoudre
   `timescaledb` par son nom sans recréer le conteneur existant ni toucher
   à son volume de données. `docker compose up -d --no-deps backend` évite
   par ailleurs tout conflit de nom de conteneur à chaque démarrage.

Nettoyage additionnel : l'image runtime (`aspnet:10.0`, Debian slim)
n'embarque pas `libgssapi-krb5-2` — Npgsql le sonde par défaut avant de
retomber sur l'authentification par mot de passe réellement configurée ; la
connexion marchait déjà mais loggait une fausse alerte (« cannot open
shared object file ») à chaque tentative. Ajouté au Dockerfile, logs
propres depuis.

**Vérifié en direct, de bout en bout, avec de vraies données** — pas
seulement les gates : `docker compose up -d --no-deps --build backend` →
`/health` répond `db: "ok"` → observer Python lancé (MT5 déjà ouvert,
compte 477029930) → `docker logs` : « MT5 observer connected » →
`persisted` passe de 3 à 186 → cockpit natif (`NEXT_PUBLIC_REALTIME_SOURCE
=backend`, `.env.local` intact) : compte réel affiché (Exness Technologies
Ltd, XAUUSDm), 33 % conformité (7j), `WS connected`, `Persistance OK`,
9 gates du Risk Engine rendus avec les vraies valeurs. Négociation SignalR
(`/hub/cockpit/negotiate`) et endpoints REST tous 200. `dotnet build`
natif toujours vert (0 erreur/warning) — seule l'exécution native reste
bloquée par Smart App Control, sans rapport avec ce changement.

`context/infrastructure/runbook.md` mis à jour (section 2 restructurée,
point de fragilité ajouté). Le blocage backend noté dans l'entrée
précédente est résolu par ce chemin, pas par un changement côté Windows.

---

## 2026-09-17 (suite — **T02c livré**, durcissement du lockout ; backend réel resté down)

« Phase suivante » relancé après T09 : l'incident de lockout du 2026-09-17
(voir entrée T15 ci-dessous et `state.md`) était resté sans réponse deux
choix de suite d'affilée — signalé cette fois plutôt que réavancé par
défaut. Traité avant toute nouvelle phase, sur demande explicite (« On
durcit le verrou, pas juste un ralentisseur »).

Vérifié en direct contre la base avant de proposer quoi que ce soit (pas
seulement relayé depuis `state.md`) : les 6 trades EURUSDm pendant lockout
confirmés exacts (`risk_lockouts`, `position_opens`, `closed_trades`) —
P&L cumulé +$0,30, donc pas une question d'argent. Un point relevé en plus,
jamais documenté avant : sur le lot du 14, plusieurs trades s'enchaînent en
moins d'une minute (47 s, 67 s) juste après le déclenchement — un rythme
proche du mode d'échec que T02 cible, sans martingale (taille constante).

Un vrai mur (refermer une position automatiquement) exigerait `OrderSend`
donc EA-07 — refusé explicitement comme option : préconditions non remplies
et circularité (Vague 1 n'est pas close à cause de cet incident précis,
s'en servir pour ouvrir la barrière aurait été l'inverse de la logique
voulue). Décision retenue : « Durcir sans exécuter » — détail complet
(conception, décisions validées, incréments, vérification) dans
`T02-lockout.md`, section T02c.

**Découverte d'environnement, sans rapport avec le code** : Smart App
Control (Windows) bloque le chargement de tout binaire .NET fraîchement
recompilé sur cette machine — confirmé par le journal Code Integrity
(« did not meet the Enterprise signing level requirements »), pas une
vérification en cours, un refus déterministe. `dotnet build` reste propre
(0 erreur) ; `dotnet test` et le backend réel (`dotnet run`) ne le sont pas.
En arrêtant l'ancien process pour débloquer le build (piège DLL verrouillée
connu, voir `reference_local_environment`), j'ai perdu la capacité de le
relancer — le backend est resté down à la fin de la session, en attente
d'une décision de l'utilisateur (ajuster Smart App Control, signer les
builds de dev, ou faire tourner le backend en conteneur). Aucun impact sur
MT5 ni le trading manuel — uniquement le pont cockpit ↔ MT5.

Gates vertes : tsc, lint, vitest (210/210), `dotnet build`, `next build`,
`python -m py_compile`. Vérifié visuellement en mode mock (nouvelle config
`cockpit-dev-mock` dans `.claude/launch.json`, port 3001, `.env.local` de
l'utilisateur intact) : les deux nouvelles bannières et le kill switch
d'origine se comportent comme prévu.

Ne change pas la conclusion sur Vague 1 : toujours ouverte, le durcissement
prévient une récidive mais ne referme pas ce qui s'est déjà passé.

---

## 2026-09-17 (suite — **T09 livré** ; premier rendu vérifié à l'écran depuis T05)

Choisi avec sa suite pré-autorisée (« Vague 3 — T09/T10, puis T19 »).

**La cartographie a réduit l'outil avant d'écrire une ligne.** Trois des
promesses de la fiche d'origine existaient déjà : `evaluateRiskState`
exécute 8 gates tout seul, `RiskStatusPanel` les affiche déjà un par un, et
`evaluateSignalRisk` refuse déjà sur le premier gate bloqué — « tant que
tout n'est pas vert, le Risk Engine refuse » était **déjà vrai**. Restaient
un gate manquant, un verdict agrégé et une page.

**Le gate manquant était un vrai trou** : jusqu'ici le Risk Engine
approuvait un ordre sans jamais vérifier qu'un agent d'exécution était
joignable — `CockpitHub` ne le découvrait qu'à l'envoi
(`AGENT_UNREACHABLE`), après approbation. `connectionGate` comble ça, en
gate d'entrée (pas un lockout de compte). Champ `agentConnected` **non
nullable** à dessein, contre la convention des voisins : la connexion est
toujours connue, il n'y a pas de « n/a » honnête à rapporter. Le rendre
requis a fait remonter ses 6 sites d'appel par le typage.

Deux items de la fiche d'origine retirés ou reformulés (« plan écrit » —
T04, mort ; « verrous armés » → « aucun lockout actif »), un reporté
(normes de spread par heure : n'existent que dans `analyze_spread.py`,
explicitement marqué throwaway Phase 0), un seuil non dupliqué (blackout
news gardé à 30 min, celui de la policy, plutôt que les 60 de la fiche —
deux chiffres pour une règle, c'est deux vérités).

**Limite énoncée dans l'UI, pas seulement dans la fiche** : le verdict ne
porte que sur ce qui passe par ce système ; un ordre saisi directement dans
MT5 n'est contraint par aucun de ces points. Les 6 trades des 2026-09-14/15
sont exactement ce cas — « Armé » ne doit pas laisser croire davantage.

**Déblocage méthodologique, qui vaut au-delà de T09.** Premier rendu
réellement vérifié à l'écran depuis T05 : un serveur de dev lancé en mode
`mock` sur un port séparé (`.env.local` de l'utilisateur laissé intact)
affiche les pages **sans backend ni agent MT5**. C'est exactement ce qui
bloquait depuis T06 (`useCockpit().account` reste null sans flux live, donc
squelette perpétuel). Les deux états de `/preflight` vus pour de vrai :
`Armé` (9 gates au vert, dont `Execution agent — connected`) puis, en
basculant temporairement le mock, `Pas armé` (pastille rouge, point
bloquant listé) — puis reverté. **T06 et T07, jamais vus, peuvent être
vérifiés de la même façon.**

Trouvaille d'environnement au passage, sans rapport avec le code : 404 sur
`/preflight` *et* `/journal` (route pourtant livrée et vue plus tôt) alors
que `/` répondait 200 — un `.next` périmé, laissé par des `npm run build`
de production intercalés entre des serveurs de dev. `rm -rf .next` répare.

---

## 2026-09-17 (suite — **T08 livré**, revue hebdomadaire ; **Vague 2 complète**)

Choisi par défaut sur « phase suivante » (dernier des quatre outils de
Vague 2 identifiés ; le second incident de lockout signalé juste avant est
resté sans réponse de l'utilisateur, noté comme toujours ouvert dans
`state.md` plutôt que relancé). Fiche écrite en corrigeant deux formulations
T04 de catalogue.md : « ticket pré-trade » en regard des pires trades →
lien vers la capture T05 ; « comparaison plan/exécution » → abandonnée,
pas remplacée (la donnée qu'elle comparait n'existe plus).

Quatre décisions validées (« valide les quatre, enchaîne sur les
incréments ») : sortie Markdown, pas une page cockpit ni un PDF ;
génération à la demande (aucune planification n'existe dans ce dépôt,
catalogue.md accepte explicitement « CLI ») ; pires trades par P&L le plus
négatif ; comparaison plan/exécution abandonnée.

Trois incréments, gates vertes (tsc, lint, vitest 206/206, `next build`) :
calcul pur (`tools/weekly-review/stats.ts`) ; rendu Markdown pur
(`render.ts`) ; script + `npm run weekly-review` + `weekly-reviews/`
ignoré par git (données personnelles générées, pas du code). Au passage :
`tools/mcp-server/backend-client.ts` déplacé vers
`tools/shared/backend-client.ts`, réutilisé à l'identique par T15 et T08 —
T15 revérifié après coup (même handshake MCP qu'à sa livraison, toujours
vert).

**Vérifié contre de vraies données, document généré relu.**
`TRADING_OS_ACCOUNT_ID=477029930 npm run weekly-review -- --from=2026-09-14 --to=2026-09-16`
contre le backend réel : 9 trades, P&L net +$25,27, 6 violations
`LOCKOUT_ACTIVE` — exactement la somme des deux incidents connus (5 + 1).
Fichier Markdown relu ligne par ligne : ventilation par symbole, taux de
conformité (33 %), 3 pires trades avec liens de capture, tout correct.

**Vague 2 est maintenant complète** : T06, T07, T15, T08 tous livrés. Son
critère de sortie (roadmap.md — taux de conformité affiché automatiquement
en haut du cockpit) est rempli par `ComplianceBadge` (T07). `state.md`
reconsolidé au passage (la section « En une phrase » avait accumulé le
détail de quatre livraisons consécutives — recentrée sur l'instantané,
l'historique reste dans ce journal et dans chaque fiche).

---

## 2026-09-17 (**T15 livré** — serveur MCP ; second incident de lockout découvert en testant)

Session redémarrée (Docker/backend retombés, rien perdu — le commit
`1299753` était déjà poussé). Choix explicite après reprise : T15 plutôt que
T08. Fiche écrite en cartographiant d'abord ce qui existe déjà : aucune
nouvelle donnée nécessaire, tout passe déjà par du REST
(`/api/journal/trades`, `/api/risk/lockouts`, `/api/candles`,
`/api/setup-proposals`, `/api/execution/divergence`) — la seule vraie
question était où vit la logique de conformité T07, puisqu'elle n'est
persistée nulle part (calculée côté navigateur, à la demande).

Quatre décisions validées (« valide les quatre, enchaîne sur les
incréments ») : Node/TS via `tsx` (déjà une dépendance,
`scripts/run-setup-detection.ts` en est le patron), jamais Python (réservé
à MT5, ADR 0010) ni un service C# séparé — pour pouvoir **importer**
`lib/compliance/` directement plutôt que la réécrire dans un troisième
langage ; toujours via l'API REST existante, jamais Postgres/MT5 en
direct ; le serveur expose des faits, jamais une métrique de performance
pré-calculée (même ligne qu'ADR 0011) ; taille hors politique hors
périmètre (balance courante absente du REST).

Quatre incréments, gates vertes (tsc, lint, vitest 206/206, `next build`) :
squelette + `get_trades`/`get_lockouts`/`get_candles` ;
`get_setup_proposals`/`get_execution_divergence` ; `get_compliance_violations`
(import direct de `lib/compliance/evaluate.ts`) ; `tools/mcp-server/README.md`
+ `npm run mcp`.

**Vérifié par un vrai handshake MCP**, pas seulement les gates : messages
JSON-RPC construits à la main (`initialize`, `tools/call`), backend et
TimescaleDB relancés après le redémarrage de session, les 6 outils appelés
contre le vrai compte (477029930) et leurs réponses inspectées.

**En testant `get_compliance_violations` sur toute la plage 2026-09-14/15
plutôt que sur un seul trade, 5 positions EURUSDm de plus ressortent
ouvertes pendant un lockout actif** — la gate « Daily loss guard » du
2026-09-14 (`lockout-mu1af4l7-8lbceb`, verrouillée 13:37:28, jamais
acquittée avant le lendemain 08:54:25) : 3225706315, 3225729956, 3225966706,
3226050174, 3226089957. Jamais documenté avant ce jour — le seul incident
connu jusqu'ici était le trade isolé du 2026-09-15. Vérifié à la main
contre les horodatages bruts avant d'être retenu comme un fait, pas une
suspicion : une position XAUUSDm ouverte une seconde avant le
déclenchement du lockout (3225577967) n'est, à raison, pas comptée —
signe que la détection ne sur-déclenche pas. Ni un bug de T15 ni de T07 :
un fait réel, resté invisible parce que personne n'avait encore posé cette
question précise sur toute la plage. `state.md` mis à jour en conséquence
(« Ce qui bloque » — l'ampleur du problème double, pas la conclusion :
Vague 1 était déjà ouverte).

---

## 2026-09-16 (suite — **T07 livré**, tracker d'erreurs et taux de conformité)

Choisi explicitement après T06 (question ouverte : T07/T15/T08, tous
débloqués par T06). Fiche écrite en vérifiant chaque violation de la
taxonomie réduite (déjà posée par une session antérieure après le retrait
de T04) une par une plutôt qu'en bloc :

- Lockout actif, fenêtre de session : détectables proprement, données déjà
  là (`risk_lockouts`, `DEFAULT_SESSION_WINDOWS`).
- Taille hors politique : détectable, mais **pas** avec
  `evaluateSignalRisk` (`lib/risk/sizing.ts`) — cette fonction code en dur
  le facteur XAUUSD (« 1.00 price move on 1.0 lot ≈ 100 USD ») et aurait
  donné un faux verdict sur la majorité des trades réels, tous
  EURUSD/GBPUSD. La bonne formule passe par `symbolMetadata`
  (`lib/market/symbols/registry.ts`, tick size/value).
- Stop déplacé après l'entrée : pas détectable du tout — rien ne trace les
  modifications de position (`execution.modify` existe dans le protocole
  wire, jamais câblé).

Trois décisions soumises et validées (« valide les trois, enchaîne sur les
incréments ») : deux violations ce tour (lockout, session) ; taille
construite quand même avec la balance courante comme approximation de la
balance au moment du trade (pas de suivi historique de `account.snapshot`,
séparable plus tard si besoin) ; stop déplacé reporté, hors périmètre.

Quatre incréments, gates vertes à chaque étape (tsc, lint, `dotnet build`
0 warning, `dotnet test` 34, vitest 206 — 22 nouveaux, `next build`) :

1. `lib/compliance/violations.ts` — trois détecteurs purs, testés contre le
   **vrai** lockout kill-switch du 2026-09-15 (`lockout-mu2h6tvb-8qosw0`,
   requêté en base pour construire le fixture) : le trade EURUSDm de
   09:36:00 ressort bien en violation.
2. `lib/compliance/evaluate.ts` + `GET /api/risk/lockouts`
   (`RiskLockoutHistoryRepository`, nouveau — `RiskTodayRepository` ne
   couvre que « maintenant ») + colonne Violations sur `/journal`. Bug
   trouvé en écrivant l'intégration : `closed_trades.symbol` est le nom
   broker (`EURUSDm`), pas le canonique qu'attend `symbolMetadata` — le
   type `ComplianceTradeInput.symbol` est `SymbolCode | null`, et seul le
   contrôle de taille se désactive sur un symbole non résolu, jamais
   lockout/session avec lui.
3. `ComplianceBadge` dans `TopCommandBar` — fenêtre glissante de 7 jours,
   indépendante du filtre de `/journal`, même détecteurs.
4. Taille hors politique : déjà branchée depuis l'incrément 2 (conçue avec
   dès le départ) — rien à ajouter, seulement vérifié.

**Vérifié contre de vraies données.** `GET /api/risk/lockouts` appelé
directement contre la base réelle : retrouve le lockout kill-switch, et au
passage les 4 lignes « Daily loss guard » dupliquées à 73 ms d'intervalle du
2026-09-14 (artefact historique de l'ancien bug de course, corrigé le
2026-09-15 — sans conséquence ici). `ComplianceBadge` chargé dans le
navigateur intégré : rendu correct de son état « Conformité — » (aucun
compte connecté), aucune erreur console nouvelle. Même limite que T06 :
jamais vu rendu avec de vraies données à l'écran.

---

## 2026-09-16 (suite — **T06 livré**, journal auto-alimenté)

Choisi explicitement par l'utilisateur (« phase suivante » posée en question
ouverte après EA-06 : Vague 2/T06 préféré à EA-07 ou à la clôture de
Vague 1). Fiche écrite, trois décisions soumises et validées (« valide les
trois, enchaîne sur les incréments ») :

1. P&L réalisé par trade + calendrier P&L : oui, ce sont des faits sur des
   trades déjà pris. Expectancy/profit factor/taux de réussite/courbe
   d'équité : non dans ce tour — exactement le vocabulaire qu'[ADR 0011](../adr/0011-banc-de-replay.md)
   bannit pour le banc de replay, et ce que le charter écarte déjà comme KPI.
2. Aucune nouvelle table — vue de lecture pure sur `closed_trades`/
   `position_opens`/`trade_captures`/`setup_proposals` : ce que backlog.md
   décrivait comme « nouveau modèle de données à construire » existait déjà,
   éclaté sur quatre tables.
3. Lien Capture uniquement quand une ligne `trade_captures` existe —
   jamais un lien mort (deux trades du 2026-09-14 ont perdu leur capture de
   sortie pour de bon, voir le journal T05).

Quatre incréments, gates vertes à chaque étape (tsc, lint, `dotnet build`
0 warning, `dotnet test` 34, vitest 184, `next build`) :

1. `JournalRepository.GetTradesAsync` + `GET /api/journal/trades` —
   `LEFT JOIN` partout, pas l'`INNER JOIN` du précédent le plus proche
   (`SetupProposalRepository.GetClosedTradesAsync`) : un trade reste visible
   même sans `position_opens` ou sans capture.
2. `/journal` : table filtrable (dates, symbole côté client), lien Capture
   conditionnel.
3. Calendrier + ventilations (symbole, session, heure d'entrée, jour de la
   semaine), agrégées côté TypeScript depuis la même liste — aucun nouvel
   endpoint par vue.
4. Enrichissement EA-02 — trouvaille en cours de route : une fonction pure
   de rapprochement existait déjà, `lib/setup/reconciliation.ts::reconcile`
   (tolérance 5 min), déjà utilisée par `/setups`. Réutilisée telle quelle
   après avoir commencé à en écrire une seconde à 30 min — jetée avant
   d'aller plus loin.

**Vérifié contre de vraies données, au-delà des gates.** TimescaleDB
redémarrée (arrêtée depuis 6 h), backend relancé, `GET /api/journal/trades`
appelé directement contre les trades réels du 2026-09-14/15 (accountId
477029930) : jointures correctes, `entryPrice`/`stopLoss` bien `null` sur le
seul trade sans capture, et — trouvaille en vérifiant — **tous les autres
trades réels ont `stopLoss: 0`** (jamais posé pendant cette période
OBSERVE), donc la colonne R multiple est vide sur les données actuelles :
honnête, pas une régression. `GET /api/setup-proposals` ne renvoie que des
`blocked` (cohérent avec le taux d'accord EA-02 toujours à 0/595) : rien à
accrocher pour l'incrément 4 aujourd'hui, vérifié comme vide plutôt que
supposé.

**Non vérifié : le rendu dans un navigateur.** `/journal` chargé dans le
navigateur intégré — aucune erreur console, l'état de chargement s'affiche
correctement — mais aucun agent MT5 n'est connecté à ce backend fraîchement
relancé, donc `useCockpit().account` reste `null` indéfiniment (même
comportement que toute autre page du cockpit sans connexion live). Table,
calendrier et ventilations jamais vus rendus à l'écran avec des données
réelles.

---

## 2026-09-16 (**EA-06 livré** — résolution `UNKNOWN`, positions externes, surface cockpit)

Fiche écrite et deux décisions soumises la veille (« lance EA-06
maintenant ») ; validées telles que proposées ce jour (« valide les deux,
enchaîne sur les incréments ») : comportement par défaut `WARN` sur une
position externe (l'exposition est déjà comptée sans distinction via
`PositionsTotal()`, ce qui manque est l'attribution, pas une barrière de
plus), et logique de réconciliation dans l'agent MQL5 (seul endroit avec un
accès direct à `HistoryDealsGet`/`PositionsGet`, même raisonnement que
l'observer Python pour `scan_missed_round_trips`).

Quatre incréments, gates vertes à chaque étape :

1. **Wire** — `Mt5ReconciledMessage`/`Mt5PositionScannedMessage` dans
   `mt5-wire.ts` + miroirs C#. Un message par position, jamais un tableau
   (`JsonLite.mqh` ne lit que du plat).
2. **Résolution `UNKNOWN`** — `CommandStore.mqh` gagne
   `CommandStoreFindUnknown` (énumération, n'existait pas). L'agent cherche
   par `InpMagicNumber` + `"TradingOS "+commandId` dans le commentaire du
   deal/ordre, lit toujours `DEAL_POSITION_ID`, jamais un ticket — le piège
   du 2026-09-05 revérifié à la main. Déclenché sur le heartbeat et sur
   toute connexion. Écart assumé par rapport au brouillon de la fiche :
   `not_found` n'abandonne jamais (pas de plafond à 3 tentatives, pas de
   `RECONCILIATION_PENDING`) — détail dans le journal de la fiche.
3. **Positions externes** — `ScanOpenPositions`, `isExternal` sur magic
   number seul, `POSITION_IDENTIFIER` jamais un ticket. Corrigé au passage
   un commentaire d'EA-05 qui annonçait à tort qu'EA-06 exclurait les
   positions externes du compte `PositionsTotal()` — c'est l'inverse de la
   décision validée ; le compte n'a pas bougé.
4. **Persistance + cockpit** — `command_reconciliations`/`position_scans`
   (upsert, pas d'accumulation — `envelopes` porte déjà l'historique
   complet) ; `GET /api/execution/divergence` ; `/positions` sort de son
   placeholder (il réservait déjà ce texte à « reconciliation state »).
   Nommé « divergence », pas « réconciliation », pour ne pas percuter le
   sens qu'EA-02 donne déjà à ce mot (`SetupProposalRepository`).

Gates : MetaEditor 0/0 à chaque incrément MQL5, tsc, lint, `dotnet build`
(0 warning), `dotnet test` (34), vitest (184), `next build`.

**Deux limites assumées, pas cachées** (détail : journal de la fiche EA-06) :
la propagation du commentaire de commande jusqu'au deal MT5 est une
hypothèse jamais vérifiée en réel — `OrderSend` n'a encore jamais tourné ;
et le scénario « mort de l'agent entre `OrderSend` et l'accusé » n'a été
vérifié que par lecture du code (même méthode que l'incrément 6 d'EA-05),
jamais par un test exécuté — aucun harnais MQL5 n'existe dans ce dépôt.

Seul l'incrément 3 produit du trafic réel dès aujourd'hui (`PositionsTotal()`
ne dépend pas du mode) ; l'incrément 2 reste sans trafic tant qu'`OrderSend`
est inatteignable. `OrderSend` lui-même : vérifié inchangé après les 4
incréments (un seul site d'appel, `g_mode` toujours `const MODE_OBSERVE`).
`state.md` : plus de « prochaine action » construite — le projet passe en
observation jusqu'à ce que les préconditions d'EA-07 se remplissent par de
vrais trades.

---

## 2026-09-15 (suite — rendu T05 réparé, course de lockout corrigée, **EA-05 incrément 6 livré**)

**Rendu des captures, réparé et vérifié à l'écran.** Deux défauts, pas un.
(1) Le viewer demandait le timeframe déclaré par la capture — « M15 », hérité
de l'observer XAUUSD — pour un symbole qui n'a que du M1 en base. Corrigé
dans `app/(cockpit)/journal/[brokerPositionId]/page.tsx` : si le store n'a
rien au timeframe déclaré, il le rebâtit depuis le M1 avec `aggregateCandles`
(la fonction pure et testée d'EA-02). Le repli vit côté TypeScript et pas
dans le `/api/candles` en C# parce que l'ADR 0004 interdit de réimplémenter
le moteur d'analyse dans un autre langage. (2) Une fois les bougies là, elles
restaient invisibles : les marqueurs `SL 0` / `TP 0` — MT5 écrit 0 pour « pas
de stop posé », pas « stop à zéro » — tiraient `computePriceScale` de 0 à
1,1534 et écrasaient 24 bougies en une bande d'un pixel. `buildMarkers`
n'émet plus de ligne pour un niveau absent : une ligne absente se lit
correctement comme « aucun stop ». Vérifié sur la position 3230177984 :
24 bougies M15 agrégées depuis 361 M1, entrée, sortie, overlay order-block.
Premier rendu T05 jamais validé visuellement sur EURUSD.

**Course sur le registre de lockout, corrigée.** Les 4 lignes « Daily loss
guard » à 73 ms d'intervalle du 2026-09-14 : `detectNewLockout` est
correctement edge-triggered sur son entrée, mais l'appelant lui passait un
`activeLockout` périmé — le store n'apprend l'existence du lockout qu'au
retour de l'écho du hub, et les ticks continuent de déclencher des recalculs
pendant ce temps. Ajout d'un `lockoutPublishPending` dans
`signalr-client.ts`, remis à false dès que l'écho atterrit, donc il ne peut
jamais masquer un verrou réellement nouveau. Logique pure inchangée.

**EA-05 incrément 6 — livré, sur accord explicite et séparé.** L'utilisateur
l'a demandé nommément après que j'aie refusé de l'inclure dans une demande
générale de clôture la veille ; c'est le feu vert que la fiche attendait.

Le dépôt contient désormais **un** `OrderSend`, et un seul. Vérifié en lisant
le code, comme la fiche l'impose, pas en me croyant : `grep` sur tout le
dépôt → un seul site d'appel ; il est dans `ExecuteOrder` dont la première
instruction sort si le mode n'est pas `CONFIRM` ; `ExecuteOrder` n'a qu'un
appelant, lui-même derrière un test de mode ; et `g_mode` est déclaré une
fois en `const … = MODE_OBSERVE` et **jamais affecté nulle part**. Le chemin
est donc prouvablement mort dans ce build — écrire la voie et pouvoir
l'emprunter sont deux accords distincts, et le second (EA-07) n'est pas
demandé ni rempli.

Idempotence traitée à l'endroit qui compte : `UNKNOWN` écrit sur disque
**avant** l'appel broker, résultat réel réécrit après — un agent qui meurt
au milieu laisse `UNKNOWN`, et le rejeu retourne `DUPLICATE` sans jamais
renvoyer d'ordre. Un refus broker est un résultat définitif (`FAILED`), pas
une ambiguïté. Trouvé au passage : `tp` n'était parsé nulle part dans
`HandleOrderCommand` alors que le wire l'envoie — ajouté.

Corrections exigées par l'ADR 0010 faites dans la foulée : `README.md` et
`.claude/CLAUDE.md` ne prétendent plus qu'aucun appel de trade n'existe — ils
décrivent la barrière, et CLAUDE.md gagne une consigne explicite de ne pas
l'élargir sans accord séparé. `charter.md` n'a pas eu à bouger : son principe
6 (« aucun ordre n'est envoyé sans qu'un humain l'ait déclenché ») reste vrai.

Gates : `MetaEditor64.exe /compile` → **0 errors, 0 warnings** ; lint, tsc,
184 tests TS, `npm run build`, `py_compile`, `dotnet build` (0 warning),
`dotnet test` (34). Prochaine action passée à EA-06 dans `state.md`.

---

## 2026-09-15 (kill switch réel, correctif T05 confirmé, gap de rendu trouvé — Vague 1 toujours ouverte)

Reprise après redémarrage complet de session (docker/backend/observer/worker
tous tombés avec la session précédente) — toute la chaîne relancée et
revérifiée avant tout diagnostic, pas supposée repartie seule.

**Reset de minuit** : confirmé que le mécanisme est bien côté client, comme
prévu la veille. `dayAnchorStartsAtUtc` avait basculé côté serveur
(2026-09-15T00:00:00Z), mais le lockout *Daily loss guard* est resté marqué
actif jusqu'à la reconnexion du cockpit — personne n'était là au moment de
la bascule. Levé automatiquement (`next-day-reset`) à la reconnexion.

**Kill switch testé pour de vrai par l'utilisateur.** Cycle complet tracé en
base : verrouillage 09:34:44 UTC (`risk_lockouts`, raison « Kill switch
manuel ») → acquittement 09:37:15 (`kill_switch_acks`) → levée 09:37:18
(`cleared_by = kill-switch-ack`, seul chemin qui existe dans le code pour ce
type de lockout). Ferme la case correspondante de la checklist T02a/T02b —
la seule qui ne dépendait que de l'utilisateur.

**Trouvé en vérifiant la clôture de Vague 1** : une position EURUSDm a été
ouverte à 09:36:00 UTC — **pendant** la fenêtre du lockout kill-switch
(09:34:44 → 09:37:18), fermée 60 s plus tard à 09:37:00, avant même
l'acquittement. C'est exactement la situation que le critère de sortie
reformulé la veille interdit. Constat neutre, pas une remontrance : la vague
reste ouverte, et c'est le critère qui fonctionne, pas un échec à cacher.

**Correctif T05 (course entrée/sortie) confirmé en conditions réelles.** Le
même trade (60 s, plus rapide que les deux qui avaient échoué le
2026-09-14) a ses deux captures — entrée et sortie — vérifiées via l'API.
Le correctif tient en production, pas seulement aux gates.

**Trouvé en vérifiant le rendu, jamais fait avant** : `/journal/3230177984`
affiche « No candles in the captured window » sur les deux captures. Cause
identifiée : `candles` ne porte que du M1 pour EURUSDm/GBPUSDm (pipeline
EA-02) et que du M15 pour XAUUSDm (seul symbole que diffuse
`mt5_observer.py`). Le rendu de capture demande du M15 dans la fenêtre —
absent pour tout symbole hors XAUUSD, donc pour tout le périmètre réel de
S01 (EURUSD/GBPUSD). Les faits sont bien écrits ; seul le rendu échoue.
Non corrigé — décision de conception à prendre (agréger le M1 à la volée
côté rendu, ou persister le M15 depuis le worker EA-02), pas un correctif
d'une ligne. Détail dans le journal de `T05-captures-auto.md`.

**Précision trouvée sur la barrière EA-07** : T02a (kill switch, daily loss
guard) a tourné en réel plusieurs fois. **T02b — la pause temporisée de
30 min sur deux pertes consécutives — n'a elle jamais été déclenchée** :
un seul trade perdant est survenu à ce jour, jamais deux d'affilée
(`risk_lockouts` : zéro ligne avec `until` renseigné). La barrière d'EA-07
n'est donc que partiellement remplie, pas entièrement comme on aurait pu le
lire trop vite dans le state.md d'avant cette entrée.

**EA-02, état chiffré** : 595 évaluations à ce jour, **zéro** `proposed`.
Toutes bloquées avant la séquence S01 elle-même (fenêtre horaire, lockout,
ou biais H4/D1 non aligné). Le taux d'accord reste à l'état de pipeline
fonctionnel, pas de mesure — sans changement de fond depuis la veille.

**Explicitement pas touché, sur demande de « clôturer toutes les phases
ouvertes »** : EA-05 incrément 6 (`OrderSend`). Aucune formulation de
demande de clôture globale ne vaut accord explicite séparé pour celui-ci —
c'est la règle elle-même (ADR 0010, fiche EA-05) et elle ne se déduit pas.
Toujours pas donné.

`state.md` mis à jour en conséquence (bloque désormais sur trois points
précis plutôt qu'un vague « rien n'est vérifié ») ; `context/product/tools/T05-captures-auto.md`
complété (correctif confirmé + gap de rendu trouvé) ; `03_Suivi_Projet/Suivi.md`
resynchronisé dans la foulée.

---

## 2026-09-14 (suite — correctif calendrier EA-02, recadrage post-T01/T04)

Quatre tâches enchaînées après « à part attacher l'EA, que peut-on faire
pour avancer maintenant ».

**1. Correctif fail-closed du gate calendrier, worker EA-02.** Trouvé en
vérifiant ce qui bloquerait réellement `run-setup-detection.ts` une fois le
lockout levé : `upcomingReleases(client)` faisait un `SELECT` brut sur
`news_releases` et renvoyait `[]` si la table était vide — jamais `null`.
`isNewsBlackout(now, [], ...)` avec un tableau vide renvoie `false` (pas de
blackout). Résultat : la précondition calendrier **ne bloquait jamais rien**
dans ce worker, contrairement au vrai gate T03 côté backend .NET
(`NewsCalendarRepository.GetUpcomingOrNullAsync`, qui distingue correctement
« jamais synchronisé » de « synchronisé, rien à venir » via
`SELECT EXISTS(...)`). Corrigé en miroir exact de ce mécanisme :
`upcomingReleases` renvoie maintenant `null` si la table est vide, et
l'appelant bloque explicitement (`precondition_calendar`,
« FRED calendar never synced — fail-closed ») avant même d'appeler
`isNewsBlackout`. Pas de test dédié (le script fait de l'I/O Postgres directe,
même statut que le reste des composants socket/DB du dépôt). Effet non
observable en direct cette session : à l'heure du correctif (16h UTC), la
précondition de fenêtre horaire bloque déjà avant d'atteindre le calendrier —
se vérifiera à la prochaine fenêtre Londres ou NY AM.

**2. Recadrage T06/T07 post-retrait de T04.** La fiche d'origine de T06
dépendait explicitement du contexte du ticket T04 (setup déclaré, biais,
confiance, invalidation — capturés avant que le résultat ne biaise le
souvenir). Sans T04, ce contexte n'existe plus : T06 redevient un journal des
faits d'exécution (base + captures T05 + `setup_proposals` d'EA-02 en
approximation machine, jamais l'intention humaine), pas des intentions.
Conséquence en cascade sur T07 : sa taxonomie fermée comptait *« trade hors
plan »* et *« absence de ticket »* — toutes deux supposent un plan déclaré.
Redéfini vers ce qui reste mesurable sans déclaration : stop déplacé, taille
hors politique, trade pendant lockout, trade hors fenêtre. Écrit dans
`context/product/backlog.md` et `context/project/roadmap.md`.

**3. Critère de sortie de Vague 1 reformulé.** L'original (« dimensionner,
armer et journaliser via le cockpit ») n'a plus de sens sans T01/T04. Nouveau
critère, sur ce qui reste (T02/T03/T05, une couche passive) pendant une
séance réelle : kill switch déclenché et acquitté pour de vrai, capture
entrée+sortie sur chaque trade sans exception, aucune règle de risque active
contournée en tradant directement dans MT5. Décision prise par moi, à
l'instruction explicite de l'utilisateur (« enchaîne jusqu'à la fin ») —
signalée comme telle, pas illustrée comme si elle allait de soi. Noté
explicitement : la séance du jour même ne remplit pas ce critère (deux trades
EURUSD pendant un lockout actif), donc ne clôt pas la vague — le critère
fonctionne, il ne s'auto-valide pas complaisamment.

**4. `roadmap.md` nettoyé** : lignes T01/T04 marquées retirées, table Vague 2
mise à jour, `03_Suivi_Projet/Suivi.md` corrigé sur son unique mention de T04
(reste de la staleness de ce fichier hors périmètre — il datait du
2026-09-11, avant toute la séance EA-05 ; son propre en-tête dit que le dépôt
fait foi en cas de divergence).

Gates vertes (tsc, lint, 184 tests TS — inchangé, aucune logique pure
touchée). Worker EA-02 relancé sur le code à jour.

---

## 2026-09-14 (suite — retrait du pipeline Signal → RiskDecision → Command factice)

Trouvé en répondant à « à quoi sert l'interface Signals » : `signalr-client.ts`
(le client **réel**, pas mock) démarrait sans condition, à chaque connexion,
une boucle Phase 09 vieille d'avant le pivot — toutes les 30s, elle fabriquait
un faux `StrategySignal` à partir du **vrai** contexte de marché et du **vrai**
état de compte, le faisait juger par le **vrai** Risk Engine, et — si approuvé
— soumettait une **vraie** `PlaceOrderCommand` via `connection.invoke("SubmitCommand", ...)`,
le même chemin que l'agent EA-05 réel. Vérifié en base avant toute suppression :
309 lignes dans `strategy_signals`/`risk_decisions`, 0 dans `execution_commands`
— aucune n'avait encore atteint la soumission, mais rien ne l'empêchait
structurellement. Aucun risque financier dans tous les cas (EA-05 est
`OBSERVE` figé, pas d'`OrderSend`), mais de quoi polluer une vraie séance de
vérification EA-05 avec des rapports `SIMULATED` fantômes.

**Erreur évitée en creusant avant de couper** : la fiche EA-03 documente
`lib/execution/command-builder.ts::buildPlaceOrderCommand` comme *« seule
porte d'entrée d'une commande, dérivée d'une RiskDecision approuvée »* — ce
n'est pas un reliquat de la boucle factice, c'est le protocole réel qu'EA-05
consomme en aval. Conservés intacts : `command-builder.ts` (+ test),
`lib/domain/execution.ts`, `lib/domain/strategy.ts` (type dont
`buildPlaceOrderCommand` dépend), `lib/contracts/commands.ts`,
`CockpitHub.SubmitCommand`, et tout l'audit `CommandRow`/`AckRow`/`ReportRow`
(`execution_commands`, `command_acks`, `execution_reports` — ce dernier sert
la télémétrie EA-05 réelle, `execution.order.simulated` alimente les deux).

Retiré, précisément : la boucle elle-même (`startSignalLoop`/`runDecisionLoop`
+ `submitCommand`/`onAckTimeout`/`pendingAcks`, glue client-side propre à son
rythme de fake-submit, pas documentée comme protocole par EA-03) des deux
clients (réel et mock — sans UI pour l'afficher, le générateur mock devenait
lui aussi sans objet) ; `StrategySignal`/`RiskDecisionView`/`ExecutionCommandView`
(lecture-modèle dashboard, `signalId`-shaped, distincts du `StrategySignal`
domaine que `command-builder.ts` garde) ; les pages/composants `/signals`,
`signal-queue.tsx` (+ son point de montage sur Command Center) ; `SignalRow`/
`DecisionRow` et leurs tables `strategy_signals`/`risk_decisions` (`DROP
TABLE`-ées en local) ; les entrées `strategy.signal.created`/`risk.decision.made`
de la liste blanche `CockpitHub.PublishableTypes` et de `EventType`. Trouvé et
nettoyé au passage : `journal.ticket.created` traînait encore dans `envelope.ts`
depuis le retrait de T04 — oublié la première fois.

Gates vertes (lint, tsc, 184 tests TS — 202 au départ de la séance, T01/T04 et
ceci expliquent la baisse —, build, `dotnet build`, `dotnet test` 34).
Backend et cockpit relancés sur le code à jour.

---

## 2026-09-14 (retrait T01/T04, correctif T05, séance réelle EA-02)

Séance avec trading réel en parallèle (compte démo 477029930), pipeline
EA-02 tournant en continu. Trois choses faites, dans l'ordre où elles sont
arrivées :

**Correctif T05** — `TradeCaptureRepository.RecordExitAsync` no-opait
silencieusement sur deux trades EURUSDm réels (47 s et 2 min 13 de durée de
vie), alors que `closed_trades` les avait bien. Cause : `RecordEntryAsync`
et `RecordExitAsync` sont dispatchées fire-and-forget depuis
`GatewayBridgeService`, chacune sur sa propre connexion, sans garantie
d'ordre — sur un aller-retour assez rapide, l'exit peut chercher la ligne
'entry' avant que son insert ait committé. Corrigé par une relecture bornée
(5 tentatives, 200 ms d'écart) dans `FindEntryWithRetryAsync` — le cas
« aucune entrée n'existera jamais » (position antérieure au backend, ex. la
position backfillée le même jour) continue de no-oper exactement comme
avant, une fois le budget de tentatives épuisé. Gates vertes. Pas de test
dédié ajouté — même précédent que le reste des classes socket/DB de ce
fichier, vérifiées en intégration.

**Retrait T01 + T04** — décision explicite de l'utilisateur, pas la mienne :
panneau de sizing et ticket pré-trade supprimés du cockpit, ainsi que toute
la chaîne qui les portait (`lib/domain/ticket.ts`, le chemin
`journal.ticket.created` de bout en bout côté TS et C#, la table
`pretrade_tickets`). Détail complet dans le journal des fiches T01 et T04.
Rien d'autre n'en dépendait — vérifié par grep avant de couper, pas supposé.
Gates vertes après coup (lint, tsc, 193 tests TS, build, `dotnet build`/`test`
36). Conséquence non résolue dans cette entrée : le critère de sortie de la
Vague 1 (« séance 100% cockpit ») perd deux de ses trois outils — à
retrancher ou reformuler la prochaine fois que la clôture de vague est
rediscutée.

**Trading réel pendant la séance** — 5 puis plusieurs trades supplémentaires
pris directement dans MT5 (XAUUSDm et EURUSDm), aucun via le cockpit. Un
trade (position 3225412263, TP-gagnant) manqué par l'observer parce qu'il a
tourné entièrement avant que `mt5_observer.py` soit relancé en session
précédente — backfillé dans `closed_trades`/`position_opens` à partir de
`mt5.history_deals_get()`, valeurs identiques à ce que l'observer aurait
écrit (`sum_realized_pnl`/`weighted_exit_price` recalculés à la main). Un
lockout *Daily loss guard* s'est déclenché en réel (13:37:28) sur la perte
flottante d'une position XAUUSDm — confirmé qu'il n'existe aucun clear
manuel pour ce type de lockout (`acknowledgeLockout` est câblé en dur sur
`kill-switch-ack`), seulement `shouldAutoClearForNewDay` au prochain
rollover UTC, et seulement si le cockpit est ouvert à ce moment pour
l'évaluer. Aucun des trades du jour n'avait de stop-loss — le critère « R
cohérent » de la checklist T02a/T02b reste donc non vérifiable, pas par
manque de code mais par absence de stop sur les trades réels.

---

## 2026-09-12 (EA-05 — incréments 2–5 livrés, en attente avant l'exécution)

Agent MQL5. Cartographie avant code a trouvé un trou structurel que le
prompt de lancement ne nommait pas : aucun point d'écoute Gateway n'existait
pour un agent entrant (`Mt5ObserverClient` ne fait que dialer *vers*
l'observer Python). Trouvé aussi un conflit documentaire :
`context/realtime/mt5_agent_realtime_lifecycle.md` décrit une architecture
sidecar pré-pivot, obsolète, contredisant `mt5_wire_protocol.md`. Deux
décisions validées avec l'utilisateur : TCP brut (pas WSS) entre l'agent et
le Gateway, et le nouveau point d'écoute dans le périmètre de cette fiche.

Livré : `Mt5AgentServer.cs` (nouveau, jamais fusionné avec l'observer),
`CockpitHub`/`GatewayBridgeService`/`Program.cs` branchés,
`tools/mt5-execution-agent/TradingOsAgent.mq5` + deux includes (JSON plat
maison, persistance `commandId → résultat` sur disque), toutes les
barrières locales de `safety.md` sauf l'exécution elle-même. **Aucun
`OrderSend` dans le fichier.** Correction en route : `Mt5ExecutionMode`
portait encore `"live"` (vocabulaire pré-ADR 0010) — renommé `"confirm"`,
renommage pur vérifié sans effet de bord.

Nouvelle gate ajoutée : compilation MQL5 headless via `MetaEditor64.exe`
(trouvé installé localement), 0 erreur sur le premier essai.

Ouvert : incréments 2–5 vérifiés seulement par compilation au moment
d'écrire ce qui précède. **Mise à jour même session** — l'utilisateur a
testé les incréments 2 à 5 contre un vrai terminal, tout est vert (procédure
du README de l'outil suivie). L'incrément 6 (exécution) reste soumis à un
accord explicite séparé, distinct de cette vérification, conformément à
l'ADR 0010 — pas encore donné.

---

## 2026-09-12 (EA-04 — livré)

Profils de compte, modèle de coût, registre de symboles. Cartographie avant
code : `TradingAccount`/`AccountKind` (`lib/domain/account.ts`) existaient
déjà mais n'étaient utilisés nulle part ; `RiskProfile` demandé par le prompt
de lancement est le même concept que `RiskPolicy` existant. La porte de coût
d'EA-01 attendait déjà `costThreshold`/`commission` en paramètres — seul
`scripts/run-setup-detection.ts` les codait en dur.

Trois décisions validées avec l'utilisateur avant code : réutiliser
`AccountKind` plutôt qu'un second axe `AccountType`, `XAUUSDm` comme symbole
XAUUSD canonique (`XAUUSD247m` documenté à part), et une structure FTMO avec
placeholders `TODO(FTMO-rules)` documentés plutôt que des chiffres devinés —
le compte FTMO n'existe pas encore.

Livré : `lib/market/symbols/registry.ts` (canonique↔broker, réutilise
`SymbolMetadata`), `lib/accounts/{types,cost-model,ftmo,real,registry}.ts`,
`defaultRiskPolicy` étendu avec un paramètre `registry` optionnel (signature
compatible, les cinq appelants réels dont T01 sont inchangés puisque le
registre réel est vide), et le câblage réel dans
`scripts/run-setup-detection.ts`. T01 vérifié inchangé — cette fiche rend la
*policy* multi-compte, pas le *sizing* multi-symbole (hors périmètre,
assumé).

Ouvert : `ACCOUNT_PROFILES` reste vide tant qu'un compte FTMO ou réel n'est
pas confirmé ; les valeurs FTMO/real restent des placeholders à renseigner
depuis la source officielle avant d'enregistrer un compte.

---

## 2026-09-12 (EA-03 — livré)

Protocole d'exécution et machine à états, sans MQL5 ni réseau. Cartographie
avant code : le chemin `RiskDecision → Command → ACK → Report` existait déjà
au niveau wire, mais sans machine à états nommée, sans `UNKNOWN`, sans
`ACCOUNT_MISMATCH`, sans `protocolVersion` explicite sur la commande.

Décision d'architecture validée avec l'utilisateur : la machine à états (12
états, `transition()` pure) vit dans `lib/domain/execution-state.ts`, pas
dans `lib/contracts/execution/` — écart assumé au texte du prompt de
lancement, par cohérence avec l'ADR 0004. `lib/contracts/execution/` porte le
vocabulaire de rejet typé (`ACCOUNT_MISMATCH` en premier) et la règle
d'idempotence (`recordOrReplay`, testée : un rejeu ne ré-exécute jamais).
Trois documents `context/execution/{protocol,state-machine,safety}.md`
écrits. `CockpitHub.SubmitCommand` non branché — posé pour EA-05/EA-06.

Ouvert : le branchement réel (persistance de l'état par `commandId`,
vérification `ACCOUNT_MISMATCH` contre un agent réel, résolution
d'`UNKNOWN`) attend l'agent MQL5 (EA-05) et la réconciliation (EA-06).

---

## 2026-09-12 (EA-02 — livré côté code)

Écart trouvé avant tout code : la chaîne temps réel ne fournit ni le
multi-symbole ni le M1 nécessaires à S01 (un seul symbole, M15, en dur).
Architecture validée avec l'utilisateur : `tools/mt5-observer/export_m1_candles.py`
(nouveau, ne touche pas `mt5_observer.py`) + `scripts/run-setup-detection.ts`
(worker `npx tsx`, Postgres direct pour les pré-conditions T02a/T02b/T03).

Dix incréments livrés et vérifiés de bout en bout contre le terminal démo
réel : extension d'EA-01 (`evaluateSetup`), agrégation M1→H1/H4/D1,
killzones NY (DST-aware, valeurs ICT provisoires), export Python, table
`setup_proposals`, worker de détection, endpoint .NET + rapprochement,
panneau cockpit (`/setups`) — observé dans Chrome avec de vraies données.

Quatre défauts réels trouvés en testant (pas en relisant) : double comptage
de volume dans l'agrégation de bougies ; un bug de mapping Dapper
(`DateTimeOffset` dans un record lu, même classe de bug que celui déjà
documenté dans `/api/audit/recent` le 2026-07-12) ; `closed_trades` sans
heure d'ouverture (jointure `position_opens` ajoutée) ; un appariement de
rapprochement premier-arrivé-premier-servi au lieu du plus proche
globalement. Détail complet dans `EA-02-observe-taux-accord.md`.

Gates verts : lint, tsc, 165 tests TS, build, dotnet build/test (38,
inchangé). Non fait : le critère de réussite de S01 (taux d'accord sur un
échantillon de séances) — demande de faire tourner le worker plusieurs
séances réelles, pas du code qui manque.

---

## 2026-09-12 (EA-01 — livré)

`lib/setup/` : neuf modules purs (bias, dealing-range, liquidity, sweep,
displacement, poi, stop, gates, proposal) détectant la séquence S01 sur des
bougies, sans réseau ni exécution. `SetupProposal` (nouveau, distinct de
`StrategySignal`) dans `lib/domain/setup.ts`. 36 tests dédiés, 143 au total
dans le dépôt, quatre gates vertes (lint, tsc, test, build). `lib/analysis/`
et `lib/risk/` non modifiés ; `lib/strategy/` n'existe pas.

Défaut trouvé et corrigé en construisant : calculer le pool de liquidité sur
des bougies qui contiennent déjà la bougie du sweep se contredit tout seul
(`detectLiquidity` marque le niveau « balayé » avant que `detectSweep` ait pu
tester la réintégration). Corrigé en séparant l'entrée en `contextCandles` /
`reactionCandles`. Détail complet et cinq autres décisions dans la fiche
`EA-01-detection-s01.md`.

Prochaine étape : EA-02 (mode OBSERVE + taux d'accord machine/humain) —
voir `02_Plan_Projet/prompt-claude-code-vague-ea.md`.

---

## 2026-09-12 (Phase 0 — préalables et mesure)

Aucun code de production, conformément au bloc Phase 0 de
`02_Plan_Projet/prompt-claude-code-vague-ea.md`.

Écrits : `tools/mt5-observer/log_spread.py` (échantillonnage jetable du
spread EURUSD/GBPUSD toutes les 5 s, JSONL local, ne touche pas à
`mt5_observer.py`), `analyze_spread.py` (médiane/p90/p99/max par tranche de
15 min en heure de New York), `list_symbols.py` (résolution des suffixes
broker). Testés en syntaxe et sur un JSONL synthétique.

Bloqué : le terminal MT5 local est lancé mais pas connecté à un compte
(`mt5.initialize()` échoue avec `Authorization failed`) — aucun identifiant
n'est demandé ni stocké ici (charte). `context/domain/symbols-broker.md` est
créé avec la structure attendue et un statut « en attente » ; la connexion
manuelle puis `list_symbols.py` restent à faire pour le remplir, et
`log_spread.py` doit tourner au moins cinq séances avant de calibrer le
seuil de `c`.

Tags d'archive : confirmé via `git ls-remote --tags origin` que
`archive/pre-pivot-2026-09-04` et `archive/pivot-commits-2026-09-04`
n'existaient que localement. Poussés sur `origin` après confirmation.

---

## 2026-09-11 (suite — cadrage EA)

Aucun code. Interview de cadrage sur une proposition d'évolution arrivée de
l'extérieur (`01_Recherche/EA_implementation.md`) : ajouter un agent d'exécution
MT5 et deux profils de compte séparés, FTMO et réel.

Décisions prises : l'EA passe en priorité **devant** la clôture de la Vague 1,
qui attend ; construction jusqu'au mode CONFIRM seulement, AUTO explicitement
exclu ; v1 sur EURUSD/GBPUSD ; stratégie unique synthétisée depuis trois systèmes
réellement tradés (SCALP, Liquidity Trap, FULL 1:20RR), régime de sortie hybride ;
banc de replay autorisé en dépôt séparé, sans aucune métrique de performance.

Écrit : **ADR 0009** (dette de T05, en attente depuis le 05/09), **ADR 0010**
(le Trading OS exécute, l'EA est un agent), **ADR 0011** (banc de replay ≠
backtester), **fiche S01** (stratégie « Sweep aligné »).

Ouvert : les vérifications listées en fin de S01 — le spread réel contre un SL de
3 à 7 pips en tête, parce qu'il peut invalider le régime de sortie — puis les
fiches EA-01 à EA-06.

---

## 2026-09-11 (suivi)

Aucun code. Six jours sans session depuis le 2026-09-05 : la clôture de la
Vague 1 n'a pas été faite. Mise à jour de `state.md` — « Ce qui bloque »
nomme désormais le seul point ouvert, la validation contre un vrai terminal
MT5 — et remplissage de `03_Suivi_Projet/Suivi.md`, vide depuis la création
du dossier.
Ouvert : ADR 0009 (faits capturés / rendu à la demande), puis la séance
réelle de bout en bout qui clôt la vague.

---

## 2026-09-05 (revue T05)

Deux défauts trouvés en revue sur `tools/mt5-observer/mt5_observer.py`
(T05, livré dans la session précédente), corrigés avant tout usage réel —
détail complet dans `context/product/tools/T05-captures-auto.md` :

1. **Mauvais identifiant comme clé** — le diff et
   `history_deals_get(position=...)` utilisaient `p.ticket` au lieu de
   `p.identifier` (`POSITION_IDENTIFIER`, égal à `DEAL_POSITION_ID`). Les deux
   coïncident dans le cas courant (d'où le bug invisible) mais divergent sur
   des opérations de service côté broker — le jour où ça arrive sur une
   position vivante : fausse clôture, fausse ouverture, `tradesToday` faussé,
   capture d'entrée sur le mauvais trade, entrée parasite dans la série de
   pertes consécutives.
2. **Trade ouvert-et-fermé entre deux sondages invisible** — le sondage à
   2 s ne peut voir un aller-retour plus court : le ticket/identifiant
   n'entre jamais dans `_known_position_ids`, donc ne peut jamais en sortir
   côté diff. Exactement les scalps courts et les stops touchés
   immédiatement — les trades qui pèsent le plus sur les métriques de
   discipline.

Corrections : `identifier` partout où une position est clé ; nouvelle
fonction `scan_missed_round_trips` (balayage des deals de sortie récents à
chaque poll, reconstruit `opened`+`closed` pour tout `position_id` fermé
jamais vu ouvert — `stopLoss`/`takeProfit` à `0.0`, la convention MT5
elle-même pour « pas de stop », pas une valeur inventée, puisque les deals ne
portent pas ces champs). 7 tests ajoutés (17 au total côté observer),
`unittest.mock` stdlib, aucune nouvelle dépendance. `python -m py_compile`
et `python -m unittest` verts ; aucun changement côté TS/C#.

---

## 2026-09-05 (suite 3)

Outil : T05 (livré) — captures automatiques entrée/sortie. **La Vague 1 est
entièrement livrée** (T01–T05) ; reste la clôture de vague elle-même.

Décision d'architecture rediscutée en session et inversée par rapport à la
fiche initiale : la fiche proposait un rendu côté serveur .NET (SVG ou PNG).
L'utilisateur a signalé le défaut de raisonnement — porter `lib/analysis/` en
C# pour dessiner créerait une seconde source de vérité (contraire à l'ADR
0004), et le cockpit devra de toute façon savoir rendre un graphique pour
T06. Conception retenue : **le serveur capture des faits immuables et bornés
(fenêtre, prix), le cockpit rend l'image à la demande** avec
`analyzeMarketContext` — jamais une image pré-calculée. Candidat ADR identifié
pour la clôture de vague (le principe dépasse ce seul outil).

Deux trouvailles ont élargi le périmètre au-delà de la fiche :
- Le vrai événement de fill est `journal.position.opened`/`journal.trade_closed`
  (T02a/T02b), pas les rapports SIMULATED de la boucle de décision transitoire.
- `journal.position.opened` était détecté côté navigateur (T02a) — un trade
  manuel pris sans onglet cockpit ouvert ne déclenchait ni le comptage
  `tradesToday` ni, pour T05, la capture d'entrée. Migré côté Gateway (même
  schéma que la fermeture T02b : un seul diff `positions.snapshot` calcule
  ouvertures et fermetures, `seed_known_positions` évite tout événement
  fantôme au démarrage). Corrige un vrai bug T02a en le faisant.

Ajouts : `exitPrice` sur `journal.trade_closed`/`closed_trades` (moyenne
pondérée par volume, même risque de piège que T02b si on prenait un seul
deal) ; table `trade_captures` (écrite par une réplique dédiée hors pipeline
`PersistenceWriter` — l'écriture de la ligne 'exit' doit relire la ligne
'entry' d'abord, un envelope ne mappe pas vers deux tables) ; premier
endpoint de lecture par plage sur `candles` ; `lib/journal/chart-scale.ts`
(pur, testé) + `components/journal/trade-chart.tsx` (SVG) + viewer minimal
`/journal/[brokerPositionId]` (pas le journal complet — T06 reste le stub).

Gates tous verts : `npm run lint`, `npx tsc --noEmit`, `npm test` (107,
+6), `npm run build`, `dotnet build`, `dotnet test` (38, inchangé — glue DB
non testée en unitaire, même convention qu'ailleurs), `python -m unittest`
(10, +6). Non vérifié : la chaîne complète contre un terminal MT5 réel (pas
d'extension Chrome connectée, même limite qu'en T02/T03).

---

## 2026-09-05 (suite 2)

Outil : T03 (livré) — gate calendrier économique FRED. Vague 1 : reste T05.

Suivi `02_Plan_Projet/prompt-claude-code-vague-1.md`. Trois décisions
proposées avant code, validées par l'utilisateur :
- **Liste blanche à 5, sans ISM** — vérifié que l'ISM a fait retirer toutes
  ses séries de FRED en 2016 (litige de licence), aucun `release_id` de
  remplacement n'existe. CPI (10), NFP (50), PCE (54), Retail Sales (9),
  FOMC (101) — chaque ID confirmé individuellement sur `fred.stlouisfed.org`.
- **Clé FRED côté backend .NET, jamais `.env.local`** — le fetch se fait
  serveur pour ne jamais exposer la clé dans le bundle navigateur ; déviation
  assumée de la fiche initiale.
- **Cache en table Postgres** `news_releases`, écrite directement par
  `NewsCalendarRepository` (hors pipeline `PersistenceWriter`, qui suppose un
  envelope → une ligne — un rafraîchissement remplace tout un `release_id`
  d'un coup).

Trouvaille en cours de route qui a changé la conception : FRED ne renvoie
qu'une **date**, jamais une heure de publication. Résolu en combinant la
date FRED avec l'heure de publication officielle et stable de chaque série
(8h30 ET pour CPI/NFP/PCE/Retail Sales, 14h00 ET pour FOMC), convertie en UTC
réel via `TimeZoneInfo`/`America/New_York` (jamais un offset figé — testé
contre un vrai communiqué FOMC daté du 10/12/2025).

Deuxième trouvaille, plus subtile : un backend qui vient de démarrer, avant
son premier fetch FRED réussi, a une table vide — si ça se traduisait par
« calendrier connu, rien à venir », la gate s'ouvrirait à tort au boot,
exactement le fail-open que l'outil doit empêcher. Résolu en distinguant
`null` (jamais synchronisé, gate refuse) de `[]` (synchronisé, rien à venir,
gate ouverte) — `NewsCalendarRepository.GetUpcomingOrNullAsync`.

`newsBlackoutMinutes` passé de 15 à 30 dans `defaultRiskPolicy` (lu depuis la
policy, jamais codé en dur). Chip permanent dans `TopCommandBar` (pas dans un
onglet, comme exigé).

Gates tous verts (`npm run lint`, `npx tsc --noEmit`, `npm test` — 101 tests,
`npm run build`, `dotnet build`, `dotnet test` — 38 tests). Non vérifié :
mise à jour du badge après hydratation et cycle FRED réel contre une vraie
clé API — pas d'extension Chrome connectée cette session (même limite qu'en
T02a/b) ; confirmé seulement par `curl` que le rendu serveur ne plante pas et
affiche honnêtement l'état fail-closed avant hydratation.

---

## 2026-09-05 (suite)

Outil : T02b (livré) — historique des deals MT5 et pause de 30 min sur deux
pertes consécutives, dernier morceau de T02. T02 est maintenant entièrement
livré.

Ce qui a changé, en suivant le plan écrit en session précédente
(`context/product/tools/T02-lockout.md`) sans déviation :
- **Observer** — `poll_positions()` (un seul appel `positions_get()` par
  tick, détecte les fermetures par diff de tickets) + `sum_realized_pnl` /
  `build_position_closed`, extraites en fonctions pures et testées
  (`tools/mt5-observer/test_mt5_observer.py`, stdlib `unittest`) : le test
  reproduit le piège signalé en revue (position gagnante fermée en deux
  deals partiels, le dernier négatif après swap — la somme doit rester
  positive).
- **Wire + Gateway** — `Mt5PositionClosedMessage` (TS/C#), publié en direct
  par le Gateway sous `journal.trade_closed` (comme `risk.day_anchor.resolved`,
  jamais via `PublishEvent`).
- **Persistance** — table `closed_trades`, sans scope de journée (la traîne
  de pertes consécutives ne se réinitialise pas à minuit, contrairement à
  `tradesToday`).
- **`GET /api/risk/today`** — étendu avec `consecutiveLosses` /
  `lastConsecutiveLossAt` ; `activeLockout` filtre désormais aussi
  `until IS NULL OR until > now()`.
- **`lib/risk/lockout.ts`** — `detectConsecutiveLossPause` (déclenché
  spécifiquement sur le gate `gate-consec-loss`, pas sur `mode === "locked"`
  en général) et `isLockoutExpired` extraite séparément ; `applyActiveLockout`
  prend maintenant un `now` obligatoire.
- **Cockpit** — chrono de la pause dans `RiskStatusPanel` (`setInterval` 1s
  local, dérivé de `risk.lockoutUntil`, aucun nouvel état dans le store).

Gates tous verts (`npm run lint`, `npx tsc --noEmit`, `npm test` — 84 tests,
`npm run build`, `dotnet build`, `dotnet test` — 35 tests, `python -m
py_compile`). Non vérifié en session : la chaîne complète contre un
terminal MT5 réel (pas d'extension Chrome connectée, même limite qu'en T02a).

---

## 2026-09-05

Outils : T01 (livré), T04 (livré), T02a (livré, T02b reste ouvert).

Ce qui a changé :
- **T01** — panneau de sizing permanent dans le cockpit, appelle
  `evaluateSignalRisk` sans le modifier. Trois défauts corrigés en revue
  avant tout commit : budget de perte quotidien calculé sur le solde
  restant (pas le total), `null` affiché comme « — » jamais « 0 % », R
  cible qui refuse un TP du mauvais côté de l'entrée.
- **T04** — ticket pré-trade en 4 boutons, publié via `PublishEvent`
  (pas de nouvel endpoint). Confirmation par écho (pas par soumission) après
  revue des trois refus silencieux de `PublishEvent` ; badge de persistance
  ajouté au cockpit pour le cas qu'aucun écho ne couvre (écriture perdue
  après diffusion).
- **T02a** — ancre de journée (minuit serveur, offset MT5 résolu
  dynamiquement), `tradesToday` réel (comptage de positions, pas de P&L),
  état verrouillé stocké dans un ledger (jamais dérivé), kill switch réel
  (verrouillage + bandeau + accusé de réception journalisé, aucun
  `close_all` simulé). Plan initial (7 incréments) coupé en T02a/T02b en
  revue : un seul verrou (pertes consécutives) a besoin de l'historique des
  deals MT5, les quatre autres non.
- **Gouvernance** — ADR 0008 : réintroduction bornée d'un journal de
  session (ce fichier), `state.md` redevient un instantané.

Ouvert : T02b (deal history MT5, verrou de pertes consécutives — plan détaillé
dans `context/product/tools/T02-lockout.md`). Rien n'est commité pour T04/T02a
au moment de cette entrée.
