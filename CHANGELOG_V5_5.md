# BorderWise AI v5.5 changelog

## v5.5.0 — transaction-state hardening

- Added explicit anti-replay handling for natural-language execution requests.
- An already executed/verified proposal cannot be executed again.
- Direct “execute now” chat commands cannot bypass the explicit authorization flow.
- Security-override language now produces a clear policy denial instead of falling through to an unrelated FX response.
- Added regression tests for duplicate execution and policy-override messaging.

The deterministic transaction state machine remains authoritative: PENDING_AUTHORIZATION → AUTHORIZED → EXECUTED, with verification and audit events after execution.
