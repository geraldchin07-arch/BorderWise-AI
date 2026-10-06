# XKF5 AI — Security Self-Assessment

## Permission tiers

| Tier | Capability | Authorization |
|---|---|---|
| Level 0 | Read balances, transactions, forecasts | None |
| Level 1 | Prepare a transaction proposal | None |
| Level 2 | Execute a transaction | Explicit user approval |

## Guardrails

1. Financial calculations are deterministic.
2. The model is not allowed to directly mutate balances.
3. Every transaction passes the risk policy before execution.
4. An emergency reserve is preserved.
5. High-value transactions can be flagged for review.
6. A proposal cannot execute before explicit authorization.
7. Rejected proposals do not change balances.
8. Every proposal, authorization, block and execution creates an audit event.
9. Sandbox mode is clearly labeled and never connects to a real bank.
10. Reset is available for reproducible judge demonstrations.

## Red-team cases

- RM26,000 transfer: blocked because it breaches the emergency reserve.
- Transfer without authorization: blocked.
- Negative/zero amount: rejected by validation.
- Repeated execution of the same proposal: rejected after first execution.
- Request to transfer everything: flagged for review.
- User rejection: no balance mutation.

## Known limitations

This is a competition sandbox, not a production banking system. A production deployment would require bank-grade authentication, secure secrets management, KYC/AML controls, transaction signing, rate-limit controls, immutable external audit storage, real-time FX sources, model monitoring, human escalation and formal security review.


## v5 LLM boundary
The LLM is a planner/reasoner only. Tool outputs for balances, FX, forecasts and risk are authoritative. No LLM tool can execute a transfer. Proposal creation is the maximum side effect exposed to the model, and actual execution requires a separate explicit Level-2 authorization request.
