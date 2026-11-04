# Architecture Decision Records — série 2

La série 1 (`0001-platform-over-ea` à `0013-backtest-diagnostics`, juillet 2026) a été supprimée le 2026-09-04 avec le reste de l'historique de recherche.

Les décisions de la série 1 qui gouvernent encore ont été reprises et réécrites ici. Celles qui portaient sur la recherche d'edge (moteur de signal, backtesting, diagnostics, holdout) sont caduques.

| # | Titre | Statut |
|---|---|---|
| 0001 | Le process est le produit | Accepté |
| 0002 | Fin de la recherche d'edge | Accepté |
| 0003 | Stack et topologie | Accepté — pile .NET/SignalR supersédée par 0016 (le reste tient) |
| 0004 | Contrats de domaine et wire MT5 | Accepté — le modèle canonique devient le modèle Python (0016) ; le wire EA tient |
| 0005 | L'IA reste en lecture | Accepté |
| 0006 | Gouvernance par outils et vagues | Accepté |
| 0007 | Le Risk Engine est le point de contrôle unique | Accepté |
| 0008 | Journal de session, réintroduit et borné | Accepté |
| 0009 | Le serveur capture des faits, le cockpit rend | Accepté |
| 0010 | Le Trading OS exécute, l'EA est un agent | Accepté |
| 0011 | Un banc de replay n'est pas un backtester | Accepté |
| 0012 | Système de design : shadcn/ui | Accepté — amende 0003 (dépendances front, densité) ; l'apparence (sombre seul, menthe) est supersédée par 0017, la bibliothèque tient |
| 0013 | Connexion au compte depuis l'application | Accepté le 2026-09-25, rédigé le 2026-09-26 — amende 0003 ; texte soumis à relecture |
| 0014 | Armement de l'agent depuis l'application | Accepté le 2026-09-25 (volet armement), rédigé le 2026-09-26 avec le bail côté serveur de 0015 — amende 0010 ; texte soumis à relecture |
| 0015 | Mode autonome : le Trading OS exécute la stratégie configurée | Accepté le 2026-09-26 — supersède la clause AUTO de 0010, amende 0001 et la charte (v3) ; amendé le même jour (spread relatif au stop, pertes levées par accusé, arrêts de stratégie) |
| 0016 | Architecture Python-native : le cœur est un monolithe Python | Accepté le 2026-10-07 — supersède la pile .NET/SignalR de 0003, amende 0004 et 0013 (stockage opt-in des identifiants) ; réalise le Risk Engine côté serveur de 0007/0015 ; points à confirmer listés dans l'ADR |
| 0017 | Système de design : « ExponentValue Monochrome » | Accepté le 2026-10-08 — supersède l'apparence de 0012 (thème clair + sombre, panneau de métriques sombre, une seule pastille menthe), amende 0003 (« cockpit sombre ») ; écarts assumés par rapport au design d'origine et points laissés ouverts listés dans l'ADR |
| 0018 | Suppression de la capture graphique : on garde les données | Accepté le 2026-10-09 — supersède 0009 pour le rendu (plus aucun graphique ni image de trade) ; les faits enregistrés (prix d'entrée, stop, objectif, sortie) et le dossier du trade restent |
| 0019 | Risque dynamique par trade et nouvelles limites officielles | Accepté le 2026-11-01 — amende 0015 (limites : 15 trades, 5 positions, perte hebdomadaire 10 %, grille de risque −5 % → 1,5 %, déclencheur 200 $) ; interprétations et points à confirmer listés dans l'ADR |
| 0020 | Connexion par identifiants du courtier, lecture du compte chez lui, profil FTMO répété sur une démo | Accepté le 2026-11-01 — réalise l'incrément I3 de 0013 ; amende 0019 (plafonds contractuels portés par le challenge des règles) ; essai avec mot de passe à faire par l'utilisateur |
| 0021 | Un seul compte connecté à la fois ; le formulaire de connexion sur Account, et à la place des écrans vides | Accepté le 2026-11-01 — supersède 0020 pour l'emplacement du formulaire, amende 0013 (D2) ; `set_active` à retirer dans un lot à part |
| 0022 | Aucune limite de positions par symbole ; la perte hebdomadaire se règle dans Settings | Accepté le 2026-11-01 — amende 0019 et 0015 ; le champ `max_positions_per_symbol` (jamais appliqué) est retiré |
| 0023 | Ordres `LIMIT`, `MODIFY`, `CLOSE`, `PARTIAL_CLOSE`, `CANCEL` et Position Manager (phase 3) | Accepté le 2026-11-01 — côté cœur ; l'agent MQL5 n'est pas modifié |
| 0024 | Stratégie S02 (ICT 2022) : le pipeline de S01 recomposé, arrêtée par défaut (phase 2) | Accepté le 2026-11-01 |
| 0025 | Account Guardian : un surveillant indépendant des positions du cœur (phase 4) | Accepté le 2026-11-01 |
| 0026 | Banc de validation : mesurer une configuration figée, jamais en chercher une (phase 5) | Accepté le 2026-11-01 — amende 0002 de façon bornée |
| 0027 | Critères de passage de chaque mode d'autonomie : mesurés, affichés, jamais imposés (phase 6) | Accepté le 2026-11-01 — consultatif |
| 0028 | « Pourquoi pas de trade ? » : une seule réponse lisible (phase 7) | Accepté le 2026-11-01 |
| 0029 | Agent MQL5 : gestionnaires `LIMIT`, `MODIFY`, `CLOSE`, `PARTIAL_CLOSE`, `CANCEL` derrière un seul `ExecuteOrder` | Accepté le 2026-11-01 — réalise la partie MQL5 de 0023 ; agent 1.12, toujours `OBSERVE` compilé, un seul `OrderSend` |
| 0030 | Fenêtres horaires propres à chaque stratégie : S02 à 08:30–11:00 New York, S01 inchangée | Accepté le 2026-11-01 — amende 0024 (S02 n'hérite plus des heures de S01) |
| 0031 | N8 « Drawdown Flatlining » : un plafond qui ne fait que baisser le risque, par pas de 0,1 % | Accepté le 2026-11-01 — étend 0019 ; désactivé et inerte tant que la plus petite unité n'est pas écrite |
| 0032 | Account Guardian complet : surveiller spread, glissement et santé ; demander une réconciliation (plan §9) | Accepté le 2026-11-02 — étend 0025 ; l'annulation sur spread large est désactivée par défaut |
| 0033 | Sous `HALTED`, les fermetures et les annulations passent ; tout le reste reste refusé | Accepté le 2026-11-02 — amende 0025 ; agent 1.13 ; une sortie humaine seulement, jamais l'automatique |
| 0034 | « Fermer toutes les positions » et « Démarrer le système » depuis le cockpit ; les sorties humaines passent dans tous les modes ; l'échelle du plan lue sur celle du dépôt | Accepté le 2026-11-02 — amende 0023 et 0033 ; aucun changement de l'agent MQL5 |
| 0035 | Développement piloté par le marché réel et le courtier : la preuve est un fait observé au terminal, `OBSERVE` redevient un mode de diagnostic, aucun garde-fou touché | Accepté le 2026-11-03 — méthode seulement ; mesures de base dans `context/execution/live-baseline-2026-11-03.md` |
| 0036 | Plusieurs environnements, une seule plateforme : identification du compte par signaux indépendants, règles du fournisseur par produit avec leur provenance, planchers de perte FTMO (solde de 00:00 CE(S)T), politique de risque effective (la plus stricte l'emporte, et on voit pourquoi), commission observée, spécification d'instrument sans valeur supposée — ne fait que resserrer | Accepté le 2026-11-03 ; amende 0019 et 0020 |

Format : contexte, décision, conséquences. Un ADR ne se modifie pas — il se remplace par un ADR suivant qui le supersède.

## Correspondance série 1 → série 2

Des documents techniques hérités et quelques commentaires de code citent encore les numéros de la série 1. Table de conversion :

| Série 1 | Devient |
|---|---|
| 0001 platform over EA | **0001** — Le process est le produit |
| 0002 Next.js + .NET · 0003 WebSocket-first · 0009 backend bootstrap · 0011 persistance Timescale | **0003** — Stack et topologie |
| 0004 schéma TypeScript · 0005 wire MT5 lean | **0004** — Contrats de domaine et wire MT5 |
| 0008 risk engine TypeScript · 0010 execution bridge | **0007** — Le Risk Engine est le point de contrôle unique |
| 0006 moteur ICT/SMC · 0012 backtesting MVP · 0013 diagnostics de backtest | **Caducs** — voir 0002, fin de la recherche d'edge |
| 0007 prototype live observe | Absorbé dans **0003** ; le raccourci de traduction côté navigateur qu'il décrivait n'existe plus (traduction serveur depuis la Phase 08) |

Aucune de ces citations n'a été corrigée dans les documents hérités : elles sont exactes pour l'époque décrite, et cette table suffit à les résoudre.
