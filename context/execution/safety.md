# Barrières locales de l'agent MT5

Statut : accepté (EA-03), descriptif seulement. Rien ici n'est implémenté
dans cette fiche — aucun code MQL5, aucun réseau, aucun ordre. Ce document
fixe la raison d'être de chaque barrière avant que l'agent (EA-05) n'existe,
pour que son implémentation n'ait pas à (re)découvrir ces règles depuis le
mauvais bout.

## Principe

Ces barrières sont **la dernière ligne de défense, jamais une décision**
(ADR 0007, ADR 0010). Le Risk Engine reste le point de contrôle unique en
amont : ce que l'agent vérifie ici, c'est que la commande qui lui parvient
correspond bien à ce que le Risk Engine a approuvé et à ce que ce terminal
peut exécuter en sécurité — pas si le trade est une bonne idée. Une barrière
locale qui se mettrait à raisonner sur l'opportunité d'un trade serait une
stratégie déguisée dans l'EA (interdit, ADR 0010, contrainte 1).

## Les barrières, et pourquoi chacune existe

| Barrière | Raison d'être | Résultat si elle échoue |
|---|---|---|
| **Whitelist stricte de symboles** | Une commande pour un symbole que ce terminal ne trade pas est soit un bug amont, soit une commande mal adressée. L'agent ne doit jamais improviser un symbole voisin (ex. suffixe broker différent). | Rejet — code à définir avec le registre de symboles (EA-04, `SYMBOL_MISMATCH` probable). |
| **Volume maximum par ordre** | Protège contre une erreur de calcul de taille en amont (bug de sizing, décimale déplacée) qui produirait un ordre disproportionné. | Rejet local, jamais une exécution partielle « au mieux ». |
| **Positions simultanées maximum** | Protège contre un empilement de positions si plusieurs commandes légitimes arrivent en rafale (ex. plusieurs signaux rapprochés). | Rejet des commandes au-delà du plafond. |
| **Stop-loss obligatoire** | Une position sans SL n'a pas de risque explicite — viole le principe 8 de la charte (« toute position a un risque explicite, une invalidation, un stop »). | Toute commande `place_order` sans `stopLoss` valide est rejetée avant `OrderSend`, jamais exécutée avec un stop ajouté après coup. |
| **Spread maximum au moment de l'exécution** | Le spread peut s'être élargi entre la proposition et l'exécution (ouvertures de session, en particulier). Un stop très serré rend le coût réel du trade sensible au spread — c'est la porte de coût de S01 (`c = coût / distance SL`), revérifiée ici au dernier instant, pas seulement à la proposition. | Commande annulée, motif journalisé, jamais exécutée à un coût dégradé silencieusement. |
| **Kill switch local** | Doit fonctionner même si le backend est injoignable — sinon ce n'est pas un kill switch, c'est un espoir. Local veut dire : une commande locale à l'agent, pas un aller-retour réseau. | Aucune commande n'est exécutée tant que le kill switch local est armé, quel que soit l'état du lien avec le gateway. |
| **`accountId` de la commande ≠ compte du terminal** | Isolation des comptes (ADR 0010) : un environnement par compte (terminal, instance d'agent, magic number, profil de risque). Une commande mal adressée ne doit jamais s'exécuter « au mieux » sur le mauvais compte. | Rejet `ACCOUNT_MISMATCH` (`lib/contracts/execution/reject-reason.ts`) — voir `protocol.md`. |
| **Magic number propre à l'environnement** | Distingue les positions gérées par le Trading OS des positions manuelles du même terminal. Sans lui, la réconciliation (EA-06) ne peut pas savoir laquelle des positions ouvertes lui appartient. | Toute position ouverte par l'agent porte ce magic number ; une position sans ce magic number est traitée comme externe, jamais comme une commande du Trading OS (EA-06, `EXTERNAL_POSITION`). |

## Ce que ces barrières ne sont pas

- Elles ne remplacent pas le Risk Engine : une commande qui n'a jamais été
  approuvée par le Risk Engine n'atteint pas l'agent (contrat côté OS,
  `buildPlaceOrderCommand` ne construit rien sans `riskApprovalId`).
- Elles ne décident jamais d'attendre un meilleur prix, d'ajuster une entrée,
  ou de modifier un stop en dehors d'un événement significatif — l'agent
  reste orienté événement, pas tick (contrainte FTMO citée dans le prompt de
  lancement d'EA-05 : une modification de stop à chaque tick ressemble à de
  l'hyperactivité serveur aux yeux d'une prop firm).
- Elles ne sont pas un filet qui autorise à relâcher le Risk Engine : si une
  barrière locale devait un jour être la seule chose qui empêche une
  violation de règle, c'est que le Risk Engine a un trou — à corriger côté
  Risk Engine, pas à combler ici.

## Implémentation

Aucune ici. Ce document est consommé tel quel par EA-05 (agent MQL5), qui
implémente chaque barrière comme un contrôle local avant `OrderSend`, et par
EA-06 (réconciliation), qui s'appuie sur le magic number et
`ACCOUNT_MISMATCH` pour distinguer les positions gérées des positions
externes.
