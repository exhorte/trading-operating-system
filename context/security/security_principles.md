# Principes de sécurité

## Secrets

- Ne jamais committer de clé d'API, d'identifiant de courtier ou de prop firm, ni de mot de passe de compte.
- Variables d'environnement et `04_code/.env` (gitignoré) ; les secrets sont séparés de la configuration.
- Séparer les identifiants de démonstration, de test et réels.
- **Aucun mot de passe de compte de trading n'est demandé, stocké ni partagé** (ADR 0013) : MT5 garde le sien. Là où un identifiant doit transiter, c'est dans un modèle de requête en `SecretStr`, en écriture seule, jamais dans une réponse, un événement, un journal, une exception ni une table (un test parcourt les modèles et `information_schema` pour que cela reste vrai).

## Sûreté de trading

- Mode explicite : le plafond `TRADING_MODE` (`OBSERVE` par défaut) ; le relever est un geste de l'utilisateur.
- L'exécution réelle exige une configuration délibérée, un accord nommé et sa propre étape (`.claude/CLAUDE.md`).
- L'arrêt d'urgence existe avant toute exécution réelle : kill switch du cœur, arrêt local de l'agent (bouton du graphique, fichier), interrupteur d'homme mort.
- Les sessions WebSocket s'authentifient, et les commandes d'un client non autorisé sont rejetées ; une commande est protégée contre le rejeu et le doublon (`commandId`, idempotence aux deux bouts).

## Contrôle d'accès

- Les droits d'exécution sont plus stricts que ceux de la lecture : un jeton de cockpit pour toute l'API, un jeton d'agent pour le lien MT5, et rien d'autre ne peut ordonner.
- L'assistant de développement (Claude) ne déclenche jamais un ordre, un armement ou l'autonomie, et ne voit jamais de mot de passe réel.

## Surface locale

Ce qui peut piloter le Trading OS sur cette machine, et avec quoi. Réécrit le 2026-10-09 pour le cœur Python ; le modèle de menace est celui de l'ADR 0013.

| Porte | Qui y entre | Garde |
|---|---|---|
| API REST `/api/*` (8000) | le cockpit | jeton du cockpit (`Authorization: Bearer`) **et** Origin autorisée, sur **chaque** requête, lectures comprises ; seul `GET /api/system/health` est ouvert (un lanceur ou une supervision le lit sans navigateur) |
| WebSocket `/ws` (8000) | le cockpit | même jeton (`?access_token=` : un navigateur ne peut pas poser d'en-tête sur un WebSocket) **et** Origin autorisée, dès la poignée de main ; le jeton est masqué dans les journaux |
| Le cœur (8000, 9765) | — | lié à `127.0.0.1` : le cœur refuse de démarrer sur une autre adresse |
| Lien agent (9765) | l'agent EA-05 | jeton de l'agent dans le `hello`, lu par l'EA dans `MQL5\Files\tradingos_agent.token` (écrit par `scripts/start.ps1`) ; comparé en temps constant, jamais gardé ; sans jeton configuré, **tout** agent est refusé |
| Processus de lecture MT5 | le cœur | un processus enfant par terminal, JSON sur stdio, **liste blanche** de fonctions de lecture : aucune fonction d'ordre n'y est exécutable |
| Cockpit Next (3000) | le navigateur | lié à `127.0.0.1` ; `proxy.ts` refuse tout Host hors loopback |
| Route `/api/cockpit-token` (3000) | les scripts de la page | Host loopback et `Sec-Fetch-Site: same-origin` |

Les jetons (`TRADINGOS_COCKPIT_TOKEN`, `TRADINGOS_AGENT_TOKEN`) vivent dans `04_code/.env`, gitignoré, que `scripts/start.ps1` complète une fois et n'affiche jamais ; le cœur et `next dev` le lisent eux-mêmes. Sans jeton configuré, chaque porte gardée refuse tout (échec fermé). Les journaux du cœur passent par un formateur de masquage (jetons enregistrés, `Bearer …`, `access_token=…`, `password=…`) : et uvicorn est configuré **sans** son propre format de journal (`log_config=None`), parce que son format d'origine écrivait la ligne d'acceptation du WebSocket avec le jeton en clair — un test le garde.

**Contre quoi ça protège** : une page web ouverte dans un autre onglet (CORS ne couvre pas les WebSockets : sans l'Origin, n'importe quel site pourrait rejoindre le flux et le lire), le DNS rebinding, le réseau local (tout est sur la boucle locale), un autre programme qui parle au port sans le jeton.

**Contre quoi ça ne protège pas** : un programme qui tourne sous le compte Windows du trader (il lit `.env`, la mémoire et les fichiers de MT5), et un client qui forge délibérément Host et `Sec-Fetch-Site` pour demander le jeton au serveur Next, puis forge l'Origin pour l'API. Limite assumée : le modèle de menace est une page web hostile et le réseau, pas un logiciel malveillant ciblé sur cette machine (ADR 0013).
