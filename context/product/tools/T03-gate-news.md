# T03 — Gate calendrier économique

Statut : **livré** (2026-09-05) · Vague 1 · Effort 1–2 j · Valeur 5 · Dépend de : rien

## Problème

Sur XAUUSD, les mouvements qui sortent d'un trade correct viennent de publications programmées, connues à la minute près des semaines à l'avance. Se faire sortir par un CPI oublié est une erreur d'agenda, pas d'analyse.

## Comportement attendu

Un service qui charge les dates de publication à venir, les met en cache localement, expose `isNewsBlackout(t)` et alimente **une gate du Risk Engine** (ADR 0007) — pas une règle de stratégie.

Fenêtre par défaut : **−30 / +30 minutes** autour d'une publication de la liste blanche. Configurable.

Affichage permanent dans le cockpit : « prochaine publication : CPI US dans 1 h 47 — blackout à 14:00 ».

## Source de données

**API FRED de la Fed de Saint-Louis.** L'endpoint est **`fred/release/dates`** (singulier — la fiche initiale disait `fred/releases/dates`, corrigé après vérification de la doc officielle le 2026-09-05) ; avec `include_release_dates_with_no_data=true` il retourne les **dates futures** du calendrier. Clé API gratuite, source officielle, licence claire.

Liste blanche de release IDs, vérifiée le 2026-09-05 via `fred.stlouisfed.org/release?rid=X` (chaque ID confirmé par le titre de la page) :

| Release | release_id | Heure de publication (ET) |
|---|---|---|
| CPI (Consumer Price Index) | 10 | 8:30 |
| Employment Situation (NFP) | 50 | 8:30 |
| Personal Income and Outlays (PCE) | 54 | 8:30 |
| Advance Monthly Sales for Retail and Food Services | 9 | 8:30 |
| FOMC Press Release | 101 | 14:00 |

**ISM est absent, et c'est définitif, pas un oubli** : l'ISM a fait retirer toutes ses séries de FRED en 2016 (litige de licence) — aucun `release_id` ISM n'existe. Pas de source de remplacement (la fiche exclut déjà les sources commerciales et ForexFactory) ; si ISM devient nécessaire un jour, ce sera une nouvelle décision, pas un contournement de celle-ci.

**Piège non documenté par la fiche initiale** : `fred/release/dates` ne renvoie qu'une **date**, jamais une heure. Les heures ci-dessus sont l'horaire de publication officiel, stable depuis des années (BLS/BEA/Census : 8h30 ET ; annonce FOMC : 14h00 ET depuis mars 2013 — vérifié par une source réelle : le communiqué FOMC du 10/12/2025, publié à 14h00 EST). Combinées à la date FRED, elles sont résolues en instant UTC réel via `TimeZoneInfo`/`America/New_York` (jamais un offset UTC figé — `FredReleaseSchedule.ToUtcInstant`, testé contre ce même communiqué réel pour l'hiver et un cas synthétique pour l'été).

Ce que FRED ne donne pas : le consensus des analystes. Il ne sert pas à décider de ne pas trader, donc il est hors périmètre de cet outil.

**Écarté explicitement** : les scrapers ForexFactory — fragiles et juridiquement exposés.

## Ancrage dans le code

