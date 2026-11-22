# ADR 0044 — Un seul mode : `AUTONOMOUS` (et l'arrêt d'urgence `HALTED`)

Date : 2026-11-22. Statut : **accepté — à construire** — décidé par Exhorte : « le but de la plateforme étant d'être autonome, le plafond est et doit toujours être AUTONOMOUS ; le système doit tourner tout seul en fonction de la stratégie », puis « supprimer toutes les autres règles … ne garder que la règle AUTONOMOUS comme règle générale et unique », précisé par son choix : **« Supprimer les autres modes »** (retirer `OFF`, `OBSERVE`, `CONFIRM` et `ARMED` du code ; le système est soit `AUTONOMOUS`, soit arrêté d'urgence ; **les limites de risque restent**). Amende les ADR 0014, 0034, 0041 et 0043 ; s'appuie sur l'ADR 0042.

## Constat

- L'échelle `OFF → OBSERVE → CONFIRM → ARMED → AUTONOMOUS` (+ `HALTED`) servait la montée prudente d'un système piloté à la main. Depuis l'ADR 0043, un pilote la gravit seul à chaque lancement : ses échelons intermédiaires ne sont plus des états voulus, seulement des étapes.
- Elle a coûté cher le 2026-11-22 : la base restaurée (dump du 05/11) a ramené le plafond du compte à `OBSERVE`, un détachement a mis le pilote en pause, et le cockpit n'avait aucun moyen de relever le plafond. Trois blocages pour un système censé tourner seul.

## Décision

1. **Deux états seulement** : `AUTONOMOUS` (le système trade seul, selon la stratégie configurée, dans les limites du Risk Engine) et `HALTED` (arrêt d'urgence : plus aucune entrée, l'agent est coupé, en sortir est un geste humain). `OFF`, `OBSERVE`, `CONFIRM` et `ARMED` disparaissent du domaine, de l'API, du cockpit et des réglages.
2. **Plus de plafond** : `TRADING_MODE` et `executionProfile.maxMode` disparaissent (une valeur ancienne est lue sans effet et le dit) ; il n'y a plus rien à relever.
3. **Ce qui reste, inchangé** : le Risk Engine et toutes ses limites (pertes jour/semaine/totale, nombre de trades, positions, risque par trade, grille dynamique), l'Account Guardian, la préparation (les 16 contrôles) **comme condition des entrées** — un contrôle rouge bloque les nouvelles entrées (comme le mode `SAFE` du superviseur aujourd'hui), il ne fait plus « redescendre » un mode —, la réconciliation, les sorties sous arrêt (ADR 0033), « FERMER TOUTES LES POSITIONS ».
4. **Jamais sur un compte en argent réel sans geste** : sur un compte `LIVE`, le système reste à l'arrêt tant qu'Exhorte ne l'a pas lancé lui-même (la règle du pilote de l'ADR 0043, gardée telle quelle).
5. **Hors périmètre** : le mode compilé de l'agent MQL5 (`OBSERVE`/`CONFIRM`, ADR 0029 et 0043) — c'est la barrière de l'agent, pas l'échelle du cœur ; sa suppression serait une décision séparée.

## Plan de construction (tests d'abord, une étape verte à la fois)

1. Domaine : `AutonomyMode` réduit à `AUTONOMOUS` et `HALTED` ; machine d'états, critères de passage, correspondance du plan (`DEMO_AUTO`…) ; tests réécrits.
2. Services : démarrage (vérifier, rattacher, réconcilier — plus de montée), pilote (rattacher et tenir, plus d'échelons), superviseur (`DISARM` → blocage des entrées), exécution (le refus `MODE_NOT_PERMITTING` ne vaut plus que pour `HALTED`).
3. API et types générés : retrait de `arm`, `disarm`, `renew`, `authorize-automatic` ; `halt` et la sortie d'arrêt restent.
4. Cockpit : retrait des sélecteurs et boutons de mode ; l'état affiché devient `AUTONOMOUS` ou `HALTED`, avec la raison des entrées bloquées.
5. Réglages et migration douce : `TRADING_MODE`, `AUTOPILOT_TARGET` et `maxMode` lus sans effet ; documentation et runbook.

## Avancement

- 2026-11-22 : décision écrite ; rien n'est encore construit. En attendant, le plafond de la démo est `AUTONOMOUS` (version de règles `rules-e642a18a821e`) et le système tourne en `AUTONOMOUS`.
