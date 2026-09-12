# S01 — Stratégie « Sweep aligné »

Statut : **à faire** · Vague EA · Effort 3–5 j · Valeur 5 · Dépend de : rien pour
la détection ; l'exécution dépend de EA-01 à EA-06.

Première fiche de la série S : une stratégie n'est pas un outil du cockpit, mais
elle suit la même discipline — écrite avant de coder, complétée pendant, close
après.

## Problème

Le poste de travail sait dimensionner, verrouiller, refuser et journaliser. Il ne
sait pas reconnaître un setup. Tant que la reconnaissance vit uniquement dans la
tête de son utilisateur, rien ne peut être proposé, ni mesuré, ni exécuté — et le
taux de conformité au plan reste invérifiable, puisque le plan n'est écrit nulle
part sous forme testable.

Cette fiche formalise le process de trading réellement pratiqué, en règles
déterministes. Elle ne cherche pas un edge et n'en revendique aucun (ADR 0002) :
elle transcrit une pratique existante pour que la machine puisse la proposer, la
vérifier et la journaliser.

## Origine

Synthèse de trois systèmes tradés, documentés dans
`C:\Ebrain\06_ENTREPRISES\Trading\03_Idees\01_strategy\` :

| Source | Ce qui en est retenu |
|---|---|
| **The SCALP Trading System** (Waqar Asim) | Hiérarchie 1H / 5M / 1M, filtre prime-décote à 50 %, POI extrême et décisionnel, fenêtres de session, risque 1 % |
| **Liquidity Trap Strategy** (Marco Trades) | Le sweep comme condition obligatoire, SL derrière la mèche, partiels sur liquidité interne et non sur R fixe, interdiction du break-even prématuré, time-stop avant le NY Lunch |
| **The FULL 1:20RR** (Riz Iqbal) | Le HTF commande la direction et la cible, le LTF ne sert qu'à comprimer le risque, partiels puis runner |

Les trois s'accordent sur la direction — le HTF commande, le sweep ne donne que
le timing — et sur le stop. Leur seul désaccord réel portait sur le régime de
sortie ; il est tranché ci-dessous (régime hybride).

Onze autres fiches du même dossier fournissent les briques : géométrie du FVG et
Consequent Encroachment, anatomie du Breaker, matrice PD Array, distinction
LRLR / HRLR, neutralisation des mèches, analyse inter-marchés.

## Comportement attendu

### Périmètre

EURUSD et GBPUSD uniquement. XAUUSD est hors périmètre jusqu'à ce que les
paramètres exprimés en pips soient passés en ATR-relatif.

### Pré-conditions

Évaluées avant toute recherche de setup. Si une seule manque, il n'y a pas de
recherche.

| Condition | Règle |
|---|---|
| Fenêtre horaire | Killzone Londres ou Killzone NY, en heure de New York, offset serveur résolu dynamiquement (mécanisme de T02a) |
| NY Lunch | Aucune nouvelle position après 12:00 NY ; les positions restantes sont fermées |
| Calendrier | Gate FRED (T03) : aucun blackout en cours |
| Verrous | T02a / T02b : aucun lockout actif, `tradesToday` sous la limite |
| Profil de marché | Chemin dégagé vers la liquidité cible. Marché encombré ou en consolidation : pas de setup |

### Séquence

**1 — Biais (H4/D1).** Une seule direction autorisée pour la journée. Structure
validée par BOS ou CHoCH **en clôture de corps**. En consolidation, il n'y a pas
de biais, donc pas de trade.

**2 — Dealing range (1H).** Dernière impulsion, external high et external low,
équilibre à 50 %. Achat uniquement sous l'équilibre, vente uniquement au-dessus.

**3 — Liquidité.** Cartographier PDH/PDL, Asia High/Low, Equal Highs/Lows. La
cible du trade est la poche opposée non encore purgée.

**4 — Sweep (M5/M1).** Le prix dépasse le niveau puis y revient dans la même
bougie : `Low[0] < niveau ET Close[0] > niveau` pour un achat, l'inverse pour une
vente. Sans réintégration, c'est une cassure et non un sweep — le setup est
abandonné, pas mis en attente.

**5 — Déplacement et MSS (M1).** Clôture de corps au-delà du dernier swing
opposé, accompagnée d'un FVG non comblé. Le corps de la bougie de rupture doit
valoir au moins 1,5 × ATR(14). Une mèche qui traverse ne vaut rien.

**6 — Entrée.** Ordre limite sur le FVG laissé par le déplacement ; à défaut, sur
l'Order Block ou le Breaker à l'origine du mouvement. Le CE est le point médian
du FVG.

**7 — Stop Loss.** Au-delà de l'extrême de la mèche du sweep, plus un buffer de
spread. Si la distance obtenue dépasse le plafond calibré du symbole, le setup
est refusé — les « 3 à 7 pips » du SCALP servent de contrôle de qualité, pas de
valeur figée.

**8 — Portes de viabilité.** Deux refus possibles avant toute proposition :

- **Porte de coût.** Soit `c = coût aller-retour ÷ distance SL`, le coût étant
  le spread **lu en direct au moment de la décision** plus la commission du
  compte. Si `c` dépasse le seuil du profil de compte, le setup est refusé.
  Le R réellement encaissé vaut `R_réel = (R_nominal − c) / (1 + c)` : le coût
  rogne le gain et gonfle chaque perte, et c'est ce second effet qui domine.
  Ordres de grandeur mesurés en recherche le 2026-09-11 (à confirmer en réel) :

  | | `c` | R réel sur un 1:3 | Win rate d'équilibre |
  |---|---|---|---|
  | EURUSD, SL 3 pips | 0,30 | 2,08 | 32,5 % |
  | EURUSD, SL 5 pips | 0,18 | 2,39 | 29,5 % |
  | EURUSD, SL 7 pips | 0,13 | 2,54 | 28,2 % |
  | GBPUSD, SL 3 pips | 0,40 | 1,86 | 35,0 % |
  | GBPUSD, SL 5 pips | 0,24 | 2,23 | 31,0 % |
  | GBPUSD, SL 7 pips | 0,17 | 2,42 | 29,2 % |

  Conséquence : **c'est le petit stop qui coûte cher, pas le grand.** La fiche
  avait un plafond de SL ; cette porte lui donne son plancher, exprimé en ratio
  et non en pips — ce qui la rend transposable telle quelle à XAUUSD, où parler
  en pips n'a pas de sens.

  Le seuil de `c` est un **paramètre de profil de compte**, provisoirement fixé
  à 0,25. Il se déplacera quand le win rate réel sera mesuré, pas avant.

- **Porte R:R.** La liquidité externe opposée doit offrir au moins 1:3 depuis le
  prix d'entrée, **après** application du coût. En dessous, le setup n'est même
  pas proposé.

La porte de coût est réévaluée au remplissage : un spread qui s'élargit entre la
proposition et l'exécution peut invalider un setup déjà accepté. C'est le cas
courant, pas le cas rare — le spread s'élargit précisément à l'ouverture de
Londres et de New York, c'est-à-dire dans les deux seules fenêtres où cette
stratégie travaille.

**9 — Sorties (régime hybride).**
- Partiel de 50 % au **premier des deux** : 1:3 atteint, ou première liquidité
  interne touchée — définie comme le premier swing opposé validé par fractale
  entre l'entrée et la cible externe.
- Break-even **uniquement après** ce partiel. Jamais avant.
- Le solde vise la liquidité externe opposée.
- Tout est fermé avant le NY Lunch, quel que soit l'état du trade.

### Invalidations

À tout moment, et par ordre de priorité :

- clôture de corps au-delà du CE du FVG d'entrée → ordre annulé s'il n'est pas
  déclenché, position coupée s'il l'est ;
- clôture au-delà de l'extrême du sweep → invalidation absolue ;
- sortie de la fenêtre horaire sans déclenchement → ordre purgé du carnet ;
- délai de retest dépassé → ordre purgé.

### Risque

1 % du capital par trade. 0,5 % pour une éventuelle ré-entrée. La politique de
risque est portée par le profil de compte, jamais globale — un compte FTMO et un
compte réel n'ont pas les mêmes bornes, ni le même modèle de coût.

## Ancrage dans le code

À réutiliser tel quel, **sans le réécrire** :

- `lib/analysis/` — swings, structure, liquidité, PD arrays, sessions, ATR. Pur
  et testé. C'est la source des niveaux de cette stratégie. Aucun portage dans un
  autre langage (ADR 0004, ADR 0009).
- `lib/risk/` — `evaluateSignalRisk`, `defaultRiskPolicy`, lockout. La stratégie
  **propose**, le Risk Engine **décide** (ADR 0007). S01 ne contourne aucune
  gate et n'en ajoute aucune de son côté.
- `lib/execution/` — `RiskDecision → Command → ACK → Report`, déjà validé en
  idempotence.
- Gate calendrier de T03, verrous de T02a/T02b : consommés comme pré-conditions,
  jamais dupliqués.

À créer : `lib/setup/`, détection pure et testée, une fonction par étape de la
séquence.

Le nom `lib/strategy/` est délibérément évité : c'est celui qu'a supprimé l'ADR
0002, et le réutiliser ferait croire à une réintroduction de la recherche d'edge
là où il s'agit de formaliser un process humain.

## Critère de réussite

La stratégie est considérée juste quand, sur un échantillon de séances en mode
OBSERVE :

- tout trade réellement pris a été proposé par la machine — aucun manque ;
- tout setup proposé et refusé s'explique par une règle nommable, qui est alors
  soit ajoutée à la fiche, soit assumée comme écart.

Le seuil et la taille de l'échantillon restent à fixer. Ni le P&L ni le taux de
réussite n'entrent dans ce critère : ce qui est mesuré est l'accord entre la
machine et l'humain, pas la performance (ADR 0002, ADR 0011).

## À vérifier avant de coder

1. **Spread réel, mesuré et non recherché.** Les chiffres du 2026-09-11 viennent
   d'une recherche documentaire, pas du terminal. L'observer Python est déjà
   connecté et en lecture seule : lui faire journaliser le spread par symbole et
   par minute pendant quelques séances transforme l'hypothèse en mesure, sans
   toucher à aucune décision ni à aucun ADR. C'est le préalable au calibrage du
   seuil de `c`.
2. **Suffixes broker** (`EURUSDm` chez Exness) — le symbole registry en dépend.
3. **Modèle de coût par compte** — FTMO (commission ≈ 5 $/lot aller-retour) et
   Exness Raw/Pro n'ont pas le même profil. Le même setup peut passer sur l'un et
   être refusé sur l'autre ; c'est une propriété du profil de compte, pas de la
   stratégie.

## Journal

- 2026-09-11 — fiche créée. Issue de l'interview du même jour et du brief associé.
  Décisions prises avant tout code :
  1. **Le HTF commande la direction, le sweep donne le timing.** Les trois
     systèmes retenus sont d'accord. La fiche *Inducement & Liquidity Framework*
     du même dossier, qui soutenait l'inverse — l'inducement annule la structure
     — n'a pas été retenue par l'utilisateur.
  2. **Deux étages de contexte, pas un conflit.** SCALP tire son biais du 1H,
     Marco pose H4/D1 en pré-condition. Ils ne se contredisent pas : H4/D1 donne
     le sens autorisé, 1H donne le dealing range pour prime-décote. Les deux sont
     conservés.
  3. **Régime de sortie hybride**, choisi par l'utilisateur parmi trois. Il
     respecte Marco (jamais de break-even avant un partiel) et Riz (partiel puis
     runner) sans garder le 1:3 sec du SCALP, qui interdisait le runner.
  4. **La liquidité interne est définie strictement** comme le premier swing
     opposé validé par fractale entre l'entrée et la cible externe. Ni Marco ni
     Riz n'en donnent de définition mathématique ; celle-ci est une convention de
     ce dépôt, à ajuster après observation.
  5. **v1 sur EURUSD/GBPUSD seulement**, là où les chiffres du SCALP sont
     calibrés. XAUUSD attend le passage en ATR-relatif.

- 2026-09-11 (suite) — **porte de coût ajoutée** après recherche sur les spreads
  et commissions FTMO et Exness. Ce qui a changé et pourquoi :

  1. **Le régime hybride survit au coût.** Sur un partiel à 1:3, le win rate
     d'équilibre passe de 25 % à 28–35 % selon le symbole et la taille du stop.
     Contre les ~50 % revendiqués par le SCALP il reste de la marge, mais elle
     est environ un quart plus mince que les chiffres nominaux ne le laissent
     croire.
  2. **Le régime hybride est le plus résistant au coût des trois** envisagés.
     Le runner à 1:8 ne perd que 17 % de sa valeur là où le partiel à 1:3 en
     perd 22 % ; le 1:3 sec du SCALP aurait subi le coût sur 100 % du volume.
     Le choix fait en interview se trouve confirmé pour une raison qui n'avait
     pas été envisagée au moment de le faire.
  3. **Le plancher de stop remplace l'intuition du plafond.** La fiche refusait
     les stops trop larges ; elle refuse désormais aussi les stops trop serrés,
     puisque `c` explose quand le stop rétrécit. Exprimé en ratio plutôt qu'en
     pips, ce plancher vaut pour tout symbole — y compris l'or, où la notion de
     pip n'est pas stable d'un broker à l'autre.
  4. **Le spread est lu en direct, pas moyenné.** Il s'élargit à l'ouverture de
     Londres et de New York, donc exactement dans les deux fenêtres de cette
     stratégie. Une moyenne journalière serait systématiquement optimiste là où
     ça compte.
  5. **Le seuil de `c` n'est pas dérivé, il est posé.** 0,25 provisoire. Le
     fixer « correctement » demanderait un win rate mesuré, qui n'existe pas
     encore — il viendra de la phase OBSERVE et du journal (T06), pas d'un
     calcul a priori.
