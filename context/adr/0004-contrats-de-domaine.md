# ADR 0004 — Contrats de domaine et wire MT5

Date : 2026-09-04. Statut : accepté. Consolide les anciens ADR 0004 et 0005, sans changement technique.

## Décision

- Les schémas canoniques du domaine sont du **TypeScript portable** dans `lib/domain/`, sans dépendance externe.
- `lib/contracts/` est la couche wire ; elle peut dépendre du domaine, jamais l'inverse.
- Les read models (`lib/contracts/snapshots.ts`) sont des projections d'affichage, pas des modèles de domaine.
- `TradingOs.Contracts` en C# **reflète** les schémas TypeScript. Le TypeScript fait foi ; le C# suit.
- Le bord MT5 parle un JSON « lean » versionné sur WSS. Le Gateway le traduit vers l'enveloppe interne. SignalR est réservé au cockpit.
- Les détecteurs respectent un invariant de non-anticipation : l'état d'une bougie n'utilise que les bougies jusqu'à cette bougie.

## Conséquences

- Un changement de schéma se fait en TypeScript d'abord, puis dans le miroir C#, avec les tests des deux côtés.
- L'invariant de non-anticipation reste utile même sans backtester : il garantit que le brief pré-séance et les captures reflètent ce qui était réellement connu à l'instant considéré.
