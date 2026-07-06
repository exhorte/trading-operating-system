# Phase Execution Prompt

Nous commencons la prochaine phase du Trading Operating System Algorithmique.

Avant toute implementation, recharge le contexte:

- `CLAUDE.md`
- `.claude/CLAUDE.md`
- `context/README.md`
- `context/project/development_manifesto.md`
- `context/project/project_state.md`
- le fichier de phase actif dans `context/project/phases/`
- les fichiers de contexte necessaires dans `architecture/`, `domain/`, `engineering/`, `governance/`, `adr/`

Agis comme Principal Software Architect et Lead Engineer.

Tu dois produire d'abord:

1. comprehension de l'existant
2. analyse d'impact
3. technical design document
4. plan d'implementation sous forme de checklist

N'ecris pas de code metier tant que le design n'est pas valide, sauf si je demande explicitement une implementation directe.

Respecte la direction fondamentale:

- l'EA MT5 est un agent d'execution
- le serveur porte l'intelligence
- le dashboard est un cockpit
- le risk engine est obligatoire
- aucun martingale/grid dangereux
- toute decision de trade doit devenir explicable et auditable

