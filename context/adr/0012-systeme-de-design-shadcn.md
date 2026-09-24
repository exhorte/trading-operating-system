# ADR 0012 — Système de design : shadcn/ui

Date : 2026-09-24. Statut : accepté. Amende l'ADR 0003 sur deux points : la
clause « toute nouvelle dépendance runtime frontend doit se justifier ; à ce
jour la seule est `@microsoft/signalr` », et le cockpit « sombre, dense,
opérationnel ». Le reste de l'ADR 0003 tient intégralement.

## Contexte

Le 2026-09-24, l'utilisateur demande une refonte visuelle du cockpit
d'après une maquette de référence (`05_screenchot/dashboar.jpg`, un
dashboard de prop firm) : icônes modernes et lisibles, Settings en bas de la
barre latérale, cartes qui remplissent l'espace, barre du haut réduite au
seul compte, palette discrète — et **la bibliothèque shadcn/ui**, nommément.

Jusque-là, le cockpit n'avait qu'une poignée de primitives maison
(`card`, `status-pill`, `skeleton`, `empty-state`), des icônes SVG dessinées
à la main, et des jetons de couleur dont deux noms (`muted`, `accent`)
entraient en conflit avec ceux de shadcn/ui.

## Décision

**Le cockpit est construit sur shadcn/ui.** Les composants sont copiés dans
`components/ui/` (on possède leur code, principe de shadcn) et configurés
par `components.json`. Nouvelles dépendances runtime, toutes justifiées par
cette demande :

| Paquet | Rôle |
|---|---|
| `radix-ui` | primitives accessibles derrière les composants (menu, tooltip, sheet, avatar, progress…) |
| `lucide-react` | icônes au trait — la bibliothèque par défaut de shadcn/ui |
| `class-variance-authority` | variantes des composants (`buttonVariants`, `badgeVariants`) |
| `cn` | fusion de classes Tailwind (paquet officiel `shadcn-ui/cn`, remplace `clsx` + `tailwind-merge`) |
| `tw-animate-css` (dev) | animations d'ouverture des menus et tooltips |

**Jetons** : ceux de shadcn/ui (`background`, `card`, `primary`, `muted`,
`muted-foreground`, `accent`, `border`, `ring`, `sidebar-*`, `chart-*`),
plus quatre jetons de sens trading qui ne se devinent pas : `profit`,
`loss`, `warning`, `info`. Sombre uniquement (`<html class="dark">`).

**Palette** : un seul accent (menthe) pour ce qui compte — élément actif,
action principale, valeur positive, progression — un or discret comme seul
second accent, un corail éteint pour les pertes et les blocages ; tout le
reste en blancs et gris. Pas de nouvelle couleur sans un sens trading.

**Le cockpit reste sombre et opérationnel ; il n'est plus dense.** Cartes
aérées, grands chiffres, un écran = une question
(`information_architecture.md`) — la densité n'était pas une valeur, la
lisibilité en est une.

## Conséquences

- **Ajouter un composant** : `npx shadcn@latest add <nom>` — jamais
  `shadcn init`, qui réécrirait `app/globals.css` et ses jetons. Relire le
  diff de `globals.css` après chaque ajout. Le code généré obéit aux règles
  du dépôt : deux corrections ont été nécessaires dès l'installation
  (`hooks/use-mobile.ts` réécrit sur `useSyncExternalStore`, largeur
  déterministe dans `SidebarMenuSkeleton`) pour passer `react-hooks`.
- **Une carte d'écran est un `Panel`** (`components/ui/panel.tsx`, bâti sur
  la `Card` shadcn) ; une tuile de chiffre est un `KpiCard`
  (`components/cockpit/kpi-card.tsx`). Un seul `highlight` par écran.
- **La sécurité ne suit pas l'esthétique.** Ce qui quittait la barre du
  haut a été déplacé, jamais retiré : conformité (T07) en première carte du
  Command Center ; calendrier et blackout (T03) et arrêt d'urgence (T02a)
  en bas de la barre latérale, visibles et à un clic depuis tout écran ;
  état de la liaison et de la persistance sur la pastille du compte. Les
  bannières de verrou restent pleine largeur, au-dessus de tout.
- L'ADR 0003 garde tout le reste : monolithe, backend .NET, SignalR, bord
  MT5 en lecture, aucun identifiant partagé.
- Référence pratique (valeurs, motifs, composants) :
  `context/frontend/design_system.md`.
