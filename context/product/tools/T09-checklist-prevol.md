# T09 — Checklist de pré-vol exécutable

Statut : **livré** (3 incréments, 2026-09-17) · Vague 3 · Effort 1–2 j ·
Valeur 4 · Dépend de : T03 (livré)

## Problème

Le rituel de démarrage de séance est une intention, pas un geste : rien ne
dit, en un coup d'œil et avant d'avoir cliqué quoi que ce soit, « tout est
en ordre, tu peux commencer ». Les éléments existent, éparpillés ; la
vérification reste mentale.

## Écart trouvé avant tout code (cartographie)

Lu avant d'écrire quoi que ce soit : `catalogue.md` (#9), `backlog.md`
(T09), `lib/risk/{gates,evaluate,policy,types}.ts`,
`lib/risk/sizing.ts::evaluateSignalRisk`, `components/cockpit/risk-status-panel.tsx`,
`app/(cockpit)/risk/page.tsx`, `tools/mt5-observer/{log_spread,analyze_spread}.py`.

**L'essentiel de ce que décrit la fiche d'origine existe déjà.** C'est le
piège que `.claude/CLAUDE.md` nomme en premier ; autant le dire avant de
coder plutôt que de le redécouvrir après :

| Item de la checklist (catalogue.md) | État réel |
|---|---|
| « Le système vérifie lui-même les items » | **Déjà fait** — `evaluateRiskState` exécute 8 gates à chaque évaluation. |
| Affichage vert/rouge par item | **Déjà fait** — `RiskStatusPanel` rend chaque gate avec sa pastille et son détail. |
| « Tant que tout n'est pas vert, le Risk Engine refuse » | **Déjà vrai** — `evaluateSignalRisk` refuse sur `state.mode === "locked"` *et* sur le premier `gate.state === "blocked"` venu. Aucun mécanisme d'enforcement à ajouter. |
| Drawdown quotidien restant | **Déjà fait** — `dailyLossGate` + `maxDrawdownGate`, barres de progression comprises. |
| Blackout news | **Déjà fait** — `newsGate` (T03), fail-closed sur cache absent. |
| Spread dans la norme | **Partiel** — `spreadGate` existe mais sur un seuil plat (`maxSpreadPoints`), pas « pour l'heure ». |
| Compte connecté | **Absent** — l'état de connexion existe (`Mt5AgentServer.IsConnected`, `/health`), mais n'est évalué par aucun gate. |
| « Plan écrit pour la journée » | **Mort** — c'était T04, retiré le 2026-09-14 (même constat que T06/T07/T08). |
| « Verrous armés » | **Ambigu** — les lockouts sont réactifs, il n'y a rien à « armer » avant la séance. |

**Ce qui reste donc vraiment à construire est petit** : un gate manquant
(connexion), un verdict unique « armé / pas armé » là où il n'y a
aujourd'hui que huit lignes à lire une par une, et une surface dédiée au
rituel.

**Limite à énoncer franchement, parce qu'elle vient d'être démontrée.**
« Le Risk Engine refuse les ordres » ne contraint que ce qui passe *par ce
système* — c'est-à-dire, aujourd'hui, rien (chemin `observe` uniquement), et
même en `CONFIRM` (EA-07) cela ne couvrirait pas un ordre passé à la main
dans MT5. Les 6 trades ouverts pendant un lockout actif les 2026-09-14/15
(voir `state.md`, « Ce qui bloque ») sont exactement ce cas. T09 ne corrige
pas ça et ne peut pas : sa valeur est le **rituel et la visibilité**, pas
une nouvelle barrière. La fiche d'origine promettait implicitement plus.

## Décisions à valider avant d'implémenter

1. **T09 est une surface de rituel, pas un second moteur de règles.**
   Aucune réécriture de `evaluateRiskState` ni des gates : la checklist les
   *lit*, les agrège en un verdict unique (`armé` / `pas armé` + la liste
   de ce qui bloque), et l'affiche sur une page dédiée `/preflight` (entrée
   de nav dans « Operate »). Pas sur le Command Center, déjà dense, et pas
   sur `/risk`, dont le stub est réservé à la configuration des gates et à
   l'historique des lockouts (T02/T12).

2. **Un seul vrai nouveau gate : la connexion.** `connectionGate` dans
   `lib/risk/gates.ts`, même forme que les autres (`RiskGateResult`), nourri
   par l'état de connexion déjà publié. C'est le seul item de la checklist
   sans gate aujourd'hui — et c'est un vrai trou : le Risk Engine approuve
   actuellement des ordres sans jamais vérifier qu'un agent est joignable.

3. **Spread « dans la norme pour l'heure » : reporté, hors périmètre.**
   Les normes par tranche horaire n'existent nulle part de façon
   interrogeable — seulement dans `analyze_spread.py`, explicitement marqué
   « throwaway analysis for Phase 0 », qui recalcule médiane/p90/p99 à la
   demande depuis un JSONL. Les rendre utilisables demanderait collecte
   continue + persistance + refonte de `spreadGate` : un morceau à part
   entière, pas un sous-produit d'une checklist. Le gate plat reste.

