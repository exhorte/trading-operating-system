# T01 — Calculateur de taille one-click

Statut : **livré** · Vague 1 · Effort 0,5–1 j · Valeur 5 · Dépend de : rien

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
- 2026-09-05 — livré. `lib/risk/sizing.ts` et le reste de `lib/risk/` non modifiés
  (vérifié par diff). Décisions prises pendant la construction :

  1. **XAUUSD explicite, pas d'avertissement dynamique.** Le panneau s'affiche
     comme « Sizing — XAUUSD » sans sélecteur de symbole. Justification :
     compte, positions et flux mock/réel sont XAUUSD partout ailleurs dans le
     dépôt ; ajouter un avertissement pour un symbole qui n'existe nulle part
     dans le produit aurait été de la complexité non demandée.
  2. **Adaptateur mince `lib/risk/sizing-panel.ts`.** `evaluateSignalRisk`
     attend un `RiskState` (domaine) ; le cockpit ne reçoit que `RiskStatus`
     (projection d'affichage, `lib/contracts/snapshots.ts`). `RiskStatus` et
     `AccountSummary` portent en réalité tous les champs que la fonction lit
     (`mode`, `gates`, `lockoutReason`) — l'adaptateur ne fait que les
     regrouper sous le bon nom, il ne recalcule rien.
  3. **Policy lue via `defaultRiskPolicy(accountId)` côté client, pas via le
     fil temps réel.** `RiskStatus` ne transporte pas `maxRiskPerTradePercent`
     (nécessaire pour le risque visé). Comme un seul compte existe, avec une
     policy par défaut non éditable nulle part dans la Vague 1, appeler la
     même fonction pure que `mock-client.ts`/`initial-snapshot.ts` ne peut pas
     diverger. **À revoir** le jour où une policy par compte devient
     éditable : il faudra alors l'exposer sur le fil plutôt que la relire en
     dur ici.
  4. **Dénominateur du budget de perte quotidien = `account.balance`.** Le
     domaine distingue `initialBalance` (capital de début de journée) de
     `balance`/`equity` courants, mais seuls ces deux derniers sont sur le
     fil (`AccountSummary`). Utiliser `balance` comme proxy est une
     approximation acceptée pour ce MVP ; si `initialBalance` devient utile
     ailleurs, l'exposer sur le fil rendra ce calcul exact.
  5. **Convention point/pip pour la distance au stop** : reprend celle déjà
     implicite dans `lib/risk/policy.ts` (1 point = 0.01 sur XAUUSD) et ajoute
     1 pip = 10 points = 0.10, convention broker standard sur l'or. Aucune
     constante de ce type n'existait dans le dépôt avant ce ticket.
  6. **Panneau monté en permanence dans `CockpitShell`** (colonne fixe à
     droite, `hidden xl:flex` sous une certaine largeur), pas une page à part
     — visible sans navigation sur toutes les routes, sans bascule
     repliable (pas demandé par le critère de réussite, ajoutable plus tard
     si la largeur d'écran le justifie).

  Vérification manuelle non faite en session (pas d'extension Chrome connectée
  pour ce poste) : le rendu serveur du panneau et sa présence sur `/`, `/risk`,
  `/journal`, `/agents` sont confirmés par requêtes HTTP, mais la saisie
  interactive clavier→recalcul n'a pas été observée visuellement. À valider à
  l'ouverture réelle du cockpit. Le critère de réussite (« une séance entière
  sans ouvrir la calculatrice de MT5 ») reste à vérifier en conditions réelles.

- 2026-09-05 — trois défauts réels relevés en revue, corrigés dans la même
  session :

  1. **Le budget de perte quotidien consommé divisait par le budget total,
     pas par ce qu'il en reste.** `dailyBudgetConsumedPercent` compare
     désormais le risque réel du trade à `dailyLossLimitPercent -
     dailyLossUsedPercent` (le solde restant du jour), pas à
     `dailyLossLimitPercent` seul. Avant correction, un compte ayant déjà
     perdu 90 % de son budget quotidien affichait un pourcentage rassurant
     au lieu d'alerter. Test dédié ajouté (le seul cas qui manquait parmi
     les tests existants).
  2. **`?? 0` affichait « 0 % » pour une valeur inconnue**, à l'endroit
     précis où la convention `null` ≠ `0` du dépôt (ADR domaine) devait
     s'appliquer. `formatPercentOrUnknown` dans le composant affiche
     désormais « — » pour `null`.
  3. **Le R cible ne vérifiait pas le côté du take-profit.** Un TP saisi du
     mauvais côté de l'entrée (par rapport au sens impliqué par le stop)
     produisait un R positif crédible via `Math.abs`. `computeSizingPanel`
     compare maintenant le signe de `takeProfit - entryPrice` à celui de
     `entryPrice - stopLoss` ; en cas de désaccord, `rMultipleTarget` reste
     `null` et `takeProfitInvalid` est levé pour que le composant affiche un
     avertissement explicite plutôt qu'un chiffre.

  Une quatrième trouvaille (pas un défaut de T01, une dette pour T02) a été
  notée dans `context/product/tools/T02-lockout.md` : `RiskStatus` n'a pas
  de champ `lockoutUntil`, donc l'adaptateur de sizing le force à `null` —
  T02 devra l'ajouter au read model et à son miroir C#.
