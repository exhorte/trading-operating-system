# Roadmap

Version 2 — 2026-09-04. L'unité de travail est **l'outil**, groupé en **vagues**. Les phases numérotées de la série 1 n'existent plus (ADR 0006).

Effort en jours de travail effectif, à la louche. Valeur = impact quotidien réel, 1 à 5.

## Vague 1 — rendre la plateforme utile tous les jours

Aucun de ces cinq outils ne dépend du multi-compte. Ensemble, ils transforment le cockpit d'un projet de recherche en un poste de travail.

| Outil | Fiche | Effort | Valeur | Dépend de |
|---|---|---|---|---|
| T01 — Calculateur de taille one-click | `product/tools/T01-calculateur-taille.md` | 0,5–1 j | 5 | — |
| T02 — Lockout comportemental | `product/tools/T02-lockout.md` | 1–2 j | 5 | — |
| T03 — Gate calendrier économique | `product/tools/T03-gate-news.md` | 1–2 j | 5 | — |
| T04 — Ticket pré-trade | `product/tools/T04-ticket-pretrade.md` | 1 j | 5 | — |
| T05 — Captures automatiques | `product/tools/T05-captures-auto.md` | 1–2 j | 4 | — |

**Total : 5 à 8 jours.** Ordre conseillé : T01 → T04 → T02 → T03 → T05.

**Critère de sortie de vague** : une séance complète tradée en n'utilisant que le cockpit pour dimensionner, armer et journaliser — zéro calculatrice MT5, zéro capture manuelle.

## Vague 2 — fermer la boucle d'apprentissage

| Outil | Effort | Valeur | Dépend de |
|---|---|---|---|
| T06 — Journal auto-alimenté, zéro saisie | 3–5 j | 5 | T04, T05 |
| T07 — Tracker d'erreurs et taux de conformité | 1–2 j | 5 | T06 |
| T15 — Serveur MCP « mon trading » (lecture seule) | 1–2 j | 4 | T06 |
| T08 — Revue hebdomadaire générée | 1–2 j | 4 | T06 |

**Total : 6 à 11 jours.**

**Critère de sortie** : le taux de conformité hebdomadaire est calculé automatiquement et affiché en haut du cockpit.

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