4. **Blackout news : garder les 30 min de la policy, pas les 60 de la fiche
   d'origine.** Deux seuils pour la même règle, c'est deux vérités et un
   futur écart silencieux entre ce que la checklist affiche et ce que le
   Risk Engine applique. Si 60 min est le bon chiffre, c'est
   `newsBlackoutMinutes` qu'on change — une décision de politique de risque,
   séparée, pas un réglage d'affichage.

## Comportement attendu

1. `/preflight` affiche chaque item vérifié automatiquement, avec son état
   et son détail — les 8 gates existants plus la connexion.
2. Un verdict unique en tête : **armé** (tout vert) ou **pas armé**, avec la
   liste de ce qui bloque.
3. Aucun bouton qui « arme » quoi que ce soit : l'état est dérivé, jamais
   déclaré. Un item ne se coche pas à la main — c'est le point de la fiche
   d'origine (« pas un document à cocher ») et ça reste vrai.
4. « Plan écrit » retiré de la liste ; « verrous armés » devient « aucun
   lockout actif », qui est mesurable.

## Ancrage dans le code

- `lib/risk/gates.ts` — `connectionGate` ajouté à côté des autres, même
  signature. Testé unitairement comme ses voisins.
- `lib/risk/evaluate.ts` / `types.ts` — un champ d'entrée de plus
  (`agentConnected`), le gate rejoint la liste. Rien d'autre ne bouge.
- `lib/domain/risk.ts` — `RiskState.gates` porte déjà la forme rendue.
- `components/cockpit/risk-status-panel.tsx` — patron de rendu des gates à
  réutiliser, pas à dupliquer.
- `app/(cockpit)/preflight/page.tsx` + `components/shell/nav.ts` — nouvelle
  page et son entrée de nav.

## Découpage en incréments

1. `connectionGate` + branchement dans `evaluateRiskState` (+ tests purs).
2. Page `/preflight` : verdict unique + liste des items, lue depuis l'état
   de risque existant.
3. Entrée de nav + retrait de « plan écrit » / reformulation de « verrous
   armés » dans la doc de l'outil.

## Critère de réussite

Ouvrir une seule page avant la séance, et savoir en un coup d'œil si tout
est en ordre — sans lire huit lignes ni ouvrir MT5.

## Journal

- 2026-09-17 — fiche créée après le choix « Vague 3 — T09/T10, puis T19 ».
  Cartographie faite avant tout code, et elle réduit beaucoup le périmètre :
  l'auto-vérification, l'affichage par gate et le refus du Risk Engine
  existent déjà tous les trois ; le neuf se limite à un gate manquant
  (connexion), un verdict agrégé, et une page dédiée. Deux items de la
  fiche d'origine retirés (« plan écrit », T04 mort) ou reformulés
  (« verrous armés »), un reporté (normes de spread par heure, qui
  n'existent que dans un script Phase 0 jetable). Limite énoncée
  explicitement : aucune de ces vérifications ne contraint un ordre passé à
  la main dans MT5 — les 6 trades des 2026-09-14/15 l'ont démontré. **Arrêt
  ici, en attente de validation des quatre décisions.**

- 2026-09-17 (suite) — les quatre décisions validées telles que proposées
  (« valide les quatre, enchaîne sur les incréments »). Trois incréments,
  gates vertes (tsc, lint, vitest 210/210 — 4 nouveaux, `next build`) :

  1. `connectionGate` dans `lib/risk/gates.ts` + `agentConnected` dans
     `RiskEvaluationInput`, branché dans `evaluateRiskState` comme gate
     d'entrée (jamais un lockout de compte). Champ **non nullable** à
     dessein, contrairement à tous ses voisins : la connexion est toujours
     connue (un agent est enregistré auprès du Gateway ou il ne l'est pas),
     donc aucun « n/a » honnête à rapporter. Le champ requis a fait remonter
     ses 6 sites d'appel par le typage, aucun oublié.
  2. `/preflight` : verdict unique (`Armé` / `Pas armé` + liste des points
     bloquants) au-dessus de la liste complète des points vérifiés. Lit
     l'état de risque existant, n'évalue rien lui-même.
  3. Entrée de nav « Pré-vol » (section Operate).

  **Vérifié à l'écran, les deux états.** Serveur de dev lancé en mode `mock`
  sur un port séparé (`.env.local` de l'utilisateur laissé intact) : état
  `Armé` avec les 9 gates au vert — dont `Execution agent — connected`, le
  nouveau — puis `agentConnected` basculé temporairement à `false` dans le
  mock pour voir l'état `Pas armé` (pastille rouge, « 1 point(s)
  bloquant(s) », `Execution agent — no agent connected` listé), puis
  reverté. Première vérification visuelle réelle d'une page de ce cockpit
  depuis T05 : le blocage des sessions précédentes (« jamais vu rendu, aucun
  agent MT5 connecté ») venait de `useCockpit().account` resté null sans
  backend live — le mode `mock` le contourne entièrement. **Vaut pour T06 et
  T07 aussi**, dont les pages n'ont jamais été vues : le même mode permet de
  les regarder sans MT5.

  **Trouvaille d'environnement, sans rapport avec le code** : deux 404 sur
  `/preflight` *et* `/journal` (route pourtant livrée et vue en ligne plus
  tôt) alors que `/` répondait 200 — cause : un `.next` périmé, laissé par
  des `npm run build` de production intercalés entre des serveurs de dev.
  `rm -rf .next` répare. À connaître avant de suspecter le code.
