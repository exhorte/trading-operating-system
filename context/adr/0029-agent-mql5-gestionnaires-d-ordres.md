# ADR 0029 — Agent MQL5 : gestionnaires `LIMIT`, `MODIFY`, `CLOSE`, `PARTIAL_CLOSE`, `CANCEL` derrière un seul `ExecuteOrder`

Date : 2026-11-01. Statut : **accepté** — consigne explicite d'Exhorte du 2026-11-01 (« Agent MQL5 : oui, implémenter maintenant »,
conception validée : `ExecuteOrder` devient l'unique point d'envoi). **Réalise** la partie MQL5 laissée ouverte par l'ADR 0023 ; **ne lève aucun
verrou** : le mode de l'agent reste une constante compilée à `OBSERVE`, le plafond aussi, et Claude ne déclenche aucun ordre.

## Contexte

Le cœur sait valider et envoyer `LIMIT`, `MODIFY`, `CLOSE`, `PARTIAL_CLOSE` et `CANCEL` (ADR 0023). L'agent 1.11 ne sait recevoir que `execution.order` au
marché : tout le reste est refusé en amont par le cœur (`AGENT_CAPABILITY_MISSING`), donc rien n'est jamais envoyé dans le vide, mais rien ne peut non plus
être géré (stop remis, fin de séance, ordre périmé…). L'agent 1.12 porte les gestionnaires manquants.

## Décision

