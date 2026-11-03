# Modes d'autonomie, démarrage, arrêt et fermeture globale

Statut : accepté le 2026-11-02 (ADR 0034). Complète `safety.md` (barrières), `protocol.md` (fil et refus), ADR 0014 et 0015 (armement, autonomie). Le code : `python/trading_os/domain/autonomy/` (échelle, préparation, correspondance du plan), `services/startup.py`, `services/close_all.py`.

## 1. L'échelle du dépôt et celle du plan (§18)

Le dépôt monte `OFF → OBSERVE → PAPER → CONFIRM → ARMED → AUTONOMOUS` (+ `HALTED`), **un échelon à la fois**, jamais au-dessus du plafond (`min(TRADING_MODE, max_mode du compte)`, `OBSERVE` par défaut). Le plan nomme six modes. C'est la même échelle, vue avec l'environnement du compte :

| Plan | Dépôt | Environnement | Ce que le mode permet |
|---|---|---|---|
| (arrêté) | `OFF` | tous | rien ne tourne côté stratégie ; aucun ordre |
| `OBSERVE` | `OBSERVE` | tous | le système analyse et journalise les setups ; **aucun ordre** |
| `PAPER` | `PAPER` | tous | ordres **simulés** dans le cœur ; aucun ordre au courtier |
| `CONFIRM` | `CONFIRM` | `DEMO`, `SIMULATED` | chaque ordre attend la confirmation de l'humain, puis part vers l'agent |
| `DEMO_AUTO` | `ARMED`, `AUTONOMOUS` | `DEMO`, `SIMULATED` | le système prend des positions seul, si la préparation est verte (continuellement) |
| `LIVE_CONFIRM` | `CONFIRM` | `LIVE` | idem `CONFIRM`, argent réel |
| `LIVE_AUTO` | `ARMED`, `AUTONOMOUS` | `LIVE` | idem `DEMO_AUTO`, argent réel |
| (arrêt) | `HALTED` | tous | aucune nouvelle entrée ; surveillance et fermeture à la main restent |

C'est une **lecture** (`domain/autonomy/plan_modes.py`) : aucun état du dépôt n'est renommé, ajouté ou retiré, et rien dans le cœur ne s'y branche. Le cockpit affiche le nom du plan et ce qu'il permet.

Garde-fous qui ne changent pas : le système démarre **toujours `OFF`** (un redémarrage ne reprend jamais un mode, ADR 0014) ; seul un arrêt `HALTED` survit à un redémarrage, jusqu'à acquittement explicite (retour `OFF`) ; les modes automatiques exigent la préparation verte *au moment de l'armement* puis en continu (tolérance de 20 s, ensuite retour à `CONFIRM`) ; `ARMED` est une fenêtre de 30 minutes que l'humain renouvelle.

## 2. Trois choses qu'on ne confond pas

| Geste | Où | Ce qu'il fait | Ce qu'il ne fait jamais |
|---|---|---|---|
| **A — Démarrer l'application** | `scripts/start.ps1` (base, schéma, cœur, cockpit) | lance les processus ; le cockpit s'affiche | autoriser le moindre ordre ; se connecter à un courtier ; armer |
| **B — « DÉMARRER LE SYSTÈME »** | cockpit (Command Center, écran Démarrage) → `POST /api/system/startup` | vérifie treize étapes, force une lecture du terminal et une **réconciliation**, tente de connecter le compte sélectionné **sans mot de passe**, puis monte `OFF → OBSERVE` (ou `PAPER`/`CONFIRM` si demandé) | monter plus haut que `CONFIRM` ; envoyer un ordre ; armer |
| **C — « AUTORISER LE TRADING AUTOMATIQUE »** | cockpit (écran Démarrage) → `POST /api/system/startup/authorize-automatic` | un échelon (`CONFIRM → ARMED`, `ARMED → AUTONOMOUS`) avec la préparation verte évaluée pour cet appel, le plafond du compte respecté | se faire déduire d'un démarrage ou d'un redémarrage |

Le bouton ne peut pas lancer un cœur qui n'écoute pas (il n'est pas là pour recevoir le clic) : les étapes 1 à 3 *vérifient* l'application, ses services et la base. Les moteurs (marché, risque, stratégie, Guardian, Position Manager, exécution, superviseur) sont lancés par le cœur lui-même au démarrage du processus ; « démarrer le système » les vérifie et fait avancer l'autonomie.

### Les treize étapes et leurs états

Chaque étape affiche `STOPPED`, `STARTING`, `READY`, `RUNNING`, `DEGRADED`, `FAILED` ou `HALTED`, avec la raison du cœur. Ordre : application · services · base de données · terminal MT5 · compte · agent MQL5 · réconciliation · Market Data · Strategy Engine · Account Guardian · Risk Engine · mode d'autonomie · autorisation de prendre des positions. Les étapes **bloquantes** (base, terminal, compte) arrêtent la séquence : le système reste `OFF`, avec la raison. Les autres laissent monter jusqu'à `OBSERVE` (analyse sans ordre) mais retiennent `CONFIRM`.

