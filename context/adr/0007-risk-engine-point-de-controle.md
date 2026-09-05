# ADR 0007 — Le Risk Engine est le point de contrôle unique

Date : 2026-09-04. Statut : accepté. Étend l'ancien ADR 0008 aux gates comportementales.

## Contexte

La série 1 a construit `lib/risk/` avec une gate pure par garde FTMO : perte quotidienne, drawdown maximum, risque ouvert, nombre de trades, pertes consécutives, spread, session — plus un stub de news.

Le mode d'échec dominant d'un trader intraday n'est pourtant pas la mauvaise analyse : c'est la séquence deux pertes → trade hors plan → taille doublée. Aucune de ces violations n'est couverte par un rappel écrit ni par un bouton grisé.

## Décision

**Toute règle que l'utilisateur veut s'imposer est une gate du Risk Engine.** Pas une règle de stratégie, pas une condition d'interface.

Cela inclut les gates comportementales : compteurs de séance, séquence de pertes, fenêtre horaire autorisée, blackout autour d'une publication économique, état « séance armée » de la checklist de pré-vol.

Un refus est une `RiskDecision` refusée, tracée sur le chemin `RiskDecision → Command → ACK → Report`, avec un motif lisible. Jamais un `disabled` côté React.

## Conséquences

- Le gate calendrier (T03) est une gate de risque, pas un filtre de stratégie.
- Le lockout (T02) persiste son état : un rechargement de page ne déverrouille pas une séance verrouillée.
- **Limite assumée** : tant que MT5 reste ouvert à côté, le verrou est un ralentisseur, pas un mur. C'est suffisant — la friction de vingt secondes est exactement ce qui manque au revenge trade. Une version « mur » (déverrouillage différé) reste possible plus tard.
- Toute nouvelle règle se teste en unitaire comme une fonction pure avant d'être branchée.
