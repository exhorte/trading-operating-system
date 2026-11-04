# Règles de risque en vigueur

Décidées par l'ADR 0019 (2026-11-01), identiques pour Exness et FTMO. Ce document décrit **le code qui existe et qui est
testé** ; `risk_ftmo.md` reste le contexte d'origine (hypothèses, pas des règles).

## Limites

| Règle | Valeur | Où |
|---|---|---|
| Trades par jour | 15 — une position réellement ouverte compte ; un ordre annulé ou rejeté, non | `RiskProfile.max_trades_per_day`, `gate-max-trades` (compte `position_opens` depuis l'ancre du jour) |
| Positions simultanées | 5 sur tout le compte ; **aucune limite par symbole** (ADR 0022) | `PositionLimits.max_open_positions`, `gate-position-limit` |
| Perte du jour | 5 % | `DrawdownPolicy.daily_loss_limit_percent`, `gate-daily-loss` |
| Perte de la semaine | 10 % par défaut, **réglable dans Settings** (ADR 0022) | `DrawdownPolicy.weekly_loss_limit_percent`, `gate-weekly-loss` |
| Perte totale | 10 % du capital initial | `max_drawdown_limit_percent`, `gate-total-dd` |
| Arrêt de performance | −5 % du capital initial | `DynamicRiskPolicy`, `gate-performance-stop` |

Chaque dépassement des portes ci-dessus est un **verrou persistant** (registre `risk_lockouts`) : il ne se lève que par
accusé de l'utilisateur, et se referme aussitôt si la perte est toujours là. Les pertes sont mesurées sur l'**équité**
(flottant, commissions et swaps compris). Le jour commence à minuit **serveur** du courtier, la semaine le lundi 00:00 serveur ;
les deux ancres d'équité sont persistées (`trading_day_anchors`, `trading_week_anchors`), jamais écrasées, et inconnues elles
ferment les entrées.

## Risque par trade : le minimum de tous les plafonds

`resolve_risk_allowance` (`domain/risk/dynamic_risk.py`) renvoie une `RiskAllowance` — le risque max. d'**un** nouveau trade,
le plafond qui l'a fixé, tous ceux pesés, et la raison d'un refus.

1. **Grille** (performance = équité ÷ capital initial − 1, palier entier *atteint*, tronqué vers zéro, sans interpolation) :
   +1 % et plus → 1,5 % · de −2 % (exclu) à +1 % (exclu) → 1 % · −2 % → 0,1 % · −3 % → 0,2 % · −4 % → 0,3 % · −5 % → arrêt.
2. **Déclencheur des 200 $** : équité ≤ capital initial − 200 $ ⇒ plafond de 1 %. Ne relève jamais un risque plus bas.
3. **Plafond du profil** (`max_risk_per_trade_percent`, 1,5 % par défaut ; le 0,1 % de l'ADR 0015 reste effectif s'il est écrit).
4. **Budgets restants** : limite − perte déjà subie − risque ouvert au stop, pour le jour, la semaine et le total.
5. **Plafonds du fournisseur** (`apply_provider_ceilings`, alimenté par les jeux de règles de l'ADR 0036) : FTMO 1-Step −3 % jour /
   −10 % total ; 2-Step (Challenge, Verification, Account) −5 % / −10 % ; appliqués aux règles effectives. Un produit dont les limites
   ne sont pas sourcées (Swing) n'a **aucun** plafond ici et n'est pas exécutable ; un produit non déclaré est inconnu, jamais un défaut.
6. **Budgets restants sous les planchers du fournisseur** (`provider_daily_budget`, `provider_max_budget`) : la marge entre l'équité et
   le plancher FTMO, en pourcentage du capital initial, risque ouvert compté en plein.

Codes de refus stables : `reference_capital_not_fixed`, `equity_unknown`, `performance_stop_reached`, `risk_budget_exhausted`,
`weekly_loss_limit_reached`, `risk_over_allowance`.

## Dimensionnement

`size_position` (inchangé dans son principe) : perte par lot = (distance du stop + spread) ÷ `tick_size` × `tick_value_loss` du
symbole MT5 + commission par lot ; volume = budget ÷ perte par lot, **arrondi vers le bas** au pas du courtier ; si le lot
minimum dépasse le budget, refus (`min_volume_exceeds_risk`). La base est `min(balance, équité)`. Spécification absente ou
incohérente → refus. Le risque réel au stop (`sizing.risk_at_stop`, `effective_risk_percent`) est dans la `RiskDecision`,
**persistée avant tout envoi** ; un contrôle final refuse toute décision dont le risque effectif dépasse l'allocation.

## Points ouverts (à trancher par l'utilisateur)

- Le déclencheur des 200 $, tel qu'écrit (« sous le capital initial »), ne change jamais rien : la grille plafonne déjà à 1 %
  sous le capital initial. S'il visait « 200 $ sous le plus haut d'équité », c'est une autre règle, qui demande un plus-haut persistant.
- La grille est non monotone (0,1 % à −2 %, 0,3 % à −4 %) : appliquée à la lettre.
- `max_open_risk_percent` (2 % par défaut, ADR 0015) limite à deux positions à 1 % par trade : la limite de 5 positions n'est
  atteignable qu'en le relevant. `max_correlated_risk_percent` (1,5 %) bride de même deux positions corrélées.
- Les ordres en attente ne comptent pas encore dans les 5 positions (le protocole d'agent n'envoie que du marché) ; à traiter avec le `LIMIT`.


## Couche fournisseur (ADR 0036)

Le Risk Engine reçoit, en plus des règles personnelles, un `ProviderContext` (`domain/providers/context.py`) : **il ne peut qu'ajouter des
raisons de refus**. Sans contexte, rien ne change. Documentation des valeurs et de leur provenance :
`context/domain/regles-par-environnement.md`.

| Contrôle | Raison(s) stable(s) | Quand |
|---|---|---|
| Identification du compte | `provider_not_identified`, `provider_ambiguous`, `provider_mismatch`, `environment_mismatch`, `account_product_unknown`, `provider_rules_unsourced`, `rules_profile_on_real_account`, `leverage_contradicts_product`, `account_facts_missing` | compte non exécutable ; lecture et surveillance continuent |
| Planchers de perte du fournisseur | `provider_daily_loss_breached`, `provider_max_loss_breached` (verrou persistant, `gate-provider-loss`) ; `provider_daily_reference_missing`, `provider_daily_reference_stale`, `provider_max_reference_incomplete`, `provider_max_method_unsupported`, `provider_initial_capital_missing`, `provider_equity_unknown` (entrées refusées, pas de verrou) | produit avec plancher (FTMO) |
| News du fournisseur | `provider_news_restriction`, `provider_news_calendar_unknown`, `provider_news_symbol_unclassified` | FTMO Account Standard seulement |
| Pause de marché de plus de 2 h | `provider_overnight_restriction`, `provider_overnight_schedule_unknown` | FTMO Account Standard et Instant |
| Budget de requêtes | `provider_request_budget_exhausted`, `provider_request_count_unknown` | FTMO (2 000 par jour ; arrêt des entrées à 90 %) |
| Spécification de l'instrument | `instrument_specification_missing` | ordre dont le symbole n'a pas dit son mode de négociation, d'exécution, de remplissage ou ses niveaux de stop et de gel |

**Politique effective** (`domain/risk/effective.py`) : pour chaque limite, les valeurs candidates (`personal`, `provider`, `product`,
`instrument`, `market`, `account`), celle qui l'emporte et la porte qui l'applique. Les objectifs (profit, jours minimaux) y figurent
comme **informationnels** : un test d'architecture interdit au Risk Engine de les lire.
