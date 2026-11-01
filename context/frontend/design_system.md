# Système de design du cockpit

Décidé le 2026-10-08 (ADR 0017) : « ExponentValue Monochrome », qui supersède
l'apparence de l'ADR 0012 (sombre seulement, menthe). Ce document est la
référence pratique : où sont les jetons, quel composant pour quoi, comment
composer un écran, comment vérifier.

**Une phrase** : un cockpit blanc, aéré, sobre, où un noir légèrement bleuté
porte tout ce qui est action ou mise en avant, avec un seul accent (une pastille
menthe pâle) et des couleurs franches réservées au sens.

## Jetons — `app/globals.css`

Format hexadécimal (deux composants SVG lisent `var(--profit)`… comme des
couleurs complètes), noms shadcn/ui. Clair = `:root` ; sombre = `.dark` sur
`<html>`. La source HSL de chaque valeur est en commentaire dans le fichier.

| Jeton | Clair | Sombre | Rôle |
|---|---|---|---|
| `background` / `foreground` | `#ffffff` / `#18181b` | `#0e0e10` / `#f5f5f5` | page, texte (noir neutre) |
| `card` | `#ffffff` | `#141417` | cartes |
| `primary` | `#151320` | `#f5f5f5` | **la couleur d'action** (boutons) ; s'inverse en sombre |
| `muted` / `muted-foreground` | `#f4f4f5` / `#6c6c75` | `#1f1f23` / `#9c9ca5` | surfaces et texte secondaires (5,2:1 sur blanc) |
| `accent` / `secondary` | `#efeff0` / `#f3f3f4` | `#27272b` / `#222225` | survol, boutons gris |
| `border` / `input` / `ring` | `#e4e4e7` / `#dfdfe2` / `#a1a1aa` | `#27272b` / `#303036` / `#6d6d78` | filets, champs, focus |
| `sidebar*` | `#f6f4f5` (gris à peine rosé) | `#121214` | barre latérale |
| `panel*` | `#151320` | `#1e1d26` | **surfaces sombres** : panneau de métriques, bandeau, en-têtes de tableau — sombres dans les deux thèmes |
| `panel-highlight` | `#e7f3ee` | idem | la pastille menthe : **une seule par panneau** |
| `panel-success` / `-warning` / `-destructive` | `#54d498` / `#fab742` / `#f47171` | idem | sens, lisibles sur fond sombre |
| `success` / `warning` / `destructive` | `#1b744a` / `#9f5704` / `#ca2121` | `#37be7f` / `#f6a328` / `#ec5151` | sens, sur fond clair (≥ 5,4:1) |
| `profit` / `loss` | = `success` / = `destructive` | idem | sens trading ; noms conservés de l'ADR 0012 |
| `info` | `#52637a` (ardoise à peine teintée) | `#99abc2` | information neutre (« simulé », « coïncide avec S01 ») |
| `chart-1…5` | `#151320`, `#b9b9c0`, `#259d65`, `#6f6f7b`, `#f98806` | `#ebebeb`, `#52525b`, `#39c684`, `#94949e` | barres positives (quasi-noir), négatives (gris), courbe |

Règles : **le noir bleuté est sur des aplats, jamais sur du texte** ; aucune
couleur codée en dur dans une page (`grep` d'un hexadécimal ou d'un
`text-red-500` dans `app/` et `components/` ne doit rien trouver) ; une seule
pastille `solidIcon` par `MetricPanel`.

**Contrastes** (WCAG, mesurés sur les jetons le 2026-10-08, 44 paires, deux
thèmes) : toutes ≥ 4,5:1. Les couleurs sémantiques claires sont plus sombres que
celles du design d'origine (voir ADR 0017) ; en sombre, le texte d'un aplat
`destructive` / `success` / `warning` est sombre, pas blanc.

## Typographie, formes, espacements

- **Inter** variable, auto-hébergée (`@fontsource-variable/inter`),
  `font-feature-settings: "cv11", "ss01"`. Chiffres tabulaires sur toute valeur
  numérique (`tabular-nums`, ou `.tnum`).
