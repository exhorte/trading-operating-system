# ADR 0011 — Un banc de replay n'est pas un backtester

Date : 2026-09-11. Statut : accepté. Borne l'ADR 0002 sans le lever.

## Contexte

L'ADR 0002 a supprimé `lib/backtest/`, `lib/strategy/` et toute la machinerie de
verdict. La roadmap exclut explicitement le backtester et l'optimiseur de son
périmètre.

La fiche S01 formalise une stratégie en règles déterministes : détection de
sweep, déplacement validé en corps, géométrie de FVG, seuils de CE. Ces règles
doivent être vérifiées — non pas « sont-elles rentables », mais « se déclenchent-
elles là où elles devraient ». L'ADR 0002 ne laisse aucun outil pour répondre à
cette question.

La demande a été posée le 2026-09-11 : reconstruire le backtester, éventuellement
réutilisable sur d'autres projets. Le mot recouvre trois choses de risque très
différent — un banc de replay, un backtester de performance, un optimiseur — et
les confondre est le chemin le plus court pour rouvrir sans l'avoir décidé ce que
juillet 2026 a coûté.

## Décision

**Un banc de replay est autorisé. Il vit dans un dépôt séparé. Il ne calcule
aucune métrique de performance.**

Ce que le banc fait : rejoue les détecteurs sur des bougies stockées et répond
« où et quand se sont-ils déclenchés ». Sortie : une liste d'événements datés.

Ce que le banc ne fait pas, et ce qui le rendrait caduc au premier manquement :

- aucun P&L, aucun taux de réussite, aucune espérance, aucun drawdown, aucun
  profit factor, aucune courbe d'équité ;
- aucun balayage de paramètres, aucune optimisation, aucun classement de
  variantes ;
- aucune sélection de configuration sur la base d'un résultat.

**Dépôt séparé.** Le banc n'entre pas dans `lib/`. Le Trading OS le consomme
comme dépendance de test. La réutilisation sur d'autres projets est la raison
d'être de cette séparation ; la protection de l'ADR 0002 en est la conséquence
utile.

## Conséquences

- `lib/backtest/` ne revient pas dans ce dépôt. L'ancien code reste là où le
  pivot l'a laissé : dans l'historique git, aux tags
  `archive/pre-pivot-2026-09-04` et `archive/pivot-commits-2026-09-04`.
- **Ces deux tags ne sont pas poussés sur GitHub** — vérifié le 2026-09-11 via
  l'API : le dépôt distant ne porte aucun tag. Ils n'existent que sur la machine
  locale. Les pousser avant toute récupération de code.
- Le jour où une question de performance se pose — « est-ce que ça marche » et
  non « est-ce que ça se déclenche » — ce n'est plus ce banc. C'est un nouvel
  ADR qui supersède l'ADR 0002, pris délibérément, pas une fonction ajoutée à un
  outil existant.
- La validation de S01 ne repose donc pas sur ce banc seul : le banc dit où les
  détecteurs se déclenchent, les tests unitaires disent que la géométrie est
  juste, et le taux d'accord machine/humain en mode OBSERVE dit que la stratégie
  codée est bien celle qui est tradée. C'est ce troisième point qui fait foi.
