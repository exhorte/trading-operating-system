# Architecture d'information du cockpit

Décidé le 2026-09-20. Complète `final_interface_spec.md` (qui décrit le *feel*
et les panneaux) en tranchant la question que la spec laissait ouverte : quel
écran répond à quelle question, et donc ce qui n'a rien à faire ailleurs.

## Le problème qu'on a corrigé

Le Command Center affichait **~104 valeurs distinctes** dans un seul viewport :

| Bloc | Valeurs |
|---|---|
| Bande KPI | 8 |
| Market Context | ~13 |
| Risk Status (2 barres + 9 gates) | ~14 |
| Agent Health | ~7 |
| Positions (2 × 11 colonnes) | 22 |
| Calendrier P&L | ~21 |
| Rapports d'exécution | ~12 |
| Barre de commande | 7 |

Le nombre n'était pas le vrai problème. La page mélangeait **quatre horizons
de temps** — maintenant (positions, agent), aujourd'hui (P&L, gates), ce mois
(calendrier), et la structure de marché — sans qu'aucune question ne soit
posée. L'œil n'avait aucun point d'ancrage.

En parallèle, cinq des dix entrées de navigation étaient des placeholders
« not built yet ». Une navigation qui annonce des écrans vides coûte un clic à
chaque fois pour le réapprendre.

## La règle : un écran, une question

| Écran | La question | Statut |
|---|---|---|
| Command Center | Où j'en suis, là, maintenant ? | allégé |
| Pré-vol | Est-ce que je peux ouvrir une position maintenant ? | inchangé |
| Market Context | Pourquoi le marché est dans cet état ? | rempli |
| Positions | Qu'est-ce qui est ouvert, et est-ce que ça colle ? | complété (2026-09-24 : les positions ouvertes en tête, puis la divergence) |
| Risque & Discipline | Où en est ma discipline, combien avant le verrou ? | rempli |
| Trades Journal | Qu'est-ce que j'ai fait, et est-ce que je l'ai bien fait ? | inchangé |
| Setups (S01) | Le détecteur voit-il ce que je vois ? | inchangé |
| Analyse de compte | Que disent mes données de mon process ? | créé |
| Account | Qu'est-ce qui est branché, maillon par maillon, et sous quelles règles ? | créé (T12, 2026-09-21 comme `/comptes` ; renommé et élargi le 2026-09-23) |
| Settings | Comment chaque compte est configuré et branché ? | revenu (T12 incrément 2, 2026-09-23) |
| Agents & Audit | Qu'a fait le système, et est-il en vie ? | rempli |

Onze écrans, tous porteurs. Deux avaient été retirés le 2026-09-20 :
`/settings` (rien à configurer — pas d'auth, pas de bascule backend, pas de
paramètre de stratégie) et `/replay` (attend le pipeline analytics,
ADR 0011). `/settings` est revenu le 2026-09-23 avec de la matière : le
registre des paramètres de compte et la procédure de connexion MT5.
`/replay` attend toujours.

## Ce que le Command Center garde, et pourquoi

1. **La ligne de verdict** (`SessionVerdictBanner`) — « Armé / Pas armé » et la
   raison, en haut, en gros. La page répondait à cette question uniquement par
   déduction : une tuile « Risk state: NORMAL » parmi sept autres et neuf
   lignes de gates dans un panneau latéral.
2. **Quatre KPI** au lieu de huit. Drawdown journalier, drawdown total, risque
   ouvert et état de risque étaient quatre *composantes* de la même question —
   combien de marge avant un verrou — présentées comme quatre pairs sans
   réponse entre elles. Elles deviennent une tuile, « Marge avant verrou », qui
   nomme la limite la plus proche de mordre (`lib/cockpit/verdict.ts`,
   `tightestHeadroom`).
3. **Les positions ouvertes.** Le seul objet sur lequel une action est possible
   dans l'instant.

Chaque tuile KPI porte une ligne de détail sous le nombre — l'unité, la source,
ou ce dont le nombre est une part. C'est le motif ⓘ de FTMO MetriX rendu
lisible sans survol : un cockpit se lit d'un coup d'œil, et un nombre que
personne ne survole est un nombre que personne n'interprète.

## Où est parti ce qui est sorti

Rien n'a été supprimé dans le déplacement. Chaque bloc est allé dans un écran
qui était vide :