- Titre de page `text-2xl sm:text-[1.75rem] font-semibold tracking-tight` ; section
  (h2) `text-xl` ; titre de carte `text-sm font-semibold` ; corps `text-sm` ;
  libellé de champ `text-[0.8125rem]` gris ; micro-texte `text-xs`.
- **Échelle : un seul réglage.** Toute taille est en `rem` (les classes Tailwind, et les
  quelques valeurs arbitraires — jamais de `px` pour un texte, une icône ou une hauteur de
  squelette). `html { font-size: 106.25% }` (`app/globals.css`) fait donc grandir texte,
  icônes et espacements ensemble : 17 px au lieu de 16 px depuis le 2026-11-01 (« un peu plus
  grand »). Pour changer l'échelle, c'est cette ligne et nulle part ailleurs ; elle suit le
  réglage de taille du navigateur de l'utilisateur, et les points de rupture (media queries)
  ne bougent pas. Les valeurs `0.6875rem` / `0.8125rem` / `1.75rem` sont les anciens 11 / 13 / 28 px.
- Rayon `--radius: 0.625rem`. Cartes, panneaux, tableaux `rounded-xl` ; boutons,
  champs, badges `rounded-md` ; navigation `rounded-lg` ; pastilles `rounded-full`.
- Une carte = `border` + `shadow-xs` ; le panneau sombre n'a pas de bordure
  (`shadow-sm`). Pas d'ombre portée marquée : la profondeur vient de la couleur et
  du filet.
- Page `px-4 sm:px-6 lg:px-10`, `py-8 lg:py-10` ; entre grandes sections `gap-10` ;
  grilles `gap-6` ; cartes empilées `gap-4`. Focus : anneau de 3 px sur tout élément
  interactif (`focus-visible:ring-[3px] ring-ring/40`).
- Icônes **Lucide**, `size-4` dans l'interface ; l'icône d'un champ de formulaire ou
  d'un bouton ne porte jamais seule le sens (`aria-label`, ou `aria-hidden` si
  décorative).

## Thème

`app/layout.tsx` pose la classe `dark` avant le premier rendu (script en ligne dans
`<head>` : préférence enregistrée `localStorage.theme`, sinon celle du système) ;
`components/shell/theme-toggle.tsx` bascule la même classe et la même clé. La
bascule rend les deux icônes et laisse `dark:` choisir : aucun état React, aucun
écart d'hydratation, aucun flash.

## Coque — `components/shell/`

| Zone | Composant | Notes |
|---|---|---|
| Barre latérale (≥ `lg`) | `SidebarNav` dans `CockpitShell` | 16 rem, fixe, `bg-sidebar`. Écrans groupés Opérer / Analyser / Système ; élément actif = blanc surélevé |
| Tiroir (< `lg`) | `MobileNav` | le même `SidebarNav` dans un `Sheet` ; un clic sur un lien le ferme |
| Barre du haut | `SiteHeader` | 4 rem, collante, floutée ; fil d'Ariane à gauche (≥ `lg`), à droite le compte (`AccountMenu`), le thème, le hamburger |
| Contenu | `CockpitShell` | `max-w-6xl`, le **même** conteneur pour la barre, la page et le pied de page |
| Titre de page | `PageHeader` | `screen={screenAt("/risk")}` : le nom de l'écran + la question à laquelle il répond (`nav.ts`) ; ou `title` / `subtitle` / `icon` / `actions` |
| Section | `SectionHeading` | h2 avec la même sous-ligne à icône |

**La sécurité ne suit pas l'esthétique.** Épinglés en bas de la barre latérale
**et du tiroir** : le statut des publications (`NewsStatus`, T03), l'arrêt
d'urgence (`KillSwitchButton`, T02a) et Settings. Les bannières de verrou
(`LockoutAckBanner`, `LockoutViolationBanner`) restent pleine largeur au-dessus du
contenu. Où est passé ce qui a changé de place :

