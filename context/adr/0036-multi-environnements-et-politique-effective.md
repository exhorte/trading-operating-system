# ADR 0036 — Plusieurs environnements, une seule plateforme : identification, règles du fournisseur par produit, politique de risque effective

Statut : accepté le 2026-11-03 — mission d'Exhorte « finaliser l'intégration multi-environnements, le Risk Engine et l'exécution live » (Exness Standard et FTMO sur le même Core, la même stratégie, le même Risk Engine, le même cockpit). **Amende** l'ADR 0019 (les plafonds contractuels viennent désormais de jeux de règles sourcés, pour tous les produits FTMO) et l'ADR 0020 (plus de challenge FTMO par défaut ; plus de commission générique appliquée à un compte Standard). **Ne lève, n'assouplit ni ne contourne aucun garde-fou** : tout ce que cet ADR ajoute ne fait que **resserrer** (ADR 0007, 0014, 0015, 0033, 0034, 0035 inchangés). L'agent MQL5 n'est pas touché, il reste compilé `OBSERVE`.

## Contexte

Le cœur savait distinguer deux fournisseurs par le nom du serveur et du courtier, et plafonnait les pertes d'un seul produit FTMO (2-Step Challenge, lu dans les exports MetriX d'Exhorte). L'audit du 2026-11-03 (`context/execution/audit-multi-environnements-2026-11-03.md`) a trouvé :

* un produit FTMO **fabriqué** (2-Step de 10 000 $) quand aucun n'était déclaré ;
* une commission de 5 $/lot **appliquée à la démo Exness Standard** par le profil FTMO répété (ADR 0020 §5), alors que Standard n'en annonce aucune ;
* des limites FTMO mesurées contre l'équité de **minuit du serveur**, alors que FTMO les construit sur le **solde de 00:00 CE(S)T** (page `trading-objectives`, modifiée le 2026-11-02) et que sa page technique dit que ses serveurs MetaTrader sont en GMT+2 avec heure d'été — soit une heure d'écart avec minuit CE(S)T ;
* aucune restriction de news, de week-end ni de requêtes propre à un produit ;
* une spécification de symbole sans swap, sans mode de remplissage, sans mode d'exécution.

## Décision

### 1. Une architecture en six couches, sans second moteur

