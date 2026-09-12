# ADR 0009 — Le serveur capture des faits, le cockpit rend

Date : 2026-09-11. Statut : accepté. Précise l'ADR 0004 sans le modifier.
Décision prise en session le 2026-09-05 pendant T05, écrite ici avec six jours
de retard.

## Contexte

La fiche T05 proposait que le Gateway .NET produise l'image de la capture de
trade — un SVG ou un PNG rendu côté serveur, stocké, puis affiché tel quel par
le cockpit.

Le défaut a été relevé en session avant tout code : dessiner un graphique côté
serveur suppose de connaître les niveaux, la structure et les sessions, donc de
porter `lib/analysis/` en C#. Ce portage crée une seconde implémentation du même
domaine — exactement ce que l'ADR 0004 interdit. Et il est inutile : le cockpit
devra de toute façon savoir rendre un graphique pour T06, le journal
auto-alimenté.

Le principe dépasse T05. Il se pose à l'identique pour le journal (T06), la revue
hebdomadaire (T08) et le brief pré-séance (T10) : à chaque fois, la tentation est
de figer côté serveur une représentation que le client sait produire.

## Décision

**Le serveur capture des faits immuables et bornés. Le cockpit rend à la
demande.**

Un fait capturé est une donnée brute, datée, non interprétée : une fenêtre de
bougies, un prix d'entrée, un prix de sortie, un identifiant de position. Il ne
contient ni niveau calculé, ni structure, ni image.

Le rendu — graphique, annotations, niveaux, contexte de marché — est produit par
le cockpit au moment de l'affichage, en appelant `analyzeMarketContext` sur les
faits stockés.

## Conséquences

- `trade_captures` stocke des faits, jamais une image ni un rendu pré-calculé.
- `lib/analysis/` n'est porté dans aucun autre langage. Il reste l'unique
  implémentation du domaine analytique, conformément à l'ADR 0004.
- Une capture ancienne rejouée avec un moteur d'analyse amélioré produit une
  meilleure image à partir des mêmes faits. C'est voulu : les faits ne se
  périment pas, les interprétations si.
- Corollaire pour l'agent d'exécution (ADR 0010) : l'EA remonte des faits
  d'exécution — prix, volume, ticket, horodatage — et aucune interprétation.
- Ce qui est stocké doit être suffisant pour re-rendre sans le marché : si une
  fenêtre de bougies manque, la capture est incomplète, pas « à recalculer plus
  tard ».
