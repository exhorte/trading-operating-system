# T13 — Connecter un compte depuis l'application

Statut : **livré le 2026-11-01, essai avec mot de passe à faire par l'utilisateur.** ADR 0013 (I3), ADR 0020, ADR 0021 (un seul compte connecté ; formulaire sur Account). Cette fiche
a été écrite **après** le code, contrairement à ce que l'ADR 0013 demandait : l'écart est signalé ici plutôt que gommé.

## Ce que l'outil fait

Prendre les identifiants d'un compte (login, serveur, mot de passe facultatif), lire chez le courtier tout ce qu'il dit du compte,
et enregistrer puis rattacher le compte — avec un capital initial **confirmé** par l'utilisateur. Le mot de passe traverse le
cœur et n'est gardé nulle part.

## Ancrage

| Quoi | Où |
|---|---|
| Formulaire | `components/accounts/connect-account-form.tsx`, monté sur `app/(cockpit)/account/page.tsx` (ancre `#connecter`) et affiché à la place de tout écran qui lit un compte quand aucun n'est connecté (`components/shell/connect-gate.tsx`, ADR 0021) |
| Règles du formulaire (blocages, requête d'enregistrement) et du garde | `lib/accounts/connect.ts`, `lib/accounts/connected.ts` + leurs tests |
| Lecture chez le courtier | `AccountService.discover`, `domain/accounts/discovery.py`, `POST /api/accounts/discover` |
| Profil FTMO sur démo | `AccountCreate.rules_profile`, `domain/accounts/profiles.py` (`provider_ceilings`) |
| Tests | `tests/unit/domain/test_account_discovery.py`, `tests/unit/services/test_accounts_service.py`, `tests/unit/api/test_accounts_routes.py` (sentinelle), `tests/integration/test_terminal_contract.py` (live, lecture seule) |

## Critère de réussite

- Sans mot de passe, sur un terminal déjà connecté : le formulaire affiche les vrais chiffres du compte. **Vérifié le 2026-11-01**
  sur la démo Exness (solde, équité, levier 1:100, hedging, EURUSDm / XAUUSDm avec leurs spécifications réelles).
- Avec mot de passe : le compte se connecte, se lit, et le mot de passe est absent de tout ce que le cœur dit ou écrit.
  **Non vérifié contre un vrai courtier** (ADR 0013 : l'utilisateur le fait lui-même) ; vérifié contre le terminal simulé, avec sentinelle.
- « Enregistrer et rattacher » : **fait le 2026-11-01 sur la démo Exness** (capital 10 000 $ confirmé comme l'utilisateur l'avait annoncé, profil FTMO 2-Step), sans mot de passe. Les données s'affichent : équité, solde, portes de risque, profil, liaison MT5.

## Ce qui reste

- Proposer le stockage du mot de passe dans le coffre Windows (opt-in) depuis le formulaire.
- Le premier dépôt n'est pas lisible dans l'historique de la démo Exness du 2026-11-01 : vérifier sur un compte réel et sur FTMO.
- `scripts/start.ps1` : paramètres de ports (`-CorePort`, `-CockpitPort`, `-DatabasePort`) quand des ports par défaut sont pris.
