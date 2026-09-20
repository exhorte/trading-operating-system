# Références visuelles — journal TradeZella & FTMO (2026-09-20)

Complète `visual_reference_analysis.md` (templates TradeZella de septembre).
Sources : `05_screenchot/` — `journal interace.png`, l'export PDF
« Analyse de compte 511333949 » et l'export PDF « Account MetriX 511333949 ».

Inspiration seulement. Le produit reste le *process* (ADR 0001) : on emprunte
des structures d'écran, jamais la hiérarchie de valeurs de ces outils, qui
placent tous les trois le P&L au centre.

---

## Modèle 1 — Journal de trades (type TradeZella), thème sombre

### Structure observée

| Zone | Contenu |
|---|---|
| Rail gauche | icônes seules, ~48 px, pas de libellés |
| Barre de filtres | chips-dropdowns horizontales : Symbol, Setup, Side, Mistake, Status, Portfolio, Date, Custom Tags, More… + bouton primaire « Add Trade » |
| Bandeau KPI | 3 cartes héros avec sparkline *dans* la carte : Accumulative Return Net $, Profit/Loss Ratio, Win % (donut) |
| Table | checkbox · chevron d'expansion · chip STATUS (WIN/LOSS/OPEN) · chip SIDE (LONG/SHORT) · symbole · dates · entry/exit · size · cost · net return $ coloré · net % · chips SETUPS · NOTE · MISTAKES · ⚙ config colonnes |
| Rail droit | Account Performance (AVG RETURN / AVG RETURN % / WIN % + courbe d'equity) ; **Setups** : liste + barre horizontale de P&L par setup ; **Mistakes** : idem par erreur ; pagination « 1 of 5 » + « View Report » |
| Footer collant | « Trades: 100/3952 » à gauche, « Return: $208,529.98 » à droite |

### Ce qui transfère

1. **Les filtres comme objets de première classe.** Aujourd'hui `/journal` n'a
   que From/To/Symbol dans une carte « FILTERS ». La barre de chips condense
   plus de dimensions dans moins de hauteur et se lit d'un coup d'œil.
2. **Le rail droit d'attribution.** C'est le vrai apport de ce modèle : à côté
   de la table, une ventilation *par cause* avec barre proportionnelle.
   Chez nous les deux axes ne sont pas « setups » et « mistakes » au sens P&L
   mais **Setups S01 (proposé / pris / accord)** et **Violations T07**.
3. **Le footer collant** (n/total + agrégat) — on a la donnée, pas le bandeau.
4. **Chevron d'expansion par ligne** : ouvrir le détail sans quitter la table.

### Ce qu'on refuse

- L'attribution en dollars par erreur (« fomo : $5,367.48 ») : chez nous une
  violation n'a pas de prix, elle a un compte et une gate.
- Le bouton « Add Trade » : nos trades viennent de MT5, jamais d'une saisie.
- Le duo teal/rose comme couleurs porteuses de sens — notre palette
  vert/rouge/ambre est déjà sémantique (`final_interface_spec.md`).

---

## Modèle 2 — FTMO « Analyse de compte », thème clair, rapport narratif

### Structure observée

Un motif unique répété onze fois :

```
[ carte de prose qui explique la dimension ]
[ tableau ]                 [ graphique ]
```

Dimensions couvertes, dans l'ordre : informations de base + courbe du solde ·
statistiques générales (Résultat, Taux de réussite, Profit moyen, Perte
moyenne, RRR, Profit Max., Perte Max.) · comparaison Achat/Vente (avec courbes
séparées) · **résultats par jour, distingués par Fermeture *et* par Ouverture**
· résultats par instrument (split acheteurs/vendeurs) · analyse jours de
trading (nb jours, moy. trades/jour, jours positifs/négatifs) · résultats par
taille de position · **résultats par durée de trade** (00:00–00:02, 00:02–00:05,
00:05–00:15…) · résultats par heure d'ouverture · évaluation finale
(Objectifs / Résultats / État ✅❌).

### Ce qui transfère

1. **La prose adossée au chiffre.** « During the evaluation period, you traded
   2 different position volumes. Most often, your positions were sized at 0.2
   lot with a result of −$1,023.22. » C'est exactement le `explainable` de
   `final_interface_spec.md`, et c'est mécaniquement générable depuis nos
   données. **T08 (`npm run weekly-review`) produit déjà ce genre de texte en
   Markdown.** Formulation corrigée après implémentation : l'écran n'est *pas*
   « T08 rendu ». T08 ne calcule ni durée, ni taille de position, ni jour
   d'ouverture contre jour de fermeture — ces ventilations-là ont demandé un
   module à part (`lib/account-analysis/`). Ce qui est partagé, ce sont les
   données et les détecteurs de conformité, pas le calcul.
2. **Fermeture vs Ouverture comme deux colonnes distinctes.** Un trade ouvert
   lundi et fermé mardi n'appartient pas au même jour selon la question posée.
   Notre journal ne fait pas cette distinction aujourd'hui.
3. **Les ventilations qu'on n'a pas** : par durée, par taille de position, par
   heure d'ouverture avec fuseau explicite. `/journal` ventile déjà par
   symbole / session / heure / jour ; durée et taille manquent.
4. **L'évaluation finale** en fin de rapport : objectif → résultat → état.

### Ce qu'on refuse

- Le thème clair et le format « rapport figé » : notre spec interdit
  explicitement que le cockpit se réduise à un rapport statique.
- La granularité en lots seuls : chez nous le risque se lit en % et en R.

---

## Modèle 3 — FTMO « Account MetriX », thème clair, dashboard live

### Structure observée

| Bloc | Contenu |
|---|---|
| Résultats actuels | Solde · Equity · PnL non réalisé |
| Graphe equity | contrôles inline : « Lignes des Objectifs » Activé/Désactivé, « Valeurs PnL » Absolu/%, « Dézoomer » ; **les seuils d'objectif sont dessinés sur le graphe** (bande rouge = zone de perte max, ligne bleue = solde) |
| Panneau Challenge | Résultat (chip « Non validé ») · Statut · 2-Step · dates · taille · type · plateforme |
| **Score de discipline** | jauge semi-circulaire, 63 %, libellé « Bon », bandes 0–30 rouge / 30–80 orange / 80–100 vert |
| Objectifs | Objectif de Trading · Résultat · État ✅/❌ |
| Bandeau de violation | rouge, texte explicite de la règle enfreinte et de la conséquence |
| Statistiques | grille de 11 tuiles, chacune avec ⓘ : Equity, Solde, Taux de réussite, Profit moyen, Perte moyenne, Nombre de trades, Lots, Ratio de Sharpe, RRR moyen, Valeur attendue, Facteur de profit |
| Résumé quotidien | Date · Trades · Lots · Résultat |
| Journal de Trading | onglets **PnL Journalier** (calendrier mensuel, cellule = montant + « Trades: 8 ») / **Trades clôturés** / **Graphiques** ; en-tête : mois ‹ › + « Statistiques mensuelles » + « Jours de trading: 4 » |
| Calendrier économique | événements du jour, lien vers la semaine |

### Ce qui transfère — c'est le modèle le plus proche de notre produit

1. **Le Score de discipline est notre écran-titre.** FTMO met une jauge de
   discipline à côté du P&L ; nous, la discipline *est* le produit (ADR 0001).
   On a déjà la donnée : `ComplianceBadge` (T07) affiche le taux de conformité
   hebdomadaire en haut du cockpit. La jauge à bandes lui donne une surface.
2. **Les objectifs dessinés sur la courbe d'equity**, avec bascule
   Activé/Désactivé. Nos 9 gates ont toutes un seuil numérique : les tracer sur
   la courbe rend le « combien il me reste avant le verrou » visible sans calcul.
3. **La grille de tuiles avec ⓘ.** Chaque métrique porte sa définition. Notre
   spec demande `explainable` ; c'est le moyen le moins cher de l'obtenir.
4. **Les onglets du journal** (PnL / Trades / Graphiques) : trois vues sur le
   même jeu filtré, au lieu d'un empilement vertical.
5. **Le bandeau de violation** : on a déjà `LockoutViolationBanner` et
   `LockoutAckBanner` (T02c) — la forme FTMO confirme le choix.

### Ce qu'on refuse

- Les métriques de performance pure (Sharpe, facteur de profit, valeur
  attendue) en position haute : ce sont des chiffres de *résultat*, pas de
  *process*. À garder, mais sous la discipline, jamais au-dessus.
- Le cadre « Challenge » figé : notre registre de comptes est vide à ce jour.

---

## Cartographie vers nos écrans

| Notre écran | État au 2026-09-20 | Référence | Adaptation proposée |
|---|---|---|---|
| Command Center | construit, dense, tient en un viewport | MetriX (haut) | courbe d'equity avec lignes d'objectifs ; ⓘ sur les tuiles KPI |
| **Risk Monitor** | **vide** (« not built yet ») | **MetriX (jauge + objectifs + violation)** | **meilleur candidat** : jauge de discipline T07, table des 9 gates avec état, historique des lockouts et de leurs acquittements |
| Trades Journal | construit, vide en mock | Journal + MetriX (onglets) | barre de filtres en chips ; rail droit d'attribution Setups S01 / Violations T07 ; onglets PnL / Trades / Graphiques ; footer collant |
| **Analyse de compte** | **livré 2026-09-20** (`/analyse`) | **Analyse de compte FTMO** | ventilations durée / taille / heure / jour (ouverture *et* fermeture) / sens / instrument, chacune avec sa phrase générée ; discipline en tête, aucun conseil, aucune table de trades |
| Pré-vol | construit, sobre | MetriX (objectifs) | déjà conforme ; éventuellement la distance au seuil, pas seulement l'état |
| Market Context | vide | aucune des trois | hors périmètre de ces références |
| Replay | vide | `reference-trade-replay.webp` (ancien lot) | inchangé |

## Anti-patterns à tenir

Ceux de `visual_reference_analysis.md` restent valables, plus :

- **Ne pas classer par dollars ce qui se juge en conformité.** L'attribution
  par cause se fait en nombre d'occurrences et en gate, pas en P&L.
- **Ne pas dupliquer le moteur de T08** pour faire l'écran d'analyse.
- **Ne pas remonter Sharpe / facteur de profit au-dessus de la discipline.**

## Contrainte d'itération — levée le 2026-09-20

Le serveur mock servait `accountId: "account-001"`, qui n'a aucune ligne en
base : `/journal`, `/positions`, `/analyse` et le badge de conformité y
étaient donc vides en permanence, et la préversion mock inutilisable pour
travailler ces écrans-là.

`lib/mock/initial-snapshot.ts` lit désormais `NEXT_PUBLIC_MOCK_ACCOUNT_ID`,
avec `"account-001"` comme valeur par défaut. Renseignée dans `.env.local`
(gitignoré), elle fait lire à ces écrans les vraies lignes du compte pendant
que l'equity, les positions et les ticks restent scriptés ; le libellé du
compte passe alors à « Compte réel — flux simulé » pour que le mélange soit
visible.

**Jamais une constante.** `.claude/CLAUDE.md` : « Aucun identifiant de compte
n'est jamais demandé, stocké ou partagé ». `.env*` est gitignoré, `.env.example`
documente la variable sans valeur.
