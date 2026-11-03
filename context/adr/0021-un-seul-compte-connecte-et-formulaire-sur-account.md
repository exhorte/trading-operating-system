# ADR 0021 — Un seul compte connecté à la fois ; le formulaire de connexion là où on le cherche

Date : 2026-11-01. Statut : **accepté** — décision de l'utilisateur en session le 2026-11-01 : « pourquoi les données ne
s'affichent pas et pourquoi j'ai pas de formulaire pour entrer mes identifiants du courtier et me connecter à un compte, et le
formulaire de connexion doit mentionner un choix de compte à ajouter entre Exness et FTMO, et uniquement un compte doit être
connecté à la fois ». **Supersède l'ADR 0020 pour l'emplacement du formulaire** (il était en bas de Settings) ; **amende l'ADR 0013**
(D2, « un terminal, des comptes successifs » : devient une règle du cœur, pas une conséquence du nombre de terminaux).

## Contexte

Aucun compte n'était enregistré, donc chaque écran n'affichait que des blocs gris vides : rien n'expliquait pourquoi, ni ne disait
quoi faire. Le formulaire existait, mais tout en bas de Settings. Et le cœur acceptait plusieurs comptes connectés à la fois (un
terminal chacun), ce que l'utilisateur ne veut pas.

## Décision

1. **Un seul compte connecté à la fois, imposé par le cœur** (point de contrôle unique) : `connect` et `discover` refusent tant qu'un
   autre compte est connecté (`another_account_connected`, avec l'id et le nom du compte à détacher). Le compte qui se connecte
   devient **le** compte actif. Détacher reste refusé tant qu'il pourrait cacher un risque (position ouverte, ordre en attente,
   commande en doute) : on ne prend donc pas un autre compte pendant que le premier en porte.
2. **Aucun compte connecté → l'écran propose d'en connecter un**, au lieu de squelettes muets : le formulaire s'affiche à la place
   de tout écran qui lit un compte (tableau de bord, Positions, Risque, Journal, Analyse, Pré-vol, Contexte, Setups, Agents),
   avec les comptes déjà enregistrés et leur bouton « Rattacher ». Account et Settings restent ouverts. Le garde n'agit que
   lorsque le cœur a répondu (premier instantané reçu) : jamais « aucun compte » par erreur pendant le chargement.
3. **Le formulaire vit sur Account** (ancre `#connecter`, entrée « Connecter un compte » dans le menu du compte), plus dans
   Settings. Quand un compte est connecté, il est remplacé par « Un compte est connecté — détache-le pour en connecter un autre »
   et le bouton pour le détacher (avec les raisons si le cœur refuse).
4. **Le choix Exness / FTMO est la première question** du formulaire : deux cartes (« Quel compte veux-tu ajouter ? »), puis, pour
   Exness, les règles à suivre (les siennes, ou le profil FTMO sur une démo, ADR 0020).

## Conséquences

- Supprimé : le bouton « Rendre actif » et l'action `makeActive` du cockpit (le compte connecté est le compte actif). La route
  `PUT /api/active-account` et `AccountService.set_active` **restent** et ne servent plus que de confirmation du compte connecté :
  à retirer dans un lot à part (route, schéma, types générés, test de surface).
- Tests : ceux qui connectaient deux comptes sont réécrits pour la nouvelle règle (service, API, moteur, exécution) ; le test
  « un échec dans le poll d'un compte épargne les autres » devient « un job en échec n'arrête pas les autres ».
- `ConnectGate` (`components/shell/connect-gate.tsx`) et `lib/accounts/connected.ts` (testé sans navigateur) portent le garde.
- La démo Exness du 2026-11-01 est enregistrée et rattachée depuis le formulaire (capital 10 000 $ confirmé, profil FTMO 2-Step),
  sans mot de passe : le terminal était déjà connecté.
