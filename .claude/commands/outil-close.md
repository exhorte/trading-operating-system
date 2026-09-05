---
description: Clore un outil livré (remplace /phase-close)
---

Clore l'outil **$ARGUMENTS**.

1. Exécuter toutes les gates de `context/governance/quality_gates.md`. Ne rien clore avec une gate rouge ou ignorée.
2. Vérifier le **critère de réussite** écrit dans la fiche. S'il n'est pas atteint, la fiche reste `en cours` — le dire franchement plutôt que de clore.
3. Mettre à jour la fiche `context/product/tools/$ARGUMENTS-*.md` :
   - statut → `livré` ;
   - journal → les décisions réellement prises, les alternatives écartées et pourquoi, les surprises rencontrées.
4. Mettre à jour `context/product/tools/README.md` (tableau des statuts).
5. Mettre à jour `context/project/state.md` **seulement** si un fait qu'il énonce est devenu faux, ou si la vague se termine.
6. Si une décision d'architecture a été prise en route, écrire un ADR dans `context/adr/` — ne pas l'enterrer dans le journal de la fiche.
7. Proposer un message de commit qui nomme l'outil et ce qu'il change réellement.

Pas de changelog à mettre à jour : l'historique git et le statut des fiches en tiennent lieu.
