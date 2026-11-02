# Risk Engine

Réécrit le 2026-10-09 (ADR 0016, 0007, 0015). Domicile : `python/trading_os/domain/risk/` (pur, sans E/S) ; orchestré par `services/risk.py`, qui possède la persistance et la publication. Le moteur est **le point de contrôle unique** avant toute exécution : aucune règle ne passe par l'interface (ADR 0007). Il s'évalue dans le cœur, plus dans le navigateur.

> Les seuils sont ceux que l'utilisateur écrit dans les limites de **chaque compte** (Settings) ; aucun n'est un fait validé du marché, et aucun n'est codé en dur. Sans limites configurées, l'autonomie refuse de démarrer.

## Pipeline

```text
compte (solde, équité, référence) + positions + politique du compte + spread + session + calendrier
  → portes (une fonction pure chacune, `gates.py`)
  → evaluate_risk_state() → RiskState (usage, portes, posture, verrou)        ← l'état affiché en continu
TradeIntent
  → decide() → RiskDecision (approuvée | refusée, raisons stables, dimensionnement, expiration)
  → ExecutionService (qui exige une décision approuvée, liée au même compte, non expirée)
```

`can_i_trade(compte, intention?)` répond `ALLOWED` ou `DENIED` avec les contrôles et des raisons stables (`daily_risk_budget_exceeded`, `news_restriction`, `correlated_exposure_too_high`…). `decide()` ajoute ce que seule une intention peut échouer : stop du mauvais côté ou trop proche, rapport coût/distance (porte de coût S01, sans plafond de spread fixe : ADR 0015), dimensionnement, risque ouvert et corrélé **après** la nouvelle position. Une décision vaut peu de temps (`expires_at`) : le marché bouge, et le moteur d'exécution refuse une approbation périmée.

## Portes

| Porte | Bloque | Nature |
|---|---|---|
| Perte du jour | usage ≥ limite journalière du compte | verrou de compte |
| Drawdown maximal | usage ≥ limite totale (référence fixe ou solde de rattachement) | verrou de compte |
| Trades par jour | `trades_today ≥ max` | verrou de compte |
| Pertes consécutives | série ≥ max (pause temporisée) | verrou de compte |
| Risque ouvert | somme des risques > limite | entrée |
| Exposition corrélée | devise commune > limite | entrée |
| Limite de positions | ouvertes ≥ max, tous symboles confondus (pas de limite par symbole, ADR 0022) | entrée |
| Spread / coût | coût trop grand devant la distance au stop | entrée |
| Session | hors fenêtre de trading du compte | entrée |
| Actualité | publication à venir dans la fenêtre de la politique ; calendrier inconnu ⇒ fermé | entrée |
| Symbole | hors liste autorisée | entrée |
| Connexion | agent d'exécution injoignable | entrée |
| Kill switch / verrou | verrou actif | tout |

Posture : **verrouillé** dès qu'une porte de verrou est franchie ; **avertissement** à partir de 60 % d'une limite ; sinon **normal**. Les portes d'entrée bloquent les nouvelles entrées sans verrouiller le compte. Les verrous sont des lignes **persistantes** d'un registre : perte du jour, drawdown et trades se lèvent par accusé humain (T02c), la pause sur pertes consécutives par le temps, le kill switch par un accusé explicite.

## Dimensionnement avec les spécifications réelles du symbole (`sizing.py`)

Jamais `risque / distance_du_stop` seul :

```text
perte_par_lot = ((distance_stop + spread) / tick_size) × tick_value_loss + commission_aller_retour   [devise du compte]
volume_brut   = budget_de_risque / perte_par_lot
volume        = arrondi inférieur au pas, borné à [volume_min, volume_max]
volume_brut < volume_min  →  refus « min_volume_exceeds_risk » (on n'arrondit jamais au-dessus du budget)
```

Données manquantes ou nulles ⇒ `SizingError` (refus), jamais de valeur par défaut. Testé sur XAUUSD, EURUSD, GBPUSD, GBPJPY, BTCUSD.

## Règles d'honnêteté

- **Inconnu ≠ zéro.** Sans historique de trades, `trades_today` et les pertes consécutives sont inconnus ; la porte le dit, l'écran affiche « — ».
- Une position sans stop est exclue du risque ouvert (risque indéfini), jamais comptée comme `|entrée − 0|`.
- Un verrou n'est ouvert qu'une fois un instantané de compte lu : avant, rien n'est mesuré, donc rien n'est franchi.
- La référence de la perte du jour est le début de la **journée de trading** du courtier — minuit *serveur*, avec le décalage mesuré sur le terminal (jamais codé en dur : il bouge avec l'heure d'été) —, pas minuit UTC.

## Testé

`python/tests/unit/domain/risk/` (portes, verrous et jour de trading, exposition, dimensionnement, décision) et `tests/unit/services/test_risk_service.py` (persistance, accusés, kill switch). Le cockpit n'a plus aucune copie de ces règles.
