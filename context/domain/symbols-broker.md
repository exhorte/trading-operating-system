# Symboles broker

Base du registre de symboles d'EA-04 (canonique <-> broker). Rempli en
Phase 0 de la Vague EA (`02_Plan_Projet/prompt-claude-code-vague-ea.md`).

## Statut : EN ATTENTE

Le terminal MT5 local n'est pas connecte a un compte au moment ou ce fichier
a ete cree (2026-09-12) : `mt5.initialize()` echoue avec
`(-6, 'Terminal: Authorization failed')` — le terminal est installe et
lance, mais aucune session n'est ouverte. Aucun identifiant de compte n'est
demande ni stocke ici (charte, section Securite) : c'est a l'utilisateur de
se connecter manuellement dans le terminal.

Une fois connecte, executer :

```
cd tools/mt5-observer
python list_symbols.py --canonical EURUSD GBPUSD XAUUSD
```

et remplacer le tableau ci-dessous par la sortie reelle — nom exact,
digits, point, tick value, tick size, volume min/max/step, stops level —
pour chacun des trois symboles canoniques. Ne pas deviner un suffixe : la
sortie du script fait foi.

## Registre (a completer)

| Canonique | Nom broker | Digits | Point | Tick value | Tick size | Volume min | Volume max | Volume step |
|---|---|---|---|---|---|---|---|---|
| EURUSD | *(en attente)* | | | | | | | |
| GBPUSD | *(en attente)* | | | | | | | |
| XAUUSD | *(en attente)* | | | | | | | |

XAUUSD est hors perimetre pour S01 v1 (fiche S01, section Perimetre) mais
son registre est capture ici en meme temps : EA-04 en aura besoin des que
la strategie passe en ATR-relatif.
