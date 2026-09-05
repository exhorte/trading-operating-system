> **Note de reprise (2026-09-04).** Ce document est la recherche qui a produit la roadmap.
> Il est conservé dans le dépôt comme référence : le raisonnement, les efforts estimés et la
> section « ce que je ne recommande pas de construire » y sont argumentés en entier.
> La numérotation `#1..#19` correspond aux identifiants `T01..T19` de la roadmap.
> **La roadmap qui fait foi est `context/project/roadmap.md`** ; en cas de divergence, elle gagne.
> Ce document ne sera plus mis à jour.

# Catalogue d'outils — automatiser et augmenter le travail de trader intraday

Date : 2026-09-04
Demande : « quels outils / systèmes / produits construire pour automatiser et augmenter ma productivité de trader intraday ».
Périmètre déclaré comme prioritaire par l'utilisateur : **les quatre goulots à la fois** — préparation pré-séance, exécution & discipline, revue & journal, admin prop firm / multi-comptes.

Ce document **ne remplace pas** `2026-09-03-audit-reprise-et-recherche-verifiee.md`. Il le complète sur un axe différent : l'audit dit *quoi construire pour que la plateforme existe*, celui-ci dit *quoi construire pour que la plateforme te fasse gagner du temps et de l'argent le plus tôt possible*.

## Contraintes héritées, non rediscutées ici

- **ADR 0001** — la plateforme est le produit, l'EA n'est pas le cerveau.
- **`context/ai/ai_future.md`** — l'IA reste côté lecture, classement, résumé, explication. Jamais côté décision, jamais côté ordre.
- **Usage strictement personnel** (décision du 2026-09-03). Aucun de ces outils n'est pensé pour être vendu.
- **Étape 0 du plan de reprise** (débloquer + lecture unique du holdout) passe avant tout ce qui suit.
- **Aucune nouvelle chasse à l'edge** avant que la plateforme tienne.

---

## 0. Le constat qui structure ce catalogue

Trois observations avant la liste.

**1. Le gain d'un intraday ne vient pas d'un meilleur signal.** Il vient de trois choses mesurables : décider vite et avant l'ouverture, ne pas violer son propre process en séance, et ne pas payer la taxe de saisie après. Un outil qui améliore le signal est un pari ; un outil qui supprime une violation de process est un gain certain. Tout le classement ci-dessous découle de ça.

**2. La moitié des outils à plus fort ratio valeur/effort ne dépendent pas du multi-compte.** Le plan de reprise place le multi-compte (Étape 2, 1–2 semaines) en prérequis de tout le reste — c'est vrai pour le Prop Firm Control Center, c'est faux pour le calculateur de taille, le gate news, le lockout comportemental, le ticket pré-trade et les captures automatiques. Ces cinq-là fonctionnent sur un compte unique, avec le code déjà présent dans `lib/risk/` et `tools/mt5-observer/`. **C'est la tranche à livrer en premier** : elle rend la plateforme utile quotidiennement en une semaine au lieu de six.

**3. Ton vrai KPI n'est pas le P&L, c'est le taux de conformité au plan.** Le P&L d'un intraday sur 20 trades est du bruit. Le pourcentage de trades pris conformément au plan écrit avant l'ouverture ne l'est pas, et il est mesurable dès que le ticket pré-trade existe. Plusieurs outils ci-dessous n'ont pas d'autre but que de rendre ce chiffre observable.

---

## 1. Vue d'ensemble priorisée

Effort en jours de travail effectif, à la louche. Valeur = impact quotidien réel, 1 à 5.

