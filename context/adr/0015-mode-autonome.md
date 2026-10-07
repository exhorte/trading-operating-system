# ADR 0015 — Mode autonome : le Trading OS exécute la stratégie configurée

Date : 2026-09-25. Statut : **accepté le 2026-09-26** — accord nommé de
l'utilisateur : « J'approuve l'ADR 0015 » (voir « Accord » en fin
d'ADR) ; **amendé le même jour** (spread, levée des limites de perte,
arrêts de stratégie : voir « Amendement » en fin d'ADR). Supersède la clause « Aucun mode AUTO dans ce chantier » de l'ADR
0010. Amende l'ADR 0001 (« l'humain décide et déclenche ») et le principe 6
de la charte (« aucun ordre n'est envoyé sans qu'un humain l'ait
déclenché »).

## Contexte

L'ADR 0010 a ouvert un chemin d'exécution en s'arrêtant à CONFIRM, la
validation humaine de chaque ordre. Il a écrit que « le passage à AUTO
exigera un ADR qui supersède celui-ci ; ce n'est pas un paramètre de
configuration ».

Le 2026-09-25, l'utilisateur fixe le but de l'agent : rendre l'application
autonome, qu'elle fonctionne sans son intervention et exécute des ordres
selon la stratégie configurée. Il la veut sur son compte réel dès
l'incrément I5 (« plus de démo »), avec des garde-fous cohérents avec
l'autonomie. Claude avait recommandé la démo, puis CONFIRM. L'utilisateur a
choisi le réel en connaissance de cause (`session-log.md`, 2026-09-25).

L'état des preuves à cette date, écrit ici pour ne pas se perdre :
- la seule stratégie formalisée du dépôt est S01 ;
- son détecteur n'a produit **aucune proposition** en observation : 595
  évaluations au 2026-09-15, entonnoir bloqué à l'étape 4 sur 9 ;
- ses étapes d'entrée, de stop et de cible n'ont jamais tourné sur des
  données réelles ;
- aucun backtest n'existe (ADR 0002).

Rien ne dit que cette stratégie est rentable.

## Décision

**Le Trading OS peut ouvrir et fermer des positions sans validation humaine
de chaque ordre. Il exécute la stratégie configurée par l'utilisateur, dans
des limites automatiques.**

- **La stratégie décide des entrées ; jamais une IA, jamais une
  optimisation.** Aujourd'hui, c'est S01 telle que sa fiche la définit :
  EURUSD, puis XAUUSD quand ses seuils seront relatifs à l'ATR. Ses
  paramètres sont posés par l'utilisateur, jamais choisis par balayage ni
  par classement de résultats (ADR 0002 et 0011 inchangés). L'ADR 0005 est
  inchangé : aucune IA ne décide.
- **L'humain décide quand l'autonomie est active.** Démarrer depuis
  l'application (l'armement, ADR 0014) vaut accord pour toutes les décisions
  de la stratégie, jusqu'à l'arrêt. L'agent redémarre toujours désarmé.
  L'arrêt reste possible à tout moment, depuis l'application ou depuis le
  graphique MT5.
- **Les garde-fous deviennent des limites automatiques.** C'est ce qui rend
  l'autonomie possible sans surveillance : en marche normale, aucun ne
  demande d'intervention humaine.

