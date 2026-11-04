# Règles par environnement et leur provenance

Document de référence de l'ADR 0036. **Lu le 2026-11-03.** Ce qui est dans `python/trading_os/domain/providers/rules.py` est la copie exécutable de ce document : si les deux divergent, c'est le code qui compte pour le Risk Engine, et ce document qui compte pour savoir **d'où vient** une valeur.

Règles de lecture :

* Une valeur documentaire est une **borne**, jamais une description du compte : le terminal du compte connecté prime (levier, niveaux de marge, spread, swap, commission, volumes).
* **Comment** chaque page a été lue est écrit : *page lue* = texte de la page extrait automatiquement (à relire par Exhorte avant tout compte réel) ; *résumé de recherche* = la page n'a pas pu être lue, une recherche web la résume ; *déclaration* = donnée par Exhorte.
* « Non sourcé » veut dire que la valeur n'a pas été trouvée : elle n'est pas devinée, et un produit dont les limites de perte ne sont pas sourcées **ne peut pas trader**.

## 1. Règles personnelles (communes à tous les environnements)

Source : ADR 0019 (décision d'Exhorte du 2026-11-01), reprises dans la mission du 2026-11-03. Code : `domain/risk/policy.py`, `dynamic_risk.py`. Détail et interprétations : `risk_rules.md`.

| Règle | Valeur |
|---|---|
| Trades exécutés par jour | 15 |
| Positions simultanées (tout le compte) | 5 |
| Perte quotidienne | 5 % |
| Perte hebdomadaire | 10 % |
| Risque par trade | grille : +1 % et plus 1,5 % · capital initial et −1 % : 1 % · −2 % : 0,1 % · −3 % : 0,2 % · −4 % : 0,3 % · −5 % : arrêt pour la journée. Aucune interpolation (palier entier atteint, tronqué vers zéro). |
| Plafond des 200 $ sous le capital initial | 1 %, jamais une hausse d'un risque déjà plus bas |
| Plafond par trade du profil | 1,5 % |
| Risque ouvert | 2 % ; risque corrélé 1,5 % |

**La plus stricte prévaut**, avec la règle du fournisseur et du produit (`domain/risk/effective.py`, `GET /api/accounts/{id}/effective-policy`).

## 2. Exness Standard (MT5)

Produit : `EXNESS_STANDARD`, version `2026-11-03`. Environnement d'exécution : **courtier**.

| Paramètre | Valeur documentaire | Source | Lecture |
|---|---|---|---|
| Exécution | Market Execution | <https://get.exness.help/hc/en-us/articles/17537782738460-Standard-account> | résumé de recherche (la page répond HTTP 403) ; déclaration d'Exhorte |
| Spread | flottant, à partir de 0,2 pip annoncé | idem | déclaration d'Exhorte |
| Commission de trading | aucune sur Standard (`documentaryCommissionPerLot = 0`) | idem | déclaration ; **remplacée par la mesure** dès qu'une position fermée du compte montre une charge |
| Lot minimum | 0,01 en général (varie par instrument) | idem | déclaration ; **le terminal prime** |
| Marge couverte | 0 % | idem | déclaration |
| Margin call / stop out | 60 % / 0 % | <https://get.exness.help/hc/en-us/articles/360014693340-Margin-call-and-stop-out-levels-by-account-type> | résumé de recherche (page HTTP 403) ; documentaire seulement |
| Suffixe de symboles | `m` | observé sur le terminal de la démo (`EURUSDm`, `XAUUSDm`, 2026-11-03) | **vérifié sur le live** (contrats de terminal) |
| Triple swap | forex : mercredi soir ; crypto et indices : vendredi soir (résumé de recherche) | <https://get.exness.help/hc/en-us/articles/360014709151-About-swap> | résumé de recherche, **à ne pas utiliser** : le jour réel est `swap_rollover3days` de chaque symbole, lu au terminal |
| Limite de perte imposée par le courtier | aucune | — | seules les règles personnelles s'appliquent |

**Non sourcé** : swap par instrument (lu au terminal), horaires par instrument (non lisibles en Python), commission réelle (mesurée sur les deals).

## 3. FTMO — environnement **simulé** sur cotations réelles

FTMO n'est pas un courtier : les comptes sont des fonds fictifs, les cotations viennent de fournisseurs de liquidité, un délai simulé allant jusqu'à 200 ms est appliqué à tous les clients d'une plateforme, et les commissions simulées sont publiées par symbole sur le site (page « technical infrastructure », modifiée le 2026-10-04). Le cœur le traite comme `SIMULATED`, quel que soit le mode de compte que le terminal annonce.

### 3.1 Produits et phases (page « Trading Objectives », <https://ftmo.com/en/trading-objectives/>, modifiée le 2026-11-02 — *page lue*)

| Produit (`ProviderProduct`) | Perte quotidienne | Perte maximale | Objectif de profit | Jours min. | News | Pause > 2 h |
|---|---|---|---|---|---|---|
| Challenge 1-Step (`FTMO_CHALLENGE_1STEP`) | 3 % | 10 %, **glissante fin de journée** | 10 % | non listé | non | non |
| Challenge 2-Step (`FTMO_CHALLENGE_2STEP`) | 5 % | 10 %, **statique** | 10 % | 4 | non | non |
| Verification (`FTMO_VERIFICATION`) | 5 % | 10 %, statique | 5 % | 4 | non | non |
| FTMO Account 1-Step (`FTMO_ACCOUNT_1STEP`) | 3 % | 10 %, glissante fin de journée | aucun | — | **oui** | **oui** |
| FTMO Account 2-Step (`FTMO_ACCOUNT_2STEP`) | 5 % | 10 %, statique | aucun | aucun | **oui** | **oui** |
| FTMO Instant (`FTMO_INSTANT`) | 3 % | 10 %, glissante **intrajournalière** (basée solde) | — | — | **oui** | **oui** |
| FTMO Swing (`FTMO_SWING`) | **non sourcé** | **non sourcé** | — | — | non (exempt) | non (exempt) |

Méthode de calcul (identique pour tous les produits ci-dessus) :

* Les pourcentages sont ceux du **capital initial simulé**.
* Limite quotidienne : recalculée chaque jour à **00:00 CE(S)T** à partir du **solde de 00:00 CE(S)T précédent** (le premier jour : le capital initial) ; le contrôle porte sur l'**équité** = solde + P/L flottant ± swaps − commissions.
* Perte maximale statique (2-Step) : capital initial − montant (p. ex. 90 000 sur 100 000).
* Perte maximale glissante fin de journée (1-Step) : **plus haut solde de 00:00 CE(S)T**, ou capital initial s'il est plus grand, − montant ; elle ne peut que monter. *Le montant est lu comme un pourcentage du capital initial : la page ne le dit pas en toutes lettres* (voir ADR 0036, interprétation 1).
* Perte maximale glissante intrajournalière (Instant) : décrite en une ligne ; **non suivie par le cœur** (état « inconnu », entrées refusées) ; page à relire.
* Cohérence / « Best Day » (50 % pour 1-Step, 30 % pour Instant) : règle de **récompense**, pas de risque ; non appliquée par le Risk Engine.
* Jour de négociation (2-Step) : jour calendaire CE(S)T où au moins une position est ouverte.

Les objectifs de profit et les jours minimaux sont des **objectifs du compte** : affichés, jamais utilisés pour décider d'un risque.

### 3.2 News (<https://ftmo.com/faq/can-i-trade-news/>, modifiée le 2026-10-11 — *page lue*)

* S'applique à tous les comptes **sauf** Swing et phases Challenge / Verification. Les pages ne parlent pas de « 1-Step » ou « 2-Step » par leur nom : la restriction suit « un compte FTMO (Standard) une fois qu'on y trade, hors évaluation ».
* Fenêtre : **2 minutes avant, 2 minutes après** une publication restreinte ; toute exécution d'ordre est visée (ouverture, fermeture, ordres en attente, stop loss, take profit). Une position ouverte plus de 2 minutes avant peut rester ouverte.
* Instruments visés : ceux qui portent la devise ou l'actif. USD : paires forex USD, XAUUSD, indices américains (US2000, US500, US100, US30 `.cash`), DXY. EUR, GBP, CAD, AUD, NZD, CHF : paires forex contenant la devise. Pétrole : USOIL, UKOIL (`.cash`). Exemple de la page : pendant le NFP américain, EURGBP et AUDNZD sont négociables, USDJPY et GBPUSD non.
* Publications restreintes : USD — taux des Fed Funds et déclaration ; Non-Farm Employment Change ; taux de chômage et salaires ; PIB avancé t/t ; minutes du FOMC ; CPI a/a. EUR — taux de refinancement principal. GBP — taux officiel et votes du MPC ; CPI a/a. CAD — taux au jour le jour ; CPI m/m ; emploi et chômage. AUD — taux de caisse (RBA) ; emploi et chômage ; CPI m/m et a/a ; PIB t/t. NZD — taux officiel (RBNZ) ; emploi et chômage ; CPI t/t ; PIB t/t. CHF — taux directeur de la BNS. Pétrole — stocks de pétrole brut. Elles sont marquées « Restricted event » dans le calendrier économique de FTMO.
* Conséquence d'une violation : résiliation possible du compte.
* **Aucun calendrier restreint FTMO n'est branché au cœur.** Un calendrier économique générique ne peut pas autoriser une action (ADR 0036) : un produit soumis à la règle refuse donc ses entrées (`provider_news_calendar_unknown`) tant qu'une source fournie par FTMO n'est pas chargée. Les entrées de la liste ci-dessus sont des **événements à saisir**, pas des événements chargés.

### 3.3 Week-end et pauses (<https://ftmo.com/en/faq/can-i-hold-positions-overnight-or-over-the-weekend/>, modifiée le 2026-10-11 — *page lue*)

| Compte | Position tenue à travers une pause de plus de 2 heures |
|---|---|
| Swing | aucune restriction |
| Standard, phase d'évaluation (Challenge, Verification) | aucune restriction |
| Standard, compte FTMO (Instant compris) | **interdit** : fermer avant la pause |

Aucune exception par instrument n'est listée ; les horaires varient par instrument et changent avec les jours fériés. **Le week-end compte** comme pause. Conséquence : résiliation possible. Le paquet `MetaTrader5` n'expose pas les sessions de négociation : sans horaire de pause connu, le produit soumis à la règle refuse ses entrées (`provider_overnight_schedule_unknown`). Un arrêt général (`HALT`) ne ferme **pas** tout (ADR 0033) : la fermeture avant une pause est une règle à part (`closing_plan_before_break`).

### 3.4 Pratiques interdites (<https://ftmo.com/en/forbidden-trading-practices/>, modifiée le 2026-11-02 — *page lue*)

Exploitation d'erreurs de service (erreurs de prix, retards, flux lents ou externes) ; trades coordonnés manipulatoires (positions opposées permises seulement sur **un** compte) ; violation des conditions ; outils déloyaux (logiciels, IA, outils ultra-rapides, saisie de masse) ; trading de gap (autour d'annonces majeures, ou dans les deux heures avant une fermeture de marché d'au moins deux heures) ; trading irréaliste (surlevier, surexposition, paris unilatéraux, « account rolling ») ; **hyperactivité d'EA : plus de 2 000 requêtes de serveur par jour** (ouvertures, modifications, fermetures ; les modifications comptent dans le même total) ; étalement artificiel du profit ; positions surdimensionnées ; nombre de positions inhabituel ; exposition cumulée croissante ; interdiction de laisser un tiers trader ; interdiction de trader le compte d'autrui ; accès restreint des personnes morales. Sanctions : retrait de trades, restriction d'accès, disqualification, perte de récompenses, résiliation.

Ce que le cœur applique aujourd'hui : le **budget de requêtes** (arrêt des entrées à 90 % de 2 000, jamais de refus d'une fermeture). Le reste est de la conduite du trader et de la stratégie, pas une porte.