| # | Outil | Goulot | Où | Effort | Valeur | Dépend de |
|---|---|---|---|---|---|---|
| 1 | Calculateur de taille one-click | Exécution | TOS (cockpit) | 0,5–1 j | 5 | rien |
| 2 | Lockout comportemental (kill switch) | Exécution | TOS (`lib/risk`) | 1–2 j | 5 | rien |
| 3 | Gate calendrier économique | Pré-séance + Exécution | TOS (`lib/risk/gates`) | 1–2 j | 5 | rien |
| 4 | Ticket pré-trade (15 s) | Exécution + Revue | TOS (cockpit) | 1 j | 5 | rien |
| 5 | Captures automatiques entrée/sortie | Revue | TOS (observer) | 1–2 j | 4 | rien |
| 6 | Journal auto-alimenté, zéro saisie | Revue | TOS (Étape 4) | 3–5 j | 5 | #4, #5 |
| 7 | Tracker d'erreurs + taux de conformité | Revue | TOS (journal) | 1–2 j | 5 | #6 |
| 8 | Revue hebdomadaire générée | Revue | TOS ou CLI | 1–2 j | 4 | #6 |
| 9 | Checklist de pré-vol exécutable | Pré-séance | TOS (cockpit) | 1–2 j | 4 | #3 |
| 10 | Brief pré-séance automatique | Pré-séance | TOS (`lib/analysis`) | 2–3 j | 4 | #3 |
| 11 | Multi-compte natif | Admin | TOS (Étape 2) | 1–2 sem | 3 | rien |
| 12 | Prop Firm Control Center | Admin | TOS (Étape 3) | 1–2 sem | 5 | #11 |
| 13 | Simulateur de règles pré-trade | Admin + Exécution | TOS | 1–2 j | 4 | #12 |
| 14 | Alertes lecture seule (Telegram/push) | Admin | Standalone | 1 j | 3 | #12 partiel |
| 15 | Serveur MCP « mon trading » | Transverse | Standalone | 1–2 j | 4 | #6 |
| 16 | Dictée vocale horodatée (Vozel) | Exécution + Revue | Standalone | 1–2 j | 4 | rien |
| 17 | Rapport hebdo CLI depuis export MT5 | Revue | Standalone | 1 j | 3 | rien |
| 18 | Watcher de conditions de marché | Pré-séance | Standalone | 0,5 j | 2 | rien |
| 19 | AI Analyst RAG (lecture seule) | Transverse | TOS (Étape 5) | 1–2 sem | 3 | #6, #15 |

**Ratio valeur/effort décroissant** : 1, 4, 2, 3, 5, 7, 16, 15, 8, 17, 9, 13, 6, 10, 14, 12, 18, 11, 19.

Note sur #11 et #12 : le multi-compte a une valeur *propre* faible (3) mais il débloque le Prop Firm Control Center qui vaut 5. Ne pas lire la ligne 11 isolément.

---

## 2. Vague 1 — les cinq quick wins (~5 à 8 jours cumulés)

Aucun de ces cinq ne dépend du multi-compte. Ensemble, ils transforment le cockpit d'un projet de recherche en un poste de travail utilisable dès le lendemain.

### 1. Calculateur de taille one-click

**Problème.** Tu calcules ta taille de position à la main ou dans MT5, plusieurs fois par jour, sous pression, au moment exact où l'erreur coûte le plus cher. C'est l'action la plus répétée de ta journée et la plus dangereuse à faire de tête.

**Ce que ça fait.** Un panneau permanent dans le cockpit : tu saisis prix d'entrée et stop, il sort en temps réel le nombre de lots, le risque en devise du compte, la distance en pips, le R cible pour un TP donné, et — le point important — **la part du drawdown quotidien autorisé que ce trade consomme s'il part au stop**.

**Où ça se branche.** `lib/risk/sizing.ts` existe déjà et est testé (`sizing.test.ts`). Il manque uniquement l'interface. C'est un composant React branché sur une fonction pure existante.

**Effort.** 0,5 à 1 jour. C'est le meilleur ratio du catalogue, de loin.

**Signal de réussite.** Tu n'ouvres plus la calculatrice de MT5.

---

### 2. Lockout comportemental (kill switch)

