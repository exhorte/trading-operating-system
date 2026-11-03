# ADR 0026 — Banc de validation : mesurer une configuration figée, jamais en chercher une (phase 5)

Date : 2026-11-01. Statut : **accepté** — mission « Trading OS autonome » du 2026-11-01 (phase 5 : « coûts réels, walk-forward, Monte
Carlo, analyse par session » ; l'accord nomme « un banc de backtest » et précise que l'ADR 0002 n'est levé que par l'ADR de la phase).
**Amende l'ADR 0002** sur un point précis et le laisse entier pour le reste.

## Contexte

L'ADR 0002 a fermé la recherche d'edge après une leçon précise : un candidat « NY AM » **choisi après coup** sur des données déjà
regardées, puis « validé » en rejouant le même sous-ensemble ; des données de développement consommées ; un holdout qu'on ne pouvait lire
qu'une fois. Le dispositif a été supprimé, pas désactivé. La mission demande pourtant de pouvoir répondre, avant d'élever l'autonomie, à
une question que seule la mesure tranche : *que donnent S01 et S02, tels que l'utilisateur les a écrits, avec des coûts réels ?*

## Décision

1. **Ce qui est levé** : le projet peut contenir un *banc de validation* (`domain/validation/`, commande `validate`). **Ce qui ne l'est pas** :
   la recherche d'edge, l'optimiseur, le générateur de signaux, la balayage de paramètres. L'ADR 0002 reste la règle ; cet ADR en
   borne l'exception.
2. **Une configuration figée par exécution.** Le banc prend *une* stratégie, *une* configuration (S01Config ou S02Config, plan de
   sortie, coûts, risque par trade) et la rejoue sur une période. Il n'existe aucune fonction qui en prenne plusieurs, en compare ou en
   retienne la meilleure : le code ne permet pas la sélection a posteriori. Un « walk-forward » ici est donc un **contrôle de stabilité
   hors échantillon d'une configuration fixe** (mêmes règles sur des fenêtres glissantes successives), pas un réglage fenêtre par fenêtre.
3. **Les regards sont comptés.** Chaque exécution porte l'empreinte de sa configuration et s'inscrit dans un registre
   (`exports/validation/ledger.jsonl`). Le rapport dit combien de fois cette empreinte, ou une autre, a déjà regardé une période qui
   chevauche celle-ci : relire dix fois les mêmes données jusqu'à ce que le résultat plaise est visible dans le rapport, pas caché.
4. **Coûts réels, supposés dits.** Commission aller-retour du compte, spread (la fenêtre d'exécution exige que le prix traverse le spread
   pour remplir un `LIMIT` d'achat), glissement sur les stops. Le calendrier de publications et les verrous de risque historiques ne sont
   **pas** rejoués (non disponibles pour le passé) : le rapport le liste parmi ses limites. Le spread est une valeur constante donnée,
   pas une série.
5. **Pessimisme aux bougies ambiguës.** Dans une même bougie M1, le stop passe avant la cible ; sur la bougie de remplissage seule la
   cible n'est jamais comptée. Un ordre qui voit la cible avant son prix est invalidé, pas gagné.
6. **Le plan de sortie réel.** La simulation applique `plan_position` du Position Manager (break-even, clôture partielle, suivi, fin de
   séance) : on mesure le système tel qu'il tournerait, pas une version idéalisée.
7. **Monte Carlo par blocs de jours.** Un tirage avec remise des *journées* réellement observées (une journée garde ses trades groupés),
   graine fixe, donne : probabilité d'atteindre la limite journalière, la limite totale, quantiles du rendement et du drawdown. C'est une
   distribution sur un échantillon passé, pas une prévision.
8. **Une mesure n'est pas une preuve.** Le rapport affiche toujours le nombre de trades et prévient quand il est trop petit pour
   conclure. Aucun critère d'autonomie ne dépend d'un chiffre de rentabilité (voir ADR 0027).

## Ce que cet ADR ne fait pas

- Il ne stocke pas de résultats dans la base et ne crée aucune table (`backtest_*` ne revient pas) : un rapport JSON + le registre.
- Il ne construit pas de simulateur de carnet, de ticks ni de swaps.
- Il ne dit rien de la rentabilité de S01 ou S02 : il fournit l'outil pour la mesurer honnêtement.

## Conséquences

- Tests : simulation (remplissage `LIMIT`, stop avant cible, coûts, expiration, invalidation, break-even et partiel appliqués, fin de
  séance), métriques, Monte Carlo (déterminisme, bornes), fenêtres glissantes, empreinte et registre, rejeu de S01/S02 sur le scénario.
- Commande : `python -m trading_os validate --strategy S01 --symbol EURUSDm --from … --to …`.
