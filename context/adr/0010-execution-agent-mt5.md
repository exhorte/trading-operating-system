# ADR 0010 — Le Trading OS exécute, l'EA est un agent

Date : 2026-09-11. Statut : accepté. Amende l'ADR 0001 : la clause « aucun appel
de trade n'existe dans ce dépôt » ne tient plus. Le reste de l'ADR 0001 — le
process est le produit, aucun module ne dit quoi trader — tient intégralement.

## Contexte

Depuis le pivot du 2026-09-04, le poste de travail mesure et empêche. Il
dimensionne (T01), verrouille (T02), refuse pendant les publications (T03),
enregistre l'intention (T04) et capture le résultat (T05). Il ne propose rien et
n'exécute rien. Le chemin `RiskDecision → Command → ACK → Report` existe et son
idempotence a été validée en live, mais en mode `observe` / SIMULATED : aucun
appel de trade n'existe nulle part dans le dépôt.

Une proposition d'évolution est arrivée le 2026-09-11
(`01_Recherche/EA_implementation.md`) : ajouter un Expert Advisor MT5 et deux
profils de compte séparés, FTMO et réel. L'interview qui a suivi a tranché le
cadrage — priorité devant la clôture de la Vague 1, construction jusqu'au mode
CONFIRM uniquement, stratégie unique synthétisée depuis trois systèmes réellement
tradés (fiche S01).

Le risque de cette évolution n'est pas technique, il est doctrinal : un EA qui
exécute est à un pas d'un EA qui décide, et c'est exactement ce que le projet a
abandonné en juillet.

## Décision

**Le Trading OS peut émettre des ordres d'exécution réels. L'agent MT5 n'est
qu'un exécutant.**

Répartition stricte des rôles :

| Trading OS | Agent MT5 (EA) |
|---|---|
| Contexte de marché, détection de setup, décision | Connexion, heartbeat |
| Risk Engine, politique de risque, profils de compte | Validation locale de dernière barrière |
| Journal, audit, réconciliation de référence | Exécution, accusé de réception |
| Kill switch global | Kill switch local, télémétrie, réconciliation |

L'EA ne contient **aucune** stratégie, aucun signal, aucune analyse, aucun
paramètre de décision. Il ne sait pas pourquoi il exécute. S'il se retrouve isolé
du backend, il ne prend aucune initiative autre que protéger le compte.

**Aucun mode AUTO dans ce chantier.** La progression s'arrête à CONFIRM :
OBSERVE, puis PAPER, puis CONFIRM — validation humaine explicite de chaque ordre.
Le passage à AUTO exigera un ADR qui supersède celui-ci ; ce n'est pas un
paramètre de configuration.

## Conséquences

- `README.md` et `context/project/charter.md` doivent être corrigés : la phrase
  « aucun appel de trade n'existe dans ce dépôt » devient fausse le jour où
  EA-02 est livré. Ne pas la laisser traîner.
- **MQL5 entre dans le dépôt** comme nouveau langage, sous
  `tools/mt5-execution-agent/`. Le dépôt en comptera quatre : TypeScript, C#,
  Python, MQL5. L'observer Python reste en lecture seule et distinct de l'agent
  d'exécution — deux processus, deux responsabilités, jamais fusionnés.
- **Toute commande porte un `commandId`.** L'idempotence est obligatoire, pas
  optionnelle : une commande rejouée retourne le résultat précédent, elle ne
  produit jamais une seconde position.
- **L'état `UNKNOWN` est de premier ordre.** Si l'EA meurt entre l'envoi au
  broker et l'accusé, le système ne rejoue jamais l'ordre : il passe en
  réconciliation, interroge MT5, et ne conclut qu'ensuite.
- **L'ADR 0007 est inchangé.** Le Risk Engine reste le point de contrôle unique.
  Les garde-fous locaux de l'EA — whitelist de symboles, volume maximum, stop
  obligatoire, spread maximum, positions maximum — sont une dernière barrière,
  jamais une décision. Aucun ordre ne peut atteindre l'EA sans être passé par le
  Risk Engine.
- **L'ADR 0005 est inchangé.** L'IA ne décide toujours pas. Elle classe, résume,
  explique.
- **L'ADR 0002 est inchangé.** Cette décision ouvre un chemin d'exécution, pas
  une recherche d'edge. La stratégie exécutée est la formalisation d'un process
  humain existant (S01), pas un candidat issu d'une optimisation.
- **T02a et T02b deviennent porteurs.** Le kill switch et le lockout cessent
  d'être des aides à la discipline pour devenir de la sécurité d'exécution.
  Aucun passage en CONFIRM avant qu'ils aient tourné contre un vrai terminal
  MT5 — indépendamment de la clôture formelle de la Vague 1, qui reste en
  attente par décision du 2026-09-11.
- **Isolation des comptes.** Un environnement par compte : terminal, instance
  d'EA, magic number, profil de risque. Une commande adressée à un compte et
  reçue par un autre est rejetée (`ACCOUNT_MISMATCH`), jamais exécutée « au
  mieux ».