**Problème.** Le mode d'échec dominant de l'intraday n'est pas la mauvaise analyse, c'est la séquence : deux pertes, puis un trade hors plan pour se refaire, puis une taille doublée. Aucun rappel écrit n'a jamais arrêté ça. Seul un système qui refuse physiquement l'ordre l'arrête.

**Ce que ça fait.** Un ensemble de verrous durs, configurés à froid, appliqués à chaud :

- perte quotidienne maximale atteinte → séance verrouillée jusqu'au lendemain ;
- nombre de trades maximum par séance atteint → verrouillé ;
- deux pertes consécutives → pause forcée de 30 minutes, chrono affiché ;
- hors fenêtre de session autorisée (ex. : hors 12:00–16:00 UTC pour NY AM) → refus ;
- kill switch manuel : un bouton qui coupe tout, ferme les positions et verrouille.

Le verrou vit dans le Risk Engine, pas dans l'interface — un refus doit être un `RiskDecision` refusée sur le chemin `RiskDecision → Command → ACK → Report`, pas un `disabled` sur un bouton qu'on peut contourner en passant par MT5.

**Où ça se branche.** `lib/risk/gates.ts`, `lib/risk/policy.ts`, `lib/risk/evaluate.ts`. Les gates existent ; il manque les gates *comportementales* (compteurs de séance, séquence de pertes, horloge) et la persistance de l'état de verrouillage.

**Limite à assumer.** Tant que tu peux ouvrir MT5 à côté, le verrou est un ralentisseur, pas un mur. Il reste efficace : la friction de 20 secondes est exactement ce qui manque au revenge trade. Une version « mur » (mot de passe scellé, déverrouillage différé de 24 h) est possible plus tard.

**Effort.** 1 à 2 jours.

**Signal de réussite.** Le nombre de trades pris après 15h30 tombe à zéro alors que tu n'as rien changé à ta discipline.

---

### 3. Gate calendrier économique

**Problème.** Sur XAUUSD, les mouvements qui te sortent d'un trade correct viennent de publications programmées, connues à la minute près, des semaines à l'avance. Se faire sortir par un CPI qu'on avait oublié est une erreur d'agenda, pas d'analyse.

**Ce que ça fait.** Un service qui charge les dates de publication à venir, les met en cache, expose `isNewsBlackout(t)` et alimente **une gate du Risk Engine** — pas une règle de stratégie, conformément au plan de reprise. Fenêtre par défaut : −30 / +30 min autour d'une publication à impact élevé. Affichage permanent dans le cockpit : « prochaine publication : CPI US dans 1 h 47, blackout à partir de 14:00 ».

**Source de données — le point qui bloquait.** L'audit notait qu'il n'existe que des scrapers ForexFactory fragiles et juridiquement exposés. La sortie, pour un usage personnel et pour un besoin qui se limite à *quand*, est l'API FRED de la Fed de Saint-Louis : l'endpoint `fred/releases/dates` retourne les dates de publication de toutes les séries, et avec `include_release_dates_with_no_data=true` il retourne **les dates futures** du calendrier de publication. Clé API gratuite, source officielle, licence claire. Il suffit de figer une liste blanche d'une dizaine de release IDs (CPI, NFP/Employment Situation, PCE, retail sales, ISM, FOMC) : cet ensemble est petit et stable.

Ce que FRED **ne donne pas** : la classification d'impact et le consensus des analystes. Pour la gate, ce n'est pas nécessaire — la liste blanche *est* la classification d'impact, et le consensus ne sert pas à décider de ne pas trader. Si le consensus devient utile plus tard (côté lecture uniquement), les candidats commerciaux sont Trading Economics, Financial Modeling Prep et Finnhub ; tous trois documentent un endpoint calendrier, mais **les tarifs et les tiers doivent être vérifiés au moment de l'achat** — je n'ai pas pu les confirmer depuis leurs pages publiques.

