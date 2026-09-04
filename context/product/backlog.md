# Backlog — T06 à T19 et outils standalone

Ces outils n'ont pas encore de fiche. Une fiche s'écrit au moment de démarrer l'outil, pas avant : une fiche rédigée trois mois trop tôt décrit un problème qui a changé.

Le raisonnement complet de chacun est dans `catalogue.md`. Ce fichier n'en garde que l'essentiel et le statut.

## Vague 2 — fermer la boucle d'apprentissage

**T06 — Journal auto-alimenté, zéro saisie** · 3–5 j · valeur 5 · dépend de T04, T05
Les trades viennent de TimescaleDB, le contexte du ticket pré-trade, les images des captures. L'humain n'ajoute rien après coup, sauf s'il en a envie. À construire : modèle de données du journal (schéma inspiré de TradeNote, GPL-3.0 — sans contrainte en usage personnel non distribué), réconciliation trade ↔ ticket ↔ captures, vues calendrier P&L / equity / expectancy / profit factor. Ventilations : setup, session, heure d'entrée, jour de la semaine, **niveau de confiance** — cette dernière apprend le plus vite.

**T07 — Tracker d'erreurs et taux de conformité** · 1–2 j · valeur 5 · dépend de T06
Taxonomie **fermée** : entrée anticipée, stop déplacé, taille hors politique, revenge trade, trade hors plan, sortie prématurée, absence de ticket. Fermée, sinon elle dérive. La plupart sont **détectables automatiquement** (taille > politique, stop modifié après entrée, trade sans ticket, trade hors fenêtre). Sortie : une courbe unique, le taux de conformité hebdomadaire, affiché en haut du cockpit à la place du P&L.

**T15 — Serveur MCP « mon trading »** · 1–2 j · valeur 4 · dépend de T06
Serveur MCP **en lecture seule** exposant trades, tickets, erreurs, statistiques, bougies. Permet de poser les questions en langage naturel sans construire une interface par question. Remplace 80 % de ce que ferait T19 pour 5 % de l'effort. Référence de protocole : `ariadng/metatrader-mcp-server` (MIT) — **sans en brancher la partie exécution** (ADR 0005).

**T08 — Revue hebdomadaire générée** · 1–2 j · valeur 4 · dépend de T06
Générée le vendredi soir : statistiques, taux de conformité, les trois pires trades avec leur ticket en regard du résultat, les trois erreurs les plus fréquentes. Un document qui se lit une fois et se garde, pas un tableau de bord.

## Vague 3 — poste de travail complet

**T09 — Checklist de pré-vol exécutable** · 1–2 j · valeur 4 · dépend de T03
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
