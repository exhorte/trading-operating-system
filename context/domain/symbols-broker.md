# Symboles broker

Base du registre de symboles d'EA-04 (canonique <-> broker). Rempli en
Phase 0 de la Vague EA (`02_Plan_Projet/prompt-claude-code-vague-ea.md`).

## Statut : mesuré

Sortie réelle de `python list_symbols.py --canonical EURUSD GBPUSD XAUUSD`,
compte démo Exness (login 477029930, serveur `Exness-MT5Trial9`), le
2026-09-12.

## Registre

| Canonique | Nom broker | Digits | Point | Tick value | Tick size | Volume min | Volume max | Volume step | Stops level |
|---|---|---|---|---|---|---|---|---|---|
| EURUSD | `EURUSDm` | 5 | 0.00001 | 1.0 | 0.00001 | 0.01 | 200.0 | 0.01 | 0 |
| GBPUSD | `GBPUSDm` | 5 | 0.00001 | 1.0 | 0.00001 | 0.01 | 200.0 | 0.01 | 0 |
| XAUUSD | `XAUUSDm` *(voir note)* | 3 | 0.001 | 0.1 | 0.001 | 0.01 | 200.0 | 0.01 | 0 |

Pip pour EURUSD/GBPUSD (5 digits) : `10 × point = 0.0001`, conforme à la
convention déjà utilisée dans `log_spread.py`.

## Note — deux symboles XAUUSD sur ce broker

`list_symbols.py` a trouvé **deux** correspondances pour `XAUUSD*` :
`XAUUSDm` et `XAUUSD247m`. Ni deviné ni tranché ici — la sortie du script ne
dit pas laquelle est la bonne, seulement qu'elles existent toutes les deux :

- `XAUUSDm` — probablement l'or classique, horaires de marché standard.
- `XAUUSD247m` — le nom suggère une cotation continue (24/7, week-end
  compris), typique des CFD or "always-on" que certains brokers proposent en
  plus du contrat classique.

XAUUSD est hors périmètre pour S01 v1 (fiche S01, section Périmètre), donc
ceci ne bloque rien maintenant. **À trancher avant EA-04** : quel des deux
symboles entre dans le registre canonique, et si les deux ont leur usage,
comment le registre les distingue sans ambiguïté pour l'humain qui lit un
log ou une capture.

## Prochaine étape

`log_spread.py` doit tourner au moins cinq séances complètes (fenêtres
Londres/NY) avant de calibrer le seuil de `c` de la porte de coût (fiche
S01). Rien ici ne bloque le démarrage d'EA-01, qui est pur TypeScript et ne
dépend pas de ce registre.