| Couche | Où | Rôle |
|---|---|---|
| A. Règles personnelles | `domain/risk/` (inchangé) | 15 trades, 5 positions, 5 % / 10 %, grille de risque (ADR 0019). Indépendantes du fournisseur. |
| B. Adaptateur de fournisseur | `domain/accounts/profiles.py` | `ProviderProfile` gagne une **signature** (comment le fournisseur se montre au terminal) et la **résolution de produit**. Seul fichier autorisé à brancher sur le fournisseur (invariant d'architecture). |
| C. Profil de compte | `domain/providers/identity.py`, `profile.py` | Identification par signaux indépendants ; vue unique `AccountProfile` (déclaré à côté d'observé). |
| D. Spécification d'instrument | `domain/market/instrument.py` | `InstrumentSpecification` = un `SymbolSpec` + tout `symbol_info` + la liste de ce que le terminal n'a pas dit. |
| E. Politique effective | `domain/risk/effective.py` | Pour chaque limite, toutes les valeurs candidates et celle qui l'emporte. Ne décide rien de neuf : elle **montre**. |
| F. Exécution | inchangée | Le Risk Engine reste le point de contrôle unique ; les règles du fournisseur lui ajoutent des **raisons de refus**, jamais une autorisation. |

Règles du fournisseur : `domain/providers/rules.py` (jeux de règles versionnés, par produit, avec leurs sources) ; planchers de perte : `loss_floors.py` ; news, pauses de marché, requêtes : `restrictions.py` ; commission : `commission.py`. Service : `services/providers.py`. Persistance : migration `0006_provider_loss_references`.

### 2. Identifier un compte, c'est croiser plusieurs faits

Trois lectures **indépendantes** du fournisseur (nom du serveur, société du compte, société du terminal), le suffixe réel des symboles (signal faible pour le produit), l'effet de levier (contre-vérification), puis la déclaration de l'utilisateur, qui **confirme ou contredit, jamais ne suffit**. Le login n'est jamais une preuve. Résultat : un niveau de confiance (`CONFIRMED`, `PROBABLE`, `WEAK`, `CONFLICT`, `NONE`) et des **blocages explicites** (`provider_not_identified`, `provider_ambiguous`, `provider_mismatch`, `environment_mismatch`, `account_product_unknown`, `provider_rules_unsourced`, `rules_profile_on_real_account`, `leverage_contradicts_product`, `account_facts_missing`). Un blocage rend le compte **non exécutable** : le Risk Engine refuse toute nouvelle entrée avec la raison ; la lecture et la surveillance continuent.

* Le **produit FTMO** n'est pas lisible dans MT5 : c'est ce que l'utilisateur a **déclaré** (`FtmoChallenge`), ou il est inconnu. Jamais de valeur par défaut. `FtmoChallenge` gagne `variant` (`standard` | `swing`) et le type `instant`.
* Le **produit Exness** se lit au suffixe des symboles (Standard : `m`, un seul suffixe, le même partout).
* Un compte **démo déclaré qui est réel** au terminal (ou l'inverse) est refusé : un compte réel n'hérite jamais de l'autorisation d'une démo. Un profil FTMO répété sur un compte Exness reste réservé à la démo (ADR 0020).
* FTMO est un **environnement simulé** sur des cotations réelles, jamais un courtier : `account_mode = SIMULATED`, quel que soit le mode que le terminal annonce.

### 3. Les règles d'un fournisseur sont des données avec leur provenance

Chaque `ProviderRuleSet` porte : produit, version (date de modification de la page source), date d'effet, ses sources (URL, **date de lecture**, date de modification de la page, **comment** elle a été lue : page lue, résumé de recherche, déclaration de l'utilisateur), ce qui **n'est pas sourcé** et ce qui **demande relecture**. Aucune valeur documentaire n'est une vérité permanente : le terminal prime. Ce qui n'est pas sourcé reste « non sourcé » : **FTMO Swing** (limites de perte non lues) est identifié mais **non exécutable** ; **FTMO Instant** a une perte maximale glissante intrajournalière que le cœur ne suit pas : état « inconnu », donc entrées refusées. Le détail et les dates sont dans `context/domain/regles-par-environnement.md`.

### 4. La politique effective : la plus stricte l'emporte, et on voit pourquoi

Six sources (`personal`, `provider`, `product`, `instrument`, `market`, `account`). Pour chaque limite : toutes les valeurs candidates, celle qui lie, sa provenance, et la porte qui l'applique. Les plafonds de perte du fournisseur resserrent les limites personnelles par le mécanisme existant (`apply_provider_ceilings`, maintenant alimenté par les jeux de règles de **tous** les produits sourcés : 1-Step 3 % / 10 %, 2-Step 5 % / 10 %). `GET /api/accounts/{id}/effective-policy`. Une limite montrée mais non appliquée le dit (`enforcedBy = null`).

**Les objectifs de profit et le nombre minimal de jours d'une phase sont des objectifs du compte, jamais une entrée du risque** : listés « informationnels », jamais « actifs » ; un test d'architecture interdit à `domain/risk`, `domain/execution`, `domain/strategy`, `services/risk.py` et `services/execution.py` de les lire.

### 5. Les planchers de perte du fournisseur (FTMO)

Plancher quotidien = **solde enregistré à 00:00 CE(S)T** (`Europe/Prague`, fuseau **nommé**, jamais déduit de l'horloge du serveur) − le montant quotidien (un pourcentage du capital **initial**) ; plancher maximal = capital initial − montant (`STATIC_INITIAL`, 2-Step) ou **plus haut solde de 00:00** (ou capital initial s'il est plus grand) − montant (`TRAILING_EOD_BALANCE`, 1-Step). L'**équité** est ce qui est testée. Les références sont des **lignes écrites une fois** (`provider_loss_references`, `ON CONFLICT DO NOTHING`, aucun `UPDATE` ni `DELETE`) : elles survivent à un redémarrage, une déconnexion, un changement de réglage ou de stratégie. Au démarrage d'un cœur qui n'était pas là à minuit, le solde de ce moment est **reconstruit** depuis l'historique des deals (un solde ne dépend pas du flottant : une position ouverte à minuit n'empêche pas la reconstruction). Référence manquante, périmée ou incomplète ⇒ état `unknown` ⇒ **entrées refusées**. Un plancher franchi ⇒ verrou **persistant** (`gate-provider-loss`), comme les limites personnelles. Les budgets restants sous chaque plancher entrent dans le minimum du risque autorisé par trade (risque ouvert compté en plein).

### 6. News, pauses de marché, requêtes : le doute bloque

* **News FTMO** : ±2 minutes autour d'une publication restreinte, sur les instruments qu'elle touche (paire de devises contenant la devise ; or et indices américains pour le dollar ; pétrole seulement pour les publications pétrolières), pour toute action d'ordre ; seulement pour le **compte FTMO Standard** (ni Challenge, ni Verification, ni Swing). Sans calendrier restreint **fourni par le fournisseur** (aucune source n'est branchée, un calendrier économique générique ne peut pas autoriser), le produit refuse ses entrées : `provider_news_calendar_unknown`, **voulu**.
* **Pauses de plus de deux heures** : le Standard FTMO doit être à plat avant. La règle est distincte de tout arrêt général (ADR 0033 : un `HALT` ne ferme pas tout). Le paquet `MetaTrader5` n'expose pas les sessions (`SymbolInfoSessionTrade` est MQL5) : sans horaire de pause connu, le produit soumis à la règle refuse ses entrées (`provider_overnight_schedule_unknown`). La source possible est l'agent MQL5 (accord séparé).
* **Requêtes** : plus de 2 000 requêtes de serveur par jour est de l'hyperactivité d'EA (page « forbidden-trading-practices »). Les entrées s'arrêtent à 90 % du plafond ; **fermer n'est jamais refusé** par le budget.

### 7. Commission : la mesure d'abord, la documentation ensuite, l'hypothèse étiquetée

Ordre de confiance : **observée** (commissions des deals des positions entièrement fermées du compte, par lot, aller-retour) > **documentaire** (le contrat du produit : Exness Standard, aucune) > **supposée** (le chiffre réglé par l'utilisateur, étiqueté comme une hypothèse, remplacé dès le premier aller-retour observé). La commission est celle du **porteur** : un profil FTMO répété sur la démo Exness ne lui fait plus payer 5 $/lot. Elle remplace la valeur réglée dans les règles effectives (`AccountService.effective`), donc partout où elle est lue (revue du risque, dimensionnement, tampon du break-even, porte de coût de la stratégie). Un écart avec la documentation est signalé.

### 8. Spécification d'instrument complète, sans valeur supposée

`InstrumentSpecification` lit : cotes, spread flottant, modes de négociation et d'exécution, modes de remplissage, swap long / court / mode / jour du triple swap, volume maximal et limite, niveaux de stop et de gel, devises. Ce que le terminal n'a pas dit est dans `missing`, reste `None` et n'est jamais remplacé (un swap de 0 *déclaré* est une valeur ; l'absence de swap est une inconnue). Ce qui bloque un ordre (`trade_mode`, `execution_mode`, `filling_mode`, `stops_level`, `freeze_level`) fait refuser l'entrée avec `instrument_specification_missing`. Les sessions sont toujours marquées manquantes.

## Interprétations retenues, à confirmer ou corriger par Exhorte

1. **Montant de la perte maximale glissante (1-Step)** : lu comme un pourcentage du **capital initial** (10 % de 100 000 = 10 000, plancher = plus haut solde de minuit − 10 000). La page ne le dit pas en toutes lettres ; le seuil « 90 % du capital initial » cité pour un retrait de récompense va dans ce sens.
2. **Fuseau du jour FTMO** : `Europe/Prague` (CE(S)T), comme l'écrit la page des objectifs. La page technique situe les serveurs MetaTrader en « GMT+2 avec heure d'été » : si c'était vrai, minuit serveur ≠ minuit CE(S)T. À vérifier sur un terminal FTMO réel (aucun n'est connecté).
3. **Pages Exness illisibles** (HTTP 403 le 2026-11-03) : marge à 60 %, stop out à 0 %, exécution au marché, aucune commission sur Standard sont les valeurs de la mission, recoupées par un **résumé de recherche**, pas par la page. À relire.
4. **Pages FTMO lues par extraction automatique du texte** : à relire avant tout compte réel (surtout la méthode du Instant et le montant du plafond glissant).
5. **Prudence personnelle, pas règles du fournisseur** : aucune entrée à moins de 30 minutes d'une pause restreinte, avertissement à 75 % et arrêt des entrées à 90 % des requêtes du jour. Réglables, à décider.
6. **Observation de l'ADR 0019 §4 toujours ouverte** : avec un capital initial fixé, le déclencheur de 200 $ ne change rien (la grille donne déjà ≤ 1 % sous le capital initial). Non modifié.
7. La **commission supposée de 5 $/lot** reste **réglée** dans les règles stockées de la démo (`execution_profile`) : elle n'est plus utilisée tant qu'une valeur observée ou documentaire existe, mais la ligne du registre n'a pas été réécrite (une règle de compte change par un geste d'Exhorte).

