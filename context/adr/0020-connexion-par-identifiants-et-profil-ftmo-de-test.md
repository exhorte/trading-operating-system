# ADR 0020 — Connexion par identifiants du courtier, lecture du compte chez lui, profil FTMO répété sur une démo

Date : 2026-11-01. Statut : **accepté** — décision de l'utilisateur en session le 2026-11-01 : « Construis le formulaire de
connexion demandant les identifiants réels soit FTMO ou Exness », « Extraire toutes les informations liées au compte (le
capital, l'effet de levier, …) directement chez le courtier une fois que nous avons les identifiants », « étant donné que
les règles sont les mêmes pour les deux courtiers on peut utiliser Exness pour tester le profil FTMO pour l'instant ».
**Réalise l'incrément I3 de l'ADR 0013** (accord nommé du 2026-09-25) : la règle de fond de l'ADR 0013 tient — le mot de
passe ne fait que traverser. Amende l'ADR 0019 (les plafonds contractuels suivent le challenge des règles, pas le nom du courtier).

## Décision

1. **Un formulaire, un flux** (« Connecter un compte », écran Settings) : fournisseur, login, serveur, mot de passe
   *facultatif*, chemin du terminal *facultatif* → le cœur **lit le compte chez le courtier** (`POST /api/accounts/discover`)
   → l'utilisateur vérifie → « Enregistrer et rattacher ». Sans mot de passe, le cœur s'attache au terminal tel qu'il est
   (déjà connecté par l'utilisateur) ; avec, il s'en sert **une fois** pour se connecter, lire, puis l'oublie.
2. **Le mot de passe** (ADR 0013) : du champ au cœur, jamais par Next ; champ sans `name`, non contrôlé par React, lu par ref,
   vidé dans un `finally` ; requête `no-store`, sans cookie ni referrer ; côté cœur `SecretStr` borné (256), enregistré auprès du
   masqueur de journaux le temps de l'appel, absent de toute réponse, de toute erreur, de tout événement et de toute table.
   Une validation qui échoue ne renvoie jamais ce qu'elle a reçu. Tests à sentinelle (`test_accounts_routes.py`).
   **Claude ne l'a ni vu, ni saisi, ni testé** : le chemin « avec mot de passe » n'est éprouvé que contre le terminal simulé ;
   l'essai réel est celui de l'utilisateur.
3. **Ce que le courtier dit** (lecture seule, liste blanche du worker) : société, serveur, login, devise, levier, solde, équité,
   marge utilisée / libre / niveau, démo ou réel, mode de marge (hedging…), FIFO, trading autorisé et automatique, positions et
   ordres déjà ouverts, et pour EURUSD et XAUUSD : le nom exact chez ce courtier (donc le **suffixe**), lot minimum et pas,
   taille du contrat, valeur du tick, spread. Jamais le nom du titulaire. Le fournisseur est **reconnu depuis les noms du courtier**
   (serveur, société) : un formulaire « FTMO » rempli avec un serveur Exness est refusé, pas obéi.
4. **Le capital initial est la seule donnée qu'un courtier ne donne pas** : il donne le solde du jour. Le cœur propose le premier
   dépôt trouvé dans l'historique du courtier (fiable) et, à défaut, le solde actuel (signalé non fiable) — **l'utilisateur
   confirme explicitement**, car la grille de risque (ADR 0019) se mesure contre lui. Sur la démo Exness du 2026-11-01, aucun
   dépôt n'est lisible dans l'historique : c'est le solde (10 000 $) qui est proposé, à confirmer.
5. **Profil FTMO répété sur une démo** : `AccountCreate.rules_profile = FTMO` sur un compte dont le courtier est Exness donne un
   challenge 2-Step (taille = capital confirmé, objectifs, commission supposée de 5 $/lot — prudente sur un Standard à 0) avec les
   plafonds du contrat (−5 % jour, −10 % total, ADR 0019). Le courtier reste Exness : ses symboles, son suffixe, son terminal.
   **Démo seulement** : `rules_profile_demo_only` refuse un compte réel (un profil prop sur de l'argent réel mentirait sur le
   contrat). Les règles internes sont déjà les mêmes (ADR 0019) ; seul le contrat du challenge s'ajoute.
6. **Le migrateur met l'ancienne table de suivi de côté sans la détruire** : la vraie base garde `schema_migrations(migration_id,
   checksum_sha256…)` de l'ère .NET ; elle est renommée `schema_migrations_dotnet` (ligne conservée), puis le suivi Python est
   créé. Remplace la modification non commitée qui supprimait des lignes et n'était appelée nulle part.

## Conséquences

- Nouveau : `domain/accounts/discovery.py`, `AccountService.discover`, `POST /api/accounts/discover`, `components/accounts/connect-account-form.tsx`,
  `lib/accounts/connect.ts` (règles du formulaire, testées sans navigateur), `AccountCreate.rules_profile`.
- Exécuté pour la première fois sur la vraie base le 2026-11-01, **après une sauvegarde `pg_dump -Fc` relue** : schéma 0001 à 0004
  appliqué, 9 trades clos, 2 834 verdicts S01 et 5 verrous intacts.
- **Ports** : 3000, 8000 et 5433 sont tenus par d'autres projets (conteneurs `jobart-*`, `dossier-db-1`). Les arrêter a été refusé
  par la couche de permissions de la session ; l'application tourne donc sur **3001 (cockpit), 8001 (cœur), 5434 (base)** —
  `docker-compose.yml` lit `TRADINGOS_DB_PORT` (défaut 5433, inchangé). `scripts/start.ps1` attend toujours les ports par défaut.
- Non fait ici : stockage du mot de passe dans le coffre (opt-in, `CREDENTIAL_STORE=windows`) depuis le formulaire ; le cœur sait
  le faire (`PUT …/credentials`), le formulaire ne le propose pas encore.
