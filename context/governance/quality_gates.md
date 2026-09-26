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

Depuis EA-05, si `tools/mt5-execution-agent/*.mq5` a changé, en plus des gates
ci-dessus — compilation headless via MetaEditor (aucune gate MQL5 n'existait
avant EA-05) :

```powershell
& "C:\Program Files\MetaTrader 5\MetaEditor64.exe" `
  /compile:"tools\mt5-execution-agent\TradingOsAgent.mq5" `
  /log:"tools\mt5-execution-agent\compile.log"
```

Lire `compile.log` : doit afficher `0 errors`. Ne vérifie que la syntaxe et
le typage — pas le comportement réseau ni l'exécution, qui restent à valider
à la main contre le terminal (voir `tools/mt5-execution-agent/README.md`).
Le chemin de MetaEditor suppose une installation locale de MetaTrader 5 ;
adapter s'il diffère.

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

**Rappel** (corrigé le 2026-09-26 — la version précédente affirmait encore qu'« aucun appel de trade n'existe ») : un seul appel de trade existe, `OrderSend` dans `ExecuteOrder` (`tools/mt5-execution-agent/TradingOsAgent.mq5`, EA-05 incrément 6), structurellement inatteignable tant que `g_mode` est le `const` `MODE_OBSERVE`. Les accords nommés du 2026-09-25/26 (ADR 0014, EA-08, EA-07, ADR 0015) ouvrent son élargissement incrément par incrément (étude, I4 à I8) ; tant qu'un incrément n'est pas livré et vérifié, le mode `observe` / SIMULATED reste le seul chemin qui s'exécute. Passer en mode live reste une décision d'ADR, pas un changement de configuration.

## Gates temps réel

Toute fonctionnalité WebSocket/SignalR doit définir : états de connexion, hypothèses d'authentification, portée d'abonnement, enveloppe d'événement, reconnexion, comportement en donnée périmée, resynchronisation par snapshot, champs d'observabilité.

Authentification, depuis I0 (2026-09-26) : le hub, les écritures `/api` et l'observateur exigent leur jeton, le hub aussi une Origin autorisée — `context/security/security_principles.md`, « Surface locale ». Toute nouvelle porte (méthode de hub, endpoint d'écriture, port) passe derrière la même garde, avec un test de refus.

## Gate IA

Tout composant IA doit démontrer qu'il est en lecture (ADR 0005) : il ne produit ni signal, ni pondération de décision, ni modification de paramètre de risque. Un serveur MCP exposant ce projet est en lecture seule.
