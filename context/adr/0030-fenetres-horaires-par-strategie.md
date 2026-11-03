# ADR 0030 — Fenêtres horaires propres à chaque stratégie : S02 à 08:30–11:00 New York, S01 inchangée

Date : 2026-11-01. Statut : **accepté** — décision d'Exhorte du 2026-11-01 (« retenir 08:30–11:00 pour S02 ; la fenêtre historique 07:00–10:00 de S01 ne doit
pas être supprimée sans vérifier ses dépendances ; toutes les fenêtres configurables, fuseau `America/New_York`, changement d'heure automatique, sans mélanger
UTC, heure du serveur MT5 et heure de New York »). **Amende l'ADR 0024** (S02 héritait des heures de S01) ; ne touche aucune limite du Risk Engine.

## Contexte — où les heures de S01 vivaient (vérifié dans le code)

1. `domain/strategy/s01/preconditions.py` : une table `KILLZONE_WINDOWS_NY_MINUTES` (Londres 02:00–05:00, New York AM 07:00–10:00). C'est la précondition de
   la stratégie ; **S02, qui réutilise le pipeline de S01, en héritait**, c'est-à-dire de 07:00–10:00 au lieu de 08:30–11:00.
2. `domain/market/sessions.py` : `DEFAULT_TRADING_WINDOWS`, les mêmes heures, valeur par défaut de `TradingRules.trading_windows` du compte. Lues par la porte de
   session du Risk Engine, le Position Manager (fin de séance), la conformité du journal et les défauts du banc de validation.
3. Des tests et un vecteur doré (`test_golden`, `test_market`, `test_compliance`) qui fixent le comportement de S01.

Les notes (`07_trading_strategy/00_Synthese_strategies.md`, §2.5 et fiches N4, N5, N6) donnent **08:30–11:00 NY** comme zone d'exécution principale (08:30 est l'heure
des annonces) et **12:00–13:00 NY** comme abstention ; elles donnent Londres **02:00–05:00 NY** (N6, repérage des hauts et bas) et le matin NY **07:00–10:00** comme
sessions de *repérage*. La valeur de Londres dans le code (02:00–05:00) est donc la même que celle des notes : rien à corriger.

## Décision

1. **Les heures sont un réglage de chaque stratégie** (`S01Config.trading_windows`, `S02Config.trading_windows`), lu par la précondition de la stratégie, par le
   banc de validation et par le Position Manager. Une fenêtre est `nom=HH:MM-HH:MM`, **heure locale de New York** (`America/New_York`) : l'heure d'été s'applique
   d'elle-même, aucun décalage UTC n'est écrit nulle part ; un instant est un `datetime` avec fuseau, l'heure du serveur MT5 est convertie au bord du
   terminal et n'est jamais comparée à une fenêtre.
2. **Valeurs par défaut.** S01 : `S01_TRADING_WINDOWS` = Londres 02:00–05:00 et New York AM 07:00–10:00 (la configuration historique, conservée telle quelle,
   propre à S01). S02 : `S02_TRADING_WINDOWS` = Londres 02:00–05:00 (la fenêtre des notes, cohérente avec le code) et New York AM **08:30–11:00**. Rien d'autre :
   le profil de l'après-midi de N4 (13:30–16:00) n'est pas une valeur par défaut de S02.
3. **Configurables sans toucher au code** : `STRATEGY_S01_WINDOWS` et `STRATEGY_S02_WINDOWS` (`london=02:00-05:00,new_york_am=08:30-11:00`). Une valeur
   mal formée, une fenêtre qui finit avant de commencer, un nom répété ou un chevauchement arrête le démarrage (`parse_trading_windows`) ; vide = les valeurs
   par défaut de la stratégie. Une fenêtre qui traverserait minuit n'est pas prise en charge : on en écrit deux.
4. **L'enveloppe du compte** (`TradingRules.trading_windows`, lue par la porte de session du Risk Engine) devient, pour un **nouveau** compte,
   `ACCOUNT_TRADING_WINDOWS` : toutes les heures qu'au moins une stratégie peut trader (Londres 02:00–05:00, New York 07:00–11:00), rien de plus ; chaque stratégie
   reste dans ses propres fenêtres à l'intérieur. Un compte créé avant cet ADR **garde les fenêtres qu'il a enregistrées** (la démo `exness-486046157` a encore
   07:00–10:00) : les élargir est un geste d'Exhorte dans Settings — je ne le fais pas à sa place, le registre anti-tilt existe pour cela. Tant qu'elles ne sont
   pas élargies, la porte de session du Risk Engine refuse un trade de S02 entre 10:00 et 11:00 : c'est la protection qui tient, pas un défaut.
5. **Fin de séance du Position Manager.** Une position est aplatie `flat_minutes_before_window_end` minutes avant la fin de la fenêtre de la stratégie qui l'a
   ouverte **ou** de l'enveloppe du compte, la plus proche des deux ; « dans la fenêtre » veut dire dans les deux. Une position de S01 reste donc aplatie à
   09:55 NY, une position de S02 à 10:55. Les ordres en attente (dont la stratégie d'origine n'est pas relue) suivent l'enveloppe du compte, plus leur
   péremption de 30 minutes.
6. **Banc de validation** : `replay` et `simulate_trade` lisent par défaut les fenêtres de la configuration rejouée, pas celles de S01.
7. Le filtre « pas de nouvelle position à partir de 12:00 NY » (`past_ny_lunch`, N4/N6) est conservé ; il est de toute façon au-delà des deux jeux de fenêtres.

## Ce que cet ADR ne fait pas

- Il ne supprime pas la fenêtre 07:00–10:00 de S01 et ne change aucun de ses comportements d'entrée (vérifié : mêmes bornes, mêmes tests).
- Il ne modifie pas le compte enregistré de la démo et ne désactive aucune protection.
- Il ne tranche pas M5 contre M1 (question 1 du plan de reprise) et n'ajoute pas de fenêtre d'après-midi.

## Conséquences

- Tests : `tests/unit/domain/test_trading_windows.py` (propriété des heures, bornes 08:30 et 11:00 des deux côtés du changement d'heure de mars et de novembre, un
  même instant écrit en UTC ou à l'heure du serveur, analyse et refus des réglages mal formés, précondition de S01 inchangée et de S02), Position Manager
  (S01 aplatie à 09:55, S02 non).
- Le message de refus de la précondition cite les fenêtres en vigueur : `outside the strategy's trading windows (NY time): london 02:00–05:00, new_york_am 08:30–11:00`.
- Documentation : fiche S02 (§ Heures), `state.md`, `session-log.md`, README du projet.
