# T15 — Serveur MCP « mon trading »

Serveur MCP en lecture seule (ADR 0005) exposant les données déjà
disponibles via l'API REST de `TradingOs.Host` : trades clos, historique de
lockout, bougies, propositions EA-02, divergence d'exécution (EA-06), et une
recombinaison des violations de conformité (T07). Aucune connexion directe à
Postgres ou à MT5 depuis ce process — voir
`context/product/tools/T15-serveur-mcp.md` pour le détail des décisions.

## Prérequis

- `TradingOs.Host` démarré (`dotnet run` dans
  `backend/src/TradingOs.Host`, écoute sur `http://localhost:5080` par
  défaut).
- La variable d'environnement `TRADING_OS_ACCOUNT_ID` — l'`accountId` du
  compte à interroger (usage strictement personnel : un seul compte,
  configuré une fois, jamais redemandé outil par outil).
- Optionnel : `NEXT_PUBLIC_BACKEND_HUB_URL` si le backend n'écoute pas sur
  `http://localhost:5080/hub/cockpit` (même variable que le cockpit —
  `lib/realtime/backend-url.ts`).

## Lancer en local

```bash
TRADING_OS_ACCOUNT_ID=<ton accountId> npm run mcp
```

Le serveur communique en `stdio` — il n'affiche rien tant qu'aucun client
MCP ne lui parle. `Trading OS MCP server running on stdio.` sur stderr
confirme qu'il a démarré.

## Configurer dans Claude Desktop / Claude Code

Ajouter dans la configuration MCP du client (`claude_desktop_config.json`
pour Claude Desktop, ou l'équivalent Claude Code) :

```json
{
  "mcpServers": {
    "trading-os": {
      "command": "npx",
      "args": ["tsx", "tools/mcp-server/index.ts"],
      "cwd": "C:\\Dev\\trading-operating-system\\04_code",
      "env": {
        "TRADING_OS_ACCOUNT_ID": "<ton accountId>"
      }
    }
  }
}
```

Ce projet ne s'auto-enregistre jamais dans les réglages MCP de
l'utilisateur — cette étape reste manuelle, par choix (fiche T15,
« Comportement attendu »).

## Outils exposés

| Outil | Source | Description |
|---|---|---|
| `get_trades` | `/api/journal/trades` | Trades clos sur une plage, P&L réalisé, capture disponible ou non. |
| `get_lockouts` | `/api/risk/lockouts` | Historique des fenêtres de lockout jusqu'à une date. |
| `get_candles` | `/api/candles` | Bougies OHLC pour un symbole/timeframe/plage. |
| `get_setup_proposals` | `/api/setup-proposals` | Évaluations EA-02 (proposées ou bloquées) depuis une date. |
| `get_execution_divergence` | `/api/execution/divergence` | Positions externes (EA-06) et résolutions `UNKNOWN`. |
| `get_compliance_violations` | `get_trades` + `get_lockouts`, recombinés | Violations T07 (lockout actif, fenêtre de session) par trade + taux de conformité. Recalculé à chaque appel, jamais mis en cache — pas la taille (balance courante indisponible en REST, voir la fiche). |

Aucun outil n'écrit quoi que ce soit. Aucun outil ne calcule ou n'expose une
métrique de performance déjà figée (expectancy, profit factor, taux de
réussite) — ce sont des faits, l'interprétation se fait dans la
conversation.
