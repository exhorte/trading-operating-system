# Quality Gates

Version 2 — 2026-09-04. Les gates de backtesting ont disparu avec la recherche d'edge (ADR 0002).

## Avant de modifier du code produit

- Les fiches et documents de contexte pertinents sont lus.
- Le code d'ancrage existant est inspecté — pas supposé.
- L'impact est compris.

## Avant de clore un outil

```bash
npm run lint          # ESLint
npx tsc --noEmit      # typage, doit sortir 0
npm test              # Vitest
npm run build         # compilation Next.js
cd backend && dotnet build && dotnet test   # C#
python -m py_compile tools/mt5-observer/*.py
```

- Toutes vertes, sans exception tolérée en silence.
- La nouvelle logique de domaine a des tests, ou l'absence de test est écrite dans la fiche.
- Tout comportement lié au risque est relu explicitement.
- Le critère de réussite de la fiche est atteint, ou la fiche reste ouverte.

## Gates spécifiques au trading

Aucune fonctionnalité touchant à l'exécution n'est acceptable si elle ne remplit pas toutes ces conditions :

- les commandes sont auditables ;
- elles passent par le chemin temps réel approuvé `RiskDecision → Command → ACK → Report` ;
- elles sont idempotentes et acquittées ;
- les échecs sont rapportés ;
- les doublons sont gérés ;
- les verrous de risque sont appliqués côté moteur, pas côté interface ;
- un arrêt d'urgence existe ;
- le comportement de reconnexion et de resynchronisation est spécifié.

**Rappel** : aucun appel de trade n'existe nulle part dans ce dépôt. Le mode `observe` / SIMULATED est le seul chemin implémenté. Passer en mode live est une décision d'ADR, pas un changement de configuration.

## Gates temps réel

Toute fonctionnalité WebSocket/SignalR doit définir : états de connexion, hypothèses d'authentification, portée d'abonnement, enveloppe d'événement, reconnexion, comportement en donnée périmée, resynchronisation par snapshot, champs d'observabilité.

## Gate IA

Tout composant IA doit démontrer qu'il est en lecture (ADR 0005) : il ne produit ni signal, ni pondération de décision, ni modification de paramètre de risque. Un serveur MCP exposant ce projet est en lecture seule.
