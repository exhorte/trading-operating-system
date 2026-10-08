# ADR 0017 — Système de design : « ExponentValue Monochrome »

Date : 2026-10-08. Statut : **accepté** — décision de l'utilisateur : refondre
toute la plateforme en appliquant le skill `ui-redesign-from-reference` en mode
par défaut (aucun modèle visuel fourni). Supersède l'ADR 0012 pour
**l'apparence** (palette sombre-seulement et menthe, surfaces éclairées avec
halo, rayons 12/20 px, barre latérale shadcn repliable) ; l'ADR 0012 tient pour
le reste : shadcn/ui, Radix, Lucide, `cn`, `npx shadcn@latest add` et jamais
`init`, les quatre jetons de sens trading. Amende l'ADR 0003 là où le cockpit y
est « sombre » : il a maintenant un thème clair **et** un thème sombre.

## Contexte

Le design de l'ADR 0012 (24 septembre) était dérivé d'une maquette de prop
firm : tout en sombre, un accent menthe, des cartes éclairées par le haut. Le
2026-10-08 l'utilisateur demande de redessiner la plateforme avec le design
système du projet `exponentvalue-roi-app`, « ExponentValue Monochrome », livré
par le skill : un SaaS financier **monochrome, aéré, sobre**, où un noir
légèrement bleuté porte tout ce qui est action ou mise en avant. Aucune maquette
n'est fournie : le skill appliqué est donc son design par défaut, sans demander
de modèle, avec contrôle de conformité plutôt que réapplication quand les
jetons y sont déjà (ce qui était le cas à la reprise de la session).

## Décision

**Le cockpit adopte le design « ExponentValue Monochrome » : thème clair et thème
sombre dérivés des mêmes jetons, une coque à barre latérale fixe, et une
composition d'écran unique — le contenu à gauche, les chiffres clés dans un
panneau sombre à droite.**

**Couleurs** (`app/globals.css`). Le noir bleuté `#151320` est la couleur
d'**action** : boutons principaux, panneau de métriques, en-têtes de tableau. Il
habille des surfaces, jamais du texte. **Un seul accent** : la pastille menthe
pâle `#e7f3ee`, sur *une* métrique par panneau. Les couleurs franches ne servent
que le sens — succès, alerte, erreur — et, côté trading, `profit` (= succès),
`loss` (= erreur), `warning`, `info` (ardoise à peine teintée). La profondeur
vient de la couleur et du filet de 1 px, pas de l'ombre (`shadow-xs`).

**Format des jetons : hexadécimal**, et non les triplets HSL du design par
défaut. Deux composants SVG (la jauge de discipline, le graphique de capture)
lisent `var(--profit)`, `var(--card)`… comme des couleurs complètes, ce que des
triplets casseraient. La source HSL de chaque valeur est en commentaire.

**Thème.** `.dark` sur `<html>`, posé avant le premier rendu par un script en ligne
(`app/layout.tsx`) : le choix enregistré (`localStorage.theme`) sinon la
préférence du système. La bascule rend les deux icônes et laisse `dark:` choisir :
aucun état React, aucun écart d'hydratation. Les panneaux sombres restent sombres
dans les deux thèmes.

**Typographie.** Inter variable, auto-hébergée (`@fontsource-variable/inter`, seule
dépendance ajoutée), chiffres tabulaires sur toute valeur numérique.

