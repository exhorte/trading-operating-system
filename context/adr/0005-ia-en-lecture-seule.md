# ADR 0005 — L'IA reste en lecture

Date : 2026-09-04. Statut : accepté. Formalise `context/ai/ai_future.md` en décision opposable.

## Contexte

L'audit du 2026-09-03 a vérifié les modèles disponibles et conclu sur deux limites structurelles :

- **Sentiment ≠ direction.** Les modèles de sentiment financier sont entraînés sur du corpus actions anglophone. Le vocabulaire or/forex y est absent. Une nouvelle « positive » peut faire chuter l'or si elle déplace les anticipations de taux.
- **Forecasting ≠ stratégie.** Les modèles de série temporelle extrapolent des motifs numériques sans accès au calendrier macro ni au langage des banques centrales. Sur XAUUSD, dont les mouvements majeurs viennent de chocs discrets programmés, ils sont structurellement aveugles.

## Décision

Tout composant IA de ce projet est **en lecture**. Il peut classer, résumer, retrouver par RAG, expliquer un régime *a posteriori*, répondre à une question sur le journal.

Il ne peut pas : produire un signal, pondérer une décision, modifier un paramètre de risque, déclencher ou annuler un ordre.

Un serveur MCP exposant la base de ce projet est **en lecture seule** — c'est explicitement le cas de T15.

## Conséquences

- La référence `ariadng/metatrader-mcp-server` sert de modèle de protocole ; sa partie exécution n'est jamais branchée.
- Une réponse d'IA qui ressemble à une recommandation d'entrée est un défaut à corriger, pas une fonctionnalité.
- Cet ADR ne peut pas être contourné par « l'IA propose, l'humain valide » : une proposition affichée au moment de décider est une décision déguisée.
