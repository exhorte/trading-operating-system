---
description: Démarrer un outil de la roadmap (remplace /phase-start)
---

Démarrer l'outil **$ARGUMENTS** (identifiant `Tnn`).

Séquence, dans l'ordre, sans sauter d'étape :

1. Lire `context/project/charter.md`, `context/project/state.md` et `context/project/roadmap.md`.
2. Lire les ADR de `context/adr/` — ils sont courts, les lire tous.
3. Ouvrir la fiche `context/product/tools/$ARGUMENTS-*.md`.
   - Si elle n'existe pas, la rédiger à partir de `context/product/backlog.md` en suivant le format des fiches T01–T05, puis la soumettre à l'utilisateur avant d'écrire du code.
   - Si elle existe, vérifier que ses dépendances sont au statut `livré`.
4. **Lire le code d'ancrage nommé dans la fiche.** Ne rien supposer : dans ce dépôt le code existant est presque toujours plus complet qu'attendu, et le réécrire est le piège classique.
5. Produire une analyse d'impact courte : ce qui est touché, ce qui ne l'est pas, ce qui casse.
6. Proposer un découpage en incréments dont chacun laisse les gates vertes.
7. **Attendre la validation de l'utilisateur** avant d'implémenter, sauf s'il demande explicitement d'exécuter directement.

Rappels non négociables : le Risk Engine est le point de contrôle unique (ADR 0007) ; l'IA reste en lecture (ADR 0005) ; aucun module ne produit d'opinion de marché (ADR 0001).
