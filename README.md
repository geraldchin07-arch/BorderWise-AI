
# XKF5 AI

## v7.4.0 — Expanded currency intelligence and safer planning

XKF5 AI v7.4 strengthens the currency-first workflow: the web selector and offline planner now recognize 150+ ISO currency codes, common currency names are normalized more consistently, shorthand amounts and thousands separators are validated, and ambiguous word-shaped codes or the yen symbol are not guessed. Transfer preparation requires an explicit matching MYR amount; execution is blocked before mutation if either wallet currency is missing. Unsupported automatic FX quotes require a custom rate or a retry, and failed profile updates roll back atomically.


XKF5 now starts with currency setup rather than assuming MYR + SGD. The user chooses a primary planning/reporting currency and can enter any number of currency balances with automatic reference FX or a user-entered quoted rate. Income, reserve, tuition, accommodation and monthly spending can be entered in the relevant selected currency; trusted arithmetic is normalized internally and displayed back in the planning currency. Any-currency conversion remains user-directed (for example CNY → MYR, USD → SGD, or MYR → SGD). The sandbox transaction module still requires explicit Level-2 authorization and does not grant the planner unrestricted execution authority.

## v5.5 update
- Natural-language authorization now matches an existing pending proposal by exact MYR amount.
- Explicit authorization triggers sandbox execution, verification, and audit; it never bypasses policy.
- Ambiguous authorization without a matching proposal is blocked.
## Project overview — Agentic Cross-Border Student Finance

A competition-ready prototype for Topic C: Cross-border & Student Finance Assistant.

## What changed from the first prototype

This version is a genuine multi-intent financial agent prototype rather than a single tuition workflow.

It supports:

- Balance analysis
- Transaction history
- Spending analysis
- 30-day cash-flow forecasting
- Tuition/obligation affordability
- Any-currency FX analysis and multi-currency wallet valuation
- Natural-language transfer preparation
- Risk and reserve enforcement
- Level-2 authorization
- Sandbox execution
- Post-execution verification
- Audit trail
- One-click judge-demo reset
- Python 3.14 compatibility
- Optional LLM integration point can be added without moving financial calculations into the model

## Security principle

The language model must never directly move money.

The safe architecture is:

User → agent planning → deterministic financial tools → policy engine → proposal → explicit authorization → sandbox execution → verification → audit.

Financial arithmetic and policy checks live in `app/engine.py`, not in the language model.

## Run on Windows / Python 3.14

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open:

http://127.0.0.1:8000

## Demo

1. Click `Reset judge demo`.
2. Ask: `Can I afford my tuition?`
3. Review the agent trace.
4. Review the recommended conversion.
5. Authorize the Level-2 proposal.
6. Observe sandbox execution.
7. Observe verification and audit.
8. Then test:
   - `How much money do I have?`
   - `What are my biggest expenses?`
   - `Will I run out of SGD?`
   - `What is the MYR SGD exchange rate?`
   - `Prepare a RM5,000 transfer to Singapore.`
   - `What are my recent transactions?`

## Tests

```bat
pytest -q
```

## Competition positioning

Normal chatbot:
Analyze → Advice

XKF5:
Understand → Observe → Reason → Recommend → Protect → Authorize → Execute → Verify → Audit

The demo uses simulated accounts only. No real money is moved.

## Submission evidence to prepare

- Architecture diagram
- Security self-assessment
- Test cases including blocked high-risk transfers
- Sandbox execution logs
- 5–10 minute presentation
- Short demo video
- Source code + README

## v5 dynamic FX

XKF5 now refreshes the MYR/SGD reference rate from the Frankfurter API. The engine caches a successful quote for 15 minutes, shows the provider/source and rate date, and falls back to the last known/demo rate if the network is unavailable. Transfer proposals and tuition-affordability calculations use the refreshed rate rather than a hard-coded FX value.

The displayed rate is a reference/mid-market rate, not a guaranteed bank/remittance execution quote. Frankfurter documents the public v2 rate endpoint and notes that latest rates are published on a daily/working-day basis rather than being a tick-by-tick market feed.


