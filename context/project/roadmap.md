# Roadmap

Version 2 — 2026-09-04. L'unité de travail est **l'outil**, groupé en **vagues**. Les phases numérotées de la série 1 n'existent plus (ADR 0006).

Effort en jours de travail effectif, à la louche. Valeur = impact quotidien réel, 1 à 5.

## Vague 1 — rendre la plateforme utile tous les jours

Aucun de ces cinq outils ne dépend du multi-compte. Ensemble, ils transforment le cockpit d'un projet de recherche en un poste de travail.

**T01 et T04 retirés le 2026-09-14**, décision explicite de l'utilisateur, après livraison — voir leur journal respectif. Ce qui reste de la vague (T02, T03, T05) n'exige aucune interaction cockpit : ce sont des gates et un enregistreur qui tournent en arrière-plan, pas des panneaux qu'on utilise pour dimensionner ou armer.

| Outil | Fiche | Effort | Valeur | Dépend de |
|---|---|---|---|---|
| ~~T01 — Calculateur de taille one-click~~ | `product/tools/T01-calculateur-taille.md` | — | — | **retiré** |
| T02 — Lockout comportemental | `product/tools/T02-lockout.md` | 1–2 j | 5 | — |
| T03 — Gate calendrier économique | `product/tools/T03-gate-news.md` | 1–2 j | 5 | — |
| ~~T04 — Ticket pré-trade~~ | `product/tools/T04-ticket-pretrade.md` | — | — | **retiré** |
| T05 — Captures automatiques | `product/tools/T05-captures-auto.md` | 1–2 j | 4 | — |

**Critère de sortie de vague — reformulé le 2026-09-14** (l'original supposait
T01/T04 encore présents : « dimensionner, armer » via le cockpit n'a plus de
sens sans eux). Nouveau critère, portant sur ce qui reste réellement — la
couche passive de sécurité et d'enregistrement — pendant une séance réelle
complète :

- le kill switch a été déclenché pour de vrai au moins une fois, et acquitté ;
- chaque trade de la séance a sa capture entrée **et** sortie, sans exception
  (y compris les allers-retours rapides — voir le correctif T05 du
  2026-09-14) ;
- aucune règle de risque active (lockout, limite de trades, blackout
  calendrier) n'a été contournée en tradant directement dans MT5 pendant
  qu'elle l'était — sinon la séance documente un écart, elle ne clôt rien.

La séance du 2026-09-14 (journal de session) ne remplit pas ce critère — deux
trades EURUSD pris pendant un lockout actif — et ne clôt donc pas la vague.
Ce n'est pas un échec caché : c'est exactement ce que ce critère existe pour
détecter.

## Vague 2 — fermer la boucle d'apprentissage

| Outil | Effort | Valeur | Dépend de |
|---|---|---|---|
| T06 — Journal auto-alimenté, zéro saisie | 3–5 j | 5 | T05 (T04 retiré, voir note) |
| T07 — Tracker d'erreurs et taux de conformité | 1–2 j | 5 | T06 (portée réduite, voir note) |
| T15 — Serveur MCP « mon trading » (lecture seule) | 1–2 j | 4 | T06 |
| T08 — Revue hebdomadaire générée | 1–2 j | 4 | T06 |

**Total : 6 à 11 jours.**

**T06 recadré le 2026-09-14, suite au retrait de T04.** La fiche d'origine
disait *« les trades viennent de TimescaleDB, le contexte du ticket pré-trade,
les images des captures »* — le ticket pré-trade n'existe plus. Ce qui reste
disponible sans aucune saisie : `closed_trades`/`position_opens` (T02a/b, les
faits d'exécution), `trade_captures` (T05, le contexte visuel), et
`setup_proposals` (EA-02, arrivé après l'écriture de cette fiche) — quand un
trade coïncide avec une proposition machine, son biais/structure/liquidité au
moment détecté est une approximation du contexte de marché, **jamais** du
« pourquoi » de l'utilisateur.

Ce qui est perdu, sans détour possible : le setup nommé, le biais déclaré, le
niveau de confiance, l'invalidation distincte du stop — tout ce que T04
capturait **avant** que le résultat ne biaise le souvenir. C'était la raison
d'être de T06 (« le souvenir du pourquoi a disparu »). Sans T04, T06 devient
un journal des **faits d'exécution**, pas des **intentions** — un journal
mécanique, toujours zéro saisie, mais qui ne peut plus répondre à « à quoi je
pensais ».

**Conséquence directe sur T07** : sa taxonomie fermée compte *« trade hors
plan »* et *« absence de ticket »* parmi les violations auto-détectables —
les deux supposent qu'un plan a été déclaré quelque part. Sans T04, ni l'un
ni l'autre n'est détectable. Le taux de conformité de T07 devra se
redéfinir sur ce qui reste mesurable sans déclaration préalable : respect du
stop (jamais élargi après l'entrée), respect de la politique de taille,
absence de trade pendant un lockout actif, respect de la fenêtre horaire —
en clair, la conformité **au Risk Engine**, plus la conformité **au plan de
trade**, qui n'existe plus comme donnée.

**Critère de sortie** : le taux de conformité hebdomadaire — dans sa version
réduite ci-dessus — est calculé automatiquement et affiché en haut du
cockpit.

## Vague 3 — poste de travail complet

| Outil | Effort | Valeur | Dépend de |
|---|---|---|---|
| T09 — Checklist de pré-vol exécutable | 1–2 j | 4 | T03 |
| T10 — Brief pré-séance automatique | 2–3 j | 4 | T03 |
| T11 — Multi-compte natif | 1–2 sem | 3 | — |
| T12 — Prop Firm Control Center | 1–2 sem | 5 | T11 |
| T13 — Simulateur de règles pré-trade | 1–2 j | 4 | T12 |
| T14 — Alertes en lecture seule | 1 j | 3 | T12 (partiel) |

**Total : 3 à 5 semaines.** T11 a une valeur propre faible mais débloque T12, qui vaut 5.

**Déclencheur d'anticipation** : si un deuxième compte prop firm est ouvert avant la fin de la Vague 2, T11 et T12 remontent immédiatement en tête.

## Vague 4 — intelligence de marché

Le déterministe d'abord, l'IA ensuite, et l'IA uniquement en lecture (ADR 0005).

| Outil | Effort | Valeur | Dépend de |
|---|---|---|---|
| T16 — Corrélations glissantes XAUUSD / DXY / US10Y / EURUSD / BTC | 3–5 j | 3 | — |
| T19 — AI Analyst RAG sur journal + news | 1–2 sem | 3 | T06, T15 |

## Outils standalone

Hors plateforme, construisibles isolément, sans dépendance à l'avancement des vagues.

| Outil | Effort | Valeur |
|---|---|---|
| S1 — Dictée vocale horodatée (Vozel) | 1–2 j | 4 |
| S2 — Rapport hebdo CLI depuis l'export MT5 | 1 j | 3 |
| S3 — Watcher de conditions de marché | 0,5 j | 2 |

## Hors périmètre, volontairement

- Bot d'exécution autonome, générateur de signaux IA, copy-trading.
- Nouvelle recherche d'edge, optimiseur de stratégie, backtester.
- Scraper ForexFactory.
- Dashboard de marché temps réel dupliquant MT5.
- Migration vers Nautilus, Lean ou Jesse.
- Multi-tenant, authentification tierce, distribution.

Le raisonnement complet est dans `context/product/catalogue.md`, section « Ce que je ne recommande pas de construire ».
