# T05 — Captures automatiques entrée / sortie

Statut : **à faire** · Vague 1 · Effort 1–2 j · Valeur 4 · Dépend de : rien

## Problème

Les captures d'écran sont prises à la main, après coup, sur un graphique qui a déjà bougé. C'est la corvée qui fait abandonner les journaux.

## Comportement attendu

Sur événement de fill (entrée) et de clôture (sortie), le système capture l'état du graphique et l'attache au trade. Sans intervention.

## Décision d'implémentation à prendre au démarrage

**Position par défaut : rendu maison.** Le cockpit reconstruit le graphique depuis TimescaleDB — les bougies y sont déjà — et l'exporte en image : fenêtre centrée sur l'entrée, niveaux de `lib/analysis/` superposés, marqueurs entrée / stop / TP.

L'alternative est la capture de la fenêtre MT5 : plus fidèle à ce qui était réellement affiché, mais fragile (dépend de la fenêtre au premier plan, du terminal ouvert, de la résolution).

Le raisonnement derrière la position par défaut : la fidélité au pixel près n'a aucune valeur, la reproductibilité en a. Un rendu maison fonctionne aussi en rejeu et reste versionnable.

Trancher au démarrage et noter la décision ici.

## Ancrage dans le code

- `tools/mt5-observer/mt5_observer.py` émet déjà les événements d'exécution — il manque le déclencheur.
- Bougies : table `candles` (hypertable TimescaleDB).
- Niveaux : `lib/analysis/` (`sessions.ts`, `atr.ts`, `liquidity.ts`, `pd-arrays.ts`).
- Stockage des images : décider entre système de fichiers local et colonne binaire. Le système de fichiers est probablement suffisant en usage personnel — et sauvegardable simplement.

## Critère de réussite

Plus une seule capture prise à la main.

## Journal

- 2026-09-04 — fiche créée au moment du pivot. Rien de démarré.
