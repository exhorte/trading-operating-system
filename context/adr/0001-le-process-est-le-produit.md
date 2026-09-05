# ADR 0001 — Le process est le produit

Date : 2026-09-04. Statut : accepté. Supersède l'ancien ADR 0001 « platform over EA », dont il conserve la substance.

## Contexte

La série 1 posait « la plateforme est le produit, la stratégie est un module ». C'était vrai mais incomplet : la plateforme y servait surtout à héberger la recherche d'un edge. Neuf mois plus tard, la recherche est abandonnée (ADR 0002) et la plateforme se retrouve sans raison d'être si on ne la redéfinit pas.

## Décision

La plateforme automatise, mesure et fait respecter **le process de trading de son utilisateur**. Elle ne produit aucune opinion de marché.

Concrètement :

- Aucun module ne dit quoi trader, quand, ni dans quel sens.
- `lib/analysis/` fournit du **contexte** (niveaux, sessions, ATR, structure). Un module qui conclurait « biais haussier aujourd'hui » violerait cet ADR.
- L'humain décide et déclenche ; la plateforme dimensionne, vérifie, refuse, enregistre et restitue.
- L'EA n'est pas le cerveau. MT5 est un point d'exécution et de télémétrie.

Le KPI du produit est le **taux de conformité au plan**, pas le P&L.

## Conséquences

- Toute proposition de fonctionnalité se teste par : « est-ce que ça supprime une violation de règle, ou est-ce que ça parie sur une opinion de marché ? »
- Le cockpit ne duplique pas MT5 sur l'affichage des prix.
- Aucune prétention de performance n'est publiée par ce projet.
- Un générateur de signaux, quel qu'en soit le moteur, est hors périmètre.
