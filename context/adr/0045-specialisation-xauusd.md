# ADR 0045 — Spécialisation sur XAUUSD

Date : 2026-11-22. Statut : **accepté — étape 1 construite, la purge reste à faire** — décidé par Exhorte : « supprimer toutes les informations relatives aux autres actifs, excepté le XAUUSD, de la plateforme et du projet : nous allons nous spécialiser sur le XAUUSD », précisé par ses choix : **« Purger tout le projet »** et, pour les seuils, **« les déduire comme le BTC »**. Amende les ADR 0043 (S01 sur BTCUSD) et 0036 (plusieurs environnements : les fournisseurs restent, un seul instrument).

## Décision

1. **Un seul instrument : XAUUSD** (`XAUUSDm` chez Exness Standard). La stratégie S01, la surveillance du marché, l'agent, les presets et le cockpit ne connaissent que lui.
2. **Seuils de S01 pour l'or**, posés comme ceux du BTC (ADR 0043 : la géométrie de l'EURUSD portée par le rapport de prix, rien n'est cherché — ADR 0002). Lu sur la démo le 2026-11-22 (dernière cote du vendredi) : XAUUSDm ≈ 3 540,18, EURUSDm ≈ 1,09678, rapport ≈ 3 228 → tolérance des niveaux égaux 3 pips → **1,0 $**, FVG minimale 1 pip → **0,3 $**, marge de spread **0,3 $** (1,25 × le spread de 0,24 $), niveaux à **2 décimales** (celles d'origine de la stratégie, dont le moteur d'analyse était réglé pour l'or). À relire un jour ouvré (le spread du week-end n'est pas celui d'une séance).
3. **Purge** : le code, les tests, le cockpit et la documentation courante ne citent plus EURUSD, GBPUSD, GBPJPY, BTCUSD ni aucun autre actif. Les faux terminaux de test passent sur XAUUSDm (prix, spécification, valeur du tick). **Les ADR et les journaux de session ne sont pas réécrits** : ce sont l'histoire du projet ; ils peuvent nommer d'autres actifs.

## Étapes

1. **Faite le 2026-11-22** : `XAUUSD_SCALE` dans `domain/strategy/s01/config.py` (tests `test_s01_symbol_scales.py`, rouges puis verts) ; `.env` : `STRATEGY_S01_SYMBOLS=XAUUSD` (copie d'avant : `var/rules-backup/env-before-xauusd-2026-11-22.bak`) ; terminal déclaré XAUUSDm M5 ; preset `TradingOS-XAUUSDm.set`. Effet au prochain redémarrage du cœur.
2. **À faire** : S01 par défaut sur XAUUSD, échelles BTC et EURUSD retirées ; fixtures et constructeurs de test (`tests/support/builders.py`, `api.py`, terminal simulé) sur XAUUSDm, attentes numériques recalculées (taille de lot, valeur du tick, coûts) ; cockpit ; documentation courante (README, runbook, fiches d'outil, `state.md`). Ampleur mesurée le 2026-11-22 : EURUSD dans 14 fichiers de code, 81 de tests, 5 du cockpit (545 occurrences) ; GBPUSD, BTCUSD, GBPJPY, USDJPY en plus.