| Bloc sorti | Destination |
|---|---|
| `MarketContextPanel` | `/market-context` |
| `RiskStatusPanel` (9 gates) | `/risk` |
| `AgentHealthPanel` | `/agents` |
| `ExecutionReportsFeed` | `/agents` |
| `PnlCalendar` | supprimé — `/journal` a déjà son `MonthCalendar`, plus riche et alimenté par la base plutôt que par l'instantané temps réel |

## Trois surfaces de données qui n'avaient aucun écran

Repérées en cartographiant les endpoints du backend contre leurs consommateurs
front. Elles ont servi à donner du contenu propre aux écrans receveurs :

- **`GET /api/audit/recent`** — zéro consommateur côté front. Un système dont
  la revendication est que chaque décision est auditable gardait sa piste
  d'audit derrière `curl`. Désormais `AuditFeed` sur `/agents`.
- **`GET /api/risk/lockouts`** — lu seulement par les détecteurs de conformité,
  jamais montré comme historique. C'est la trace des deux incidents de Vague 1
  et du cycle d'acquittement rendu obligatoire par T02c. Désormais
  `LockoutHistory` sur `/risk`.
- **Le calendrier FRED** — réduit à un chip dans la barre de commande alors
  qu'il pilote une gate fail-closed. Désormais `EconomicCalendar` sur
  `/market-context`.

## Duplications supprimées au passage

- **La règle « armé / pas armé »** existait deux fois (`/preflight`, et
  implicitement dans la tuile « Risk state »). Elle vit maintenant dans
  `lib/cockpit/verdict.ts` — pur, testé, importé par les deux.
- **Le calcul du taux de conformité** existait dans `ComplianceBadge` et allait
  être recopié dans la jauge. Il vit dans
  `lib/compliance/use-compliance-rate.ts` : un fetch, une valeur, deux
  affichages. Deux composants calculant le même taux depuis deux fetchs
  indépendants, c'est ainsi que deux « taux de conformité » finissent par se
  contredire sur le même écran.

## Ce qui reste ouvert

- ~~Écran « Analyse de compte »~~ — **livré le 2026-09-20** (`/analyse`).
  Voir « L'écran Analyse de compte » ci-dessous.
- **Journal** — barre de filtres en chips, onglets PnL / Trades / Graphiques,
  rail d'attribution par type de manquement, footer collant.
- **Market Context** — le graphique annoté (liquidité, FVG, OB, BOS/CHOCH)
  n'existe pas ; l'écran ne montre aujourd'hui que le résumé textuel.
- **Replay** — rien avant le pipeline analytics.

## L'écran Analyse de compte (`/analyse`, 2026-09-20)

Adapté du rapport FTMO « Analyse de compte » : une phrase générée par
dimension, puis les chiffres. Trois écarts délibérés avec le modèle :

1. **La discipline avant le P&L**, y compris dans l'ordre de lecture de la
   page. Le rapport FTMO est un post-mortem de performance ; ici le process
   est le produit (ADR 0001).
2. **Aucun conseil.** FTMO termine ses blocs par « focus only on those
   particular trades that turned out successful for you » — de la sélection a
   posteriori, exactement l'erreur qui a mis fin à la recherche d'edge
   (ADR 0002). Les phrases d'ici décrivent et s'arrêtent là. Un test le
   vérifie (`narrative.test.ts`, « never gives trading advice »).
3. **Aucune table de trades.** C'est `/journal`, et la fiche T08 (Décision 1)
   avait raison : un second journal n'aurait servi à rien.

**Rapport à T08.** La fiche T08 a explicitement écarté une page cockpit pour
la *revue hebdomadaire* — « un document qui se lit une fois et se garde ».
Cet écran est un autre objet : T08 rend une semaine dans un fichier Markdown
qu'on garde, `/analyse` lit n'importe quelle plage à l'écran, et surtout
calcule des dimensions que T08 ne calcule pas (durée, taille de position,
jour d'ouverture *vs* de fermeture, heure d'entrée, sens). Les deux partagent
les données et les détecteurs, pas le périmètre.

**Ce qui a été mutualisé plutôt que recopié** (c'était la troisième copie dans
chaque cas) : `lib/journal/types.ts` pour la forme d'un trade clôturé,
`lib/journal/use-journal-window.ts` pour le couple trades + lockouts,
`lib/compliance/summarize.ts` pour les chiffres de conformité, et
`lib/compliance/labels.ts` pour le nom des manquements. `useComplianceRate`
n'est plus qu'une politique de fenêtre glissante par-dessus ces briques.

## Préversion mock et compte réel (2026-09-20)

