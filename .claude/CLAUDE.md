# Instructions Claude

Ce dépôt est un **poste de travail personnel pour trader intraday**. Depuis l'ADR 0015 (accepté le 2026-09-26), il doit aussi exécuter en autonomie la stratégie que l'utilisateur a lui-même configurée, dans des limites automatiques — ce n'est pas encore construit. Ce n'est pas un backtester, ni un générateur de stratégies.

## Avant toute implémentation

1. Lire `AGENTS.md` et garder l'avertissement Next.js actif.
2. Lire `context/project/charter.md` — ce que le projet est et ce qu'il n'est plus.
3. Lire `context/project/state.md` — instantané de ce qui existe et la prochaine action.
4. Lire `context/project/session-log.md` — ce qui s'est passé dans les dernières sessions (ADR 0008 ; ne pas confondre avec `state.md`, qui ne raconte rien).
5. Lire `context/adr/` en entier. ADR courts ; ils tranchent la plupart des questions.
6. Lire la fiche de l'outil en cours dans `context/product/tools/`.
7. Lire les documents de domaine, d'architecture et d'ingénierie pertinents **avant** de toucher au code.

## Direction non négociable

- **Le process est le produit, pas le signal.** Aucun module n'invente quoi trader, quand, ni dans quel sens (ADR 0001). Seule la stratégie formalisée et configurée par l'utilisateur (S01 aujourd'hui) décide des entrées, dans les limites du Risk Engine (ADR 0015) : jamais une IA, jamais une optimisation, jamais un seuil assoupli pour « faire trader ».
- **La recherche d'edge est close** (ADR 0002). Ne pas proposer de backtester, d'optimiseur, de générateur de signaux, ni de « juste tester rapidement une idée ». `python/trading_os/domain/market/analysis/` fournit du contexte, pas des signaux.
- **L'EA n'est pas le cerveau.** MT5 est un point d'exécution et de télémétrie.
- **Le Risk Engine est le point de contrôle unique** (ADR 0007). Toute règle passe par une gate testée, jamais par un bouton grisé.
- **L'IA reste en lecture** (ADR 0005). Classer, résumer, retrouver, expliquer. Jamais décider, jamais ordonner.
- **Un** appel d'exécution existe désormais (`OrderSend`, EA-05 incrément 6, livré le 2026-09-15 sur accord explicite) : `tools/mt5-execution-agent/TradingOsAgent.mq5`, dans `ExecuteOrder` uniquement. Il est **structurellement inatteignable** — première instruction de la fonction, sortie si le mode n'est pas `CONFIRM` ; et `g_mode` est un `const` de compilation à `MODE_OBSERVE`, jamais affecté nulle part. `observe` / SIMULATED reste donc le seul chemin qui s'exécute réellement.
- **Accords nommés donnés** (mot pour mot dans `session-log.md`, 2026-09-25 et 2026-09-26) : ADR 0013 (connexion depuis l'application), ADR 0014 (armement), EA-08 (fermeture globale), EA-07 (CONFIRM), ADR 0015 (autonomie, compte réel dès I5). Ils couvrent les incréments I3 à I8 de `02_Plan_Projet/etude-connexion-pilotage-agent-2026-09-25.md`, et seulement eux : chaque élargissement du chemin d'exécution se construit dans son incrément, après l'ADR ou la fiche qui le précède, jamais en avance.
- **Accord du 2026-11-01** (mission « Trading OS autonome », `session-log.md`) : ADR 0019 (limites de risque, **construit**). La mission nomme aussi S02 (ICT 2022), les ordres `LIMIT`/`MODIFY`/`CLOSE`/`PARTIAL_CLOSE`, un banc de backtest et un compte FTMO : ils se construisent un par un, **après leur propre ADR**, et la recherche d'edge (ADR 0002) n'est levée que par cet ADR-là.
- **Ne jamais élargir au-delà sans nouvel accord explicite et séparé** : autre chemin d'exécution, autre stratégie, autre compte, garde-fou automatique retiré. Ça ne se déduit d'aucune consigne générale d'avancement ou de « clôture ».
- **Claude ne déclenche jamais lui-même un ordre, un armement ou l'autonomie**, ni en démo ni en réel : aucun clic sur Démarrer, Armer, Valider, Fermer tout, Arrêt d'urgence ou halt, aucune commande envoyée à un agent en live. Les essais sur le compte réel sont faits par l'utilisateur (ADR 0015 ; étude, §6).
- Pas de martingale, pas de grille, pas de moyenne à la baisse.
- Aucun identifiant de compte n'est jamais demandé, stocké ou partagé (règle réécrite avec l'ADR 0013, avant le code d'I3).

## Mode de travail

Agir en ingénieur principal :

1. Lire le contexte d'abord.
2. Analyser l'impact.
3. Concevoir avant de coder pour tout travail non trivial.
4. Implémenter par incréments qui gardent les gates vertes.
5. Vérifier — `context/governance/quality_gates.md`.
6. Mettre à jour la fiche d'outil, `session-log.md` (une entrée courte, ADR 0008), et si nécessaire `state.md` (instantané seulement, jamais de récit qui s'accumule) et les ADR.

Le cycle complet est décrit dans `context/workflows/development_workflow.md`. Commandes : `/outil-start Tnn`, `/outil-close Tnn`.

## Piège le plus fréquent dans ce dépôt

Réécrire du code qui existe déjà. `python/trading_os/domain/` (risque, analyse, stratégie S01, exécution, autonomie…), `services/`, `infrastructure/` et le cockpit (`lib/api`, `lib/realtime`) sont écrits et testés ; le cœur n'a été vérifié qu'avec un terminal simulé — rien n'a tourné contre un vrai MT5 depuis la migration (ADR 0016). Les fiches d'outil nomment les fichiers d'ancrage : les lire avant de créer quoi que ce soit.

## Sécurité

Un logiciel de trading peut causer des pertes financières. Ne jamais présenter une logique non testée comme rentable. Tout objectif de performance est une hypothèse.
