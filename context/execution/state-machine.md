# Machine à états d'une commande d'exécution

Statut : accepté (EA-03), **réécrit le 2026-10-09** pour le cœur Python (ADR 0016). L'autorité est le code : `python/trading_os/domain/execution/state.py` (la table de transitions, `next_state()`), les états dans `domain/execution/commands.py`, les tests dans `python/tests/unit/domain/`. Ce document est la narration.

## Les douze états

```
PENDING ──SENT──▶ SENT ──ACK_ACCEPTED──▶ ACKNOWLEDGED ──REPORT_EXECUTED──▶ EXECUTED ──POSITION_CONFIRMED──▶ RECONCILED
   │                │                         │
   │                │                         └──LINK_LOST──▶ UNKNOWN ──RECONCILIATION_STARTED──▶ RECONCILING ──RECONCILED──▶ RECONCILED
   │                └──LINK_LOST──────────────────────────────▲                       └─RECONCILIATION_PENDING─┘ (reste, ne devine jamais)
   │
   ├──SIMULATED_LOCALLY──▶ SIMULATED      (OBSERVE / PAPER : rien ne quitte le processus)
   ├──SEND_FAILED────────▶ FAILED         (l'agent est injoignable : rien n'a été envoyé)
   ├──EXPIRED / CANCEL_REQUESTED ──▶ EXPIRED / CANCELLED
SENT ──ACK_REJECTED──▶ REJECTED · ──ACK_EXPIRED──▶ EXPIRED · ──REPORT_SIMULATED──▶ SIMULATED · ──REPORT_FAILED──▶ FAILED
ACKNOWLEDGED ──REPORT_SIMULATED──▶ SIMULATED · ──REPORT_FAILED──▶ FAILED
EXECUTED ──RECONCILIATION_STARTED──▶ RECONCILING
```

`RECONCILED`, `FAILED`, `REJECTED`, `EXPIRED`, `CANCELLED` et `SIMULATED` sont **terminaux** : aucune transition n'en repart. `UNKNOWN` n'est **pas** terminal : c'est un état de première classe, qui n'a qu'une sortie légale — la réconciliation (`UNKNOWN → RECONCILING → RECONCILED`). Il n'existe aucune ligne de la table pour `UNKNOWN → SENT` ni `UNKNOWN → EXECUTED` : on ne peut pas l'ajouter par accident, et un déplacement illégal lève `IllegalTransition`. **UNKNOWN ne se rejoue jamais** (ADR 0010).

Le diagramme à treize états de l'audit d'origine est ramené à ceux-ci : `RISK_APPROVED` disparaît (la décision de risque précède la commande) ; `RECEIVED`, `VALIDATING`, `EXECUTING` sont internes à l'agent, non observables, et fusionnés dans `ACKNOWLEDGED`. **À partir de `ACKNOWLEDGED` il n'existe ni annulation ni expiration** : l'ordre est peut-être déjà au courtier ; annuler côté OS ne changerait rien là-bas et créerait une divergence non détectée. Seule la vérité du courtier (rapport, ou perte de lien) fait avancer la commande.

## Ce qui est persisté, et ce qui se passe si le processus meurt

| État quitté | Événement | Persisté | Si le cœur (ou l'agent) meurt juste après |
|---|---|---|---|
| — → `PENDING` | commande créée après une décision de risque approuvée | la commande entière, **avant tout envoi** (même transaction que le changement d'état) | rien n'a été envoyé : sans danger ; au redémarrage (`recover()`) elle passe `EXPIRED`, jamais renvoyée en silence |
| `PENDING` → `SENT` | écriture sur le socket de l'agent | l'heure d'envoi | la commande a peut-être atteint l'agent sans que le cœur le sache : c'est exactement la fenêtre qui produit `UNKNOWN`, pas un rejeu |
| `SENT` → `ACKNOWLEDGED` / `REJECTED` / `EXPIRED` | `execution.ack` | l'accusé et son motif typé | un `REJECTED` n'a rien exécuté ; `ACKNOWLEDGED` est confirmé reçu |
| `SENT`, `ACKNOWLEDGED` → `UNKNOWN` | perte du lien, silence, retour ambigu (`10011`, `10012`, `10031`) | le fait qu'un envoi a eu lieu sans confirmation | **l'entrée `UNKNOWN` de l'ADR 0010** : aucun rejeu, on attend une reconnexion puis la réconciliation |
| `ACKNOWLEDGED` → `EXECUTED` / `SIMULATED` / `FAILED` | `execution.report` | le rapport complet (ordre, position, prix, volume, retcode) | le rapport est arrivé : sûr de continuer ; un rapport rejoué après reconnexion (`replayed`) est reconnu par son identifiant (`commandId + statut + heure`) |
| `UNKNOWN` → `RECONCILING` → `RECONCILED` | la réconciliation interroge l'historique MT5 (magic + trace du `commandId`) | le nombre de tentatives, la preuve (identifiant de position ou de deal) | reste `RECONCILING` ; une tentative sans conclusion ne devine jamais et remonte à l'humain au-delà du seuil |
| `EXECUTED` → `RECONCILED` | le rapprochement confirme que MT5 détient bien ce que le rapport dit | la confirmation | sans danger : l'exécution est acquise, seule la confirmation manque |

Un message tardif pour une commande déjà terminale (un accusé ou un rapport après `EXPIRED`) est journalisé comme une anomalie de réconciliation, jamais appliqué comme une transition. Après un redémarrage, les états **en doute** — `SENT`, `ACKNOWLEDGED`, `UNKNOWN`, `RECONCILING` — ne sont jamais renvoyés : ils vont à la réconciliation. Une position ou un ordre qui porte la trace d'une commande dans un état « rien n'a été placé » (`PENDING`, `FAILED`, `REJECTED`, `EXPIRED`, `CANCELLED`, `SIMULATED`) contredit le registre : c'est la découverte la plus grave que la réconciliation puisse faire, et le superviseur la traite en `HALT`.

## Ce qui reste ouvert

- **Les délais** : un balayage (`sweep()`) tourne toutes les quelques secondes — `PENDING` périmée → `EXPIRED` ; `SENT` sans accusé au bout de `ACK_TIMEOUT` (15 s) → `UNKNOWN` ; `ACKNOWLEDGED` sans rapport au bout de `REPORT_TIMEOUT` (90 s) → `UNKNOWN` (`services/execution.py`). Au démarrage, `recover()` fait passer `PENDING` en `EXPIRED` et `SENT`/`ACKNOWLEDGED` en `UNKNOWN`. Les valeurs sont à ajuster avec un vrai terminal.
- Les commandes `MODIFY`, `CLOSE`, `PARTIAL_CLOSE` et `CANCEL` ont leurs états mais l'agent n'en annonce pas encore la capacité : elles sont refusées à la soumission (`AGENT_CAPABILITY_MISSING`). Les ouvrir est un élargissement du chemin d'exécution qui demande son propre accord (EA-08).
