# Contextes bornés

Réécrit le 2026-10-09 (ADR 0016). Chaque contexte est un module du même processus Python (`python/trading_os/domain/<contexte>/` et `services/`) : ce sont des frontières de code, pas de processus ni de ports.

## Comptes

Possède les comptes (Exness, FTMO — tous deux via MT5), le compte actif unique, la connexion et la déconnexion, et les **profils** qui portent leurs différences (profil de risque, règles de trading, politique d'actualité, de drawdown, limites de positions et d'exécution). Aucun secret dans le modèle : les mots de passe MT5 restent dans MT5 (ADR 0013). Pas de `if ftmo` hors des profils.

## Données de marché

Possède ticks, bougies, spreads, spécifications de symbole, sessions, calendrier économique (FRED) et la persistance des séries. Seul fournisseur de données de marché ; MT5 est la source.

## Analyse ICT/SMC

Possède la structure de marché, la liquidité, les PD arrays (FVG, order blocks), premium/discount et le contexte de marché. Fournit du contexte, jamais de signal (ADR 0002).

## Stratégie

Possède S01, la stratégie formalisée par l'utilisateur. Produit des intentions de trade et mesure son accord avec ce qui a réellement été pris (ADR 0011). Ne décide ni du risque ni de l'ordre.

## Risque

Possède les politiques par compte, les limites de la prop firm, la perte du jour, le drawdown, le dimensionnement avec les spécifications réelles du symbole, l'exposition corrélée, les verrous et le kill switch. Évalue chaque intention : le point de contrôle unique avant toute exécution (ADR 0007).

## Exécution

Possède les commandes (identifiant d'idempotence, états explicites), le routage selon le mode d'autonomie, les envois, accusés et rapports, et la réconciliation des commandes en doute. Les commandes sont idempotentes, persistées avant l'envoi, auditables.

## Positions et réconciliation

Possède l'état des positions et des ordres tel que MT5 le rapporte (identifiant de position, jamais le ticket), la détection d'ouverture et de clôture, et la comparaison entre l'état du Trading OS et celui de MT5.

## Autonomie

Possède l'échelle OFF → OBSERVE → PAPER → CONFIRM → ARMED → AUTONOMOUS (+ HALTED), le bail d'armement, la readiness et l'arrêt. Une seule condition critique en échec = autonomie bloquée.

## Journal

Reconstitue chaque trade (intention → décision → commande → résultat), enregistre les faits de capture (chiffres seulement : ADR 0018), juge la conformité après coup (T07). Aucune saisie manuelle.

## Supervision

Évalue la santé de tout le reste, ouvre et ferme des incidents, déclenche SAFE / DISARM / HALT / RECONNECT / RECONCILE selon la gravité.

## Cockpit

Possède l'interaction, la visualisation et l'explicabilité. Il n'évalue aucune règle : il affiche ce que le cœur calcule et lui envoie des gestes humains.
