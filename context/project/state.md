# État du projet

Dernière mise à jour : 2026-09-17. Instantané seulement — l'historique vit
dans `session-log.md` (ADR 0008) et dans le journal de chaque fiche d'outil.

## En une phrase

Poste de travail personnel pour trader intraday, sorti de la recherche
d'edge (ADR 0002). T01 et T04 ont été retirés le 2026-09-14 (décision
explicite) ; le critère de sortie de Vague 1 a été reformulé le même jour et
**n'est toujours pas rempli, et son ampleur réelle vient de doubler**
(2026-09-17, voir « Ce qui bloque ») — priorité au-dessus de tout ce qui
suit. L'**agent d'exécution MT5** (ADR 0010) est construit jusqu'au mode
CONFIRM uniquement : Phase 0 et EA-01 à **EA-06 sont livrés**, un seul
`OrderSend` existe (EA-05 incrément 6), **structurellement inatteignable
hors `CONFIRM`** (`g_mode` figé à `OBSERVE`, jamais affecté) — il n'a donc
jamais tourné contre un broker. Ouvrir `CONFIRM` est EA-07, non démarré,
non demandé, et ses propres préconditions ne sont pas remplies. **Vague 2
est livrée** (T06 journal, T07 conformité, T15 serveur MCP, T08 revue
hebdomadaire) — son propre critère de sortie (taux de conformité affiché
en haut du cockpit) est rempli. Détail de chaque brique dans sa propre
fiche (`context/product/tools/`) et dans `session-log.md`, pas ici — ce
fichier reste un instantané.

## Ce qui existe et fonctionne

Validé en live contre le compte de démonstration Exness (XAUUSDm) jusqu'au
28 juillet 2026 : la chaîne temps réel, les contrats, la persistance, le
chemin d'exécution. **Ce que la Vague 1 a ajouté par-dessus (T01–T05) n'a
jamais tourné contre un vrai terminal** — voir « Ce qui bloque ».