| Élément | Où il se lit maintenant |
|---|---|
| Taux de conformité (T07) | métrique « Conformité au plan » du panneau du Command Center ; titre de `/analyse` et dans `/journal` |
| Liaison temps réel, persistance, environnement | pastille d'état sur l'avatar + détail dans `AccountMenu` |
| Neuf gates du Risk Engine | `/risk` (`RiskGatesPanel`) et `/preflight` |
| Rapprochement S01 / réel, propositions | `/setups` (`SetupsScreen`) |

## Composants

| Besoin | Composant | Fichier |
|---|---|---|
| Action principale / grise / contour | `Button` (`default`, `secondary`, `outline`) | `ui/button.tsx` |
| Carte d'écran (titre, icône, description, actions) | `Panel` | `ui/panel.tsx` |
| LE chiffre de l'écran | `HighlightBar` | `ui/metric-panel.tsx` |
| Chiffres clés (3 à 5) | `MetricPanel` + `MetricPanelItem` (`tone`, `progress`, `solidIcon`) + `MetricPanelList` | `ui/metric-panel.tsx` |
| Contenu 3/5 + panneau 2/5 | `SplitLayout` (`stickyAside`, `asideFirstOnMobile`) | `ui/split-layout.tsx` |
| Liste principale | `DataList` (tableau à en-tête sombre dès `md`, cartes dessous) + `MobileCardHeader`, `MobileFields`, `Monogram` | `ui/data-list.tsx`, `ui/table.tsx` |
| Note « Important » / avertissement | `Callout` (`variant="warning"`) | `ui/callout.tsx` |
| Rien à montrer | `EmptyState` | `ui/empty-state.tsx` |
| Filtres d'une liste | `FilterBar` + `FilterField`, contrôles en `filterFieldClass` | `ui/filter-bar.tsx`, `ui/input.tsx` |
| Champ de formulaire | `Input`, `fieldClass`, `Field` | `ui/input.tsx`, `accounts/form-controls.tsx` |
| Pastille d'état (point + texte) | `StatusPill` (`onPanel` sur fond sombre) | `ui/status-pill.tsx` |
| Barre de progression | `Progress` | `ui/progress.tsx` |
| Chargement | `Skeleton` | `ui/skeleton.tsx` |

Primitives shadcn présentes : `avatar`, `badge`, `button`, `card`,
`dropdown-menu`, `input`, `progress`, `separator`, `sheet`, `skeleton`,
`tooltip`. Ajouter : `npx shadcn@latest add <nom>`, jamais `init` (ADR 0012).
La barre latérale n'est plus le composant `Sidebar` de shadcn (lourd, supprimé).

## Composer un écran

```
PageHeader
SplitLayout            contenu 3/5 · panneau sombre 2/5 (collant si l'écran est long)
  HighlightBar + MetricPanel        ← les chiffres clés, dans la même colonne
section(s) pleine largeur           DataList, répartitions, calendriers…
Callout « Important »               ce que les chiffres de l'écran ne veulent PAS dire
```

| Écran | Chiffre du bandeau | Panneau (★ = pastille menthe) |
|---|---|---|
| `/` Command Center | Equity | P&L du jour · Marge avant verrou · Conformité au plan ★ · Positions ouvertes |
| `/preflight` | `n / 9` points au vert | Verdict de séance ★ · Points bloquants · Verrou |
| `/market-context` | biais du marché | Score de contexte ★ · Session · Structure · Prochaine publication |
| `/positions` | positions ouvertes | P&L latent · Positions externes · Commandes UNKNOWN ★ |
| `/risk` | état du risque | Perte du jour · Drawdown · Trades du jour · Pertes consécutives ★ |
| `/journal` | trades clôturés | Dans le cadre ★ · Pris sur une proposition S01 · Avec capture · Résultat réalisé |
| `/journal/[id]` | symbole de la capture | Entrée ★ · Stop · Objectif · Sortie |
| `/analyse` | conformité sur la période | Trades en manquement ★ · Trades clôturés · Résultat net · Taux de réussite |
| `/setups` | évaluations de S01 | Propositions · Bloquées · Proposé et pris ★ · Pris sans proposition |
| `/account` | equity du compte connecté | Profil reconnu ★ · Capital de référence · Perte journalière max · Marge avant le plancher |
| `/agents` | agent d'exécution | Observateur MT5 ★ · Latence · Dernier battement · Rapports d'exécution |
| `/settings` | « à l'enregistrement » : Immédiat / Différé | Challenge FTMO · Capital Exness · Changement en attente ★ · Versions |

