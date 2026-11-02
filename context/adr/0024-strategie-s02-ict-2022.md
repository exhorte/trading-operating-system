# ADR 0024 — Stratégie S02 (ICT 2022) : une seconde stratégie sur le même pipeline, arrêtée par défaut (phase 2)

Date : 2026-11-01. Statut : **accepté, amendé le jour même** (relecture des notes N1–N8 que le plan, §5, impose : voir « Amendement ») — mission « Trading OS autonome » du 2026-11-01 (accord nommé : « une stratégie S02 (ICT 2022) »,
« après son ADR »), confirmée le 2026-11-01 (« continue la suite des phases restantes jusqu'à la fin »). **Ne lève pas** l'ADR 0001 :
seule une stratégie formalisée par l'utilisateur décide des entrées. **Ne touche pas S01** (golden vectors inchangés).

## Contexte

La mission décrit S02 par ses éléments — « biais H4/H1, dealing range, liquidité, sweep, displacement, MSS, POI, FVG, entrées `LIMIT` » —
sans en donner les seuils chiffrés. S01 réalise déjà tous ces éléments (`domain/strategy/s01`, testés, golden vectors) avec une seule
différence de composition : son biais lit **H4 + D1**, là où la mission écrit **H4 + H1**. Écrire un second détecteur pour les mêmes
figures serait un doublon à maintenir ; en inventer d'autres (OTE, breaker, niveaux Fibonacci) reviendrait à décider à la place de
l'utilisateur ce qu'il faut trader.

## Décision

1. **S02 recompose les détecteurs de S01.** Le pipeline de S01 (`evaluate_setup`) accepte une `Variant` — la source du biais, le choix des séries (1H ou carte M15),
   la place de l'entrée dans la zone, des règles de zone et de cible, le préfixe des identifiants — dont la valeur par défaut reproduit S01 à l'octet. S02 est cette
   variante : **biais = H4 et H1 d'accord** (sinon neutre, donc pas de trade), dealing range et carte de liquidité en **M15**, sweep et déplacement + MSS en M1, FVG
   sinon order block, zone en Discount/Premium, cible au-delà des 50 %, stop au-delà de la mèche du sweep, portes de coût et de R:R, et **un ordre `LIMIT` au bord du FVG**
   (voir « Amendement » : la première rédaction disait 1H et CE, contre les notes).
2. **Posé, pas dérivé — sauf là où les notes parlent.** Les seuils de `S02Config` sont ceux de `S01Config` (EURUSD, ATR, tolérances) et restent **posés** ; la structure suit
   N5 et N6, et `entry_fraction` vaut 0 (le bord). Ce que les notes ne chiffrent pas (stop en pips, risque, BE/trailing, double FVG, biais journalier) **n'est pas deviné** : voir
   la fiche S02. XAUUSD reste hors de S02 comme de S01 tant que ses seuils ne sont pas relatifs à l'ATR.
3. **Arrêtée par défaut, trois états.** `STRATEGY_S02` vaut `off` (rien n'est évalué), `measure` (chaque bougie est évaluée et enregistrée
   — la distribution des étapes de blocage est la mesure — mais **rien n'est transmis au Risk Engine**) ou `trade` (comme S01 : intention →
   décision de risque → exécution selon le mode). Défaut : `off`. Passer à `trade` est un acte de l'utilisateur ; en `trade`, le contrôle
   d'autonomie « stratégie valide » exige S01 **et** S02.
4. **Une seule instance de service par stratégie** : `StrategyService` reçoit l'identifiant, la version, la variante, la configuration et
   « agit ou mesure seulement ». Une intention de S02 porte `strategy_id = "S02"` ; son identifiant (`setup-s02-…`) ne peut pas entrer en
   collision avec celui d'un setup de S01 sur la même bougie.
5. **Enregistrement.** `setup_proposals` reste la table de S01 (EA-02 la lit). Les évaluations de toute autre stratégie vont dans
   `strategy_evaluations` (migration 0005, additive : une table et un index), clé `(strategy_id, symbol, event_at)`. Les lectures
   (`/api/strategy/proposals`, MCP) rendent les deux, avec `strategy_id`.

## Amendement du 2026-11-01 (notes N5, N6, N4 relues)

La première version de cet ADR a été écrite **sans lire les notes** de `07_trading_strategy/` ; elle posait l'entrée au CE de la zone et un dealing range
1H comme S01. Les notes disent autre chose, et le plan (§4 et §5) les rend prioritaires. S02 applique donc, en plus du biais H4 + H1 :
**dealing range et carte de liquidité en M15** (N5, N6) ; **zone en Discount/Premium** et non le prix (N5) ; **TP au-delà de la ligne des 50 %** (N5) ;
**ordre limite au bord du FVG, un spread au-dessus pour un achat** (N5, N6) — `entry_fraction` vaut **0** par défaut et non 0,5 ; et le Position Manager annule un
ordre dont l'objectif est atteint avant le remplissage (N6). La fiche `context/product/tools/S02-strategie-ict-2022.md` classe chaque règle (explicite, déduite,
interprétée, non spécifiée) et liste les écarts restants : exécution en M1 alors que le plan écrit M5 ; fenêtre New York 07:00–10:00 (S01) contre 08:30–11:00 (notes).

## Ce que cet ADR ne fait pas

- Il ne dit pas que S02 est rentable : aucune évaluation d'espérance n'existe (c'est la phase 5, et elle mesure, elle n'optimise pas).
- Il ne passe aucune stratégie en `trade` et n'élève aucun plafond d'autonomie.
- Il ne définit pas d'heures de séance propres à S02 : elle lit les fenêtres du compte (Londres 02:00–05:00, New York AM 07:00–10:00).

## Conséquences

- Tests : S02 bloque au biais là où S01 propose (même marché, H1 sans structure) ; S02 propose quand H4 et H1 sont haussiers et que H1
  est en discount ; la variante par défaut est S01 (les golden vectors passent sans changement) ; `entry_fraction` déplace l'entrée dans
  la zone ; deux stratégies sur la même bougie ne se marchent pas dessus ; `measure` n'engendre ni intention ni commande ; `off` n'évalue rien.
- Types TypeScript régénérés (`strategy_id` sur les évaluations).
