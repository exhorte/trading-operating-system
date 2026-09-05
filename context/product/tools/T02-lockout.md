# T02 — Lockout comportemental

Statut : **à faire** · Vague 1 · Effort 1–2 j · Valeur 5 · Dépend de : rien

## Problème

Le mode d'échec dominant de l'intraday n'est pas la mauvaise analyse : c'est la séquence deux pertes → trade hors plan pour se refaire → taille doublée. Aucun rappel écrit n'a jamais arrêté ça. Seul un système qui refuse l'ordre l'arrête.

## Comportement attendu

Des verrous durs, configurés à froid, appliqués à chaud :

| Verrou | Effet |
|---|---|
| Perte quotidienne maximale atteinte | Séance verrouillée jusqu'au lendemain |
| Nombre de trades maximum atteint | Séance verrouillée |
| Deux pertes consécutives | Pause forcée de 30 min, chrono affiché |
| Hors fenêtre de session autorisée | Refus |
| Kill switch manuel | Coupe tout, ferme les positions, verrouille |

L'état de verrouillage **persiste** : recharger la page ne déverrouille rien. Chaque refus porte un motif lisible et est tracé.

## Ancrage dans le code

- `lib/risk/gates.ts` — `maxTradesGate`, `consecutiveLossGate`, `sessionGate` **existent déjà**. Ce qui manque : les compteurs de séance réels (aujourd'hui `tradesToday` et `consecutiveLosses` sont `number | null` et valent `null` en mode observe), l'horloge de pause, et la persistance de l'état verrouillé.
- `lib/risk/evaluate.ts` — `evaluateRiskState` dérive déjà normal/warning/locked. Étendre, ne pas remplacer.
- **Trouvaille de T01 (2026-09-05) : `RiskStatus` n'a pas de champ `lockoutUntil`.** `lib/contracts/snapshots.ts` (le read model envoyé au cockpit) ne porte pas ce champ, alors que le domaine (`lib/domain/risk.ts`) l'a déjà. Tant qu'il manque, `RiskState.lockoutUntil` reste forcé à `null` côté client (voir le commentaire dans `lib/risk/sizing-panel.ts`). Pour que le chrono de pause atteigne réellement le cockpit, T02 doit : ajouter `lockoutUntil` à `RiskStatus` dans `lib/contracts/snapshots.ts`, à sa projection `toRiskStatusReadModel` dans `lib/contracts/projections.ts`, et à son miroir C# — qui n'existe même pas encore pour `RiskStatus` dans `backend/src/TradingOs.Contracts/ReadModels.cs` (seuls `AccountSummary`, `Position`, `AgentStatus`, `Candle` y sont reflétés aujourd'hui). Le jour où le backend pousse du risque réel (pas seulement le mock), ce type devra y être créé avec `lockoutUntil` inclus dès le départ.
- Persistance : nouvelle table dans `backend/src/TradingOs.Persistence/schema.sql`, ou dérivation depuis les tables d'exécution existantes si elle est fiable. Trancher au démarrage et noter la décision ici.
- Le refus doit être une `RiskDecision` refusée sur le chemin `RiskDecision → Command → ACK → Report` (ADR 0007), pas un `disabled` React.

## Limite assumée

Tant que MT5 est ouvert à côté, le verrou est un ralentisseur, pas un mur. C'est suffisant : la friction de vingt secondes est exactement ce qui manque au revenge trade. Une version « mur » (déverrouillage différé de 24 h) est possible plus tard — ne pas la construire d'emblée.

## Critère de réussite

Le nombre de trades pris hors fenêtre autorisée tombe à zéro sans effort de discipline conscient.

## Journal

- 2026-09-04 — fiche créée au moment du pivot. Rien de démarré.
