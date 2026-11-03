# ADR 0033 — Sous `HALTED`, les fermetures et les annulations passent ; tout le reste reste refusé

Date : 2026-11-02. Statut : **accepté** — décision d'Exhorte du 2026-11-02 (question de l'ADR 0032 : « un arrêt `HALTED` doit-il laisser passer les fermetures et les annulations ou tout refuser
comme aujourd'hui ? » — réponse : « Laisser passer »). **Amende l'ADR 0025** (« ce que cet ADR ne fait pas » : un système arrêté refusait toute commande, fermetures comprises) et la règle de
l'agent « le halt refuse toute commande ». **Ne lève aucun verrou d'entrée** ; le mode de l'agent reste une constante compilée à `OBSERVE`.

## Contexte

Un arrêt (`HALTED`, ou le kill switch local de l'agent) refusait *toute* commande. Un compte arrêté avec une position ouverte ne pouvait donc pas être fermé par le cœur : seul le stop, déjà chez le
courtier, la protégeait. Or un arrêt existe pour **cesser de prendre du risque** ; fermer ou annuler n'en prend pas. Trois verrous le faisaient pourtant, chacun à son niveau : la validation du cœur
(`HALTED`), le routage (`HALTED` rangé dans la route « enregistré seulement » : même acceptée, une commande n'était jamais envoyée) et l'arrêt local de l'agent (`IsHalted()` dans la chaîne d'admission).
Les trois doivent changer ensemble : en lever un seul laisserait l'ordre de fermeture mourir plus loin.

## Décision

1. **Une sortie** est une commande qui ne fait que réduire l'exposition : `CLOSE`, `PARTIAL_CLOSE`, `CANCEL` (`CommandKind.reduces_risk_only`). Un `MODIFY` n'en est pas une, même s'il resserre un stop :
   l'utilisateur a dit « fermetures et annulations ».
2. **Cœur — validation.** `HALTED` refuse toute commande **sauf une sortie émise par un geste humain** (`automatic = False`, c'est-à-dire `POST /api/execution/commands`). Une sortie *automatique*
   (Guardian, Position Manager, stratégie) reste refusée pendant un arrêt : l'arrêt arrête l'automatisme, et il reste inchangé qu'ils n'agissent pas d'eux-mêmes dans ce mode (ADR 0023, 0025).
3. **Cœur — route.** Une sortie humaine acceptée pendant l'arrêt part vers l'agent comme une sortie humaine en `CONFIRM` : le geste est la confirmation (`ExecutionService._route_for`). Sous `OFF` et
   `OBSERVE` rien ne change (enregistré seulement) ; l'interrupteur « Disable Trading » du compte continue de tout refuser.
4. **Cœur — arrêt local de l'agent.** `AgentStatus.command_refusal(exit_only=True)` ne cite plus le kill switch local ; le refus pour identité (`mismatch`, `no_account`) reste pour toute commande.
5. **Agent 1.13.** `AdmitCommand` et `ExecuteOrder` ne refusent plus pour `IsHalted()` une commande dont la nature est une sortie (`TradeCommandReducesRiskOnly`). Restent **inchangés** : la mort-subite
   (toute commande), l'identité, le compte, la péremption, la liste blanche, `InpClosableLogins` (fermer et annuler exigent encore un compte « closable »), le `OrderCheck`, l'idempotence et la ligne `UNKNOWN`
   avant `OrderSend`, le mode `OBSERVE` compilé. Le halt ne se lève toujours **que par un humain, sur le graphique** ; le cœur peut le poser, jamais le lever.
6. **Ce qui reste refusé sous arrêt** : toute ouverture (marché ou `LIMIT`), tout `MODIFY`, toute commande automatique.

## Ce que cet ADR ne fait pas

- Il ne fait pas **agir** le Guardian ni le Position Manager pendant un arrêt (ils s'en abstiennent, ADR 0023 et 0025). Si tu veux qu'un arrêt déclenche une fermeture automatique, c'est un autre ADR.
- Il n'envoie aucun ordre et ne change aucun mode : l'agent compilé reste `OBSERVE` (il répond `SIMULATED`), donc rien de nouveau n'atteint un courtier tant que tu n'as pas relu, changé la constante et recompilé.

## Conséquences

- Tests : validation (une sortie humaine passe sous arrêt, une sortie automatique, un `MODIFY` et une ouverture non), service (route et envoi, arrêt du système et arrêt local de l'agent), architecture de
  l'agent (le halt ne bloque que ce qui n'est pas une sortie, aux deux endroits ; la mort-subite et l'identité s'appliquent toujours).
- Documentation : `protocol.md` (`HALTED`), README de l'agent (« Local halt »), fiche EA-05, état, HANDOFF.
