# Security Principles

## Secrets

- Never commit API keys, broker credentials, prop firm credentials, or account passwords.
- Use environment variables or a secret manager.
- Separate demo, test, and live credentials.

## Trading Safety

- Require explicit environment mode: mock, backtest, paper, demo, live.
- Live execution must require deliberate configuration.
- Emergency stop must be available before live execution.
- WebSocket sessions must authenticate, authorize subscriptions, and reject commands from unauthorized clients.
- Execution commands must be signed or otherwise protected against replay and duplication once real trading is introduced.

## Access Control

- Users should only access accounts and strategies they are allowed to control.
- Execution permissions should be stricter than read-only dashboard permissions.
