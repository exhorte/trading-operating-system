# T12 — Prop Firm Control Center

Statut : **en cours** — incrément 1 « un compte à la fois » **livré** (2026-09-21) ;
incrément 2 « Account & Settings » **livré** (2026-09-23) · Vague 3 ·
Effort backlog 1–2 sem (incrément 1 : 1–2 j) · Valeur 5 · Dépend de : T11
**pour le multi-compte simultané seulement** — les incréments 1 et 2 s'en passent.

## Problème

Le système ne sait pas s'il regarde un challenge FTMO ou un compte Exness en
direct. EA-04 a construit la structure (`lib/accounts/` : types, gabarits
FTMO et compte réel, registre) mais a laissé le registre **vide exprès** et
les règles FTMO en `TODO(FTMO-rules)`, faute de source. Tant que ça dure, le
Risk Engine applique un jeu de limites générique à n'importe quel compte, et
rien ne suit les objectifs d'un challenge.

## Écart trouvé avant tout code (cartographie, 2026-09-21)

Lu avant d'écrire quoi que ce soit : fiche EA-04, `lib/accounts/*`,
`lib/risk/policy.ts`, `lib/risk/evaluate.ts`, `lib/realtime/signalr-client.ts`
(`recomputeRisk`, `hydrateRiskToday`), `lib/realtime/mt5-translate.ts`,
`lib/market/symbols/registry.ts`, `lib/compliance/evaluate.ts`,
`tools/mt5-observer/mt5_observer.py`, `lib/mock/initial-snapshot.ts`,
`context/domain/risk_ftmo.md`, backlog T11/T12/T13.

1. **« Se connecter à FTMO ou à Exness » ne passe pas par l'application.**
   L'observer appelle `mt5.initialize()` **sans identifiant** : il se greffe
   sur le terminal MT5 déjà ouvert et lit ce que le terminal expose
   (`login`, `server`, `company`). Changer de compte, c'est ouvrir l'autre
   compte dans MT5. Le cockpit reçoit déjà le nom du broker :
   `account.broker` = `company` MT5, via le hello de l'observer
   (`mt5-translate.ts:45`).
2. **Faille de correction : la perte max mesurée depuis la connexion du
   cockpit.** `recomputeRisk` passe `initialBalance: this.baselineBalance` —
   le solde au moment où le cockpit s'est connecté, remis à zéro à chaque
   resynchro (`signalr-client.ts:212`). Chez FTMO la perte max se mesure
   depuis la **taille initiale du compte**, fixe pour tout le challenge.
   Compte de 10 000 $, −600 $ le jour 1, cockpit rouvert le jour 2 : le gate
   autorise encore 940 $ de perte, plancher à 8 460 $, alors que FTMO a
   clôturé le compte à 9 000 $. **La perte journalière n'a pas ce défaut** :
   son ancre vient de l'equity de début de journée persistée par T02a
   (`hydrateRiskToday`), pas de la connexion.
3. **Les trades FTMO échapperaient au contrôle de taille, en silence.** FTMO
   nomme l'or `XAUUSD` (export MetriX, « Résultats par instrument ») ; le
   registre de symboles ne connaît que `XAUUSDm`, donc
   `toCanonicalSymbol("XAUUSD")` renvoie `null`, et la conformité saute le
   contrôle de taille dans ce cas (`evaluate.ts`, commentaire de
   `ComplianceTradeInput.symbol`).
4. **Les règles FTMO sont maintenant sourcées** — par les exports MetriX de
   l'utilisateur (`05_screenchot/`, compte 511333949) : 2-Step,
   10 000 $, 4 jours de trading minimum, perte journalière max −500 $, perte
   max −1 000 $, objectif de profit +1 000 $. Ce compte est échoué et en
   lecture seule (−1 004,12 $, −10,04 %) ; le profil sert au prochain
   challenge.
5. **Le mock se présentait comme « FTMO Challenge 100k »**, incohérent avec
   un challenge configuré à 10 000 $ : l'écran de compte y aurait affiché un
   objectif de profit « atteint » à +91 000 $.

## Décisions

Validées par l'utilisateur le 2026-09-21 :

