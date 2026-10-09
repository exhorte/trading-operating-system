# Quality Gates

Version 3 — 2026-10-09 (ADR 0016 : le cœur est en Python). Les gates de backtesting ont disparu avec la recherche d'edge (ADR 0002) ; les gates .NET avec le Gateway.

## Avant de modifier du code produit

- Les fiches et documents de contexte pertinents sont lus.
- Le code d'ancrage existant est inspecté — pas supposé.
- L'impact est compris.

## Avant de clore un outil

```powershell
# cœur Python (depuis 04_code\python)
.venv\Scripts\python.exe -m pytest -q                 # unitaires, intégration, base jetable, architecture
.venv\Scripts\python.exe -m ruff check . ; .venv\Scripts\python.exe -m ruff format --check .
.venv\Scripts\python.exe -m mypy trading_os           # --strict
# cockpit (depuis 04_code)
npm run lint ; npm run typecheck ; npm test ; npm run build
```

Si un modèle, une route ou un événement du cœur a changé : `python -m trading_os gen-types` (un test échoue si `lib/api/generated.ts` est périmé).

Si `tools/mt5-execution-agent/*.mq5` a changé, en plus : compilation headless via MetaEditor **sur une copie du dossier** (le `.ex5` est écrit à côté de la source) :

```powershell
& "C:\Program Files\MetaTrader 5\MetaEditor64.exe" /compile:"<copie>\TradingOsAgent.mq5" /log:"<copie>\compile.log"
```

Le dernier message du journal doit être `0 errors, 0 warnings` (le code de sortie de MetaEditor est 1 en cas de succès). Cela ne vérifie que la syntaxe et le typage — pas le comportement réseau ni l'exécution, qui se valident à la main contre un terminal (`tools/mt5-execution-agent/README.md`) ; les garanties structurelles de l'agent (un seul `OrderSend` derrière le plafond `OBSERVE`, interrupteur d'homme mort) sont, elles, des tests (`python/tests/architecture/test_execution_agent.py`). Le chemin de MetaEditor suppose une installation locale de MetaTrader 5 ; adapter s'il diffère.

Si l'interface a changé : la vérifier **dans un vrai navigateur** contre le vrai cœur en mode simulé (`MT5_ENABLED=false`) — clair et sombre, bureau et mobile, aucune erreur console, aucun débordement, contraste AA ; un onglet caché ne se peint pas (voir `testing_strategy.md`).

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

Toute fonctionnalité de flux (WebSocket) doit définir : états de connexion, hypothèses d'authentification, portée d'abonnement, forme de la trame, reconnexion, comportement en donnée périmée, resynchronisation par instantané, champs d'observabilité (`context/realtime/`).

Authentification : l'API REST et le WebSocket du cœur exigent le jeton du cockpit **et** une Origin autorisée, lectures comprises (seul `GET /api/system/health` s'en passe) ; le lien agent exige le jeton de l'agent — `context/security/security_principles.md`, « Surface locale ». Toute nouvelle porte (route, port, type de message) passe derrière la même garde, avec un test de refus.

## Gate IA

Tout composant IA doit démontrer qu'il est en lecture (ADR 0005) : il ne produit ni signal, ni pondération de décision, ni modification de paramètre de risque. Un serveur MCP exposant ce projet est en lecture seule.