### 3.5 Spécifications de compte (<https://ftmo.com/en/faq/what-are-the-account-specifications/>, modifiée le 2026-10-05 — *page lue*)

Levier : jusqu'à **1:100** (Standard, non modifiable), **1:30** (Swing). Plateformes : MetaTrader 4 et 5, cTrader, TradingView. Serveur MT : **GMT+2 avec heure d'été** (à rapprocher de « minuit CE(S)T » : voir ADR 0036, interprétation 2). Commission, devise du compte, liste des instruments : **non indiquées** sur cette page (la spécification se lit dans MetaTrader : Market Watch → Spécification).

## 4. MetaTrader 5

Pages consultées le 2026-11-03, aucune ne montre de date de modification (seulement « Copyright 2000-2026, MetaQuotes Ltd »).

| Sujet | Page | Constat |
|---|---|---|
| Propriétés de symbole | <https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants> | Énumérations de mode de négociation, d'exécution, de swap ; indicateurs de remplissage `FOK = 1`, `IOC = 2`, `BOC = 4` (le « Return » n'a pas d'indicateur, toujours disponible sauf en exécution au marché) ; `SYMBOL_VOLUME_LIMIT` plafonne le volume cumulé dans un sens (positions et ordres en attente) ; `SYMBOL_SWAP_MODE_CURRENCY_PROFIT` existe dans la documentation. |
| Valeurs numériques | paquet `MetaTrader5` 5.0.6231 installé (lu hors connexion) | `TRADE_MODE` 0 à 4 ; `TRADE_EXECUTION` 0 à 3 ; `SWAP_MODE` 0 à 8 (**sans** `CURRENCY_PROFIT`, absent du paquet : un code inconnu est rendu `UNKNOWN(n)`, jamais confondu) ; `DAY_OF_WEEK` 0 = dimanche ; `ACCOUNT_TRADE_MODE` 0 démo, 1 concours, 2 réel ; `DEAL_ENTRY` 0 entrée, 1 sortie, 2 renversement, 3 sortie par contre-position ; `DEAL_TYPE_BALANCE` 2. |
| Paquet Python | <https://www.mql5.com/en/docs/python_metatrader5> | 32 fonctions listées. **Aucune n'expose les sessions de négociation** (`SymbolInfoSessionTrade` n'est pas mentionnée) : les sessions du courtier ne sont lisibles que par l'agent MQL5. |
| Ticks | <https://www.mql5.com/en/docs/series/copyticksrange> | `CopyTicksRange(symbole, tableau, flags, from_msc, to_msc)` : ticks de `from_msc` à `to_msc` inclus, en millisecondes, du plus ancien au plus récent ; `COPY_TICKS_INFO` (changements bid/ask), `COPY_TICKS_TRADE` (last/volume), `COPY_TICKS_ALL` ; **un délai de synchronisation dépassé rend un résultat partiel, pas forcément vide** ; la page ne documente pas la fonction Python `copy_ticks_range`. Utile à L2 (non construit). |
| `OnTradeTransaction`, `MqlTradeResult`, `OrderSend` | <https://www.mql5.com/en/docs/event_handlers/ontradetransaction>, `…/constants/structures/mqltraderesult`, `…/trading/ordersend` | **Non consultées dans cette session.** Le protocole de l'agent (ADR 0010, 0029) s'appuie sur elles ; leur relecture appartient à l'étape « cycle d'exécution » (non construite). |

## 5. Ce qui reste à relire par Exhorte

1. Les pages Exness (illisibles par le cœur le 2026-11-03, HTTP 403) : marge, stop out, exécution, commission.
2. La méthode de la perte maximale glissante d'Instant et le montant de la perte glissante du 1-Step.
3. Le fuseau du jour FTMO sur un terminal FTMO réel (horloge du serveur contre 00:00 CE(S)T).
4. Les pages de FTMO Swing (limites de perte non lues).
5. La liste des publications restreintes **telle que FTMO la marque dans son calendrier** (la liste ci-dessus vient de la FAQ, pas du calendrier).