## Ce que cet ADR ne fait pas

L'ordre de la mission est respecté : les étapes 1 à 7 (identification, adaptateurs, profils, spécifications, politique effective, règles FTMO et Exness) sont construites, et une partie de l'étape 12 (carte « Environnement et règles du fournisseur » sur l'écran Compte ; les refus du fournisseur figurent dans « Pourquoi pas de trade ? » comme lignes bloquées `provider:<code>` du modèle de risque). Les étapes **8 à 11 et 13** — collecte de ticks à la milliseconde (L2), mesure des latences et coûts de bout en bout (L1 est fait), cycle d'exécution `PLACED`/`PARTIALLY_FILLED`, résilience (L5), démarrage automatique de MT5 et de l'agent — **ne sont pas construites**, ni les vues de marché (qualité des données, latences) du cockpit. Aucun ordre n'est parti, aucun terminal lancé, aucun essai sur un compte FTMO (aucun n'existe ici).

## Conséquences

* Nouveau : `domain/providers/{rules,identity,profile,loss_floors,restrictions,commission,context}.py`, `domain/market/instrument.py`, `domain/risk/effective.py`, `services/providers.py`, `infrastructure/database/repositories/providers.py`, migration 0006, `GET /api/accounts/{id}/{profile,effective-policy,provider-loss}`.
* Le Risk Engine reçoit un `ProviderContext` optionnel (`TradingContext.provider`) : cinq familles de contrôles (`provider_identity_*`, `provider_loss_*`, `provider_news`, `provider_overnight`, `provider_requests`) et un contrôle d'intention (`instrument_specification`), une porte (`gate-provider-loss`), deux budgets (`provider_daily_budget`, `provider_max_budget`). Sans contexte fourni, rien ne change.
* **Conséquence assumée** : un compte dont le produit n'est pas déclaré, ou dont les noms ne se recoupent pas, ne peut plus recevoir d'entrée. Pour la démo Exness (serveur, société et société du terminal « Exness », suffixe `m`) l'identification est attendue `CONFIRMED` — **non vérifié sur le terminal réel** à l'écriture de cet ADR (le serveur de la démo est `Exness-MT5Trial10` ; la société et le suffixe sont à constater).
* Les tests de la simulation de terminal rapportent désormais la société du compte (et non plus « Simulated Broker »), et 100:1 de levier pour FTMO : des valeurs simulées, jamais présentées comme des relevés.
