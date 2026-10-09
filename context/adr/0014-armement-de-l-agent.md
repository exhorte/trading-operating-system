# ADR 0014 — Armement de l'agent depuis l'application

> **Amendement du 2026-10-09 (ADR 0016).** « Gateway », « hub » et « backend » se lisent « cœur Python » : le bail est renouvelé par le cœur, l'armement passe par `POST /api/autonomy/arm` (gardé par le jeton et l'Origin), un cœur redémarré revient désarmé. Les propriétés décrites sont inchangées.

Date : 2026-09-26 (rédaction). Statut : **accepté** — accord nommé de
l'utilisateur le 2026-09-25 : « J'approuve l'ADR 0014, volet armement », sur
la conception de l'étude (`02_Plan_Projet/etude-connexion-pilotage-agent-2026-09-25.md`,
§1.3, §3 I4, décision D3) ; rédigé avec l'amendement de l'ADR 0015 (accepté
le 2026-09-26) : bail renouvelé **côté serveur**, plafond qui peut atteindre
AUTO. Amende l'ADR 0010 (échelle de mode) et la règle de `.claude/CLAUDE.md`
« pas de mode rendu configurable ». Texte soumis à la relecture de
l'utilisateur.

## Contexte

Aujourd'hui le mode de l'agent est une constante de compilation,
`g_mode = MODE_OBSERVE` : c'est la barrière physique de l'ADR 0010, et
aucune consigne ne la déplace. Pour qu'un ordre puisse partir un jour (I6
CONFIRM, I8 autonomie), il faut un moyen de passer au-dessus d'OBSERVE qui
garde les propriétés de cette barrière : délibéré, borné, révocable à tout
instant, et qui retombe tout seul quand quelque chose manque.

Rien ne permet d'attacher un EA ni d'activer Algo Trading par code (les
quatre permissions de MT5 sont indépendantes et manuelles, I1). L'agent
reste donc attaché en permanence ; ce qui change, c'est son mode effectif.

## Décision

**Le mode effectif de l'agent s'élève par armement, jamais au-dessus d'un
plafond compilé, et seulement sous bail.**

- **Plafond compilé.** Chaque build fixe son plafond par une constante :
  `TradingOsAgent.mq5` plafonne à OBSERVE ; un build CONFIRM (I6) puis AUTO
  (I8, ADR 0015) le définiront et incluront le même cœur. L'agent publie
  plafond et mode effectif dans chaque hello et chaque heartbeat (fait en I1).
- **Armer.** `control.arm` élève le mode effectif jusqu'au plafond, jamais
  au-dessus. N'importe quel message peut l'abaisser (`control.disarm`,
  `control.halt`). Le mode armé ne vit qu'en mémoire : il retombe à OBSERVE
  à `OnInit`, `OnDeinit`, à la déconnexion, au halt, sur `REASON_ACCOUNT`
  et à l'expiration du bail. L'agent acquitte chaque `control.arm`.
- **Bail côté serveur** (ADR 0015). Le Gateway renouvelle le bail toutes les
  10 s tant que la session est armée dans son registre et que le pré-vol
  tient ; l'agent se désarme après 30 s sans renouvellement — c'est
  l'**homme mort** (le `control.ping` d'I1 en est le support). Fermer le
  navigateur ne désarme rien ; arrêter le backend désarme en 30 s au plus.
- **Registre `execution_sessions`**, en ajout seul : qui a armé, quand,
  jusqu'où, qui a désarmé et pourquoi. Le système démarre toujours désarmé ;
  un Gateway redémarré revient désarmé.
- **Seul le cockpit arme**, par une méthode du hub gardée par le jeton et
  l'Origin (I0), après un **pré-vol calculé côté serveur** : les quatre
  permissions, **aucun EA étranger attaché**, une seule instance de l'agent,
  des ticks de moins de 10 s, le login de l'agent égal à celui du terminal
  et présent dans l'allowlist des logins tradables, un build connu, la base
  disponible, aucun verrou actif, aucun `UNKNOWN` en attente, identité `ok`,
  halt levé. Chaque point rouge dit le clic MT5 à faire.
- **L'arrêt d'urgence** devient verrou + halt de l'agent. Il ne ferme
  jamais une position (la fermeture globale est EA-08, I5).

## Conséquences

- `.claude/CLAUDE.md` : la règle « pas de mode rendu configurable » devient
  « mode effectif élevable depuis le cockpit par `control.arm`, jamais
  au-dessus du plafond compilé, seulement sous bail renouvelé par le
  serveur ; tout message peut l'abaisser ; OBSERVE à chaque démarrage ».
  Réécrit quand le code d'I4 arrive, pas avant.
- Dans l'agent, la constante devient le **plafond** et `g_mode` le mode
  effectif, borné par lui. Avec un plafond OBSERVE (I4), armer ne permet
  toujours aucun ordre : la garde de `ExecuteOrder` ne passe qu'en CONFIRM.
- Tests : démarrage désarmé ; `arm` au-dessus du plafond refusé ; expiration
  du bail ; Gateway redémarré désarmé ; pré-vol refusé point par point.
- Essais réels faits par l'utilisateur : armer et désarmer (résultats
  SIMULATED), arrêter le backend (désarmement en 30 s), poser le halt
  backend éteint. Claude n'arme jamais lui-même.
