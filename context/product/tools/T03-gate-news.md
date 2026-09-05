# T03 — Gate calendrier économique

Statut : **à faire** · Vague 1 · Effort 1–2 j · Valeur 5 · Dépend de : rien

## Problème

Sur XAUUSD, les mouvements qui sortent d'un trade correct viennent de publications programmées, connues à la minute près des semaines à l'avance. Se faire sortir par un CPI oublié est une erreur d'agenda, pas d'analyse.

## Comportement attendu

Un service qui charge les dates de publication à venir, les met en cache localement, expose `isNewsBlackout(t)` et alimente **une gate du Risk Engine** (ADR 0007) — pas une règle de stratégie.

Fenêtre par défaut : **−30 / +30 minutes** autour d'une publication de la liste blanche. Configurable.

Affichage permanent dans le cockpit : « prochaine publication : CPI US dans 1 h 47 — blackout à 14:00 ».

## Source de données

**API FRED de la Fed de Saint-Louis.** L'endpoint `fred/releases/dates` retourne les dates de publication ; avec `include_release_dates_with_no_data=true` il retourne les **dates futures** du calendrier. Clé API gratuite, source officielle, licence claire.

Une **liste blanche d'une dizaine de release IDs** suffit : CPI, Employment Situation (NFP), PCE, retail sales, ISM, FOMC. L'ensemble est petit et stable. **Cette liste blanche EST la classification d'impact** — inutile d'aller chercher un champ « impact » ailleurs.

Ce que FRED ne donne pas : le consensus des analystes. Il ne sert pas à décider de ne pas trader, donc il est hors périmètre de cet outil. Si le consensus devient utile plus tard (côté lecture uniquement), les candidats sont Trading Economics, Financial Modeling Prep et Finnhub — **tarifs et tiers à vérifier au moment de l'achat**, ils n'ont pas pu être confirmés depuis leurs pages publiques le 2026-09-04.

**Écarté explicitement** : les scrapers ForexFactory — fragiles et juridiquement exposés.

## Ancrage dans le code

- `lib/risk/gates.ts` — **`newsGate()` existe déjà en stub.** C'est exactement le point d'insertion ; il suffit de lui donner une vraie entrée.
- Nouveau module de chargement + cache (fichier local ou table). Le cache doit survivre à une coupure réseau : une clé API indisponible ne doit jamais ouvrir le blackout par défaut — **en cas de données absentes, la gate refuse**.
- Clé API dans `.env.local`, jamais commitée. Ajouter l'entrée à `.env.example`.

## Critère de réussite

Plus aucun trade ouvert dans les 30 minutes précédant une publication majeure, sans y avoir pensé.

## Journal

- 2026-09-04 — fiche créée au moment du pivot. Source FRED vérifiée le jour même (endpoint, dates futures, clé gratuite). Rien de codé.
