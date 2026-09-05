# T01 — Calculateur de taille one-click

Statut : **à faire** · Vague 1 · Effort 0,5–1 j · Valeur 5 · Dépend de : rien

## Problème

Le dimensionnement de position est l'action la plus répétée de la journée et la plus dangereuse à faire de tête. Aujourd'hui elle se fait à la calculatrice ou dans MT5, sous pression, au moment exact où l'erreur coûte le plus cher.

## Comportement attendu

Un panneau permanent du cockpit, visible sans navigation. Entrées : prix d'entrée, prix de stop, compte. Sorties, recalculées à chaque frappe :

- volume en lots ;
- risque en devise du compte et en pourcentage ;
- distance au stop en points et en pips ;
- R cible pour un TP saisi (optionnel) ;
- **part du drawdown quotidien autorisé que ce trade consomme s'il part au stop** — c'est le chiffre qui manque partout ailleurs.

Le panneau affiche aussi, en lecture seule, l'état des gates qui refuseraient ce trade maintenant (spread, session, verrous de T02). Il ne les contourne pas : il les montre.

Aucun ordre n'est envoyé depuis ce panneau.

## Ancrage dans le code

- `lib/risk/sizing.ts` — `evaluateSignalRisk(input: SignalRiskInput): RiskDecision` existe, est pur et testé (`sizing.test.ts`). **Ne pas le réécrire.** L'outil est un composant qui l'appelle.
- `lib/risk/policy.ts` — `defaultRiskPolicy(accountId)` fournit les bornes.
- `lib/risk/evaluate.ts` — pour l'affichage de l'état des gates.
- Nouveau composant sous `components/cockpit/`, monté dans `app/(cockpit)/layout.tsx` ou en panneau latéral persistant.

Si `evaluateSignalRisk` demande des champs qu'un calcul manuel n'a pas (identifiant de signal, contexte de marché), écrire un adaptateur mince plutôt que d'assouplir la fonction pure.

## Critère de réussite

Une séance entière sans ouvrir la calculatrice de MT5.

## Journal

- 2026-09-04 — fiche créée au moment du pivot. Rien de démarré.
