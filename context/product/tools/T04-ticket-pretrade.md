# T04 — Ticket pré-trade

Statut : **livré** · Vague 1 · Effort 1 j · Valeur 5 · Dépend de : rien

## Problème

Un journal rempli le soir est une reconstruction, pas un enregistrement. Le souvenir du « pourquoi » a disparu, et la justification écrite après coup est cohérente avec le résultat. C'est le biais qui rend la plupart des journaux de trading inutiles.

## Comportement attendu

Avant l'envoi de l'ordre, un formulaire de quatre champs, **tous en boutons**, aucun texte libre obligatoire :

| Champ | Forme |
|---|---|
| Setup | liste fermée (FVG, OB, liquidity sweep, retest, autre) |
| Biais | long / short / contre-tendance |
| Invalidation | le prix qui prouve l'erreur — pré-rempli depuis le stop |
| Confiance | 1 à 5 |

**Quinze secondes maximum.** Au-delà, il sera contourné. Une note vocale optionnelle viendra de S1 (dictée Vozel) plus tard.

## Pourquoi cet outil est le pivot de la Vague 1

Un seul objet, trois effets :

1. il devient la ligne de journal — T06 passe de 1–2 semaines à 3–5 jours ;
2. il rend le taux de conformité mesurable — T07 devient possible ;
3. il ralentit l'entrée impulsive — il renforce T02.

## Ancrage dans le code

- En amont de `lib/execution/command-builder.ts`.
- Persisté avec l'identifiant de commande, de sorte que le fill rattache automatiquement le ticket au trade. La table `execution_commands` porte déjà cet identifiant.
- Le vocabulaire des setups appartient au domaine : le poser dans `lib/domain/`, pas dans le composant.

## Critère de réussite

Au bout de 30 trades, l'expectancy par niveau de confiance est calculable. Attendre que les niveaux 1 et 2 soient négatifs.

## Journal

- 2026-09-04 — fiche créée au moment du pivot. Rien de démarré.
- 2026-09-05 — livré. Décisions prises pendant la construction :

  1. **Pas de `commandId`, jamais.** Aucun chemin d'envoi d'ordre n'existe
     dans ce dépôt (le trader place l'ordre à la main dans MT5, l'observer
     ne fait que le regarder passer) : il n'y a donc jamais de `RiskDecision`
     ni de `commandId` pour le trade qu'un ticket décrit. Le ticket est publié
     comme un fait indépendant (`journal.ticket.created`), pas rattaché à la
     chaîne `Signal → RiskDecision → Command`. `matched_position_id` /
     `matched_trade_id` existent dans le schéma mais restent `NULL` à la
     création — le rapprochement (symbole + sens + prix approchants + fenêtre
     de temps) est le travail de **T06**, pas de T04.
  2. **Ticket rempli sans ordre envoyé : rien de spécial.** Pas de flag
     « abandonné » — un champ qu'il faudrait remplir après coup n'est jamais
     rempli (principe 3 de la charte, zéro saisie manuelle). Un ticket non
     rapproché reste `NULL` indéfiniment ; distinguer « pas pris » de
     « pris mais pas encore rapproché » est un problème d'inférence pour T06
     (fenêtre de temps + données de position), pas un champ de saisie.
  3. **Transport : `PublishEvent` existant, pas un nouvel endpoint HTTP.**
     Conforme à l'ADR 0003 (événements, pas HTTP ad hoc). `journal.ticket.created`
     ajouté à la liste blanche `CockpitHub.PublishableTypes`, à
     `PersistenceMapper`/`PersistenceWriter`, et à `schema.sql`
     (table `pretrade_tickets`, contrainte `CHECK (confidence BETWEEN 1 AND 5)`).
  4. **Confirmation par écho, jamais par soumission.** `PublishEvent` a trois
     refus silencieux (enveloppe > 64 Ko, type hors liste blanche, écriture
     perdue si la file est pleine ou la base absente) — dont le plus probable
     ici est d'oublier d'ajouter le type à la liste blanche. Le formulaire ne
     se réinitialise donc **que** lorsque le ticket revient par le flux
     d'événements avec son propre `ticketId` (`CockpitStore.confirmedTicketIds`).
     Un délai de 8 s sans écho affiche un état « non confirmé », sans jamais
     prétendre que le ticket est enregistré. Ça ne couvre pas le troisième cas
     (écriture perdue après diffusion) — d'où le point 5.
  5. **Badge de persistance dans `TopCommandBar`.** L'écho ne prouve que la
     diffusion, pas l'écriture (`PublishEvent` diffuse avant même d'enqueue
     la persistance). `/health` expose déjà `dropped`/`db` ; un nouveau
     composant (`PersistenceHealthBadge`) le sonde toutes les 15 s en mode
     `backend` et l'affiche en permanence, pas seulement pour les tickets.
  6. **Deux champs ajoutés au schéma, pas prévus dans la fiche d'origine** :
     `take_profit` (sans lui, impossible de comparer le R annoncé au R
     réalisé — détection de sortie prématurée, taxonomie T07) et
     `target_volume`/`target_risk_usd`, repris tels quels du calcul déjà fait
     par T01 (`decision.approvedVolume` et `targetRiskUsd`, jamais recalculés
     ici) — sans eux, « taille hors politique » n'est pas détectable non plus.
     Les trois champs sont nullables (un TP est optionnel dans T01 ; sans stop
     valide, aucun sizing n'existe).
  7. **`SetupType` utilise `"other"`, pas `"autre"`** — cohérent avec le
     reste de l'énumération (anglais). L'étiquette affichée reste "Autre" en
     français, seule la valeur change.
  8. **`symbol` n'est pas figé dans `lib/domain/ticket.ts`.** Le type reste
     un `SymbolCode` général (la table a déjà une colonne `symbol`) ; seule
     l'UI défaut à XAUUSD, comme T01 — ce n'est pas une restriction du domaine.
  9. **`TradeDraftContext`** (`components/cockpit/trade-draft-context.tsx`)
     partage entrée/stop/TP/résultat de sizing entre `SizingPanel` (T01,
     écrivain) et `TicketPanel` (lecteur) — l'invalidation se pré-remplit
     depuis le stop réellement affiché, jamais retapée. Les trois défauts de
     T01 (budget quotidien, `?? 0`, signe du R) étaient déjà corrigés et
     commités (`a803994`) avant ce lift — il n'existait pas d'état commité
     "avant correction" à partir duquel les scinder après coup.

  Vérification manuelle non faite en session (pas d'extension Chrome
  connectée) : rendu serveur des deux panneaux confirmé par requête HTTP en
  mode mock ; la boucle réelle saisie → publication → écho → confirmation n'a
  pas été observée dans un navigateur. À valider à l'ouverture réelle du
  cockpit, idéalement en coupant volontairement le backend une fois pour
  vérifier que le ticket reste "non confirmé" plutôt que de sembler enregistré.
