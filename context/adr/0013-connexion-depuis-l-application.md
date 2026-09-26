# ADR 0013 — Connexion au compte depuis l'application

Date : 2026-09-26 (rédaction). Statut : **accepté** — accord nommé de
l'utilisateur le 2026-09-25 : « J'approuve l'ADR 0013 (connexion depuis
l'application) », sur la conception de l'étude
(`02_Plan_Projet/etude-connexion-pilotage-agent-2026-09-25.md`, §1.1, §3 I3,
décisions D1 et D2). Amende l'ADR 0003 (« aucun identifiant n'est jamais
partagé avec le projet ») et la règle de `.claude/CLAUDE.md` sur les
identifiants de compte. Texte soumis à la relecture de l'utilisateur.

## Contexte

Jusqu'ici, le trader se connecte à son compte dans MT5, et le Trading OS
observe le terminal déjà authentifié : aucun identifiant n'est demandé,
stocké ni partagé (ADR 0003 ; T12, décisions 4 et 12). Le 2026-09-25,
l'utilisateur demande de choisir le compte depuis l'application — serveur,
login, mot de passe — et de passer d'un compte à l'autre sans quitter le
cockpit.

`mt5.login(login, password=, server=)` le permet depuis un processus
Windows local. Sans mot de passe, MT5 prend celui qu'il a enregistré ; sans
serveur, il prend le dernier utilisé. Le paquet MetaTrader5 n'existe que sous
Windows : le Gateway (conteneur Linux) ne peut pas le faire, et l'observateur
doit rester en lecture seule (ADR 0010).

## Décision

**La connexion passe par un superviseur local, sur l'hôte Windows, et le mot
de passe ne fait que traverser.**

- Un nouveau processus, `tools/mt5-supervisor/` (Python), écoute sur
  `127.0.0.1` seulement. Endpoints : `GET /status`, `GET /servers`,
  `POST /login {login, server, password?}`. `server` est obligatoire, même
  pour une bascule sans mot de passe.
- Chaque endpoint exige un jeton (comparé en temps constant), un Host
  `127.0.0.1:<port>` ou `localhost:<port>`, une Origin autorisée (`null`
  refusé) et un en-tête personnalisé qui force un preflight. Jamais
  `Access-Control-Allow-Origin: *`, aucun changement d'état sur un GET.
  Même garde pour « Attacher l'agent » et la bascule rapide.
- **Le mot de passe va du navigateur au superviseur, directement** : jamais
  par Next, SignalR ou le Gateway. Il n'est jamais stocké, journalisé,
  persisté, renvoyé ni mis dans une URL. Le champ n'a pas d'attribut `name`,
  n'est pas contrôlé par React, est lu par ref et vidé dans un `finally` ;
  envoi `fetch` avec `cache: 'no-store'`, `credentials: 'omit'`,
  `referrerPolicy: 'no-referrer'`. Côté serveur : type secret, corps limité
  à 4 Ko, erreurs sans écho de la saisie, exceptions de `mt5.login` relancées
  sans arguments, pas de mode debug, pas de journal des requêtes, pas de
  faulthandler.
- **Mot de passe facultatif** (D1) : la bascule entre comptes déjà connus de
  MT5 passe sans lui. Le formulaire propose le mot de passe investisseur
  (lecture seule) : un compte ouvert ainsi est marqué observation seule, et
  l'armement y est refusé.
- **Un terminal, des comptes successifs** (D2). La bascule est refusée si une
  session est armée, si des positions sont ouvertes ou si des ordres sont en
  attente sur le compte courant. Déroulé : arrêt de l'observateur, login,
  lecture du compte, relance de l'observateur sur le bon symbole, attente du
  hello de l'observateur **et** de celui de l'agent sur le nouveau login.
  Les positions déjà présentes sur le nouveau compte sont montrées comme
  existantes, à accuser avant tout armement.
- **Identifiants persistés** : login, serveur, société. Jamais le nom du
  titulaire (I2), jamais un mot de passe. Chaque demande, acceptée ou
  refusée, est tracée sans mot de passe (`supervisor_actions`).

## Modèle de menace

Défend contre le réseau local, les conteneurs, les pages web d'autres
onglets et le DNS rebinding (surface locale d'I0,
`context/security/security_principles.md`). **Ne défend pas** contre un
logiciel malveillant qui tourne sous le compte Windows du trader : il lit
`.env`, la mémoire des processus et les fichiers de MT5. Limites assumées :
une chaîne Python ne s'efface pas de façon fiable ; un dump de plantage peut
contenir le mot de passe ; MT5 peut mémoriser un mot de passe transmis selon
ses propres réglages.

## Conséquences

- `.claude/CLAUDE.md` : « Aucun identifiant de compte n'est jamais demandé,
  stocké ou partagé » devient « Aucun mot de passe de compte n'est stocké,
  journalisé ou transmis par le Trading OS ; MT5 peut le conserver dans son
  propre `accounts.dat` selon ses réglages ». Réécrit quand le code d'I3
  arrive, pas avant.
- Fiche T13 (superviseur et formulaire) écrite avant le code.
- Vérification par **sentinelles** : un faux mot de passe, y compris dans
  des corps malformés et avec JavaScript désactivé, doit être absent des
  réponses, des journaux (Next, superviseur, conteneurs, `Logs\` et
  `MQL5\Logs\` de MT5, `%TEMP%`), de `Win32_Process` et des tables. Test
  négatif depuis un conteneur : 403.
- **Claude ne voit, ne saisit, ne lit ni ne teste jamais le vrai mot de
  passe** : pendant l'essai réel, l'utilisateur se connecte dans son propre
  navigateur, le superviseur tourne dans sa propre fenêtre.
- Hors du chemin critique de l'autonomie (ADR 0015) : l'ordre d'I3 face à
  I4 à I8 reste un choix de l'utilisateur.
