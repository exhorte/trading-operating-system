# ADR 0018 — Suppression de la capture graphique : on garde les données

Date : 2026-10-09. Statut : **accepté** — décision de l'utilisateur en session le
2026-10-09, pendant la phase 6 de la migration Python-native : « supprimer
totalement la fonction de capture graphique, image du graphique, capture de
l'image de la transaction, et juste garder les données ».

Supersède l'ADR 0009 (« Le serveur capture des faits, le cockpit rend ») pour sa
moitié *rendu* : il n'y a plus de rendu. Sa moitié *faits* tient : le serveur
continue d'enregistrer des faits immuables. Retire l'outil T05 en tant que
fonction graphique (la fiche est réécrite en conséquence) et la partie
graphique de T06.

## Contexte

T05 enregistrait, à l'ouverture et à la clôture de chaque position, des faits
bornés — prix d'entrée, stop, objectif, prix de sortie — **et** la fenêtre de
bougies que le cockpit avait le droit de dessiner (`timeframe`,
`window_start_utc`, `window_end_utc`). À la demande, la page d'un trade
rejouait le moteur d'analyse sur cette fenêtre figée et dessinait un
graphique annoté (niveaux de liquidité, FVG, order blocks, marqueurs
d'entrée / stop / objectif / sortie).

L'utilisateur ne veut pas de cette fonction : ni image, ni graphique, ni
capture d'écran de la transaction. Ce qui compte, ce sont les chiffres.

## Décision

**Plus aucune capture graphique. Les données restent.**

- **Supprimé** : le rendu du graphique (composants, échelles, page), la fenêtre
  de bougies attachée à une capture, tout point d'accès qui servait à dessiner
  (l'endpoint `captures/{id}/charts` ajouté le jour même n'a jamais été
  livré), la mention d'un « rendu rejoué » dans les documents.
- **Conservé** : les lignes `trade_captures` — symbole, prix d'entrée, stop,
  objectif, prix de sortie, horodatage — immuables, écrites par les événements
  réels. Ce sont elles qui donnent au journal l'entrée et le stop d'un trade,
  donc son R et le contrôle de taille de T07. Le nom « capture » reste, par
  continuité de la base et de l'API ; il ne désigne plus qu'un enregistrement
  de chiffres.
- **Conservé** : le dossier d'un trade (`GET /api/journal/trades/{id}`) :
  Intention → Décision de risque → Commande → Résultat, et la page
  `/journal/{id}` qui l'affiche — **sans aucun graphique**, en chiffres.
  « Dossier du trade » remplace « Capture du trade ».

## Conséquences

- Base : la migration `0003_captures_are_data` rend optionnelles les trois
  colonnes graphiques (additive : aucune ligne n'est touchée, les fenêtres déjà
  écrites restent lisibles). Le cœur ne les écrit ni ne les lit plus. Les
  supprimer pour de bon est une décision sur l'historique, donc un script
  manuel : `python -m trading_os db manual drop_capture_window` (à lancer quand
  l'utilisateur le décide ; faire un `pg_dump -t trade_captures` avant s'il
  veut garder les fenêtres).
- Le moteur d'analyse (`domain/market/analysis`) ne sert plus qu'au contexte de
  marché en direct (`/api/market/{symbol}/context`) et à S01. Il n'alimente
  plus aucun rendu rétrospectif.
- La revue hebdomadaire (T08) renvoie chaque pire trade vers son dossier
  (`[dossier](…/journal/{id})`), pas vers une capture.
- Le corollaire de l'ADR 0009 sur l'agent d'exécution est inchangé : l'EA
  remonte des faits d'exécution, aucune interprétation.

## Points à confirmer

- Le nom `trade_captures` / `hasCapture` est conservé pour ne pas renommer une
  table qui contient des données réelles ; un renommage (`trade_levels`) est
  possible, mais c'est une migration que personne n'a demandée.
- La page `/journal/{id}` reste, en chiffres. Si l'utilisateur la juge
  superflue, la retirer ne touche ni la base ni l'API.