Chaque écran garde **sa question** (`question` de `nav.ts`) comme sous-titre : un
écran, une question (`information_architecture.md`).

## Règles

- **Vide ≠ erreur.** `EmptyState` : « il n'y a rien ». `Callout variant="warning"` :
  « on n'a pas pu demander » (backend injoignable). Un historique illisible ne
  s'affiche jamais comme un historique vide : tirets dans le panneau, jamais des
  zéros (`0 / 0`, `+$0.00` en vert disent un résultat qui n'existe pas).
- **Le produit passe avant la mise en page** : la discipline avant le P&L (ADR 0001),
  aucune métrique de performance sur `/setups` (ADR 0011), aucun indicateur agrégé
  dans le journal (T06, décision 1).
- **Mobile** : `grid-cols-1` explicite sous le point de rupture (une grille sans
  colonnes explicites s'élargit au contenu `nowrap` et fait déborder la page),
  `min-w-0` sur les enfants flex qui tronquent ; en Tailwind 4, `flex-1` (base 0 %)
  l'emporte sur `basis-*` — écrire `flex-[1_1_7rem]` pour une vraie base. Une valeur
  qui est une information (code de verrou, date, instruction) **s'enroule**, elle ne
  se tronque pas ; seule une étiquette secondaire peut l'être, avec un `title`.
- **Un texte JSX qui suit `{expression}` et s'étend sur plusieurs lignes perd son
  espace initial** : écrire `{error}{" "}` puis le texte.
- **Langue** : le texte de l'interface est en français ; les noms d'écrans hérités
  (Command Center, Market Context, Account, Settings) et les noms de gates du
  Risk Engine restent tels quels.

## Vérifier

Une refonte se vérifie dans un navigateur, pas au compilateur : `tsc`, `eslint`,
`vitest`, puis chaque écran en 1440×900 clair et sombre et en 375×812 clair et
sombre, avec ses états rempli / vide / backend éteint — aucun débordement
horizontal, aucun texte important tronqué, thème conservé au rechargement sans
flash, anneau de focus visible, console propre. Le panneau navigateur du poste est
trop étroit (≈ 390 px) pour juger le desktop : piloter Chrome en headless
(DevTools Protocol) donne de vraies captures. Les écrans alimentés par HTTP se
voient sans backend avec un faux serveur en **lecture seule** et à données
synthétiques sur le port 5080 (jamais de numéro de compte réel). Le détail de la
dernière campagne est dans `session-log.md` (2026-10-08).

## Ce que les refontes ont révélé

- `useJournalWindow` transformait une réponse refusée (503) en historique
  **vide**, contrairement à son propre contrat ; un historique vide vaut
  100 % de conformité, et l'ancien badge l'affichait base arrêtée. Corrigé le
  2026-09-24 : un refus est un échec (`failed`), affiché comme tel.
- La jauge de discipline et l'historique des verrous restaient en
  chargement indéfini quand la lecture échouait ; ils disent désormais que
  le backend ne répond pas.
- 2026-10-08 : `muted-foreground` sur `muted` faisait 4,40:1 (les pastilles grises) ;
  la procédure de connexion de `/settings` débordait de 155 px sur mobile (grille
  sans colonne explicite) ; le graphique de capture avait une largeur fixe de 720 px
  (il s'adapte maintenant à son conteneur) ; le journal affichait les paires forex à
  deux décimales (entrée et sortie identiques) ; des valeurs-clés (`$10,15…`), des
  symboles (`EURU…`) et des instructions étaient coupés par une ellipse.