**Coque** (`components/shell/`). Barre latérale de 16 rem, fixe, visible dès `lg`
(`bg-sidebar`), tiroir dessous ; barre du haut de 4 rem, collante, floutée ; contenu
dans un même conteneur `max-w-6xl` pour la barre, la page et le pied de page, de
sorte que leurs bords s'alignent. **La sécurité ne suit pas l'esthétique** (même
principe que l'ADR 0012) : le statut des publications, l'**arrêt d'urgence** et
Settings sont épinglés en bas de la barre latérale **et du tiroir**, atteignables de
tout écran en un clic ; les bannières de verrou restent pleine largeur au-dessus du
contenu.

**Composition d'un écran.** `PageHeader` (titre, et sous-titre = la question à
laquelle l'écran répond, `question` de `components/shell/nav.ts`), puis `SplitLayout`
— contenu 3/5, panneau sombre 2/5 (`HighlightBar` pour LE chiffre de l'écran,
`MetricPanel` pour les 3 ou 4 qui le complètent), collant sur les écrans longs —
puis les listes pleine largeur (`DataList` : tableau à en-tête sombre dès `md`, cartes
au-dessous) et un `Callout` « Important » qui dit ce que les chiffres de l'écran ne
veulent **pas** dire. Écrans de résultat : le panneau passe avant le détail sur
mobile.

**Un état vide n'est pas une erreur.** `EmptyState` ne sert qu'à dire « il n'y a
rien à montrer ». Un backend injoignable est un `Callout variant="warning"` : « rien
ne s'est passé » et « on n'a pas pu demander » ne doivent jamais se ressembler (même
règle que `useJournalWindow`, qui transforme un refus en échec et non en historique
vide).

**Les règles produit passent avant la mise en page.** Elles ont été conservées
écran par écran : la discipline avant le P&L (ADR 0001) — l'en-tête de `/analyse` et
de `/journal` est la conformité, le résultat vient après ; aucune métrique de
performance sur `/setups` (ADR 0011) ; aucun indicateur agrégé dans le journal
(fiche T06, décision 1).

### Écarts assumés par rapport au design par défaut

| Écart | Raison (mesurée) |
|---|---|
| Couleurs sémantiques assombries en clair : `destructive` `#ca2121`, `success` `#1b744a`, `warning` `#9f5704` | Les valeurs du design (`#dc2828`, `#218c5a`, `#d17205`) font 4,8 / 4,2 / 3,4:1 sur blanc, et moins sur leur propre teinte à 10 % : un petit libellé y échoue au seuil AA. Ici : 5,60 / 5,76 / 5,47:1 sur blanc, 4,77 / 5,00 / 4,75 sur la teinte |
| `muted-foreground` `#6c6c75` (design : `#71717a`) | `#71717a` fait 4,40:1 sur `muted`, où les pastilles grises (« Non connecté », « Défaut du code ») posent leur texte de 11 px. `#6c6c75` : 5,20 sur blanc, 4,73 sur `muted`, 4,69 sur `secondary`, 4,52 sur `accent`, 4,75 sur la barre latérale |
| En sombre, `destructive` `#ec5151`, `success` `#37be7f`, `warning` `#f6a328` portent un texte sombre sur aplat | Le blanc sur le rouge clair ne ferait que 3,6:1 ; le texte sombre en fait 5,2 |
| Logo : monogramme « TO » | Marque du projet ; rien de la marque ExponentValue n'est repris, aucune mention de réassurance (« hébergé en UE », « formules traçables ») n'est reprise : aucune n'est vraie ici |

Contrastes mesurés le 2026-10-08 sur les valeurs de `app/globals.css` (44 paires,
deux thèmes) : toutes ≥ 4,5:1 après le correctif de `muted-foreground`.

## Conséquences

- **Une dépendance ajoutée** : `@fontsource-variable/inter`. Rien d'autre.
- **Supprimés** (aucune référence restante, `tsc` propre) : le composant `Sidebar`
  shadcn et son hook (`components/ui/sidebar.tsx`, `hooks/use-mobile.ts`),
  `components/shell/app-sidebar.tsx`, et les composants remplacés par le panneau
  sombre — `kpi-card`, `kpi-strip`, `compliance-card`, `risk-status-panel`
  (devenu `risk-gates-panel` + `risk-metrics`), `reconciliation-view` et
  `setup-proposals-panel` (devenus `setups-screen`). Le taux de conformité n'est
  plus une carte à part : c'est une métrique du panneau du Command Center.
- **Vocabulaire commun** pour tout écran futur, y compris ceux que le design n'a pas
  prévus : `PageHeader`, `SplitLayout`, `MetricPanel`, `Panel`, `DataList`,
  `Callout`, `EmptyState`, `FilterBar`, `StatusPill`. Voir
  `context/frontend/design_system.md`.
- **Points laissés ouverts** par le design lui-même, non tranchés ici et à ne pas
  modifier sans l'utilisateur : colonnes 50/50 au lieu de 3/5–2/5, suppression des
  `shadow-xs`, valeurs du panneau en monochrome strict (aujourd'hui le P&L est
  coloré en vert ou rouge sur le panneau), échelle plus grande (texte 16 px,
  boutons de 64 px), style de l'élément de navigation actif. L'utilisateur peut
  fournir un modèle visuel à tout moment : le skill bascule alors en mode modèle.
- **Vérifié** (voir `session-log.md`, 2026-10-08) : types, lint, tests ; chaque écran en
  1440×900 clair et sombre et en 375×812 clair et sombre, sans débordement
  horizontal ni message de console hors réseau. **Non vérifié** : le cockpit contre
  le vrai backend (éteint depuis le 2026-09-28) — les écrans alimentés par HTTP ont
  été vus contre un faux serveur en lecture seule, à données synthétiques.
- **Retour arrière** : par git. Le design est entièrement porté par `app/globals.css`
  et `components/` ; aucune logique métier (`lib/`) n'a été modifiée, à une exception
  d'affichage près (`lib/format.ts` gagne `formatQuote`, la cotation à sa précision).