1. **Un seul `OrderSend`, dans `ExecuteOrder`.** `ExecuteOrder(cmd)` reçoit une `TradeCommand` (structure : nature, identifiant, symbole, sens, type, volume,
   prix, stop, cible, identifiant de position ou d'ordre) ; son premier énoncé est inchangé (`if (g_mode != MODE_CONFIRM) { return; }`). Tous les
   gestionnaires (`HandleOrderCommand`, `HandleModifyCommand`, `HandleCloseCommand`, `HandleCancelCommand`) suivent la même chaîne — idempotence, halt,
   identité, compte, péremption, **validation locale**, accusé — puis, en `CONFIRM` seulement, passent par `ExecuteOrder`. Aucun ne construit ni n'envoie de
   requête de son côté. Le test d'architecture lit désormais **tous** les fichiers MQL5 du dossier : un seul `OrderSend`, un seul fichier.
2. **Construction de la requête séparée de son envoi** (`Include/TradeRequest.mqh`, sans aucun `OrderSend`) : `BuildTradeRequest` traduit une
   `TradeCommand` en `MqlTradeRequest` — `MARKET` = `TRADE_ACTION_DEAL`, `LIMIT` = `TRADE_ACTION_PENDING` (expiration locale bornée), `MODIFY` =
   `TRADE_ACTION_SLTP`, `CLOSE`/`PARTIAL_CLOSE` = `TRADE_ACTION_DEAL` en sens inverse sur la position, `CANCEL` = `TRADE_ACTION_REMOVE`. Un script de
   vérification (`Scripts/TradingOsRequestCheck.mq5`) réutilise ce même fichier pour **`OrderCheck` uniquement** sur une démo : il valide la forme des requêtes
   auprès du serveur sans en envoyer aucune.
3. **Avant l'envoi, `ExecuteOrder` re-valide et pré-vérifie** : mêmes barrières locales que le gestionnaire (appelées une seconde fois, défense en profondeur),
   cible résolue à neuf (position par `POSITION_IDENTIFIER`, jamais par ticket reçu ; ordre par ticket), `OrderCheck` (n'envoie rien) ; un refus est un échec
   *définitif* enregistré, pas un `UNKNOWN`.
4. **Barrières locales conservées, jamais assouplies** : mort-subite (`DEAD_MAN`, sur toute commande), halt local (refuse toute commande, fermetures
   comprises — la question « un système `HALTED` autorise-t-il les sorties seules ? » reste à l'incrément E du plan de reprise), identité, compte, péremption,
   liste blanche de symboles, volume maximal par ordre, nombre maximal de positions (**les ordres en attente comptent désormais** : un ordre `LIMIT` est une
   position en puissance), spread maximal par symbole (échec fermé), stop obligatoire, `InpTradableLogins` (ouvrir, modifier) et `InpClosableLogins`
   (fermer, annuler) — listes vides = aucune.
5. **Nouvelles barrières locales** : le volume doit respecter le minimum, le maximum et le pas du symbole (`VOLUME_INVALID`) ; stop et cible du bon côté du
   prix et au-delà du niveau d'arrêts du courtier (`STOP_INVALID`) ; un `LIMIT` du bon côté du marché (`LIMIT_PRICE_INVALID`) ; un ordre en attente expire
   toujours chez le courtier (`InpPendingMaxMinutes`, 60 par défaut, borné à 1–1440 ; jamais illimité — un symbole qui n'accepte pas l'expiration est refusé,
   `ORDER_TYPE_UNSUPPORTED`) ; un `MODIFY` n'éloigne jamais un stop du prix et ne retire jamais un stop (`STOP_LOOSENED`, `STOP_MISSING`) ; une clôture partielle
   est strictement inférieure au volume ouvert et laisse un reste viable (`VOLUME_INVALID`) ; l'agent ne touche **que ses propres** positions et ordres
   (numéro magique, `TARGET_NOT_OURS`) et n'agit pas sur une cible introuvable (`POSITION_NOT_FOUND`, `ORDER_NOT_FOUND`).
6. **Idempotence et `UNKNOWN`.** Inchangé en principe : la ligne `UNKNOWN` est écrite sur disque **avant** `OrderSend` (échec d'écriture ⇒ rien n'est
   envoyé, `STORE_UNWRITABLE`) ; un `commandId` revu renvoie son résultat d'origine (`DUPLICATE`), jamais une seconde requête. La ligne `UNKNOWN` porte
   maintenant la nature de la commande, la cible et les niveaux voulus (colonnes ajoutées en fin de ligne : un ancien fichier se lit sans changement). La
   réconciliation de l'agent ne rejoue **jamais** : elle observe — ordre en attente actif ou historique (`LIMIT`), transaction de sortie portant la trace
   (`CLOSE`), stop et cible actuels (`MODIFY`), historique de l'ordre (`CANCEL`). Introuvable ⇒ `not_found`, la ligne reste `UNKNOWN` et sera cherchée de
   nouveau ; **jamais** « refusé » par déduction, sauf un ordre vu rempli avant son annulation.
7. **Rapports.** `FILLED`/`PARTIALLY_FILLED` (ordre au marché), `SUBMITTED` (ordre en attente posé chez le courtier, rien n'est rempli), `MODIFIED`,
   `CLOSED`, `CANCELLED` (nouveau), `FAILED`/`REJECTED`, `SIMULATED` (agent `OBSERVE`). Côté cœur, `SUBMITTED`/`MODIFIED`/`CLOSED`/`CANCELLED` font
   avancer la commande vers `EXECUTED` comme un remplissage (`services/execution.py`) ; la réconciliation n'attend pas de position pour un ordre `LIMIT`
   tant qu'aucune n'est vue (`services/reconciliation.py`). Le champ `side` d'un rapport sans sens est `null`, jamais `""`.
8. **Annonce.** `agent.hello` : `orderTypes: ["market","limit"]`, capacités `limit`, `modify`, `close`, `cancel` en plus de `ping`, `halt`, `dead_man`.
   Version `1.12`.

## Ce que cet ADR ne fait pas

- Il **ne compile pas** l'agent dans le dossier du dépôt (`TradingOsAgent.ex5` y est suivi) et **n'élève aucun mode** : `CONFIRM` reste inatteignable tant que
  l'utilisateur n'a pas relu ce fichier, changé la constante et recompilé lui-même. L'intégralité de `ExecuteOrder` est du code mort dans ce build.
- Il n'envoie aucun ordre, même sur la démo. Ce qui se vérifie sans en envoyer : compilation (copie), tests de structure (Python), parcours `OBSERVE` de
  bout en bout (`SIMULATED`), script `OrderCheck`. Ce qui **reste à vérifier sur un terminal** est listé dans `tools/mt5-execution-agent/README.md`
  (« Reste à vérifier sur un terminal ») : le comportement réel de `OrderSend` pour chaque nature, l'expiration chez le courtier, la clôture sur compte FIFO,
  l'effet du gel (`freeze level`).
- Il ne tranche pas le sort de `HALTED` pour les sorties (incrément E), ni ne change les valeurs de l'`ExitPlan`.

## Conséquences

- `tests/architecture/test_execution_agent.py` : un seul `OrderSend` dans tout le dossier, première instruction de `ExecuteOrder` inchangée, chaque
  gestionnaire passe par `ExecuteOrder` et par la validation, aucune requête construite hors de `BuildTradeRequest`, capacités annoncées, stop jamais
  élargi, `side` jamais vide dans un rapport.
- Cœur : `ExecutionReport.status` accepte `CANCELLED` ; `on_report` et `_settle_in_doubt` traitent les cinq statuts de réussite ; `_expected` n'attend pas de
  position pour un `LIMIT` sans position vue.
- Documentation : `protocol.md` (codes de refus et rapports), `EA-05-agent-mql5.md`, `README.md` de l'agent, `state.md`, `session-log.md`.