- `lib/risk/gates.ts` — `newsGate()` a changé de signature (`releases, now, policy`), le stub est remplacé, pas dupliqué.
- `lib/risk/news-calendar.ts` (nouveau) — `isNewsBlackout`, `nextRelease`, pures, testées.
- `lib/domain/risk.ts::UpcomingRelease` — le type portable (mirroré `TradingOs.Contracts.UpcomingRelease`).
- Backend : `backend/src/TradingOs.Gateway/FredReleaseSchedule.cs` (whitelist + résolution UTC), `FredCalendarClient.cs` (fetch FRED), `backend/src/TradingOs.Host/NewsCalendarService.cs` (BackgroundService : charge le cache DB au démarrage, rafraîchit toutes les 6h, diffuse `market.calendar.updated`), `backend/src/TradingOs.Persistence/NewsCalendarRepository.cs` (table `news_releases`, hors pipeline `PersistenceWriter` — un rafraîchissement remplace tout un `release_id` d'un coup, pas une ligne à la fois).
- `GET /api/calendar/upcoming` — surface HTTP secondaire (ADR 0003), même famille que `/api/risk/today`.
- Cockpit : `components/shell/news-calendar-badge.tsx`, branché dans `top-command-bar.tsx` (permanent, visible depuis toute page).

## Décision : où vit la clé API

La fiche initiale disait `.env.local` (convention Next.js/frontend). **Changé** : le fetch FRED se fait côté backend .NET, jamais dans le navigateur — une clé lue côté client serait visible dans le bundle. La clé vit dans la config .NET (`Fred:ApiKey`, `appsettings.json` garde une entrée vide, jamais la vraie valeur) : à définir via la variable d'environnement `FRED__ApiKey` ou `dotnet user-secrets set "Fred:ApiKey" "..."` en dev, jamais commitée. `.env.local`/`.env.example` restent réservés aux variables `NEXT_PUBLIC_*` du cockpit.

## Décision : absence de données — `null` vs `[]`

Le point le plus important de l'outil (« en cas de données absentes, la gate refuse ») a un piège au démarrage : un backend tout juste démarré, avant son premier fetch FRED réussi, a une table `news_releases` vide. Si ça se traduisait par `releases: []`, la gate lirait « calendrier connu, rien à venir » et **s'ouvrirait à tort** — exactement le fail-open que l'outil existe pour empêcher.

Résolu en distinguant `null` (jamais synchronisé — `NewsCalendarRepository.GetUpcomingOrNullAsync` retourne `null` si la table est totalement vide) de `[]` (synchronisé au moins une fois, rien à venir pour l'instant). `newsGate()` refuse sur `null`, jamais sur `[]`. Le `NewsCalendarService` diffuse l'état réel du cache DB dès le démarrage, avant toute tentative réseau, pour qu'un redémarrage sans réseau reste sur le dernier état connu plutôt que de tout effacer.

## Critère de réussite

Plus aucun trade ouvert dans les 30 minutes précédant une publication majeure, sans y avoir pensé.

## Journal

- 2026-09-04 — fiche créée au moment du pivot. Source FRED vérifiée le jour même (endpoint, dates futures, clé gratuite). Rien de codé.
- 2026-09-05 — **livré**, en suivant `02_Plan_Projet/prompt-claude-code-vague-1.md`. Trois décisions
  proposées avant implémentation et validées : liste blanche à 5 (ISM hors FRED,
  définitif), clé API côté backend .NET (jamais `.env.local`), cache en table
  Postgres (`news_releases`, hors pipeline `PersistenceWriter`). Détail des
  autres écarts trouvés en cours de route (endpoint singulier, absence d'heure
  dans la réponse FRED, distinction `null`/`[]`) : voir les sections ci-dessus.
  `newsBlackoutMinutes` passé de 15 à 30 dans `defaultRiskPolicy` (lu depuis la
  policy, jamais codé en dur dans la gate). Rafraîchissement toutes les 6h,
  garde les 3 prochaines dates par release.

  Tests : `lib/risk/news-calendar.test.ts` (9), `lib/risk/gates.test.ts`
  (5, nouveau fichier — dont le test dédié au fail-closed exigé par la fiche),
  `evaluate.test.ts` (+3), `FredReleaseScheduleTests.cs` (3, dont la
  conversion UTC vérifiée contre un vrai communiqué FOMC daté). Comme pour
  `RiskTodayRepository`, `NewsCalendarRepository`/`NewsCalendarService`
  (accès DB + HTTP FRED réel) n'ont pas de test d'intégration — même
  convention que le reste du dépôt (logique pure testée, glue DB/HTTP non
  testée en unitaire).

  Vérification manuelle : `curl localhost:3000` en mode mock confirme un
  rendu serveur sans erreur et le badge affichant honnêtement « News: no
  data » au premier paint (avant l'hydratation mock, comportement attendu).
  Pas d'extension Chrome connectée cette session (même limite qu'en T02a/b) :
  la mise à jour du badge après hydratation, le scénario `news_blackout` du
  mock, et un cycle FRED réel contre une vraie clé API n'ont pas été observés
  dans un navigateur ni contre l'API FRED réelle.
