# Journal de session

Append-only, la plus récente en haut. Une entrée par session, courte — le
détail vit dans la fiche de chaque outil (`context/product/tools/*.md`) et
dans `git log`. Voir ADR 0008 pour ce que ce fichier est et n'est pas.

---

## 2026-09-05

Outils : T01 (livré), T04 (livré), T02a (livré, T02b reste ouvert).

Ce qui a changé :
- **T01** — panneau de sizing permanent dans le cockpit, appelle
  `evaluateSignalRisk` sans le modifier. Trois défauts corrigés en revue
  avant tout commit : budget de perte quotidien calculé sur le solde
  restant (pas le total), `null` affiché comme « — » jamais « 0 % », R
  cible qui refuse un TP du mauvais côté de l'entrée.
- **T04** — ticket pré-trade en 4 boutons, publié via `PublishEvent`
  (pas de nouvel endpoint). Confirmation par écho (pas par soumission) après
  revue des trois refus silencieux de `PublishEvent` ; badge de persistance
  ajouté au cockpit pour le cas qu'aucun écho ne couvre (écriture perdue
  après diffusion).
- **T02a** — ancre de journée (minuit serveur, offset MT5 résolu
  dynamiquement), `tradesToday` réel (comptage de positions, pas de P&L),
  état verrouillé stocké dans un ledger (jamais dérivé), kill switch réel
  (verrouillage + bandeau + accusé de réception journalisé, aucun
  `close_all` simulé). Plan initial (7 incréments) coupé en T02a/T02b en
  revue : un seul verrou (pertes consécutives) a besoin de l'historique des
  deals MT5, les quatre autres non.
- **Gouvernance** — ADR 0008 : réintroduction bornée d'un journal de
  session (ce fichier), `state.md` redevient un instantané.

Ouvert : T02b (deal history MT5, verrou de pertes consécutives — plan détaillé
dans `context/product/tools/T02-lockout.md`). Rien n'est commité pour T04/T02a
au moment de cette entrée.