**Effort.** 1 à 2 jours, dont une demi-journée pour la liste blanche.

**Signal de réussite.** Plus aucun trade ouvert dans les 30 minutes précédant une publication majeure, sans que tu aies eu à y penser.

---

### 4. Ticket pré-trade (15 secondes)

**Problème.** Un journal rempli le soir est une reconstruction, pas un enregistrement. Tu ne te souviens plus de pourquoi tu es entré ; tu écris une justification rétrospective, cohérente avec le résultat. C'est le biais qui rend la plupart des journaux de trading inutiles.

**Ce que ça fait.** Avant l'envoi de l'ordre, un formulaire de quatre champs, tous en boutons, aucun texte libre obligatoire :

- **setup** (liste fermée : FVG, OB, liquidity sweep, retest…),
- **biais** (long / short / contre-tendance),
- **invalidation** (le prix qui prouve que tu as tort — c'est déjà ton stop, donc pré-rempli),
- **confiance** (1 à 5).

Plus, optionnel, une note vocale (voir #16). Quinze secondes maximum, sinon tu le contourneras.

**Pourquoi c'est le pivot du catalogue.** Ce ticket est simultanément : la ligne de journal (donc #6 devient gratuit), la mesure de conformité (donc #7 devient possible), et un ralentisseur avant l'entrée impulsive (donc il renforce #2). Un seul objet, trois effets.

**Où ça se branche.** En amont de `lib/execution/command-builder.ts`, persisté dans TimescaleDB avec l'identifiant de commande, de sorte que le fill le rattache automatiquement au trade.

**Effort.** 1 jour.

**Signal de réussite.** Tes trades à confiance 1 et 2 ont une expectancy mesurable, et elle est probablement négative.

---

### 5. Captures automatiques entrée / sortie

**Problème.** Le dossier `05_screenchot/` du projet dit tout : les captures sont prises à la main. C'est la corvée qui fait abandonner les journaux, et elle est prise *après* coup, donc sur un graphique qui a déjà bougé.

**Ce que ça fait.** Sur événement de fill (entrée) et sur événement de clôture (sortie), le système capture automatiquement l'état du graphique et l'attache au trade. Deux implémentations possibles :

- **rendu maison** — le cockpit reconstruit le graphique depuis TimescaleDB (les bougies y sont déjà) et l'exporte en image. Reproductible, versionnable, indépendant de MT5, et fonctionne aussi en rejeu ;
- **capture de la fenêtre MT5** — plus fidèle à ce que tu voyais réellement, mais fragile (dépend de la fenêtre au premier plan, du terminal ouvert, de la résolution).

Recommandation : le rendu maison, avec la fenêtre temporelle centrée sur l'entrée, les niveaux de `lib/analysis/` superposés et les marqueurs entrée/stop/TP. La fidélité au pixel près n'a aucune valeur ; la reproductibilité en a.

**Où ça se branche.** `tools/mt5-observer/mt5_observer.py` émet déjà les événements ; il manque le déclencheur et le stockage des images.

**Effort.** 1 à 2 jours.

**Signal de réussite.** Tu ne prends plus une seule capture à la main.

---

## 3. Vague 2 — le journal qui ne se saisit pas (~5 à 9 jours)

C'est l'Étape 4 du plan de reprise, mais réordonnée : la valeur n'est pas dans les jolies statistiques, elle est dans le **zéro saisie**. Un journal qui demande dix minutes par soir sera abandonné en trois semaines, quelles que soient ses courbes.

### 6. Journal auto-alimenté

Les trades viennent de TimescaleDB (déjà présents), le contexte vient du ticket pré-trade (#4), les images viennent des captures automatiques (#5). **L'humain n'ajoute rien après coup, sauf s'il en a envie.** Ce qui reste à construire : le modèle de données du journal (schéma inspiré de TradeNote, voir l'audit), la réconciliation trade ↔ ticket ↔ captures, et les vues — calendrier P&L, courbe d'equity, expectancy, profit factor, R moyen.

Découpage par setup, par session, par heure d'entrée, par jour de la semaine et par niveau de confiance. Cette dernière ventilation est celle qui apprend le plus vite.

**Effort.** 3 à 5 jours si #4 et #5 sont faits (contre 1–2 semaines en partant de zéro).

### 7. Tracker d'erreurs et taux de conformité

Une taxonomie **fermée** d'erreurs — entrée anticipée, stop déplacé, taille hors politique, revenge trade, trade hors plan, sortie prématurée, absence de ticket. Fermée, sinon elle dérive et devient inexploitable.

La plupart de ces erreurs sont **détectables automatiquement** : une taille supérieure à la politique, un stop modifié après l'entrée, un trade sans ticket, un trade hors fenêtre de session. Le système les tague seul ; tu n'arbitres que les cas ambigus.

Sortie : une seule courbe, le **taux de conformité hebdomadaire**. C'est le chiffre à afficher en haut du cockpit, pas le P&L.

**Effort.** 1 à 2 jours.

### 8. Revue hebdomadaire générée

Générée automatiquement le vendredi soir : statistiques de la semaine, taux de conformité, les trois pires trades avec leur ticket pré-trade en regard du résultat, les trois erreurs les plus fréquentes, comparaison plan / exécution. Un document, pas un tableau de bord — quelque chose qui se lit une fois et se garde.

**Effort.** 1 à 2 jours.

---

## 4. Vague 3 — préparation et contrôle prop firm

### 9. Checklist de pré-vol exécutable

Pas un document à cocher : une checklist dont **le système vérifie lui-même les items**. Compte connecté, spread dans la norme pour l'heure, drawdown quotidien restant suffisant, aucun blackout news dans les 60 minutes, plan écrit pour la journée, verrous armés. Tant que tout n'est pas vert, la séance n'est pas « armée » et le Risk Engine refuse les ordres.

Effet secondaire recherché : le rituel de démarrage devient un bouton au lieu d'être une intention. **Effort.** 1 à 2 jours.

### 10. Brief pré-séance automatique

Généré à heure fixe avant l'ouverture de ta session : niveaux clés calculés depuis TimescaleDB (PDH/PDL, high/low de la session asiatique, extrêmes de la semaine précédente), ATR et range attendu, publications du jour et heures de blackout, état des comptes (DD restant, jours restants, distance au target), et rappel de tes propres statistiques pour ce jour de la semaine et cette session.

Tout vient de `lib/analysis/` (`sessions.ts`, `atr.ts`, `liquidity.ts`, `bias.ts`, `market-context.ts`) qui est déjà écrit et testé. C'est un assemblage, pas une nouvelle analyse.

**Attention au piège.** Le brief donne du **contexte**, pas une direction. Dès qu'il commence à écrire « biais haussier aujourd'hui », il devient un signal déguisé et contredit l'ADR 0001. Il décrit l'état du marché ; il ne conclut pas.

**Effort.** 2 à 3 jours.

### 11–13. Multi-compte, Prop Firm Control Center, simulateur de règles

Le multi-compte (Étape 2, 1–2 semaines) est de la plomberie : descendre le scope `workspace / account / connection` dans l'enveloppe, le hub SignalR, le schéma TimescaleDB et le store frontend. Valeur propre faible, mais prérequis du suivant.

Le **Prop Firm Control Center** (Étape 3) est, d'après l'audit, le trou le plus net de l'open source : registre de comptes (broker, firme, phase 1 / 2 / funded), règles par firme, profit target, daily DD, max DD, jours minimum, échéance de payout, kill switch global et lockout par compte.

Le **simulateur de règles** est la petite brique qui rend le Control Center utile à la seconde plutôt qu'à la journée : avant l'entrée, « si ce trade part au stop, où me place-t-il par rapport au daily DD et au max DD, sur ce compte, dans cette phase ? ». Une ligne de plus dans le calculateur de taille (#1), une fois que le contexte firme existe. **1 à 2 jours** après #12.

---

## 5. Vague 4 — intelligence de marché et analyste

C'est l'Étape 5 du plan de reprise, inchangée dans son ordre : **le déterministe d'abord** (calendrier, corrélations glissantes XAUUSD / DXY / US10Y / EURUSD / BTC), l'IA ensuite, et l'IA uniquement côté lecture.

Un ajout au plan, à fort effet de levier compte tenu de ta façon de travailler — et le seul élément de cette vague à construire **beaucoup plus tôt**, dès la Vague 2 (voir l'ordre de construction) :

### 15. Serveur MCP « mon trading »

Un serveur MCP en lecture seule exposant ta base : trades, tickets, erreurs, statistiques, bougies. Il te permet de poser les questions directement en langage naturel dans Claude, sans construire d'interface pour chacune : « quelle est mon expectancy sur les trades à confiance ≥ 4 ? », « mes lundis sont-ils rentables ? », « quel est mon R moyen après 15 h ? », « combien de trades hors plan ce mois-ci ? ».

Ça remplace 80 % de ce que ferait un AI Analyst (#19) pour 5 % de l'effort, et ça reste dans la règle : lecture seule, jamais d'exécution. `ariadng/metatrader-mcp-server` est une bonne référence de protocole — **sans en brancher la partie exécution**, comme le note déjà l'audit.

**Effort.** 1 à 2 jours. À faire dès que #6 existe.

---

## 6. Outils standalone (hors TOS)

Ceux-là ne dépendent pas de l'avancement de la plateforme et se construisent isolément.

### 16. Dictée vocale horodatée

Pendant le trade, tu dis ce que tu fais et pourquoi ; c'est transcrit, horodaté, et rattaché au trade par timestamp. C'est le seul moyen réaliste de capturer l'état émotionnel *au moment où il existe* — écrit après coup, il est reconstruit ; dit sur le moment, il est exact.

Recoupement direct avec **Vozel** : le moteur de dictée est déjà ton produit, il ne reste que la colle (horodatage, écriture en JSONL, rattachement). C'est aussi un cas d'usage réel de Vozel, testé par son auteur tous les jours. **1 à 2 jours.**

### 17. Rapport hebdomadaire CLI depuis l'export MT5

Un script qui lit le rapport HTML/CSV exporté depuis MT5 et sort un markdown de statistiques. Aucune dépendance au TOS, aucune base, aucun serveur. **Utile dès demain matin**, y compris si la plateforme n'avance pas pendant un mois. **1 jour.**

### 18. Watcher de conditions

Un petit processus qui surveille le spread et la volatilité et alerte quand les conditions sortent de la norme pour l'heure de la journée. Utile aussi comme sonde de qualité de la donnée : c'est exactement ce qui aurait signalé le stall de l'observer du 28 juillet. **0,5 jour.**

### 14. Alertes en lecture seule

Un bot Telegram ou une notification système en **lecture seule** : DD à 70 % du seuil, phase terminée, échéance de payout proche, blackout news imminent, observer déconnecté. Lecture seule et sans commande — un bot qui peut passer des ordres est un EA-cerveau déguisé. **1 jour.**

---

## 7. Ce que je ne recommande pas de construire

- **Un bot d'exécution autonome.** Contredit l'ADR 0001, et le seul candidat de stratégie que tu avais a été sélectionné post-hoc — le holdout n'est même pas encore lu.
- **Un générateur de signaux IA.** Le point est déjà tranché dans l'audit : sentiment ≠ direction, forecasting ≠ stratégie. Ces modèles restent côté lecture.
- **Un scraper ForexFactory.** Fragile et juridiquement exposé. FRED règle le besoin réel (voir #3).
- **Un dashboard de marché temps réel.** Tu as déjà MT5 pour ça, et il est meilleur. Ne reconstruis pas ce que tu regardes déjà ailleurs — construis ce que MT5 ne fait pas : ton process, tes règles, ton historique.
- **Un optimiseur de stratégie / une nouvelle recherche d'edge.** Explicitement hors plan tant que la plateforme ne tient pas.
- **Un copy-trading multi-comptes.** Séduisant avec le multi-compte en place, mais il multiplie l'exposition d'un edge non validé par le nombre de comptes.

---

## 8. Briques externes vérifiées (4 sept. 2026)

| Brique | Usage ici | État vérifié |
|---|---|---|
| **API FRED** (`fred/releases/dates`) | Dates de publication à venir pour le gate news (#3) | Endpoint réel, documenté. Clé API requise, gratuite. Dates **futures** accessibles via `include_release_dates_with_no_data=true`. Ne fournit ni impact ni consensus. |
| **Trading Economics / FMP / Finnhub** | Calendrier enrichi (impact, consensus) si besoin plus tard | Les trois documentent un endpoint calendrier. **Tarifs et tiers non confirmables depuis leurs pages publiques** — à vérifier à l'inscription. Aucun n'est nécessaire pour #3. |
| `joshyattridge/smart-money-concepts` | Oracle de test externe pour `lib/analysis/` | MIT, ~2 000 ★ (audit du 3 sept.) |
| `gmag11/MetaTrader5-Docker` | Observer conteneurisé, résout le stall du 28/07 | MIT, 387 ★ (audit du 3 sept.) |
| `Eleven-Trading/TradeNote` | Schéma de données du journal (#6) | GPL-3.0 — sans contrainte en usage personnel non distribué |
| `ariadng/metatrader-mcp-server` | Référence de protocole pour #15, **lecture seule** | MIT, 496 ★ (audit du 3 sept.) |

---

## 9. Ordre de construction proposé

```
Étape 0 (plan de reprise) ─── lecture unique du holdout          [1–2 j]
        │
        ▼
Vague 1 ─── #1 taille · #4 ticket · #2 lockout · #3 news · #5 captures
        │   plateforme utile tous les jours                      [5–8 j]
        ▼
Vague 2 ─── #6 journal · #7 conformité · #15 MCP · #8 revue
        │   la boucle d'apprentissage se ferme                   [6–11 j]
        ▼
Vague 3 ─── #9 checklist · #10 brief · #11 multi-compte · #12 prop firm · #13 simulateur
        │   la plateforme devient un poste de travail complet    [3–5 sem]
        ▼
Vague 4 ─── #19 AI Analyst · corrélations · intelligence de marché
            l'analyse conversationnelle sur ta propre donnée     [2–3 sem]
```

Deux écarts assumés par rapport au plan de reprise du 3 septembre :

1. **L'Étape 1 (rétrograder la stratégie au rang de module) est repoussée après la Vague 1.** C'est un refactor de gouvernance, sans effet sur ta journée de trading. Il reste nécessaire — mais il n'y a aucune raison qu'il précède cinq outils utilisables en une semaine.
2. **Le journal (Étape 4) remonte avant le multi-compte (Étape 2) et le Prop Firm Control Center (Étape 3).** Le journal est ce qui rend la plateforme utile quotidiennement, indépendamment de toute stratégie ; le multi-compte est de la plomberie qui ne change rien à ta journée tant qu'un seul compte est actif. Cet ordre s'inverse le jour où tu ouvres un deuxième compte prop firm — c'est le déclencheur à surveiller.

Si tu ne construis que trois choses de tout ce document : **#1 (calculateur de taille), #4 (ticket pré-trade), #2 (lockout)**. Deux à quatre jours, et ils couvrent le mode d'échec qui coûte le plus cher à un intraday.
