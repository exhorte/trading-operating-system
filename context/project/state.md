# État du projet

Dernière mise à jour : 2026-09-17. Instantané seulement — l'historique vit
dans `session-log.md` (ADR 0008) et dans le journal de chaque fiche d'outil.

## En une phrase

Poste de travail personnel pour trader intraday, sorti de la recherche
d'edge (ADR 0002). T01 et T04 ont été retirés le 2026-09-14 (décision
explicite) ; le critère de sortie de Vague 1 a été reformulé le même jour et
**n'est toujours pas rempli, et son ampleur réelle vient de doubler** — un
second incident de lockout contourné (5 trades, 2026-09-14) a été découvert
le 2026-09-17 en testant T15, s'ajoutant au trade isolé du 2026-09-15 déjà
connu. Voir « Ce qui bloque ». La priorité reste
l'**agent d'exécution MT5** (ADR 0010), construit jusqu'au mode CONFIRM
uniquement. Phase 0 et EA-01 à **EA-06 sont livrés**. EA-05 incrément 6
(2026-09-15, sur accord explicite séparé) : le dépôt contient désormais **un**
`OrderSend`, unique, **structurellement inatteignable hors `CONFIRM`** — et le
mode est une constante de compilation figée à `OBSERVE`, jamais affectée. Il
n'a donc jamais tourné contre un broker, même en démo. EA-06 (2026-09-16, sur
« valide les deux, enchaîne sur les incréments ») ajoute la résolution
d'`UNKNOWN` et le signalement `EXTERNAL_POSITION` — la seconde tourne déjà en
réel (`PositionsTotal()` ne dépend pas du mode), la première reste sans
trafic tant qu'`OrderSend` est inatteignable. Ouvrir `CONFIRM` est EA-07.
**T06 livré le 2026-09-16** (Vague 2, choisi explicitement par l'utilisateur
plutôt qu'EA-07 ou la clôture de Vague 1) : `/journal` est maintenant une
vraie liste filtrable, plus le stub — vérifié contre les vrais trades du
2026-09-14/15 en appelant l'endpoint directement, jamais vu rendu dans un
navigateur (aucun agent MT5 connecté à cette session). **T07 livré le
2026-09-16** : taux de conformité hebdomadaire (`ComplianceBadge`, lockout +
fenêtre de session + taille). **T15 livré le 2026-09-17** : serveur MCP en
lecture seule (`tools/mcp-server/`), vérifié par un vrai handshake MCP
contre des données réelles — c'est ce test qui a révélé le second incident
de lockout ci-dessus.

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
| Cockpit | `app/(cockpit)/`, `components/` | Coquille sombre et dense ; T01 (sizing) et T04 (ticket) retirés le 2026-09-14 (décision explicite), bandeau kill switch T02a, chrono de pause T02b, chip calendrier FRED T03, viewer de capture T05 (`/journal/[brokerPositionId]`). `/journal` (T06, 2026-09-16) : table filtrable + calendrier P&L + ventilations symbole/session/heure/jour, zéro nouvelle table (vue pure sur `closed_trades`/`position_opens`/`trade_captures`/`setup_proposals`) + colonne Violations (T07). `TopCommandBar` porte désormais `ComplianceBadge` (T07, taux de conformité hebdomadaire — la vraie tête de cockpit, charter.md principe 2), à la place où le P&L irait. `/positions` (EA-06) : divergence — positions externes, `UNKNOWN` résolus. |
| Captures de trade | `lib/journal/`, `components/journal/`, `trade_captures` | T05 : faits immuables écrits par le Gateway (fenêtre, prix), rendu à la demande côté cockpit via `analyzeMarketContext` — jamais une image pré-rendue (ADR 0009). Écriture fiable même sur aller-retour rapide depuis le correctif du 2026-09-15. **Rendu cassé pour tout symbole hors XAUUSDm** (pas de M15 en base pour EURUSD/GBPUSD) — voir « Ce qui bloque ». |

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

**Aucun outil en construction.** La priorité immédiate n'est plus de coder :
c'est que l'utilisateur prenne connaissance du second incident de lockout
contourné découvert le 2026-09-17 (voir « Ce qui bloque ») — 5 trades de
plus que ce qui était documenté, sur le 2026-09-14. Rien à corriger côté
outillage pour ça ; c'est un fait sur des séances réelles, pas un défaut de
gate.

T15 (Vague 2) livré le 2026-09-17 — voir sa fiche pour le détail des 4
incréments et des quatre décisions validées (Node/TS via `tsx`, jamais
Python ni un service C# séparé ; toujours via l'API REST existante, jamais
Postgres/MT5 en direct ; expose des faits, jamais une métrique de
performance pré-calculée ; taille hors politique hors périmètre — balance
courante indisponible en REST). Vérifié par un vrai handshake MCP contre
des données réelles, pas seulement les gates.

T07 (Vague 2) livré le 2026-09-16 — voir sa fiche pour le détail des 4
incréments. Trois violations détectées automatiquement (lockout actif,
fenêtre de session, taille hors politique — approximée sur la balance
courante) ; une, stop déplacé après l'entrée, reste hors périmètre. Le taux
de conformité hebdomadaire s'affiche dans `TopCommandBar`
(`ComplianceBadge`). **Même limite que T06** : jamais vu rendu à l'écran
avec de vraies données, aucun agent MT5 connecté à cette session.

Vague 2 continue avec T08 (dépend de T06, livré) quand il sera choisi
explicitement.

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
