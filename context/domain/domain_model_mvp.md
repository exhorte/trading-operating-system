# Modèle de domaine

Réécrit le 2026-10-09 (ADR 0016). Le domaine canonique vit dans `python/trading_os/domain/` sous forme de **modèles pydantic purs** : aucun import d'infrastructure, aucune E/S (un test d'architecture le garde). Ce document explique le découpage, les règles de portabilité et la chaîne de traçabilité.

## Découpage

```
domain/      modèles et règles pures (comptes, marché, stratégie, risque, exécution, positions, autonomie, journal)
   ▲
services/    un service par capacité : orchestre le domaine et l'infrastructure, publie des événements
   ▲
api/         schémas d'API (modèles de requête/réponse), routes, flux WebSocket  ──▶  OpenAPI
   ▲
lib/api/generated.ts   les mêmes modèles, générés pour le cockpit (`python -m trading_os gen-types`)
   ▲
lib/ et components/    le cockpit : affiche, n'a aucune règle de domaine
```

La dépendance va dans un seul sens. Il n'y a **pas de second modèle** : le modèle de domaine est le schéma d'API et la charge utile d'événement ; le cockpit reçoit la version générée. Les projections « de lecture » (`RiskStatus`, `AccountState`, `MarketContextState`…) sont des modèles du cœur aussi, optimisés pour l'affichage et non pour la décision.

## Carte des modules (`python/trading_os/domain/`)

| Module | Modèles principaux |
|---|---|
| `primitives.py` | alias d'identifiants (`AccountId`, `SymbolCode`), `Side`, `Timeframe`, `DomainModel` (modèle immuable de base) |
| `accounts/` | `Account` (fournisseur EXNESS/FTMO, plateforme MT5, type, login, serveur, devise, environnement DEMO/SIMULATED/LIVE, profils de risque, de règles et d'exécution), profils par fournisseur, garde anti-tilt, registre des limites versionnées |
| `market/` | `SymbolSpec`, `Tick`, `Candle`, sessions et fenêtres, calendrier économique ; `analysis/` : swings, structure, liquidité, PD arrays, contexte de marché |
| `strategy/` | `TradeIntent`, `StrategyEvaluation` ; `s01/` : la stratégie S01 en fonctions pures |
| `risk/` | `RiskProfile`, `DrawdownPolicy`, `NewsPolicy`, `PositionLimits`, `RiskState`, `GateResult`, `RiskDecision`, dimensionnement, exposition, verrous |
| `execution/` | `ExecutionRequest`, `ExecutionCommand` (états, machine de transitions), `RejectCode`, statut de l'agent |
| `positions/` | `Position`, ordres, trades clôturés, réconciliation |
| `autonomy/` | `AutonomyMode`, `ExecutionRoute`, états, readiness |
| `journal/` | trade du journal, conformité T07, faits de capture (chiffres) |

## Règles de portabilité

Ces règles rendent un modèle traduisible mécaniquement en TypeScript (généré) et en champs d'un message de l'agent MQL5 :

1. Des modèles à champs typés ; pas de méthode qui change l'état d'un modèle, pas d'objet `datetime` naïf (tous les instants sont UTC avec fuseau).
2. Une valeur absente est un `null` explicite (`X | None`), jamais une propriété omise : inconnu ≠ zéro.
3. Volumes en lots, pourcentages sur l'échelle 0–100, monnaie dans la devise du compte.
4. JSON en camelCase sur le fil (alias générés) ; l'agent MQL5 mappe ses noms de champs à la main dans son sérialiseur.
5. Une union discriminée porte une chaîne discriminante (`type` d'un événement, `kind` d'une commande).
6. Un secret n'a sa place que dans un modèle de **requête**, en `SecretStr`, jamais dans un modèle de lecture, un événement ou un journal.

## Chaîne de traçabilité

« Chaque décision de trade est traçable jusqu'au contexte de marché, au risque, à la stratégie et à l'exécution » est encodé dans les identifiants :

`StrategyEvaluation` → `TradeIntent.intent_id` → `RiskDecision.decision_id` → `ExecutionCommand.command_id` (qui porte `risk_decision_id`, obligatoire sauf pour une commande qui ne fait que réduire le risque) → accusé → rapport → `Position` → trade clôturé → journal (`correlationId` relie tout le fil dans les événements).

## Modèles de lecture et modèles de décision

Les modèles de lecture (instantané du cockpit, état de risque affiché) sont des projections ; ils ne servent jamais à décider. La décision se prend sur les modèles de domaine (`RiskInputs`, `SymbolSpec`, `ExecutionRequest`…), dans le cœur.