| Brique | Où | État |
|---|---|---|
| Chaîne temps réel MT5 → cockpit | `tools/mt5-observer/`, `backend/src/TradingOs.Gateway/`, `backend/src/TradingOs.Host/` | Validée live. Observer Python lecture seule → gateway .NET → SignalR → cockpit. |
| Contrats de domaine | `lib/domain/`, `lib/contracts/` | TypeScript portable, miroirs C# dans `TradingOs.Contracts`. |
| Moteur d'analyse | `lib/analysis/` | Swings, structure, liquidité, PD arrays, sessions, ATR. Pur, testé. Sert de source de niveaux — **pas de source de signal**. |
| Risk Engine | `lib/risk/` | Gates FTMO, sizing, lockout (ledger stocké, pause de 30 min sur pertes consécutives depuis T02b), gate calendrier FRED fail-closed depuis T03. Pur, testé. |
| Chemin d'exécution | `lib/execution/`, `lib/domain/execution-state.ts`, `CockpitHub`, `Mt5AgentServer` | `RiskDecision → Command → ACK → Report`, mode `observe`/SIMULATED. Protocole et machine à états figés (EA-03) : `commandId`/`accountId`/`protocolVersion`, `UNKNOWN` de premier ordre, `ACCOUNT_MISMATCH` typé. **Un seul `OrderSend` existe** (`tools/mt5-execution-agent/TradingOsAgent.mq5`, `ExecuteOrder`, EA-05 incrément 6) — première instruction de la fonction : sortie si le mode n'est pas `CONFIRM` ; `g_mode` est un `const` de compilation à `MODE_OBSERVE`, jamais affecté. Chemin prouvablement mort dans ce build. EA-06 (2026-09-16) ajoute la résolution d'`UNKNOWN` (sans trafic tant qu'`OrderSend` reste mort) et le signalement `EXTERNAL_POSITION` (`ScanOpenPositions`, réel dès aujourd'hui) — cockpit sur `/positions`. |
| Comptes et symboles | `lib/accounts/`, `lib/market/symbols/` | EA-04 : `defaultRiskPolicy` résout par compte (registre vide à ce jour — aucun compte FTMO/réel confirmé), registre canonique↔broker EURUSD/GBPUSD/XAUUSD. |
| Agent d'exécution MT5 | `tools/mt5-execution-agent/`, `backend/src/TradingOs.Gateway/Mt5AgentServer.cs` | EA-05 : connexion, heartbeat, réception, validation locale, persistance `commandId → résultat` sur disque — **vérifiés par l'utilisateur contre un vrai terminal** (2026-09-12). Mode figé à `OBSERVE` par construction. |
| Persistance | `backend/src/TradingOs.Persistence/`, `docker-compose.yml` | TimescaleDB port 5433, écriture non bloquante, audit JSONB. |
| Cockpit | `app/(cockpit)/`, `components/` | Coquille sombre et dense ; T01 (sizing) et T04 (ticket) retirés le 2026-09-14 (décision explicite), bandeau kill switch T02a, chrono de pause T02b, chip calendrier FRED T03, viewer de capture T05 (`/journal/[brokerPositionId]`). `/journal` (T06, 2026-09-16) : table filtrable + calendrier P&L + ventilations symbole/session/heure/jour, zéro nouvelle table (vue pure sur `closed_trades`/`position_opens`/`trade_captures`/`setup_proposals`) + colonne Violations (T07). `TopCommandBar` porte désormais `ComplianceBadge` (T07, taux de conformité hebdomadaire — la vraie tête de cockpit, charter.md principe 2), à la place où le P&L irait. `/positions` (EA-06) : divergence — positions externes, `UNKNOWN` résolus. `/preflight` (T09) : verdict `Armé`/`Pas armé` sur les 9 gates du Risk Engine, dont le gate de connexion ajouté par T09. |
| Captures de trade | `lib/journal/`, `components/journal/`, `trade_captures` | T05 : faits immuables écrits par le Gateway (fenêtre, prix), rendu à la demande côté cockpit via `analyzeMarketContext` — jamais une image pré-rendue (ADR 0009). Écriture fiable même sur aller-retour rapide depuis le correctif du 2026-09-15. **Rendu cassé pour tout symbole hors XAUUSDm** (pas de M15 en base pour EURUSD/GBPUSD) — voir « Ce qui bloque ». |
| Outils standalone | `tools/mcp-server/`, `tools/weekly-review/`, `tools/shared/` | T15 (serveur MCP lecture seule, `npm run mcp`) et T08 (revue hebdomadaire Markdown, `npm run weekly-review`) : deux scripts `tsx` autonomes, toujours via l'API REST existante (`tools/shared/backend-client.ts`, jamais Postgres/MT5 en direct), important `lib/compliance/` plutôt que de le réécrire. |

## Ce qui a été supprimé le 2026-09-04

La recherche d'edge et la mémoire de la série 1, en entier. Liste exhaustive
et raisons : `context/project/pivot-2026-09-04.md`.

## Ce qui bloque

**Le critère de sortie de Vague 1 (reformulé le 2026-09-14) n'est pas
rempli — et c'est plus large qu'on ne le pensait.** Sur ses trois points :
le kill switch a été déclenché et acquitté pour de vrai (2026-09-15, cycle
complet vérifié dans `risk_lockouts` + `kill_switch_acks`) ; les captures
tiennent sur un aller-retour de 60 s (2026-09-15, voir T05) ; mais une
position EURUSDm a été ouverte à 09:36:00 UTC le 2026-09-15 pendant que le
lockout kill-switch était actif (09:34:44 → 09:37:18) — exactement ce que
le critère existe pour détecter. La vague reste ouverte.

**Second incident, découvert le 2026-09-17 en testant T15 — jamais
documenté avant ce jour.** `get_compliance_violations` (T15, réutilise T07)
interrogé sur toute la plage 2026-09-14/15 fait remonter **5 trades EURUSDm
ouverts pendant que la gate « Daily loss guard » était active**, du
2026-09-14 (`lockout-mu1af4l7-8lbceb`, verrouillé 13:37:28, jamais acquitté
— levée seulement le lendemain matin 08:54:25) : positions 3225706315
(13:49:49), 3225729956 (13:52:36), 3225966706 (14:19:50), 3226050174
(14:29:21), 3226089957 (14:35:04) — toutes après le déclenchement, toutes
avant la levée du lendemain. Vérifié à la main contre les horodatages bruts
avant d'être retenu (détail dans le journal de T15) : une position
XAUUSDm ouverte une seconde **avant** le déclenchement (3225577967,
13:36:35.861) n'est, à raison, pas comptée. Ni bug de T15 ni de T07 — un
fait réel sur des données réelles, invisible jusqu'ici parce que personne
n'avait encore posé cette question précise sur toute la plage plutôt que
sur un seul trade isolé. Le critère de sortie de Vague 1 était déjà non
rempli ; ceci ne change pas la conclusion, mais en révèle l'ampleur réelle
— six trades sur deux jours, pas un.

**T02a/T02b, précision utile pour EA-07** : le kill switch et la gate
« Daily loss guard » ont tous deux tourné en réel plusieurs fois (verrouillage
→ acquittement/reset → levée, tracé en base). **La pause de 30 min sur deux
pertes consécutives (T02b, la gate temporisée spécifique) n'a elle jamais
été déclenchée** — un seul trade perdant est survenu jusqu'ici, jamais deux
d'affilée (`risk_lockouts` : zéro ligne avec `until` renseigné). La barrière
d'EA-07 (« T02a/T02b vérifiés en réel ») n'est donc que partiellement remplie.

*(Corrigé le 2026-09-15 — le rendu T05 hors XAUUSD : le viewer rebâtit
désormais le timeframe de la capture depuis le M1 avec l'agrégation d'EA-02,
et n'affiche plus de ligne pour un SL/TP à 0, qui écrasait l'échelle de prix.
Vérifié à l'écran sur la position 3230177984.)*

Friction héritée du 28 juillet 2026 : l'observer a calé une fois (14:03) sur
une collecte longue. Piste si ça revient : `gmag11/MetaTrader5-Docker`.

## Prochaine action

**T10 — brief pré-séance automatique (Vague 3)**, suite pré-autorisée
(« Vague 3 — T09/T10, puis T19 »). Pas encore commencé.

T09 livré le 2026-09-17 : `/preflight` (verdict `Armé` / `Pas armé` +
points vérifiés) et un **vrai trou bouché au passage** — `connectionGate` :
jusqu'ici le Risk Engine approuvait un ordre sans jamais vérifier qu'un
agent d'exécution était joignable, la découverte n'arrivant qu'à l'envoi
(`AGENT_UNREACHABLE`). Périmètre réduit après cartographie : l'auto-
vérification, l'affichage par gate et le refus du Risk Engine existaient
déjà tous les trois.

**Déblocage méthodologique à retenir** : le mode `mock`
(`NEXT_PUBLIC_REALTIME_SOURCE=mock`, sur un port séparé) permet de voir
les pages du cockpit rendues **sans backend ni agent MT5**. C'est ce qui
bloquait la vérification visuelle depuis T05 (`useCockpit().account` reste
null sans flux live). **T06 et T07, jamais vus à l'écran, peuvent être
vérifiés de cette façon** — à faire.

**Vague 2 livrée le 2026-09-17 — les quatre outils identifiés
(T06/T07/T15/T08) sont tous délivrés**, y compris son propre critère de
sortie (roadmap.md) : le taux de conformité hebdomadaire se calcule
automatiquement et s'affiche en haut du cockpit (`ComplianceBadge`, T07).
Détail de chaque outil dans sa fiche (`context/product/tools/T0{6,7,8}-*.md`,
`T15-serveur-mcp.md`). **Même limite pour les quatre** : jamais vus rendus
à l'écran avec de vraies données — vérifiés contre le backend et la base
réels (appels directs, un vrai handshake MCP pour T15, un document généré
et relu pour T08), jamais dans un navigateur avec un agent MT5 connecté.

**Plus urgent que la prochaine phase : l'utilisateur n'a toujours pas réagi
au second incident de lockout contourné**, découvert le 2026-09-17 en
testant T15 (voir « Ce qui bloque ») — 5 trades de plus que ce qui était
documenté, sur le 2026-09-14, en plus du trade du 2026-09-15 déjà connu.
Rien à corriger côté outillage ; c'est un fait sur des séances réelles.

Aucun nouvel outil de roadmap identifié au-delà de Vague 2 pour l'instant —
la suite (Vague 3, T09+) dépend de T11/T12 (multi-compte, hors périmètre
tant qu'un deuxième compte prop firm n'existe pas) ou d'un choix explicite
de l'utilisateur.

T06 (Vague 2) livré le 2026-09-16 — voir sa fiche pour le détail des 4
incréments et des trois décisions validées (P&L par trade oui,
expectancy/profit factor/courbe d'équité non — même ligne qu'ADR 0011 ;
zéro nouvelle table ; lien Capture jamais mort). **Restant ouvert, à
vérifier à la prochaine séance avec MT5/l'observer connectés** : `/journal`
n'a jamais été vu rendu dans un navigateur — vérifié uniquement en appelant
`GET /api/journal/trades` directement contre les vrais trades du
2026-09-14/15 (confirmé : jointures correctes, `null` honnête sur le trade
sans capture et sur les stops jamais posés), jamais par un écran réel.

Le track EA reste en pause. EA-01 à EA-06 sont livrés ; EA-06 (2026-09-16) a
fermé les deux trous que l'incrément 6 d'EA-05 avait laissés ouverts
(résolution `UNKNOWN`, attribution `EXTERNAL_POSITION`) — voir sa fiche pour
deux limites assumées et non encore vérifiées en conditions réelles : la
propagation du commentaire de commande jusqu'au deal MT5 (hypothèse jamais
testée, `OrderSend` n'ayant encore jamais tourné), et le scénario de mort
agent entre `OrderSend` et l'accusé (vérifié par lecture du code, pas par un
test exécuté — aucun harnais MQL5 n'existe ici). Les conditions d'EA-07 se
remplissent par de vrais trades, pas par du code — voir « Ce qui reste
fermé » ci-dessous.

**Ce qui reste fermé, et ne s'ouvre pas par déduction** : rendre `CONFIRM`
atteignable (EA-07). Pas d'input de mode, pas de `control.set_mode`, pas de
seconde voie d'exécution — aucune consigne générale d'« avancer » ou de
« clôturer » ne vaut accord pour ça. Les conditions de sa fiche ne sont de
toute façon pas remplies : (a) T02b — la pause 30 min sur deux pertes
consécutives — n'a jamais été déclenchée en réel ; (b) le taux d'accord
d'EA-02 est toujours inconnu (zéro proposition sur 595 évaluations) ;
(c) la Vague 1 n'est pas close (un trade a été ouvert pendant un lockout
actif le 2026-09-15).

## Questions ouvertes

- Quel déclencheur pour le multi-compte ? Par défaut : le jour où un deuxième compte prop firm est ouvert.
- Le compte FTMO existe-t-il déjà ? Toute la modélisation de ses règles est urgente ou spéculative selon la réponse.
- Veut-on pousser un trade manuel par le même chemin d'exécution, pour qu'il soit journalisé identiquement ?