1. **Périmètre : un compte à la fois.** Le terminal MT5 ouvert décide. Le
   simultané (deux terminaux, un observer par compte, compte propagé dans
   l'enveloppe, le hub, la base et le store) est T11, hors de cet incrément.
2. **FTMO : gabarit 2-Step 10 000 $, phase Challenge**, valeurs des exports
   MetriX. Vérification et Funded restent `TODO(FTMO-rules)` — non sourcées,
   donc non devinées.
3. **Exness en direct : 5 % par jour, 10 % max**, soit les mêmes limites que
   FTMO. Recommandation écartée (3 %/8 %, parce qu'aucune firme ne coupe le
   compte à la place du trader) ; arbitrage de l'utilisateur, appliqué tel
   quel.

Tranchées à l'ingénierie, conformément aux règles du dépôt :

4. **Aucun identifiant de connexion stocké.** Inutile (point 1) et interdit
   (`.claude/CLAUDE.md`).
5. **Détection par le nom du broker, pas par numéro de compte.** `company`
   MT5 contient « FTMO » ou « Exness » ; aucun numéro de compte n'entre dans
   le code pour que ça marche. Le registre par `accountId` d'EA-04 reste
   vide et reste consulté en premier par `defaultRiskPolicy` — il servira au
   multi-compte (T11).
6. **Configuration dans le code, jamais depuis l'interface** (ADR 0007). Le
   challenge en cours (`ACTIVE_FTMO_CHALLENGE`) et la référence Exness
   (`EXNESS_REFERENCE_BALANCE`) se changent dans `lib/accounts/`, par un
   commit. L'écran `/comptes` affiche, il n'édite pas : desserrer sa propre
   limite d'un clic en pleine séance est ce que le produit doit empêcher.
   **Révisée le 2026-09-23 par l'utilisateur** (incrément 2, décision 8) —
   cette décision avait été tranchée à l'ingénierie, jamais validée par lui.
7. **Exécution inchangée.** Aucun mode d'exécution n'est lu ni écrit par cet
   incrément ; EA-07 reste fermé.

Incrément 2 (2026-09-23), demande : « la partie connexion aux comptes
propfirm ou FTMO et celui d'un broker ou Exness à travers deux nouvelles
interfaces Account et Settings ». Validées par l'utilisateur :

8. **Settings modifiable, avec verrou anti-tilt** (remplace la décision 6
   pour les *faits* du compte). Le challenge FTMO (type, taille, phase), le
   capital de référence Exness et le texte de reconnaissance de chaque broker
   s'éditent depuis Settings, dans un registre en ajout seul côté backend,
   tracé dans l'audit. **Appliqué tout de suite seulement si aucune séance
   n'est en cours** — aucun trade depuis l'ancre du jour, aucune position
   ouverte, aucun verrou actif, sur *n'importe quel* compte, et un compte
   vivant pour le vérifier —, **sinon au prochain jour de trading**. Les
   pourcentages (règles FTMO, limites de discipline) restent dans le code,
   affichés en lecture seule. Option écartée : rendre aussi les limites de
   discipline éditables.
9. **Vérification réelle autorisée** : `e-commerce-db-1` (autre projet,
   même port 5433) arrêté le temps du test.

Tranchées à l'ingénierie :

10. **Le verrou est décidé au point d'écriture, côté backend**
    (`AccountSettingsGuard`, C#), jamais par la page : ADR 0007 — une règle
    du moteur, pas un bouton grisé. La page affiche la décision qu'on lui
    donne (`GET /api/account-settings` → `guard`).
11. **La résolution « quelle version est en vigueur » est côté cockpit**
    (`lib/accounts/settings.ts`), contre l'ancre T02a du compte tradé — la
    même que la perte journalière. Un changement reporté entre en vigueur à
    la première ancre qui démarre *après* sa demande. L'ancre publiée vient
    de l'événement `risk.day_anchor.resolved` lui-même, pas seulement de
    `/api/risk/today` : la ligne en base est écrite de façon asynchrone, et
    la passerelle ne re-diffuse l'ancre que toutes les 5 min — sans cela, un
    changement reporté pouvait rester « en attente » jusqu'à 5 min après le
    début du nouveau jour. Au sein d'un compte l'ancre ne recule jamais
    (`nextDayAnchor`, testé). *(Première rédaction de ce point fausse — « aucune
    course » — corrigée dans la même session en relisant le code.)*
12. **Toujours aucun identifiant.** « Connexion » = la procédure MT5
    (terminal connecté par le trader, observer sur le symbole que CE terminal
    liste). Aucun formulaire login/mot de passe, par règle
    (`.claude/CLAUDE.md`, ADR 0003) — frontière posée avant tout code.
13. **`/comptes` devient Account, et Settings revient** : un écran = une
    question (`information_architecture.md`) — Account « qu'est-ce qui est
    branché, sous quelles règles », Settings « comment chaque compte est
    configuré et branché ». Redirection temporaire `/comptes` → `/account`.

## Comportement attendu

- `lib/accounts/firm.ts` — `detectFirm(broker)` → `"ftmo" | "exness" | null`.
- `lib/accounts/ftmo.ts` — règles de la phase Challenge du 2-Step sourcées,
  objectifs (jours minimum, objectif de profit) par phase,
  `ACTIVE_FTMO_CHALLENGE`.
- `lib/accounts/real.ts` — 5 %/10 % (décision 3), `EXNESS_REFERENCE_BALANCE`
  à `null` tant que l'utilisateur ne l'a pas fixé.
- `lib/accounts/active-profile.ts` — `resolveActiveProfile(account)` : firme,
  libellé, policy, **solde de référence** et sa provenance, modèle de coût,
  challenge.
- `lib/accounts/objectives.ts` — les quatre objectifs MetriX (jours min,
  perte journalière, perte max, objectif de profit), chacun avec son état.
- `lib/realtime/signalr-client.ts::recomputeRisk` — policy et **référence
  du profil actif**, repli sur l'existant si le broker n'est pas reconnu.
- `lib/market/symbols/registry.ts` — un nom canonique est accepté comme nom
  broker (convention FTMO).
- `lib/mock/initial-snapshot.ts` — le compte mock *est* le challenge
  configuré (chiffres absolus mis à l'échelle, ratios conservés).
- `/comptes` — compte actif, règles appliquées avec leurs montants, objectifs
  du challenge, provenance de chaque chiffre. Lecture seule. *(Remplacé par
  `/account` à l'incrément 2.)*

Incrément 2 :

- `backend/.../schema.sql` — table `account_settings`, registre en ajout
  seul (seule mutation : `cancelled_at` sur un changement reporté qui n'a
  gouverné aucune séance).
- `TradingOs.Persistence/AccountSettingsGuard.cs` — la règle anti-tilt, pure.
  `AccountSettingsValidation.cs` — forme et bornes. `AccountSettingsRepository.cs`
  — registre + faits de séance de **tous** les comptes (ancre < 25 h).
- `TradingOs.Host/AccountSettingsEndpoints.cs` — `GET/POST /api/account-settings`,
  `POST /api/account-settings/{id}/cancel` ; chaque écriture diffuse
  `accounts.settings.changed` et le persiste dans `envelopes`.
- `lib/accounts/settings.ts` — types, lecture défensive, résolution,
  validation miroir, libellés. `settings-api.ts` — appels HTTP.
  `connection.ts` — symbole par terminal, commande observer, whitelist et
  numéro magique suggérés de l'agent.
- `lib/accounts/firm.ts` / `active-profile.ts` — reconnaissance et profil
  pilotés par les paramètres en vigueur (défaut = comportement d'avant).
- `lib/realtime/*` — le registre et l'ancre du jour dans le store ; le moteur
  de risque résout les paramètres en vigueur avant chaque calcul.
- `/account` — chaîne de liaison MT5 maillon par maillon, les deux comptes
  côte à côte, règles et objectifs du compte branché.
- `/settings` — verrou annoncé, formulaires FTMO/Exness avec aperçu des
  montants, procédure de connexion MT5, règles du code en lecture seule,
  historique.
- `scripts/start-live.ps1` + `tools/mt5-observer/probe_terminal.py` — démarrage
  de l'environnement réel pour le compte ouvert dans MT5.

## Ancrage dans le code

EA-04 (`lib/accounts/`, `lib/market/symbols/`) étendu, pas dupliqué :
`RiskPolicy` reste le type des limites, `CostModel` celui des coûts.
`defaultRiskPolicy` garde sa signature et ses cinq appelants.

## Hors périmètre, nommé plutôt qu'oublié

- **Ancre de la journée FTMO.** T02a ancre la journée à minuit serveur, sur
  l'equity ; FTMO communique en CE(S)T (mention MetriX). Écart possible d'une
  heure et d'une base de calcul — à trancher avec le règlement FTMO, pas en
  devinant.
- **Référence Exness.** Tant qu'elle n'est pas fixée (défaut `null`, à
  fixer dans Settings depuis l'incrément 2), la perte max d'un compte Exness
  garde l'ancien comportement (solde à la connexion) — `/account` l'affiche
  comme « non fixé ».
- **Verrou anti-tilt entre comptes aux horloges différentes** (incrément 2).
  La résolution compare l'ancre du compte *branché* à l'heure de la demande :
  en changeant de compte dans MT5 autour de minuit serveur, un changement
  peut s'appliquer quelques heures plus tôt qu'un « jour suivant » strict
  (écart d'horloge FTMO CE(S)T / Exness GMT). Un ralentisseur, pas un mur
  (ADR 0007) ; l'annulation, elle, reste refusée dès qu'une journée a démarré
  sur *n'importe quel* compte.
- **Specs de symboles FTMO non mesurées.** Le contrôle de taille réutilise la
  mesure Exness : même valeur économique par lot pour XAUUSD (100 oz) et les
  majeures (100 000), à confirmer par `list_symbols.py` sur un terminal FTMO.
- **Chaîne `company` FTMO non observée en direct** — aucun terminal FTMO n'a
  jamais été relié ; la détection cherche « ftmo » dans le nom, sans
  supposer le reste.
- **Conformité et `/journal` lisent `defaultRiskPolicy`.** Ils n'utilisent
  que `maxRiskPerTradePercent`, à 1 % dans tous les profils ; un test casse si
  un profil s'en écarte, pour forcer le câblage à ce moment-là.
- **`scripts/run-setup-detection.ts`** reste sur le registre par
  `accountId` (vide) : le coût FTMO (5 $/lot) n'y entre pas encore.
- **Multi-compte simultané** : T11.

## Critère de réussite

- Sur un compte FTMO, la perte max est mesurée depuis 10 000 $ quelle que
  soit l'heure de connexion du cockpit — testé.
- Un trade `XAUUSD` passe le contrôle de taille — testé.
- `/comptes` affiche le profil détecté, ses règles en % et en $, les
  objectifs du challenge, et dit d'où vient chaque chiffre.
- Gates vertes.

## Journal

- 2026-09-21 — fiche créée. Demande : « une configuration interne de
  connexion propfirm FTMO ou un compte direct Exness ». Cartographie faite
  (voir plus haut) ; trois décisions soumises et validées ; quatre tranchées
  selon les règles du dépôt. Backend et base à l'arrêt pendant toute la
  session (`Exited (255)`), non relancés sans accord : vérification limitée
  aux tests et au rendu en mode mock.

- 2026-09-21 (suite) — **incrément 1 livré.** Dans l'ordre :
  1. `lib/accounts/firm.ts` — `detectFirm`, recherche du nom de la firme dans
     le `company` MT5, rien de plus supposé.
  2. `lib/accounts/ftmo.ts` — phase Challenge du 2-Step sourcée (MetriX),
     `ftmoObjectives` (4 jours, objectif 10 %), `ACTIVE_FTMO_CHALLENGE`
     (2-Step, 10 000 $, Challenge). Vérification/Funded restent
     `TODO(FTMO-rules)` et rendus « Non sourcé ».
  3. `lib/accounts/real.ts` — 5 %/10 % (décision 3),
     `EXNESS_REFERENCE_BALANCE = null`.
  4. `lib/accounts/active-profile.ts` — `resolveActiveProfile`.
  5. `lib/accounts/objectives.ts` — les quatre lignes MetriX, chacune avec sa
     note de provenance.
  6. `lib/market/symbols/registry.ts` — un nom canonique vaut nom broker.
  7. `lib/realtime/signalr-client.ts::recomputeRisk` — policy et référence
     du profil actif ; repli à l'identique si le broker n'est pas reconnu.
  8. `lib/mock/initial-snapshot.ts` — chiffres absolus mis à l'échelle du
     challenge configuré (10 000 $), ratios inchangés : le mock reste
     « Armé ».
  9. `/comptes` (entrée « Comptes », section Système) — lecture seule.

  **Vérifié contre le verdict réel de FTMO.** `objectives.test.ts` rejoue
  les quatre journées de 511333949 tirées du « Résumé quotidien » MetriX
  (15/07 −369,30 · 16/07 −99,96 · 17/07 −289,04 · 20/07 −245,58, soit
  −1 003,88 $ comme le rapport) et retrouve les quatre états de FTMO : jours
  atteints, perte journalière respectée, perte max dépassée, objectif non
  atteint. Et la faille est fixée par un test sur le vrai moteur de risque
  (`active-profile.test.ts`) : au jour 2, equity 8 990 $, le gate de perte
  max restait ouvert avec la référence de connexion (9 400 $) et bloque avec
  celle du challenge (10 000 $).

  **Vérifié à l'écran** (préversion mock) : état « broker non reconnu »
  (surcharge `.env.local` active, broker « override .env.local ») et état
  FTMO (surcharge neutralisée par une entrée de lancement temporaire, retirée
  ensuite — `.claude/launch.json` restauré à l'octet près) : libellé
  « FTMO · 2-Step $10,000 · Challenge », 500 $ par jour, plancher 9 000 $,
  commission 5 $/lot. Command Center toujours « Armé », equity ~10 131 $.
  **Non vu à l'écran** : le tableau des objectifs rempli — le backend et la
  base étaient arrêtés (`Exited (255)`), la carte a affiché son état d'échec,
  qui est lui aussi un état vérifié. Le calcul est couvert par les tests
  ci-dessus.

  Gates : `tsc`, `eslint`, `next build` propres, **269 tests** (+22).

- 2026-09-23 — **incrément 2 livré : écrans Account et Settings.** Demande :
  « la partie connexion aux comptes propfirm ou FTMO et celui d'un broker ou
  Exness à travers deux nouvelles interfaces Account et Settings ». Frontière
  posée avant tout code : aucune connexion broker ni identifiant dans
  l'application (ADR 0003) — la connexion reste la procédure MT5, que
  Settings décrit et que `scripts/start-live.ps1` automatise. Deux décisions
  soumises et validées (8, 9), quatre tranchées (10 à 13).

  **Vérifié en réel** (base et backend reconstruits, `e-commerce-db-1` arrêté
  sur accord) : table créée par le schéma idempotent ; `GET` → registre vide,
  verrou reporté pour `no_live_account` — recoupé à la main contre la base
  (seule ancre connue, 477029930, vieille de 4 jours donc hors fenêtre de
  25 h ; aucun verrou actif) ; deux `POST` invalides → 400, rien d'écrit ;
  **écriture par l'interface** (FTMO 25 000 $) → reportée au jour suivant,
  ligne du registre et enveloppe d'audit en base, « en vigueur » resté à
  10 000 $ ; **annulation** depuis un onglet → l'autre onglet (Account, sans
  relecture périodique ni rechargement) perd la notice en moins de 3 s : la
  diffusion `accounts.settings.changed` fonctionne ; double annulation → 409,
  version inconnue → 404. Rendu vérifié en mode backend (aucun compte
  branché) et en mock (broker non reconnu ; FTMO connecté via une entrée de
  lancement temporaire, `launch.json` restauré à l'octet près). Données de
  test supprimées ensuite, par identifiant : registre vide, zéro enveloppe
  `accounts.settings.*`.

  **Deux défauts trouvés à l'écran et corrigés** : les deux formulaires
  portaient la même clé React (`default`) tant que rien n'était enregistré ;
  la ligne « Backend » affichait « Périmé » sans dire que c'est le
  battement de cœur MT5 qui manque, pas le hub.

  **Non vérifié en réel** : le chemin « appliqué tout de suite » (il faut un
  compte vivant sans séance en cours — MT5 fermé toute la session) — couvert
  par les tests C# du verrou ; le moteur de risque consommant des paramètres
  enregistrés sur un vrai compte — couvert par les tests de résolution et de
  profil.

  Gates : `tsc`, `eslint`, `next build` propres ; **303 tests** Vitest (+34) ;
  `dotnet build` 0/0 ; **`dotnet test` 58/58 en natif** (+24) — Smart App
  Control est désactivé sur la machine (`VerifiedAndReputablePolicyState = 0`),
  le blocage du 2026-09-17 n'existe plus ; tests Python 23/23 (+6).
