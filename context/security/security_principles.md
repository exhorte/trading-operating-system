# Security Principles

## Secrets

- Never commit API keys, broker credentials, prop firm credentials, or account passwords.
- Use environment variables or a secret manager.
- Separate demo, test, and live credentials.

## Trading Safety

- Require explicit environment mode: mock, paper, demo, live.
- Live execution must require deliberate configuration.
- Emergency stop must be available before live execution.
- WebSocket sessions must authenticate, authorize subscriptions, and reject commands from unauthorized clients.
- Execution commands must be signed or otherwise protected against replay and duplication once real trading is introduced.

## Access Control

- Users should only access accounts and strategies they are allowed to control.
- Execution permissions should be stricter than read-only dashboard permissions.

## Surface locale (I0, 2026-09-26)

Ce qui peut piloter le Trading OS sur cette machine, et avec quoi.

| Porte | Qui y entre | Garde |
|---|---|---|
| Hub `/hub/cockpit` (5080) | le cockpit | jeton du cockpit **et** Origin autorisée, sur chaque requête (poignée de main WebSocket comprise) ; WebSockets seuls |
| Écritures `/api/*` (5080) | le cockpit (Settings) | même jeton, même Origin |
| Lectures `/api/*`, `/health` (5080) | cockpit, serveur MCP, revue hebdo, `start-live` | aucune : lecture seule |
| Tout le backend (5080) | — | `AllowedHosts` : `localhost` et `127.0.0.1` seulement |
| Observateur (8765) | le backend | jeton de l'observateur ; toute requête avec une Origin (navigateur) refusée |
| Cockpit Next (3000) | le navigateur | lié à `127.0.0.1` ; `proxy.ts` refuse tout Host hors loopback |
| Route `/api/cockpit-token` (3000) | les scripts de la page | Host loopback et `Sec-Fetch-Site: same-origin` |
| Agent EA-05 (9765) | l'EA | **pas encore de jeton** : prévu avec I1 (il faut une entrée côté MQL5) |

Les jetons (`TRADINGOS_COCKPIT_TOKEN`, `TRADINGOS_OBSERVER_TOKEN`) vivent dans
`04_code/.env`, gitignoré, que `scripts/start-live.ps1` complète une fois et
n'affiche jamais ; `docker compose`, `next dev` et l'observateur le lisent
eux-mêmes. Sans jeton configuré, chaque porte gardée refuse tout. Le jeton
n'apparaît jamais dans `docker logs` : le formateur de console masque
`access_token=` et `Bearer` (`RedactingConsoleFormatter.cs`).

**Contre quoi ça protège** : une page web ouverte dans un autre onglet (CORS
ne couvre pas les WebSockets : sans l'Origin, n'importe quel site pouvait
rejoindre le hub et appeler `SubmitCommand` ou publier
`risk.lockout.cleared`), le DNS rebinding, le réseau local, et le trafic
générique d'un conteneur (qui atteint les ports publiés sur 127.0.0.1 par
`host.docker.internal`).

**Contre quoi ça ne protège pas** : un programme qui tourne sous le compte du
trader (il lit `.env`), et un client qui forge délibérément Host et
`Sec-Fetch-Site` pour demander le jeton au serveur Next, puis forge l'Origin
pour le hub. Limite assumée : c'est le modèle de menace de l'étude (ADR 0013
à rédiger), pas un logiciel malveillant ciblé sur cette machine.

Vérifié le 2026-09-26 sur une instance isolée (ports à part, base coupée) :
poignée de main 101 avec jeton et Origin du cockpit ; 403 sans jeton, avec un
mauvais jeton, avec une Origin étrangère ou sans Origin ; 400 avec un Host
forgé ; écriture REST 403 sans jeton ou sans Origin ; jeton absent de tout le
journal ; observateur réel : backend accepté avec le jeton, 403 sans, avec un
mauvais jeton ou avec une Origin ; cockpit dans un navigateur connecté au hub
gardé, et message clair quand le jeton manque.