### Les vingt-deux conditions avant une position

Les seize contrôles de préparation (`domain/autonomy/readiness.py`) plus six propres au démarrage : données de marché fraîches · Account Guardian opérationnel (a bouclé il y a moins de 30 s) · aucune commande `UNKNOWN` non résolue · limites jour/semaine et capital de référence chargés · aucun verrou, arrêt ni blocage de sécurité · mode explicitement autorisé (plafond du compte ≥ `CONFIRM`). `entriesAuthorized` n'est vrai que si le mode envoie des ordres **et** que les vingt-deux sont verts. Si une seule manque, le système reste non-tradant et le dit.

**Écart connu.** Les six conditions propres au démarrage sont exigées au moment de monter à `CONFIRM` et d'autoriser l'automatique, et affichées en continu ; elles ne rétrogradent pas un mode déjà monté. Les seize de la préparation, elles, rétrogradent (ADR 0015).

### Compte réel

Un compte `LIVE` affiche en rouge, partout où un mode est montré : **COMPTE RÉEL — LES ORDRES PEUVENT ENTRAÎNER UNE PERTE FINANCIÈRE**. Monter à `LIVE_CONFIRM` ou autoriser `LIVE_AUTO` exige une confirmation explicite dans la requête (`acknowledgeRealAccount: true`), que le cockpit ne recueille qu'avec une case cochée. `OBSERVE` et `PAPER` n'envoient rien et n'en demandent pas.

## 3. Arrêter : quatre gestes distincts

| Geste | Effet | Ferme des positions ? |
|---|---|---|
| Arrêter les nouvelles entrées | `autonomy/disarm` vers `OBSERVE` : plus aucun ordre, l'analyse continue | non |
| Arrêter les moteurs de stratégie | `autonomy/disarm` vers `OFF` : les stratégies n'évaluent plus ; Guardian et Position Manager continuent de surveiller | non |
| Arrêt d'urgence (`HALTED`) | état + kill switch local de l'agent + verrou du compte ; bloque ouvertures, `MODIFY`, commandes automatiques ; **les fermetures et annulations humaines passent** (ADR 0033) | **non** |
| **Fermer toutes les positions** | voir §4 | oui, sur confirmation |

Un `HALTED` ne ferme rien par défaut. Une liquidation automatique sous arrêt serait un ADR séparé (plan de reprise, K) ; elle n'existe pas. L'annulation automatique des ordres en attente sous arrêt n'existe pas non plus : l'annulation est une option explicite de la fermeture globale.

## 4. Fermer toutes les positions

Une **commande de sortie humaine**, par le chemin existant `cockpit → API → ExecutionService → agent MQL5 → MT5`, sans second mécanisme.

1. `GET /api/execution/close-all/preview` lit le terminal à neuf et rend ce qui serait fermé (compte et fournisseur, numéro masqué aux quatre derniers chiffres, positions avec sens, volume, entrée, SL, TP, P&L latent ; ordres en attente) et un `batchId`. **N'envoie rien.**
2. Le cockpit demande la confirmation « CONFIRMER LA FERMETURE DE TOUTES LES POSITIONS ». Ouvrir la fenêtre ne ferme rien.
3. `POST /api/execution/close-all` (`confirmation: "CLOSE_ALL"`, `positionIds` vus dans la prévisualisation) : une commande `CLOSE` par position, `commandId = ca-<batch>-<positionId>`, soumise avec `automatic=False`. Les ordres en attente ne sont annulés (`CANCEL`, `ca-<batch>-o<orderId>`) que si l'option est cochée. Un double clic, un rejeu : mêmes identifiants, rien n'est exécuté deux fois.
4. `GET …/{batchId}` suit le lot ; `POST …/{batchId}/verify` lit le terminal et réconcilie (lecture seule). Le rapport est **dérivé** des commandes enregistrées et de l'événement `execution.close_all_requested` : il survit à un redémarrage.

Chaque élément passe par `IN_PROGRESS`, `VERIFYING`, puis **`CONFIRMED` seulement si la commande est exécutée ET que MT5 ne montre plus la position**. `SIMULATED` (agent compilé `OBSERVE`, mode `PAPER`) ne ferme rien et est dit tel quel. `UNKNOWN` n'est jamais renvoyé : la réconciliation tranche. Le lot n'est `COMPLETE` qu'après une réconciliation lisible terminée depuis le dernier règlement. Sinon `INCOMPLETE`, avec les motifs et l'action recommandée.

**Limite.** L'agent ne ferme que ce qu'il a lui-même placé (`TARGET_NOT_OURS`, numéro magique). Une position ouverte à la main dans MT5 ou par un autre EA est marquée `NOT_CLOSABLE`, comptée parmi les « positions encore ouvertes », avec l'action « fermer dans MT5 ». Lever cette barrière demande de modifier l'unique `OrderSend` : accord et ADR séparés.

**Et tant que l'agent est compilé `OBSERVE`**, toute fermeture répond `SIMULATED` : le cockpit l'écrit et ne dit jamais « fermé ».
