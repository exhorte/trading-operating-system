# S02 — Stratégie ICT 2022 (notes N5, N6, N4)

Statut : **construite le 2026-11-01, arrêtée par défaut, jamais mesurée** (ADR 0024, amendé le même jour après relecture des notes). Code :
`python/trading_os/domain/strategy/s02/` (la variante) sur le pipeline de `domain/strategy/s01/proposal.py`. Réglage : `STRATEGY_S02=off|measure|trade`.

Sources : `07_trading_strategy/00_Synthese_strategies.md` (synthèse, `verified: false`) et les notes **N5** (modèle 2022, base), **N6** (liquidité
de plage interne et MSS), **N4** (filtres temporels). **N8** et **N7** : voir plus bas. Ces notes décrivent des **indices futures** (NQ, ES) : leur
transposition à EURUSD n'est pas faite par les sources.

La classification demandée par le plan (§5) :

## 1. Règles explicites dans les sources, et appliquées

| Règle | Source | Où |
|---|---|---|
| Une prise de liquidité (run sur Equal Highs/Lows relatifs) précède tout signal | N5, N6 | sweep puis déplacement, dans cet ordre (`evaluate_setup`) |
| Le signal est une cassure de structure (MSS) qui laisse un FVG | N5, N6 | `detect_displacement` (+ FVG non comblé) |
| La **zone** (FVG) doit être en **Discount** pour un achat, **Premium** pour une vente (50 % du range) | N5 | `Variant.poi_location` → étape `range_location` |
| L'entrée est un **ordre limite au bord du FVG**, sans confirmation supplémentaire | N5 | `entry_fraction = 0` |
| Un achat limite se pose **un spread au-dessus** du bord (spread et glissement) | N6 (« +3 pips/ticks » sur NQ) | `Variant.entry_spread_offset` : + le spread vivant |
| Le TP est **au-delà de la ligne des 50 %** (« low hanging fruit ») | N5 | `Variant.target_beyond_equilibrium` → étape `gates` |
| Si le marché atteint l'objectif **avant** de revenir dans le FVG, on annule | N6 | Position Manager, `cancel_target_reached` (ADR 0023) |
| Stop conservateur au-delà de la mèche qui a pris la liquidité | N5, N6 | `compute_stop_loss` (mèche du sweep + tampon) |
| Cartographie de liquidité en **M15** | N5, N6 | `Variant.use_map_timeframe` (dealing range et pools sur M15) |
| Pas de trade entre 12:00 et 13:00 NY ; pas de revanche ; pas de martingale | N4, N6 ; N3, N5, N8 | `past_ny_lunch` ; interdits du projet |

## 2. Déductions nécessaires à l'implémentation

- Biais = **H4 et H1 d'accord** (le plan : « H4 contexte, H1 direction »). Les notes N3–N5, N7 renvoient la règle du biais journalier « à plus tard » ;
  la mission demande H4/H1. Sinon neutre, pas de trade.
- Swings en fractales de 5 bougies (`swing_lookback = 2`) : N5 demande « 3 ou 5 ».
- Equal Highs/Lows : tolérance 3 pips — N5 demande « une tolérance en ticks » sans la donner. **Posée.**
- Déplacement = corps ≥ 1,5 × ATR(14) avec FVG : N4 et N6 disent qu'il faut distinguer déplacement et fausse impulsion (filtre ATR). **Posé** (valeur de S01).
- Ratio R:R ≥ 3 : N8 donne 3:1 comme R:R idéal ; la porte de coût (0,25) vient de S01. **Posées.**

## 3. Interprétations proposées (à confirmer par l'utilisateur)

- **MSS validé à la clôture du corps** (S01) alors que N2 et N6 écrivent « une mèche qui traverse suffit ». C'est plus strict ; gardé tel quel.
- **Exécution en M1** : N5/N6 admettent 5/3/2/1 minutes, le plan écrit M5 (détection) puis M1 (précision). Le pipeline évalue en M1. **Écart avec le plan, non résolu.**
- **Heures — tranché le 2026-11-01 (ADR 0030).** S02 a ses propres fenêtres, en heure de New York avec changement d'heure automatique : **Londres 02:00–05:00** (la valeur des notes, N6, identique à celle du code) et
  **New York AM 08:30–11:00** (N4, N5, N6). Les 07:00–10:00 de S01 restent la configuration de S01 (`S01Config.trading_windows`) et ne sont plus l'héritage de S02. Réglables par `STRATEGY_S02_WINDOWS`
  (`london=02:00-05:00,new_york_am=08:30-11:00`). Les notes nomment Londres et le matin 07:00–10:00 comme sessions de *repérage* (marquer les hauts et bas) ; garder Londres comme fenêtre d'exécution de S02
  est le choix d'Exhorte. **Compte existant** : l'enveloppe du compte (porte de session du Risk Engine) garde ses fenêtres enregistrées — la démo a encore 07–10, à élargir dans Settings pour que S02 trade de 10:00 à 11:00.
- Premium/Discount mesuré sur le **dernier dealing range M15** et non sur « le range de la journée » de N5.

## 3 bis. Spécifié par les sources, non construit

- **Invalidation dynamique** (N6) : si les corps de bougie recouvrent entièrement le FVG en sens contraire, couper à la main (« save your stop »). Les
  notes disent elles-mêmes que juger si les corps « s'attardent » est difficile à automatiser et « non défini mathématiquement ». Non inventé.
- **N8** (Drawdown Flatlining) — **construit le 2026-11-01 comme un plafond qui ne fait que baisser le risque, désactivé et inerte** (ADR 0031). Unité de granularité : **0,1 %** (décision d'Exhorte) ; ce n'est pas un
  risque minimum obligatoire, un plafond à 0 % bloque le trade. Déclencheurs construits (ceux que la note chiffre) : une perte, 5 gains consécutifs (le 6ᵉ au minimum), équité sous le capital de départ. **Point restant
  avant activation** : la valeur de « la plus petite unité » (la note : « dépend du confort ») — à écrire dans `RISK_N8_MINIMUM_PERCENT`. Non construits : la montée par palier (augmenterait un risque, taille de palier
  non donnée) et le Soft Start (« session » non définie). La grille de l'ADR 0019 reste le plafond.
- **N7** (Turtle Soup, pyramidage) : exclu par le plan (aucun pyramidage ni moyennage).

## 4. Non spécifié par les sources

Biais journalier et hebdomadaire (règles objectives) ; frontière mathématique d'un MSS valide ; préférence entre double FVG ; préséance OB contre FVG ; distance
du stop en pips pour EURUSD/XAUUSD ; pourcentage de risque (les notes citent 1 à 4,5 %, **non importés** : la grille de l'utilisateur prévaut) ; sorties BE et
trailing pour ce modèle (seulement N1 et N7) ; détection d'un « sucker play ». XAUUSD : seuils non relatifs à l'ATR, donc hors de S02 comme de S01.

## Réglage et état

`STRATEGY_S02=off` (défaut) n'évalue rien ; `measure` enregistre chaque évaluation dans `strategy_evaluations` sans rien proposer au Risk Engine ; `trade` agit
comme S01 (et exige alors la validité des deux stratégies pour l'autonomie). **Aucune mesure sur de vraies bougies n'existe** : `python -m trading_os validate
--strategy S02 …` est l'outil, et en dessous de 100 trades un résultat ne prouve rien (ADR 0026).
