# T04 — Ticket pré-trade

Statut : **à faire** · Vague 1 · Effort 1 j · Valeur 5 · Dépend de : rien

## Problème

Un journal rempli le soir est une reconstruction, pas un enregistrement. Le souvenir du « pourquoi » a disparu, et la justification écrite après coup est cohérente avec le résultat. C'est le biais qui rend la plupart des journaux de trading inutiles.

## Comportement attendu

Avant l'envoi de l'ordre, un formulaire de quatre champs, **tous en boutons**, aucun texte libre obligatoire :

| Champ | Forme |
|---|---|
| Setup | liste fermée (FVG, OB, liquidity sweep, retest, autre) |
| Biais | long / short / contre-tendance |
| Invalidation | le prix qui prouve l'erreur — pré-rempli depuis le stop |
| Confiance | 1 à 5 |

**Quinze secondes maximum.** Au-delà, il sera contourné. Une note vocale optionnelle viendra de S1 (dictée Vozel) plus tard.

## Pourquoi cet outil est le pivot de la Vague 1

Un seul objet, trois effets :

1. il devient la ligne de journal — T06 passe de 1–2 semaines à 3–5 jours ;
2. il rend le taux de conformité mesurable — T07 devient possible ;
3. il ralentit l'entrée impulsive — il renforce T02.

## Ancrage dans le code

- En amont de `lib/execution/command-builder.ts`.
- Persisté avec l'identifiant de commande, de sorte que le fill rattache automatiquement le ticket au trade. La table `execution_commands` porte déjà cet identifiant.
- Le vocabulaire des setups appartient au domaine : le poser dans `lib/domain/`, pas dans le composant.

## Critère de réussite

Au bout de 30 trades, l'expectancy par niveau de confiance est calculable. Attendre que les niveaux 1 et 2 soient négatifs.

## Journal

- 2026-09-04 — fiche créée au moment du pivot. Rien de démarré.
