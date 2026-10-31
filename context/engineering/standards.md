# Standards d'ingénierie

Réécrit le 2026-10-09 (ADR 0016).

## Général

- Le domaine ne connaît ni l'interface ni l'infrastructure : `domain/` n'importe rien d'`infrastructure/`, de `services/`, d'`api/`, d'`app/` ni de `runtime/`, et ne fait aucune E/S (test d'architecture).
- Un contrat typé plutôt qu'un objet libre ; des petits modules à responsabilité claire.
- Pas d'abstraction prématurée : une fonction suffit quand elle suffit. Une abstraction (adaptateur, pont, usine, bus) a une justification écrite — qui l'utilise, ce qui la remplace, quand elle peut disparaître (`docs/architecture/python-native-architecture.md` § 14).
- Aucun `if provider == …` hors des profils de comptes.
- Un refus est un **résultat** (code stable + raison), pas une exception qui traverse trois couches ; un échec de persistance avant d'agir est un refus (échec fermé).

## Python

- Python ≥ 3.12, `mypy --strict`, `ruff check` et `ruff format` propres, `from __future__ import annotations`.
- Modèles pydantic pour tout ce qui traverse une frontière ; `SecretStr` pour tout secret, jamais dans un champ de lecture, un événement, un journal ni un message d'erreur (test d'architecture : aucun champ de sortie ne ressemble à un secret).
- SQL explicite dans `infrastructure/database/repositories/` ; migrations numérotées et additives (`NNNN_nom.sql`) — une migration appliquée ne se modifie plus, un script destructeur vit dans `migrations/manual/` et se lance à la main.
- Aucune fonction d'ordre de MetaTrader5 dans le cœur ; l'API MT5 n'est importée que par `infrastructure/mt5/worker.py`.
- Les refus et les états sont des énumérations ; une transition d'état passe par une table.

## TypeScript / cockpit

- Types métier explicites ; pas de `any` sauf à une frontière documentée.
- Le cockpit n'évalue aucune règle de trading : il affiche et envoie des gestes. Les contrats viennent de `lib/api/generated.ts` — jamais recopiés à la main.
- Un écran a un état vide, un état de chargement et un état d'erreur ; un chiffre inconnu s'affiche « — », jamais « 0 ». Un échec de lecture n'est pas un journal vide.
- Ne jamais présenter un faux contrôle d'exécution comme réel ; les gestes dangereux (arrêt d'urgence, armement) restent atteignables de tout écran et visibles dans les bannières.
- Contraste AA (4,5 : 1) en clair et en sombre, sans débordement horizontal à 375 px ; vérifié dans un vrai navigateur, pas supposé.

## Documentation

Mettre à jour `context/` quand l'architecture change, que le modèle de domaine change, qu'une décision est prise ou qu'un contrat d'intégration change. Les ADR et le journal de session sont des **archives** : on les amende par une note datée, on ne les réécrit pas (ADR 0008).