`NEXT_PUBLIC_MOCK_ACCOUNT_ID` (dans `.env.local`, gitignoré) décide quel
compte la source mock présente. Par défaut `"account-001"`, qui n'existe dans
aucune base : les écrans adossés à HTTP — `/journal`, `/positions`,
`/analyse`, le badge de conformité — sont alors vides, puisqu'ils
interrogent le backend par compte.

Renseignée avec un compte réel, la préversion devient hybride et c'est
l'intérêt : flux temps réel scripté, données de journal réelles. Le libellé
du compte passe à « Compte réel — flux simulé » pour que personne ne lise
l'equity scriptée comme un solde.

Premier effet constaté à l'activation : `/risk` est passé de « 100 %
conforme, 0 verrou » à **33 % hors cadre et cinq verrous réels** — le kill
switch du 2026-09-15 et les quatre « Daily loss guard » du 2026-09-14, soit
exactement la trace des deux incidents de Vague 1. Un écran de discipline
qui affiche 100 % parce qu'il n'a rien à lire est pire qu'un écran vide.

## Comptes (`/comptes`, T12, 2026-09-21)

`/settings` avait été retiré faute de contenu ; il revient sous le nom de ce
qu'il contient, dès qu'il y a un profil de compte à montrer. Il **affiche** —
compte reconnu, règles appliquées en % et en dollars, référence de calcul,
objectifs du challenge avec la provenance de chaque chiffre — et **n'édite
rien** (ADR 0007) : le profil se change dans `lib/accounts/`, par un commit.

Aucune connexion n'en part : l'observer suit le terminal MT5 ouvert, et
l'écran rapporte ce que le nom de son broker a permis de reconnaître. Détail :
`context/product/tools/T12-prop-firm-control-center.md`.

## Account et Settings (T12 incrément 2, 2026-09-23)

`/comptes` devient **Account** (`/account`, redirection temporaire depuis
l'ancienne adresse) et **Settings** revient (`/settings`) — deux questions,
deux écrans :

- **Account** — « qu'est-ce qui est branché ». La chaîne de liaison maillon
  par maillon (hub, observer, compte transmis, profil reconnu, agent EA-05,
  mode), pour que « non connecté » dise *quel* maillon manque ; puis les deux
  comptes du trader côte à côte, FTMO et Exness, branchés ou non ; règles et
  objectifs du compte branché (les cartes de `/comptes`, déplacées dans
  `components/accounts/`). N'édite rien.
- **Settings** — « comment c'est configuré ». Les *faits* d'un compte, et eux
  seuls, s'éditent : challenge FTMO (type, taille, phase), capital de
  référence Exness, texte de reconnaissance du broker. Chaque changement va
  dans un registre en ajout seul côté backend ; **le backend décide au moment
  d'écrire** s'il s'applique tout de suite (aucune séance en cours) ou au
  prochain jour de trading — l'écran annonce la décision, il ne la prend pas
  (ADR 0007). Les *règles* (pourcentages FTMO, limites de discipline) sont
  affichées en lecture seule : elles changent par un commit. Plus la
  procédure de connexion MT5 par compte, et l'historique des changements.

Aucun des deux ne demande d'identifiant : MT5 se connecte, le cockpit suit
(ADR 0003).

## Refonte visuelle (2026-09-24, ADR 0012)

Sur shadcn/ui, d'après la maquette `05_screenchot/dashboar.jpg`. Les
questions des écrans n'ont pas changé ; leur mise en forme, si. Référence
pratique : `design_system.md`.

- **La barre du haut ne garde que le titre, le fil d'Ariane et le compte.**
  Ce qu'elle portait a été placé où il se lit, rien n'a été retiré :
  conformité → première carte du Command Center ; publication et blackout,
  arrêt d'urgence → bas de la barre latérale, sur tout écran ; liaison,
  persistance, environnement → pastille et menu du compte. Settings est
  épinglé en bas de la barre latérale.
- **Command Center** : le verdict devient la carte principale (halo menthe
  ou corail, les neuf contrôles en pastilles), la conformité à côté, puis
  les quatre chiffres en grandes tuiles, puis les positions.
- **Pré-vol** : même carte de verdict, puis une carte par contrôle (icône,
  état, détail) au lieu d'une liste serrée.
- **Positions** : répond enfin aux deux moitiés de sa question — ce qui est
  ouvert (la table du Command Center, réutilisée), puis la divergence
  d'exécution.
- Partout : cartes aérées, grands chiffres légers, espacements doublés,
  plus de libellés en 10 px capitales.
