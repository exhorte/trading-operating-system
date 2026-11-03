# ADR 0019 — Risque dynamique par trade et nouvelles limites officielles

Date : 2026-11-01. Statut : **accepté** — décision de l'utilisateur en session le
2026-11-01 (mission « Trading Operating System autonome », §6, « Remplace les
anciennes valeurs de risque par les nouvelles règles »). **Amende l'ADR 0015** :
ses valeurs de limites (0,1 % par trade, 4 trades par jour, 2 positions) sont
remplacées ; le principe (limites automatiques, Risk Engine point de contrôle
unique, ADR 0007) tient. Ne lève ni l'ADR 0002 ni la clause « autre stratégie /
autre chemin d'exécution » de `.claude/CLAUDE.md` : S02, le protocole d'ordres
élargi et le banc de validation auront leur propre ADR avant leur code.

## Décision

Les règles internes sont **les mêmes pour Exness et pour FTMO** (un seul profil
de risque, `RiskProfile`). Les règles contractuelles d'un fournisseur s'y
ajoutent, et c'est toujours la plus stricte qui s'applique.

| Paramètre | Valeur |
|---|---|
| Trades par jour | 15 (une position réellement ouverte compte, même fermée aussitôt ; un ordre annulé ou rejeté ne compte pas) |
| Positions simultanées | 5, sur tout le compte (pas par symbole) |
| Perte journalière | 5 % |
| Perte hebdomadaire | 10 % (nouvelle porte `gate-weekly-loss`) |
| Perte totale (existante) | 10 % du capital initial |
| Risque par trade | dynamique — grille ci-dessous |

### Grille (performance = équité ÷ capital initial − 1)

| Performance atteinte | Risque max. par nouveau trade |
|---|---|
| +1 % et plus | 1,5 % |
| de −2 % (exclu) à +1 % (exclu) | 1 % |
| −2 % | 0,1 % |
| −3 % | 0,2 % |
| −4 % | 0,3 % |
| −5 % et moins | aucune entrée (`gate-performance-stop`, verrou persistant) |

## Interprétations retenues (à confirmer ou corriger)

Chacune est une donnée de `DynamicRiskPolicy`, pas une constante enfouie : la
corriger ne demande pas de toucher au moteur.

1. **Valeurs intermédiaires.** La ligne qui s'applique est le palier de pourcent
   entier *atteint*, tronqué vers zéro : −1,9 % → ligne −1 % (1 %), −2,0 % →
   ligne −2 % (0,1 %), +0,9 % → ligne « capital initial » (1 %), +1,0 % → 1,5 %.
   Aucune interpolation. Pourquoi tronquer et non arrondir vers le bas : la
   consigne dit « −5 % : arrêt », et l'arrêt doit tomber à −5,0 % exactement,
   pas à −4,01 %.
2. **Base de la performance** : l'**équité** (flottant, commissions et swaps
   compris) rapportée au capital initial enregistré
   (`DrawdownPolicy.reference_balance`). **Sans capital initial fixé, aucune
   entrée n'est autorisée** (`reference_capital_not_fixed`) : on ne remplace
   jamais le capital initial par la balance du jour.
3. **« La plus stricte prévaut »** : le risque autorisé est le **minimum** de la
   grille, du plafond de 1 % du déclencheur des 200 $, du plafond par trade du
   profil, et des budgets de perte *restants* — jour, semaine, total — c'est-à-dire
   limite − perte déjà subie − risque ouvert au stop. Un budget épuisé refuse
   l'entrée (`risk_budget_exhausted`). Le risque ouvert est compté au stop plein :
   c'est volontairement prudent.
4. **Déclencheur des 200 $** : appliqué tel qu'écrit — équité ≤ capital initial
   − 200 $ ⇒ plafond de 1 %. Il ne relève jamais un risque plus bas.
   **Observation à trancher** : avec un capital initial fixé, la grille donne
   déjà ≤ 1 % dès que la performance est négative ; tel qu'écrit, le déclencheur
   ne change donc jamais rien. S'il devait protéger après un gain (200 $ sous le
   *plus haut* d'équité), c'est une autre règle, qui demande un plus-haut
   persistant : elle n'est pas devinée ici.
5. **Grille non monotone** : 0,1 % à −2 %, 0,2 % à −3 %, 0,3 % à −4 % — le risque
   *remonte* quand la perte se creuse. Appliqué à la lettre ; à confirmer que
   ce n'est pas une inversion.
6. **Base du lot** : `min(balance, équité)`. Jamais plus que ce que l'une ou
   l'autre mesure autorise. Le volume est arrondi vers le bas au pas du courtier ;
   si le lot minimum dépasse le budget, l'ordre est refusé (déjà le cas).
7. **Semaine** : de lundi 00:00 à dimanche, à l'heure du **serveur** du courtier
   (même ancre que la journée, mesurée sur l'horloge MT5, DST compris). La
   référence d'équité de début de semaine est persistée (`trading_week_anchors`)
   et estimée depuis l'historique des deals comme celle du jour ; inconnue, elle
   ferme les entrées. Un changement de semaine ne lève jamais un verrou posé :
   seul un accusé le fait, et la porte se referme aussitôt si la perte est
   toujours là.
8. **Limite de risque ouvert (ADR 0015) conservée** : `max_open_risk_percent`
   (2 % par défaut) n'est pas dans les nouvelles règles, donc inchangée. À 1 %
   par trade elle plafonne en pratique à **deux** positions simultanées : la
   limite de 5 n'est atteignable qu'en relevant ce plafond. À décider par
   l'utilisateur ; ce n'est pas deviné ici.

## Conséquences

- Nouveau : `domain/risk/dynamic_risk.py` (grille, déclencheur, budgets → `RiskAllowance`), `gate-weekly-loss`,
  `gate-performance-stop`, `RiskDecision.allowance`, migration `0004_weekly_anchor`.
- Le risque réel estimé (volume × perte au stop, coûts compris) est dans
  `RiskDecision.sizing`, **persisté avant tout envoi**. Un contrôle final refuse
  toute décision dont le risque effectif dépasse l'allocation.
- `services/positions.py` : au démarrage, l'historique des deals est reconstruit depuis le début de la **semaine** (et non
  plus du jour) — sinon un cœur lancé en milieu de semaine sous-estimerait la perte hebdomadaire. Le compteur de trades
  reste ancré sur le jour.
- Les plafonds contractuels du fournisseur (`apply_provider_ceilings`) s'appliquent aux règles effectives ; seul le FTMO
  2-Step Challenge est sourcé (−5 % jour, −10 % total), les autres phases ne sont pas plafonnées plutôt que devinées.
- Hors de ce lot (phases suivantes) : l'annulation des ordres en attente au
  franchissement d'un verrou n'a rien à annuler tant que l'agent n'accepte que
  le marché ; elle se branche sur `LockoutEnabled` avec l'ajout du `LIMIT`.