| Garde-fou | En mode autonome |
|---|---|
| Validation de chaque ordre (CONFIRM) | **Supprimée** : c'est l'objet de cet ADR. |
| Bail d'armement renouvelé par l'onglet du cockpit (plan de l'ADR 0014) | Renouvelé côté serveur : fermer le navigateur n'arrête rien. |
| Risk Engine exécuté dans l'onglet du navigateur | **Côté serveur**, et il fait foi : aucun ordre sans son accord. |
| Taille de position et risque par trade | Gardés : la taille est calculée depuis les spécifications du courtier, le risque par trade est fixé par l'utilisateur. |
| Stop posé chez le courtier dès l'ouverture | Gardé : il protège même si tout le reste tombe. |
| Perte maximale du jour et perte maximale totale | Gardées : l'autonomie est suspendue jusqu'au jour de trading suivant, sans clic. *Amendé : levée par accusé.* |
| Nombre maximal de trades et de positions, liste des symboles, spread maximal par symbole | Gardés, valeurs fixées par l'utilisateur. *Amendé : pas de plafond de spread fixe, la porte de coût de S01 en tient lieu.* |
| Arrêt d'urgence | Gardé : il coupe l'autonomie, et c'est l'utilisateur qui la relance. |
| Homme mort | **Nouveau** : sans nouvelles du Trading OS, l'agent n'ouvre plus rien, et les stops restent chez le courtier. |
| Idempotence, état `UNKNOWN`, instance unique, `ACCOUNT_MISMATCH` | Gardés (ADR 0010). |

  Chaque valeur est fixée par l'utilisateur, compte par compte. Aucune
  n'est « illimitée » par défaut : sans elles, l'autonomie refuse de
  démarrer.
- **Compte réel dès l'incrément I5**, par décision de l'utilisateur du
  2026-09-25.
- **Une mesure honnête.** Ce que fait l'autonomie est enregistré et restitué
  tel quel (journal, conformité). Aucune prétention de performance n'est
  publiée, et une logique non testée n'est jamais présentée comme rentable.

## Conséquences

- **Charte, principe 6.** Il devient : « Aucun ordre n'est envoyé hors de la
  stratégie configurée et des limites du Risk Engine. L'humain arme et
  désarme l'autonomie. »
- **ADR 0001.** « L'humain décide et déclenche » devient « l'humain configure
  la stratégie, fixe les limites et arme ; la stratégie déclenche dans ces
  limites ». Le reste tient : l'IA ne décide pas, et `lib/analysis/` reste
  un fournisseur de contexte.
- **ADR 0010.** Sa clause « Aucun mode AUTO » est remplacée par cet ADR. Le
  reste tient : l'EA n'est qu'un exécutant sans stratégie, avec idempotence,
  état `UNKNOWN` et isolation des comptes.
- **ADR 0007, renforcé.** Le Risk Engine passe côté serveur, dans un
  processus qui tourne sans navigateur.
- **ADR 0014** (armement, approuvé le 2026-09-25 mais pas encore rédigé) :
  il sera rédigé avec un bail renouvelé côté serveur, et un plafond de mode
  compilé qui peut atteindre AUTO.
- **`.claude/CLAUDE.md`.** Les non-négociables sur la décision humaine, sur
  CONFIRM et sur les identifiants de compte (ce dernier déjà amendé par
  l'ADR 0013) sont réécrits en conséquence.
- **À construire avant la première entrée autonome :**
  - le Risk Engine côté serveur ;
  - la taille calculée depuis les spécifications du courtier : le calcul
    actuel surdimensionne d'environ 1000 fois hors XAUUSD ;
  - le stop et la cible posés dès l'ouverture ;
  - la gestion de sortie de S01 ;
  - l'homme mort ;
  - la supervision et le redémarrage des processus.

  Le détail et l'ordre sont dans
  `02_Plan_Projet/etude-connexion-pilotage-agent-2026-09-25.md`.
- **Claude ne déclenche jamais lui-même l'autonomie, ni aucun ordre.** Les
  essais sur le compte réel sont faits par l'utilisateur.

## Accord

Le 2026-09-26, dans un même message, l'utilisateur écrit « J'approuve
l'ADR 0015 », confirme la stratégie (« je confirme S01 ») et donne ses
premières valeurs de limites pour le compte réel. Les valeurs sont notées
mot pour mot dans `context/project/session-log.md` (2026-09-26), avec ce
qui reste à préciser. Elles n'appartiennent pas à cet ADR : elles vivront
dans la configuration de l'autonomie (incrément I7), compte par compte, et
peuvent changer sans le remplacer.

Cet accord n'ouvre rien à lui seul : l'autonomie n'existe pas encore dans
le code. Chaque élargissement se construit dans son incrément (I4 à I8 de
l'étude), après l'ADR ou la fiche qui le précède.

## Amendement du 2026-09-26

Accord de l'utilisateur, mot pour mot : « je valide tes decisions », sur
l'analyse `02_Plan_Projet/regles-deduites-scalp-marco-2026-09-26.md`, après
« ne pas definir de regle de lmite de spread laisser et s'adapter au regle
du broker ».

- **Spread.** Pas de plafond fixe par symbole. La seule règle de spread est
  la porte de coût de S01 — coût aller-retour ÷ distance du stop, sous le
  seuil du profil de compte —, évaluée à la décision et au remplissage.
- **Levée des limites de perte.** La perte du jour, la perte totale et le
  nombre maximal de trades atteints suspendent l'autonomie jusqu'à l'accusé
  de l'utilisateur (T02c), et non jusqu'au jour suivant sans clic. À 0,1 %
  de risque par trade, ces limites ne peuvent être atteintes que par un
  dysfonctionnement : se relancer seul le laisserait recommencer. Ce qui
  arrive en marche normale (pause sur pertes consécutives, fin de séance)
  se lève seul.
- **Deux arrêts de stratégie**, levés seulement par accusé : un drawdown
  exprimé en R depuis le plus haut (20 R à ce jour) et une revue après un
  échantillon de trades autonomes (50 à ce jour ; moins de 20 gagnants,
  l'autonomie reste coupée). Ils arrêtent, ils ne choisissent aucun
  paramètre : l'ADR 0002 est inchangé.

Les valeurs vivent, comme les autres, dans la configuration de l'autonomie
(I7).
