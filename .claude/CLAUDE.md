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
8. **Mission « Trading OS autonome » en cours** : lire le plan de mission `../01_context/plan trading operating system.md` (l'autorité sur *quoi construire*) et le plan de reprise
   `../02_plan/plan-reprise-2026-11-01.md` (conformité et incréments restants). **Avant toute stratégie** (S01, S02, une autre), lire `../07_trading_strategy/00_Synthese_strategies.md` : S02 a été écrite une première
   fois sans ces notes et a dû être corrigée. Ce qu'elles ne chiffrent pas n'est pas à deviner (le plan, §23).

## Direction non négociable

- **Le process est le produit, pas le signal.** Aucun module n'invente quoi trader, quand, ni dans quel sens (ADR 0001). Seule la stratégie formalisée et configurée par l'utilisateur (S01 aujourd'hui) décide des entrées, dans les limites du Risk Engine (ADR 0015) : jamais une IA, jamais une optimisation, jamais un seuil assoupli pour « faire trader ».
- **La recherche d'edge est close** (ADR 0002). Ne pas proposer d'optimiseur, de générateur de signaux, de balayage de paramètres, ni de « juste tester rapidement une idée ». **Une seule exception, bornée par l'ADR 0026** : le banc de validation (`python -m trading_os validate`) mesure *une* configuration figée de S01 ou S02 sur une période passée, compte chaque regard dans un registre, et n'offre aucun moyen de comparer ou de choisir. `python/trading_os/domain/market/analysis/` fournit du contexte, pas des signaux.
- **L'EA n'est pas le cerveau.** MT5 est un point d'exécution et de télémétrie.
- **Le Risk Engine est le point de contrôle unique** (ADR 0007). Toute règle passe par une gate testée, jamais par un bouton grisé.
- **L'IA reste en lecture** (ADR 0005). Classer, résumer, retrouver, expliquer. Jamais décider, jamais ordonner.
- **Un** appel d'exécution existe désormais (`OrderSend`, EA-05 incrément 6, livré le 2026-09-15 sur accord explicite) : `tools/mt5-execution-agent/TradingOsAgent.mq5`, dans `ExecuteOrder` uniquement. Il est **structurellement inatteignable** — première instruction de la fonction, sortie si le mode n'est pas `CONFIRM` ; et `g_mode` est un `const` de compilation à `MODE_OBSERVE`, jamais affecté nulle part. `observe` / SIMULATED reste donc le seul chemin qui s'exécute réellement.
- **Accords nommés donnés** (mot pour mot dans `session-log.md`, 2026-09-25 et 2026-09-26) : ADR 0013 (connexion depuis l'application), ADR 0014 (armement), EA-08 (fermeture globale), EA-07 (CONFIRM), ADR 0015 (autonomie, compte réel dès I5). Ils couvrent les incréments I3 à I8 de `02_Plan_Projet/etude-connexion-pilotage-agent-2026-09-25.md`, et seulement eux : chaque élargissement du chemin d'exécution se construit dans son incrément, après l'ADR ou la fiche qui le précède, jamais en avance.
- **Accord du 2026-11-01** (mission « Trading OS autonome », `session-log.md`) : ADR 0019 (limites de risque), puis, sur la consigne de continuer les phases restantes, **ADR 0023** (ordres `LIMIT`/`MODIFY`/`CLOSE`/`PARTIAL_CLOSE`/`CANCEL` et Position Manager, **côté cœur seulement**), **0024** (S02, arrêtée par défaut), **0025** (Account Guardian), **0026** (banc de validation — il borne l'exception à l'ADR 0002 : une configuration figée, jamais de recherche), **0027** (critères de passage, consultatifs), **0028** (« Pourquoi pas de trade ? ») : tous **construits**. **Accord du 2026-11-01 (suite)** : la partie MQL5 des nouveaux ordres (**ADR 0029**, agent 1.12 : un seul `OrderSend`, dans `ExecuteOrder`, toujours `OBSERVE` compilé), les fenêtres par stratégie (**ADR 0030**), N8 (**ADR 0031**, désactivé et inerte), puis le Guardian complet (**ADR 0032**, 2026-11-02) : **construits**, jamais éprouvés chez un courtier. **Pas construit** : un compte FTMO réel ; ce qui reste à vérifier sur un terminal est dans le README de l'agent.
- **Accord du 2026-11-02 (ADR 0034)** : les deux gestes du cockpit — « DÉMARRER LE SYSTÈME » (vérifie, réconcilie, monte à `OBSERVE`, `PAPER` ou `CONFIRM` au plus) et « FERMER TOUTES LES POSITIONS » (une commande `CLOSE` humaine par position, par le chemin existant, dans tous les modes) — plus la correspondance de l'échelle du plan (`DEMO_AUTO`, `LIVE_CONFIRM`, `LIVE_AUTO`) lue sur celle du dépôt. **Aucun changement de l'agent MQL5** : toujours compilé `OBSERVE` ; une position que l'agent n'a pas placée (autre numéro magique) reste à fermer dans MT5, la lever demande un accord et un ADR séparés. « AUTORISER LE TRADING AUTOMATIQUE » est un geste à part.
- **Méthode du 2026-11-03 (ADR 0035)** : développer à partir des données **réelles** du terminal et du courtier (démo Exness), pas du mode `OBSERVE` ni de simulations ; une amélioration = un problème réel, une preuve mesurée, une vérification ; rien n'est dit « validé » sans réponse réelle du terminal ou du courtier (sinon : « non vérifié sur le live »). `OBSERVE` reste le mode de diagnostic et de récupération. **Aucun garde-fou n'est touché** et la règle suivante ne change pas. Mesures de base : `context/execution/live-baseline-2026-11-03.md`.
- **Mission du 2026-11-03 (ADR 0036)** : un seul cœur, un seul Risk Engine, une seule stratégie, pour Exness Standard **et** FTMO. Le compte est **identifié** par des signaux indépendants (serveur, société du compte, société du terminal, suffixe des symboles, levier) ; le login ne prouve rien et la déclaration de l'utilisateur ne suffit pas ; un compte non identifié, au produit FTMO non déclaré (jamais de challenge par défaut) ou aux règles non sourcées est **non exécutable**. Les règles d'un fournisseur sont des **données versionnées avec leurs sources** (`domain/providers/rules.py`, `context/domain/regles-par-environnement.md`) ; la plus stricte l'emporte et la politique effective le montre (`GET /api/accounts/{id}/effective-policy`). Les objectifs de profit ne sont **jamais** une entrée du risque. Les références de perte FTMO (solde de 00:00 CE(S)T) sont écrites une fois et jamais réécrites. La commission est celle du **porteur**, mesurée d'abord. **Ne fait que resserrer** : aucun garde-fou touché, agent MQL5 inchangé (`OBSERVE`), Claude ne déclenche toujours aucun ordre. Étapes 8 à 13 de la mission non construites.
- **Ne jamais élargir au-delà sans nouvel accord explicite et séparé** : autre chemin d'exécution, autre stratégie, autre compte, garde-fou automatique retiré. Ça ne se déduit d'aucune consigne générale d'avancement ou de « clôture ».
- **Claude ne déclenche jamais lui-même un ordre, un armement ou l'autonomie**, ni en démo ni en réel : aucun clic sur Démarrer, « DÉMARRER LE SYSTÈME », « AUTORISER LE TRADING AUTOMATIQUE », Armer, Valider, « FERMER TOUTES LES POSITIONS » (ni sa confirmation), Arrêt d'urgence ou halt, aucune commande envoyée à un agent en live. Les essais sur le compte réel sont faits par l'utilisateur (ADR 0015 ; étude, §6).
- Pas de martingale, pas de grille, pas de moyenne à la baisse.
- Aucun mot de passe de compte n'est stocké, journalisé ni renvoyé par le Trading OS : le formulaire « Connecter un compte » le reçoit, le cœur s'en sert une fois pour lire le compte chez le courtier, puis l'oublie ; MT5 peut garder le sien selon ses réglages (ADR 0013, 0020). **Claude ne voit, ne saisit, ne lit ni ne teste jamais le vrai mot de passe** : l'essai réel est fait par l'utilisateur dans son navigateur.

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
