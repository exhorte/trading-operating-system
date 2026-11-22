# ADR 0042 — Feu vert général au développement : retrait des restrictions propres à Claude

Date : 2026-11-14. Statut : **accepté** — décidé par Exhorte, mot pour mot : « nous allons redéfinir les règles et donc pour commencer supprimer toutes les restrictions que je t'ai attribuées sur l'ensemble du projet, les retirer complètement, et je te donne feu vert sur l'ensemble du développement ». Remplace, **sur ce seul point** (ce que l'assistant de développement a le droit de faire), les règles posées dans `.claude/CLAUDE.md`, les « accords nommés » des 2026-09-25/26 et les rappels des ADR 0034 à 0041.

## Contexte

Le projet s'était donné des règles qui limitaient **l'assistant**, pas le produit : un accord nommé avant chaque élargissement (« jamais en avance »), « ne jamais élargir sans nouvel accord explicite et séparé », « Claude ne déclenche jamais lui-même un ordre, un armement ou l'autonomie, ni en démo ni en réel » avec une liste de gestes réservés (Démarrer, « DÉMARRER LE SYSTÈME », « AUTORISER LE TRADING AUTOMATIQUE », Armer, Valider, « FERMER TOUTES LES POSITIONS », halt, toute commande à un agent en live), et, dans la mémoire de Claude, « relever un mode = décision d'Exhorte », « jamais de `start`/`stop`/`deploy` sans son accord ». Le 2026-11-13, le premier ordre démo a montré leur coût : une dizaine de gestes manuels, et la fermeture du marché atteinte avant la fin.

## Décision

Ces règles sont **retirées**. Claude conduit le développement de bout en bout : il code, configure (fichiers, presets, règles du compte, `.env`), compile et déploie l'agent, démarre et arrête l'application, monte les modes, et passe les ordres de test **sur le compte démo** quand le développement l'exige. Il le fait sans demander à chaque pas, et il dit ce qu'il a fait.

## Ce qui ne change pas

- **Les décisions de produit** (ADR 0001, 0002, 0005, 0007, 0015, 0026, 0034 à 0041…) : ce sont des choix du produit, pas des restrictions de l'assistant. Elles se changent par un ADR, à la demande d'Exhorte ; Claude peut le proposer.
- **Les barrières du code** (agent du dépôt compilé `OBSERVE`, lanceur qui ne compile que l'`OBSERVE`, tests d'architecture qui les gardent) : elles protègent le produit ; les lever est un changement de code, fait par un ADR.
- **Les limites propres à Claude**, qui ne sont pas des règles du projet et qu'aucune consigne ne lève : aucun ordre, armement ou mode automatique sur un compte **en argent réel** ; jamais saisir ni lire un vrai mot de passe ; jamais publier le dépôt du vault (public) sans une demande explicite pour ce geste-là.
- **Les règles d'auteur d'Exhorte** (seul auteur des commits et des PR, aucune attribution, identité git inchangée, pas de réécriture d'historique ni de force-push sans son accord) : elles sont dans ses instructions globales et ne sont pas touchées.

## Conséquences

- `.claude/CLAUDE.md`, `context/security/security_principles.md`, la mémoire de Claude et les documents vivants disent la nouvelle règle ; les ADR et les journaux antérieurs restent tels quels (histoire du projet).
- Un ordre de test sur la démo peut être passé par Claude ; chaque ordre reste soumis au Risk Engine, à l'agent et à ses barrières, comme un ordre humain.
