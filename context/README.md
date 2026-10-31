# Cerveau du projet

Ce répertoire est la mémoire durable du projet. Il existe pour qu'une session Claude Code — ou l'utilisateur trois mois plus tard — comprenne le projet sans avoir à relire le code.

**Langue** : les documents de projet, produit et gouvernance sont en français (écrits ou réécrits le 2026-09-04). Les spécifications techniques de `architecture/`, `engineering/`, `execution/`, `realtime/`, `infrastructure/`, `security/`, `governance/` et `domain/domain_model_mvp.md` ont été **réécrites en français le 2026-10-09** pour le cœur Python (ADR 0016) ; les autres (`frontend/`, `monitoring/`) sont des archives de conception en anglais ou en français, amendées par une note datée quand l'architecture a changé.

**Deux sortes de documents.** Les documents *vivants* (architecture, ingénierie, exécution, temps réel, infrastructure, sécurité, gouvernance, état) décrivent le système tel qu'il est : on les réécrit quand il change. Les *archives* — ADR, journal de session, fiches d'outil et leurs journaux, plans — disent ce qui a été décidé ou fait : on ne les réécrit pas (ADR 0008), on les amende par une note datée en tête. L'historique complet reste dans Git.

## Ordre de lecture

1. `project/charter.md` — ce que le projet est, ce qu'il n'est plus, ses principes.
2. `project/state.md` — ce qui existe et fonctionne, ce qui bloque, la prochaine action.
3. `adr/` — les décisions qui gouvernent. Courts, à lire en entier.
4. `project/roadmap.md` — les vagues et les outils.
5. `product/tools/Tnn-*.md` — la fiche de l'outil en cours.
6. Le reste selon le sujet touché.

## Carte du répertoire

| Dossier | Contenu |
|---|---|
| `project/` | Charte, état, roadmap, journal du pivot. |
| `product/` | Catalogue d'outils, backlog, fiches d'outil. **L'unité de travail du projet.** |
| `adr/` | Décisions d'architecture, série 2. |
| `architecture/` | Vue d'ensemble du système, contextes bornés. La description complète est dans `../docs/architecture/`. |
| `domain/` | Ontologie du trading, framework ICT/SMC, modèle de domaine, risque FTMO. |
| `engineering/` | Stack, standards, stratégie de test, moteurs d'analyse et de risque. |
| `execution/` | Protocole cœur ↔ agent, machine à états d'une commande, barrières de sûreté. |
| `realtime/` | Flux du cockpit (WebSocket), contrats d'événements, protocole du lien agent MT5. |
| `frontend/` | Spécification d'interface du cockpit, analyse des références visuelles. |
| `infrastructure/` | **`runbook.md`** — démarrage de l'environnement. Plan d'infrastructure, persistance. |
| `governance/` | Quality gates, processus de décision. |
| `workflows/` | Cycle de développement d'un outil. |
| `security/` | Secrets, sûreté d'exécution, contrôle d'accès. |
| `monitoring/` | Observabilité et audit. |
| `ai/` | Périmètre de l'IA — formalisé en ADR 0005. |
| `templates/` | Modèles réutilisables et références visuelles. |
| `knowledge/` | Vide depuis le pivot. |

## Ce qui n'existe plus

`project/phases/`, `agents/`, `backtesting/`, `prompts/`, l'ancienne série d'ADR 0001–0013, `changelog.md`, `session-history.md`, `handoff.md`, `memory.md`, `project_state.md`, `development_manifesto.md`.

Supprimés le 2026-09-04 avec la recherche d'edge. Le détail et les raisons sont dans `project/pivot-2026-09-04.md`.

La gouvernance par phases numérotées est remplacée par une gouvernance par outils et vagues (ADR 0006).