## v5 agentic architecture
With `OPENAI_API_KEY` configured, XKF5 uses the OpenAI Responses API with custom function tools. The LLM chooses read/analysis tools, receives deterministic results, and synthesizes the response. The LLM is never given a direct execution tool; sandbox execution remains behind explicit Level-2 authorization. Without an API key, the deterministic engine remains available as a safe offline fallback.


## Offline agent mode (v5.1)
If no OPENAI_API_KEY is configured, XKF5 uses an offline local agent planner for multi-step student-finance requests. It can chain trusted tools for balances, obligations, 30-day forecasts, dynamic FX, conversion calculations and risk checks. The planner never receives direct execution authority.

Try: `I just received RM10,000 from my family. I have tuition coming up. Should I convert some of it to SGD?`


## v6.5 updates

Users can classify each monthly spending category as Core or Adjustable. The financial-health indicator is deterministic, transparent, and explicitly not a credit score.


## v7 multi-currency management
XKF5 supports a user-configured multi-currency wallet. MYR can use a live reference rate or a user-entered scenario rate. Additional currencies (for example USD, CNY, THB, or another 3-letter ISO-style code) can be entered with a rate normalized as 1 unit = S$X. Cross-currency conversions use SGD as the normalization currency, and wallet valuation displays the source/date of each rate. User-entered rates are scenario inputs, not guaranteed bank settlement quotes.


## v7.1.2.1

The dashboard state request is timeout-protected and FX refresh is deferred until after the UI renders, so a slow external FX service cannot leave the dashboard stuck on Loading.

## Automatic multi-currency FX
Additional currencies can use automatic reference FX. XKF5 fetches rates with SGD as the base, normalizes them as 1 unit = S$X, shows source/date metadata, and refreshes them as needed. Users can override a currency with a custom quoted rate for a scenario. Reference data is indicative and not a guaranteed settlement quote.


## v7.2 multi-currency conversion

The dashboard includes a currency conversion studio that lets the user choose any 3-letter currency pair (for example CNY → MYR, USD → SGD, or MYR → SGD). Auto mode fetches the current reference pair directly from Frankfurter; custom mode accepts a user-provided quoted rate. This quote/calculation does not create or execute a transaction. The wallet still uses SGD only as a common valuation base for portfolio comparison.


---

# Team Branch Roles

XKF5 AI is developed by a 5-person team. Each branch has a clear ownership area so work can happen in parallel with minimal conflicts.

| Branch | Owner | Responsibility |
|---|---|---|
| `main` | Team | Stable, review-approved integration branch. Do not develop directly here. |
| `agent` | AI Agent Lead | AI reasoning, natural-language understanding, recommendations, agent orchestration, and integration. |
| `backend` | Backend Lead | Financial engine, multi-currency calculations, FX, forecasting, tuition/funding logic, and backend tests. |
| `frontend` | Frontend Lead | Student onboarding, dashboard, multi-currency UI, visualizations, loading/error states, and user experience. |
| `security` | Security Lead | Authorization, policy enforcement, anti-replay, prompt-injection resistance, transaction safety, and red-team testing. |
| `docs-qa` | QA & Submission Lead | Regression testing, CI, README/documentation, architecture evidence, demo materials, and submission readiness. |

## Git Workflow

- Work only on your assigned branch.
- Pull the latest `main` before starting major work.
- Do not push directly to `main`.
- Push your branch when your work is ready.
- Open a Pull Request into `main` for review.
- Keep changes focused on your branch's responsibility.

## Shared Architecture

The product follows this high-level flow:

`User → AI reasoning → deterministic financial engine → policy/security checks → proposal → explicit authorization → sandbox execution → verification → audit`

The AI layer must not bypass deterministic financial calculations or security controls.

## Collaboration Rule

Before changing a file primarily owned by another branch, coordinate with that branch owner first to reduce merge conflicts.
