# ADR 0022 — Aucune limite de positions par symbole ; la perte hebdomadaire se règle dans Settings

Date : 2026-11-01. Statut : **accepté** — décision de l'utilisateur en session le 2026-11-01 : « pour le symbole j'aimerais qu'il
y ait aucune limite, un symbole peut être pris dans autant de positions simultanées que possible, je laisse définir la limite
hebdomadaire ». **Amende l'ADR 0019** (tableau des limites : « positions simultanées : 5, sur tout le compte, pas par symbole »
devient une décision explicite et non plus un oubli) et **l'ADR 0015** (« nombre maximal de trades et de positions » : le nombre
de positions est un total de compte, jamais un nombre par symbole).

## Contexte

En relisant les limites du compte (2026-11-01), deux écarts sont apparus :

- `PositionLimits.max_positions_per_symbol` (1 par défaut) était défini, affiché dans Settings (« pas de moyenne à la baisse »)
  et dans la carte des règles, mais **aucune gate ne le lisait** : seul le total de 5 positions était contrôlé. Le formulaire
  promettait donc une protection que le cœur n'offrait pas.
- `DrawdownPolicy.weekly_loss_limit_percent` (10 %, ADR 0019) était appliqué par `gate-weekly-loss`, mais **absent du formulaire** :
  l'utilisateur ne pouvait pas l'écrire, alors que l'ADR 0015 veut que chaque valeur soit posée par lui.

## Décision

1. **Pas de limite par symbole.** Le champ `max_positions_per_symbol` est retiré du modèle (`PositionLimits`), du formulaire, de la
   carte « Règles appliquées » et des types générés. Un symbole peut porter autant de positions simultanées que le reste des
   limites le permet. Ce qui borne l'empilement, par ordre d'effet : le **risque ouvert maximal** (somme des risques au stop),
   l'**exposition corrélée** (même devise, même sens), le **total de positions ouvertes** du compte, et le risque par trade
   lui-même (grille, ADR 0019). Ces gates restent le point de contrôle (ADR 0007).
2. **La perte hebdomadaire est un champ de Settings** (« Perte hebdomadaire maximale », en % du capital de référence, entre 0
   exclu et 100), au même titre que la perte journalière et la perte totale. Valeur par défaut inchangée (10 %, lundi 00:00 heure
   du courtier) ; l'utilisateur la fixe lui-même. Les mêmes règles s'appliquent : prise d'effet au prochain jour de trading si le
   compte a déjà tradé, est verrouillé ou porte une position (règle anti-tilt).
3. **La grille de risque (ADR 0019) reste hors formulaire** : elle n'est pas posée par l'utilisateur ligne à ligne, mais décidée par
   l'ADR ; la changer est un changement d'ADR.

## Conséquences

- **Rien ne change dans le comportement du cœur pour les entrées** : la limite par symbole n'a jamais été appliquée. Ce qui change,
  c'est que Settings et la carte des règles cessent de la promettre.
- **La directive « pas de moyenne à la baisse, pas de grille, pas de martingale »** (`.claude/CLAUDE.md`) n'était donc déjà pas
  tenue par un compteur ; elle reste une propriété exigée des **stratégies** (S01, S02) et se vérifie dans leurs tests, pas dans le
  Risk Engine. Si l'utilisateur veut un jour qu'une gate l'impose, c'est un nouvel ADR.
- Les profils déjà enregistrés en base portent encore la clé `maxPositionsPerSymbol` dans leur JSON : le cœur l'ignore à la lecture
  (test `test_a_profile_saved_before_adr_0022_still_loads`) et elle disparaît à la prochaine sauvegarde du compte.
- Tests : `lib/accounts/rules-draft.test.ts` (champ hebdomadaire écrit, borné, requis ; aucun champ par symbole),
  `test_evaluate_and_gates.py` (limite de positions = compte seul ; seuil hebdomadaire suivant la valeur écrite).
- Les types TypeScript sont régénérés (`python -m trading_os gen-types`) ; un test échoue si le fichier est périmé.
