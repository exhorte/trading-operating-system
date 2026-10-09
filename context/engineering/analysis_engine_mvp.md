# Moteur d'analyse ICT/SMC

Réécrit le 2026-10-09 (ADR 0016, 0006). Domicile : `python/trading_os/domain/market/analysis/` — pur et indépendant du transport ; consomme des bougies, produit le `MarketContextState` canonique. Le vocabulaire vient de `context/domain/ict_smc_framework.md`. Il tourne dans le cœur (`services/market_data.py`) et le cockpit n'en reçoit que le résultat (`GET /api/market/{symbol}/context`).

> Tout ceci est une **hypothèse, pas un edge validé**. Poids et tolérances sont des valeurs de départ. Le moteur fournit du **contexte**, jamais de signal (ADR 0002).

## Pipeline

```text
bougies
  → swings        (pivots fractals)                         swings.py
  → structure     (BOS / CHOCH) → biais structurel          structure.py
  → liquidité     (égaux hauts/bas, PDH/PDL, balayés)       liquidity.py
  → PD arrays     (FVG avec remplissage/mitigation, order blocks)   pd_arrays.py
  → session       (fenêtre ICT, DST-aware)                  ../sessions.py
  → localisation  (premium / discount / équilibre)          bias.py
  → score         (confluence pondérée + décomposition)     scoring.py
  → MarketContextState                                      market_context.py
```

`aggregate.py` agrège une série de bougies vers une période supérieure ; `atr.py` calcule l'ATR de Wilder ; `config.py` regroupe les réglages (`swing_lookback`, tolérance des niveaux égaux, taille minimale d'un FVG, fenêtres de session, poids du score).

## Invariants

- **Pas d'anticipation.** L'état d'une bougie n'utilise que les bougies jusqu'à elle ; un swing se confirme `lookback` bougies après sa formation ; les balayages et les mitigations ne regardent que vers l'avant.
- **Pureté.** Aucun import d'infrastructure ; la lecture du marché et la publication sont dans `services/`.
- **Déterminisme.** Mêmes bougies, même configuration, même contexte — vérifié par des **vecteurs d'or** hérités de l'implémentation TypeScript d'origine (`python/tests/golden/README.md` en donne la provenance) et par des scénarios lisibles.

## Hors périmètre

SMT / divergences entre actifs ; moteur d'actualité macro (NFP, CPI, FOMC) comme porte — la porte calendrier est dans le Risk Engine, alimentée par FRED ; zones OTE ; breakers, blocs de rejet, FVG inverse ; moteur de séquence d'entrée complet (c'est S01, dans `domain/strategy/s01/`) ; gestion de trade (SL/TP/BE/partiels : dette TD-09, aucune sortie S01 aujourd'hui). Biais et score sont les points d'extension : un nouveau moteur ajoute des composantes sans changer le pipeline.

## Testé

`python/tests/unit/domain/analysis/` — un détecteur, un fichier ; un test d'orchestration ; les vecteurs d'or. Voir `context/engineering/testing_strategy.md`.
