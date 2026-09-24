# Système de design du cockpit

Décidé le 2026-09-24 (ADR 0012), d'après la maquette de référence
`05_screenchot/dashboar.jpg`. Ce document est la référence pratique : où
sont les jetons, quel composant pour quoi, ce qui a bougé.

## Jetons — `app/globals.css`

Sombre uniquement (`<html class="dark">`), noms shadcn/ui.

| Jeton | Valeur | Usage |
|---|---|---|
| `background` | `#0b0d0c` | fond de page, presque noir à sous-ton vert |
| `card` | `#121615` | cartes, un ton au-dessus du fond |
| `muted` / `accent` | `#181d1b` / `#1c2220` | surfaces discrètes, survol |
| `foreground` / `muted-foreground` | `#edf1ef` / `#8b9591` | texte / libellés |
| `border` / `input` | blanc 7 % / 10 % | filets |
| `primary` | `#a3efcc` menthe | **le seul accent** : actif, action principale, progression |
| `warning` | `#e5c47f` or | second accent unique : attente, vigilance |
| `loss` = `destructive` | `#e7766e` corail éteint | pertes, blocages, arrêt d'urgence |
| `profit` | `#93e8c2` | gains (famille de la menthe) |
| `info` | `#9db4c9` acier | information neutre, mode mock — à peine teinté |
| `sidebar-*` | fond `#0d100f` | barre latérale |

Rayons : `--radius` 12 px ; cartes `rounded-2xl` (20 px), boutons `rounded-lg`.

Deux surfaces utilitaires (`@layer components`) :

- `.surface-card` — la carte de la maquette : éclairée par le haut ;
- `.surface-glow` / `.surface-glow-loss` — halo menthe ou corail dans le coin
  haut-droit, réservé à **la** carte qui répond à la question de l'écran.

## Composants

| Besoin | Composant |
|---|---|
| Carte d'écran (titre, icône, description, actions) | `Panel` — `components/ui/panel.tsx` |
| Tuile de chiffre (libellé, grand chiffre, pastille, barre) | `KpiCard` — `components/cockpit/kpi-card.tsx` |
| Pastille d'état teintée | `StatusPill` (sur `Badge` shadcn) |
| Barre de progression colorée par ce qu'elle mesure | `Progress` + `indicatorClassName` |
| Boutons | `Button` / `buttonVariants` |
| Champs de formulaire | `inputClass` — `components/accounts/form-controls.tsx` |
| Barre latérale | `Sidebar*` shadcn, repliable en rail d'icônes (Ctrl+B) |
| Menu du compte | `DropdownMenu` + `Avatar` |
| Icônes | `lucide-react`, trait 1.75, 18–20 px dans la navigation |

Primitives shadcn présentes : `avatar`, `badge`, `button`, `card`,
`dropdown-menu`, `input`, `progress`, `separator`, `sheet`, `sidebar`,
`skeleton`, `tooltip`. Ajouter : `npx shadcn@latest add <nom>`, jamais
`init` (ADR 0012).

## Mise en page

- Pages : `flex flex-col gap-5` ; grilles `gap-4`/`gap-5` ; contenu `p-6`.
- Titres de carte `text-sm font-medium` ; libellés et notes `text-xs`
  (plus de 10 px en capitales) ; chiffres principaux `text-3xl`–`text-5xl
  font-light` + `.tnum`.
- Un seul `highlight` par écran.

## Coque — ce qui a bougé le 2026-09-24

La barre du haut ne garde que le titre, le fil d'Ariane et le compte. Rien
n'a été retiré, tout a été placé là où il se lit :

| Élément | Avant | Maintenant |
|---|---|---|
| Taux de conformité (T07) | badge de la barre du haut | première carte du Command Center (`ComplianceCard`) |
| Prochaine publication et blackout (T03) | badge de la barre du haut | bas de la barre latérale, sur tout écran (`NewsStatus`) |
| Arrêt d'urgence (T02a) | bouton de la barre du haut | bas de la barre latérale, sur tout écran, un clic (`KillSwitchButton`) — choix de l'utilisateur |
| Liaison temps réel, persistance, environnement | quatre pastilles | pastille d'état sur l'avatar + détail dans le menu du compte (`AccountMenu`) |
| Settings | liste de navigation | épinglé en bas de la barre latérale |
| Symbole suivi | pastille | retiré — il est sur Market Context |

## Ce que la refonte a révélé

- `useJournalWindow` transformait une réponse refusée (503) en historique
  **vide**, contrairement à son propre contrat ; un historique vide vaut
  100 % de conformité, et l'ancien badge l'affichait base arrêtée. Corrigé :
  un refus est un échec (`failed`), affiché comme tel.
- La jauge de discipline et l'historique des verrous restaient en
  chargement indéfini quand la lecture échouait ; ils disent désormais que
  le backend ne répond pas.
