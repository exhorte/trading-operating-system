# T08 — Revue hebdomadaire générée

Statut : **livré** (3 incréments, 2026-09-17) · Vague 2 · Effort 1–2 j ·
Valeur 4 · Dépend de : T06 (livré)

## Problème

Rien ne condense une semaine de trading en quelque chose qui se lit une
fois et se garde. `/journal` (T06) est un tableau de bord qu'on interroge ;
ce n'est pas un document qu'on relit le lundi matin.

## Écart trouvé avant tout code (cartographie)

Lu avant d'écrire quoi que ce soit : `catalogue.md` (#8), `backlog.md`
(T08), `context/infrastructure/runbook.md` (aucun mécanisme de
planification n'existe dans ce dépôt), `T06-journal-auto.md`,
`T07-tracker-conformite.md`, `T15-serveur-mcp.md` (précédent le plus
proche).

**Deux formulations sont datées, T04.** Catalogue.md prévoyait « les trois
pires trades avec leur ticket pré-trade » et une « comparaison plan /
exécution » — les deux supposent un plan déclaré, qui n'existe plus depuis
le retrait de T04 (même limite déjà posée pour T06/T07). Remplacé : le
ticket devient un lien vers la capture (T05) quand elle existe ; la
comparaison plan/exécution est abandonnée, pas reformulée — il n'y a plus
rien à comparer.

**Rien à construire côté données, encore une fois.** Statistiques de la
semaine et pires trades viennent de `/api/journal/trades` (T06) ; le taux
de conformité et les erreurs les plus fréquentes viennent de
`lib/compliance/` (T07), déjà réutilisable directement (T15 l'a déjà fait).
Aucune nouvelle table, aucun nouvel endpoint.

**Aucune planification n'existe dans ce dépôt.** Catalogue.md dit « générée
automatiquement le vendredi soir », mais rien ici ne déclenche quoi que ce
soit à une heure fixe — ni cron, ni tâche planifiée, ni worker. Catalogue.md
lui-même laisse la porte ouverte : « TOS ou CLI » (tableau récapitulatif,
ligne #8). Voir Décision 2.

## Décisions à valider avant d'implémenter

1. **Format : un fichier Markdown, pas un PDF ni une page cockpit.**
   « Un document qui se lit une fois et se garde, pas un tableau de bord »
   (catalogue.md) exclut une nouvelle page `/review` — ce serait un second
   `/journal`. Markdown : lisible tel quel, versionnable si l'utilisateur le
   garde, zéro nouvelle dépendance (un PDF demanderait une bibliothèque de
   rendu, comme T05 avait explicitement refusé d'en ajouter une pour les
   captures).

2. **Génération à la demande (script), pas de planification automatique
   dans ce tour.** Construire un vrai déclenchement « vendredi soir » (cron
   Windows, tâche planifiée, ou un service qui tourne en permanence) est un
   morceau d'infrastructure à part entière, absent de ce dépôt aujourd'hui —
   pas un sous-produit de T08. Catalogue.md accepte explicitement « CLI » :
   un script lancé à la demande (`npm run weekly-review`), la semaine
   couverte passée en paramètre ou par défaut la semaine glissante des 7
   derniers jours. Le vrai vendredi-soir automatique reste possible plus
   tard, en decision séparée.

3. **Les trois pires trades : par P&L réalisé le plus négatif, lien vers la
   capture (T05) quand `hasCapture` est vrai — jamais un lien mort (même
   règle que T06 et T07).**

4. **« Comparaison plan/exécution » abandonnée**, pas remplacée — la donnée
   qu'elle comparait (le plan déclaré, T04) n'existe plus. Rien à mettre à
   la place ; l'annoncer comme retirée plutôt que de laisser un item silencieusement
   disparaître entre la fiche d'origine et celle-ci.

## Comportement attendu

Un script (`tools/weekly-review/index.ts`, patron `tsx` — comme T15)
génère un fichier Markdown pour une semaine donnée :

1. Statistiques : nombre de trades, P&L réalisé net (un fait, pas un
   objectif — même ligne que T06 Décision 1), répartition par symbole.
2. Taux de conformité de la semaine (`lib/compliance/`, même calcul que
   `ComplianceBadge`/T15).
3. Les trois erreurs les plus fréquentes — type de violation le plus
   représenté sur la semaine, avec le compte.
4. Les trois pires trades (P&L le plus négatif), avec lien vers leur
   capture si disponible (Décision 3).

## Ancrage dans le code

- `tools/mcp-server/backend-client.ts` (déplacé en incrément 1 vers
  `tools/shared/backend-client.ts`, voir journal) — patron de client HTTP
  vers l'API REST existante, à réutiliser à l'identique (même fonction
  `fetchJson`, pas une seconde implémentation).
- `lib/compliance/evaluate.ts`, `violations.ts` — importés directement,
  comme dans T15.
- `backend/src/TradingOs.Host/Program.cs` — endpoints déjà existants
  (`/api/journal/trades`, `/api/risk/lockouts`), aucun nouveau.
- `scripts/run-setup-detection.ts` — second exemple de script `tsx`
  autonome dans ce paquet.

## Découpage en incréments

1. Script + calcul (stats, conformité, pires trades) — sortie console
   d'abord, pour vérifier les nombres avant de soigner le rendu.
2. Rendu Markdown + écriture fichier.
3. `npm run weekly-review` + documentation (paramètres, semaine par défaut).

## Critère de réussite

Un fichier Markdown généré pour une semaine réelle, dont chaque nombre est
vérifiable en le recoupant à la main contre les données de la base.

## Journal

- 2026-09-17 — fiche créée sur choix par défaut (aucune nouvelle question
  posée — l'utilisateur enchaîne sur « phase suivante » sans revenir sur le
  second incident de lockout signalé juste avant ; celui-ci reste ouvert et
  documenté dans `state.md`, disponible dès qu'il voudra le regarder).
  Cartographie faite : deux formulations d'origine (ticket pré-trade,
  comparaison plan/exécution) datées T04, retirées plutôt que reformulées.
  Aucune planification n'existe dans ce dépôt — catalogue.md accepte
  explicitement « CLI », retenu comme scope de ce tour. **Arrêt ici, en
  attente de validation des quatre décisions.**

- 2026-09-17 (suite) — les quatre décisions validées telles que proposées
  (« valide les quatre, enchaîne sur les incréments »). Trois incréments,
  gates vertes (tsc, lint, vitest 206/206, `next build`) :

  1. `tools/weekly-review/stats.ts` (calcul pur) — et un déplacement au
     passage : `tools/mcp-server/backend-client.ts` devient
     `tools/shared/backend-client.ts`, importé à l'identique par T15 et T08
     plutôt que dupliqué ou importé depuis le dossier d'un autre outil.
  2. `tools/weekly-review/render.ts` (Markdown pur, séparé du calcul).
  3. `tools/weekly-review/index.ts` + `npm run weekly-review` +
     `weekly-reviews/` ignoré par git (données personnelles générées, pas
     du code source).

  **Vérifié contre de vraies données, document généré inspecté.**
  `TRADING_OS_ACCOUNT_ID=477029930 npm run weekly-review -- --from=2026-09-14 --to=2026-09-16`
  contre le backend réel : 9 trades, P&L net +$25,27, 6 violations
  `LOCKOUT_ACTIVE` — exactement 5 (Daily loss guard) + 1 (kill switch), la
  somme des deux incidents de `state.md`. Fichier Markdown généré relu :
  nombres, ventilation par symbole, taux de conformité (33 %), 3 pires
  trades avec liens de capture, tout correct. T15 revérifié après le
  déplacement de `backend-client.ts` : toujours fonctionnel (même
  handshake MCP qu'à sa propre livraison).
