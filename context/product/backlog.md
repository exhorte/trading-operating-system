# Backlog — T06 à T19 et outils standalone

Une fiche s'écrit au moment de démarrer l'outil, pas avant : une fiche
rédigée trois mois trop tôt décrit un problème qui a changé.

**Cinq ont depuis été démarrés et livrés** — T06, T07, T08, T09, T15 — et
leur fiche fait foi désormais (`tools/T0{6,7,8,9}-*.md`, `T15-serveur-mcp.md`).
Les descriptions ci-dessous sont **celles d'avant construction** : là où
elles divergent de ce qui existe, c'est la fiche qui est à jour, pas ce
fichier. Les écarts ont tous été notés dans les fiches concernées (le plus
fréquent : du vocabulaire hérité de T04, retiré le 2026-09-14, qui supposait
un plan déclaré).

Le raisonnement complet de chacun est dans `catalogue.md`. Ce fichier n'en garde que l'essentiel et le statut.

## Vague 2 — fermer la boucle d'apprentissage

**T06 — Journal auto-alimenté, zéro saisie** · 3–5 j · valeur 5 · dépend de T05 · **livré le 2026-09-16**
**Recadré le 2026-09-14** (T04 retiré, raisonnement complet dans `roadmap.md`) :
les trades viennent de TimescaleDB (`closed_trades`/`position_opens`), les
images des captures (T05), et — quand ça coïncide — le contexte machine
d'EA-02 (`setup_proposals`). Plus de ticket pré-trade à réconcilier : le
journal enregistre les **faits d'exécution**, plus les **intentions**
déclarées (setup, biais, confiance, invalidation — perdus avec T04). À
construire : modèle de données du journal (schéma inspiré de TradeNote,
GPL-3.0 — sans contrainte en usage personnel non distribué), réconciliation
trade ↔ capture ↔ proposition EA-02, vues calendrier P&L / equity /
expectancy / profit factor. Ventilations possibles sans ticket : symbole,
session, heure d'entrée, jour de la semaine — pas de ventilation par
confiance déclarée, elle n'existe plus.

**T07 — Tracker d'erreurs et taux de conformité** · 1–2 j · valeur 5 · dépend de T06 · **livré le 2026-09-16**
**Taxonomie à réviser le jour où T07 démarre** (T04 retiré) : *« trade hors
plan »* et *« absence de ticket »* supposaient un plan déclaré, qui n'existe
plus. Reste détectable sans déclaration préalable : stop déplacé après
l'entrée, taille hors politique, trade pendant un lockout actif, trade hors
fenêtre horaire. Sortie : une courbe unique, le taux de conformité
hebdomadaire **au Risk Engine** (plus au plan, qui n'est plus une donnée),
affiché en haut du cockpit à la place du P&L.

**T15 — Serveur MCP « mon trading »** · 1–2 j · valeur 4 · dépend de T06 · **livré le 2026-09-17**
Serveur MCP **en lecture seule** exposant trades, tickets, erreurs, statistiques, bougies. Permet de poser les questions en langage naturel sans construire une interface par question. Remplace 80 % de ce que ferait T19 pour 5 % de l'effort. Référence de protocole : `ariadng/metatrader-mcp-server` (MIT) — **sans en brancher la partie exécution** (ADR 0005).

**T08 — Revue hebdomadaire générée** · 1–2 j · valeur 4 · dépend de T06 · **livré le 2026-09-17**
Générée le vendredi soir : statistiques, taux de conformité, les trois pires trades avec leur ticket en regard du résultat, les trois erreurs les plus fréquentes. Un document qui se lit une fois et se garde, pas un tableau de bord.

## Vague 3 — poste de travail complet

**T09 — Checklist de pré-vol exécutable** · 1–2 j · valeur 4 · dépend de T03 · **livré le 2026-09-17**
Pas un document à cocher : une checklist dont le système vérifie lui-même les items (compte connecté, spread dans la norme, DD restant suffisant, pas de blackout dans les 60 min, plan écrit, verrous armés). Tant que tout n'est pas vert, la séance n'est pas « armée » et le Risk Engine refuse.

**T10 — Brief pré-séance automatique** · 2–3 j · valeur 4 · dépend de T03
Généré avant l'ouverture : niveaux (PDH/PDL, high/low asiatique, extrêmes de la semaine), ATR et range attendu, publications et heures de blackout, état des comptes, statistiques personnelles pour ce jour et cette session. Assemblage de `lib/analysis/` déjà écrit et testé — pas une nouvelle analyse.
**Piège à éviter** : le brief donne du contexte, pas une direction. Dès qu'il écrit « biais haussier aujourd'hui », il devient un signal déguisé et viole l'ADR 0001.

**T11 — Multi-compte natif** · 1–2 sem · valeur 3
Plomberie : descendre le scope `workspace / account / connection` dans l'enveloppe, le hub SignalR, le schéma TimescaleDB et le store frontend. Un observer par compte, réconciliation par compte. Valeur propre faible, prérequis de T12.

**T12 — Prop Firm Control Center** · 1–2 sem · valeur 5 · dépend de T11
Le trou le plus net de l'open source d'après l'audit du 2026-09-03. Registre de comptes (broker, firme, phase 1/2/funded), règles par firme, profit target, daily DD, max DD, jours minimum, échéance de payout, kill switch global, lockout par compte.

**T13 — Simulateur de règles pré-trade** · 1–2 j · valeur 4 · dépend de T12
« Si ce trade part au stop, où me place-t-il par rapport au daily DD et au max DD, sur ce compte, dans cette phase ? » Une ligne de plus dans T01, une fois le contexte firme disponible.

**T14 — Alertes en lecture seule** · 1 j · valeur 3
Telegram ou notification système : DD à 70 % du seuil, phase terminée, échéance de payout, blackout imminent, observer déconnecté. **Lecture seule et sans commande** — un bot qui peut passer des ordres est un EA-cerveau déguisé.

## Vague 4 — intelligence de marché

**T16 — Corrélations glissantes** · 3–5 j · valeur 3
XAUUSD / DXY / US10Y / EURUSD / BTC, multi-horizons. Déterministe, côté lecture.

**T19 — AI Analyst RAG** · 1–2 sem · valeur 3 · dépend de T06, T15
RAG sur news + journal (`BAAI/bge-m3` embeddings + `BAAI/bge-reranker-v2-m3`, MIT), raisonnement local (`SUFE-AIFLM-Lab/Fin-R1`, Apache-2.0, GGUF ≈ 4–5 Go RAM). Explication sourcée, jamais un ordre (ADR 0005). Largement redondant avec T15 — à ne démarrer que si T15 montre ses limites.

## Outils standalone

**S1 — Dictée vocale horodatée** · 1–2 j · valeur 4
Pendant le trade, dire ce qu'on fait et pourquoi ; transcrit, horodaté, rattaché au trade. Le seul moyen réaliste de capturer l'état émotionnel au moment où il existe. Recoupement direct avec **Vozel** : le moteur de dictée est déjà un produit de l'utilisateur, il ne reste que la colle. C'est aussi un cas d'usage réel de Vozel, testé quotidiennement par son auteur.

**S2 — Rapport hebdo CLI depuis l'export MT5** · 1 j · valeur 3
Lit le rapport HTML/CSV exporté de MT5, sort un markdown de statistiques. Aucune dépendance au projet — utile même si la plateforme n'avance pas pendant un mois.

**S3 — Watcher de conditions** · 0,5 j · valeur 2
Surveille spread et volatilité, alerte hors norme. Sert aussi de sonde de qualité de donnée : c'est ce qui aurait signalé le stall de l'observer du 28 juillet 2026.
