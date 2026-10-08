# BorderWise AI

BorderWise AI is a cross-border student-finance assistant for managing balances,
tuition, spending, cash flow, foreign-exchange scenarios, and transfer decisions.
It combines a conversational agent with a deterministic financial engine so the AI
can explain and recommend actions without receiving direct authority to move money.

> **Prototype notice:** This project uses simulated accounts and sandbox transactions.
> It is not a bank, does not move real money, and does not provide guaranteed
> financial advice or settlement exchange rates.

## Highlights

- Multi-currency wallet with configurable balances and SGD-normalized valuation.
- MYR/SGD and general currency-pair conversion using live reference FX or
  user-entered scenario rates.
- Tuition affordability and 30-day cash-flow forecasting.
- Spending analysis with Core and Adjustable classifications.
- Transaction-history and balance questions through natural language.
- Explicit transfer proposals with deterministic reserve and risk checks.
- Level-2 authorization, sandbox execution, post-execution verification, and audit events.
- Offline deterministic agent planner when no API key is configured.
- Optional OpenAI tool-calling agent for natural-language planning.
- Prompt-injection, direct-execution, ambiguous-authorization, and replay protections.
- One-page browser dashboard with profile editing, FX tools, proposals, and audit history.

## Safety model

BorderWise separates reasoning from execution:

```text
User
  -> Agent planning
  -> Deterministic financial calculations
  -> Policy and reserve checks
  -> Transfer proposal
  -> Explicit Level-2 authorization
  -> Sandbox execution
  -> Verification
  -> Audit trail
```

The language model can read data, perform analysis through trusted tools, and prepare
a proposal. It is never given an execution tool. Financial calculations, policy
decisions, state changes, and transaction verification are implemented in
`app/engine.py`.

## Requirements

- Python 3.14 or later
- Windows, macOS, or Linux
- Optional: an OpenAI API key for the LLM agent
- Internet access for live reference FX rates; the application falls back to its
  cached/demo rate when the provider is unavailable

## Installation and local development

### Windows

```bat
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8010
```

Alternatively, run `RUN_BORDERWISE.bat`, which creates the virtual environment,
installs dependencies, and starts the server on port `8010`.

### macOS/Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8010
```

Open the dashboard at <http://127.0.0.1:8010>.

## Configuration

Copy `.env.example` to `.env` if you want to enable the optional LLM integration:

```dotenv
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5
```

Without `OPENAI_API_KEY`, BorderWise uses the local deterministic planner and remains
fully usable for the demo. Never commit real credentials to the repository.

## Demo flow

1. Start the application and click **Reset judge demo**.
2. Ask: `Can I afford my tuition?`
3. Review the balances, forecast, FX quote, reserve, and proposed conversion.
4. Authorize the exact proposed amount through the dashboard.
5. Observe sandbox execution, verification, and the audit event.
6. Try:
   - `How much money do I have?`
   - `What are my biggest expenses?`
   - `Will I run out of SGD?`
   - `What is the MYR SGD exchange rate?`
   - `Prepare a RM5,000 transfer to Singapore.`
   - `Prepare a RM26,000 transfer.`

The large transfer should be blocked when it breaches the emergency-reserve policy.
Natural-language execution requests cannot bypass authorization, and an executed
proposal cannot be replayed.

## API overview

The FastAPI service exposes:

- `GET /api/health` — service and integration status.
- `GET /api/state` — current simulated wallet and dashboard state.
- `POST /api/chat` — natural-language agent request.
- `GET /api/audit` — audit events.
- `POST /api/profile` — update the financial profile.
- `POST /api/proposals` — prepare a transfer proposal.
- `POST /api/authorize` — authorize or reject a proposal.
- `POST /api/execute` — execute an authorized sandbox proposal.
- `GET /api/fx/quote` and `POST /api/fx/convert` — calculate currency conversions.
- `POST /api/fx/refresh` and `POST /api/fx/refresh-all` — refresh reference rates.
- `POST /api/reset` — restore the demo state.

Interactive API documentation is available at
<http://127.0.0.1:8010/docs> while the server is running.

## Project structure

```text
app/
  main.py          FastAPI routes and request models
  engine.py        Deterministic finance, FX, forecasting, policy, and audit logic
  agent.py         Optional OpenAI tool-calling orchestrator
  local_agent.py   Offline deterministic natural-language planner
static/
  index.html       Browser dashboard
tests/
  test_engine.py   Financial, agent, authorization, and security regression tests
```

## Testing

Run the test suite from the repository root:

```bat
pytest -q
```

## Competition positioning

Normal chatbot:
Analyze → Advice

BorderWise:
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

BorderWise now refreshes the MYR/SGD reference rate from the Frankfurter API. The engine caches a successful quote for 15 minutes, shows the provider/source and rate date, and falls back to the last known/demo rate if the network is unavailable. Transfer proposals and tuition-affordability calculations use the refreshed rate rather than a hard-coded FX value.

The displayed rate is a reference/mid-market rate, not a guaranteed bank/remittance execution quote. Frankfurter documents the public v2 rate endpoint and notes that latest rates are published on a daily/working-day basis rather than being a tick-by-tick market feed.


## v5 agentic architecture
With `OPENAI_API_KEY` configured, BorderWise uses the OpenAI Responses API with custom function tools. The LLM chooses read/analysis tools, receives deterministic results, and synthesizes the response. The LLM is never given a direct execution tool; sandbox execution remains behind explicit Level-2 authorization. Without an API key, the deterministic engine remains available as a safe offline fallback.


## Offline agent mode (v5.1)
If no OPENAI_API_KEY is configured, BorderWise uses an offline local agent planner for multi-step student-finance requests. It can chain trusted tools for balances, obligations, 30-day forecasts, dynamic FX, conversion calculations and risk checks. The planner never receives direct execution authority.

Try: `I just received RM10,000 from my family. I have tuition coming up. Should I convert some of it to SGD?`


## v6.5 updates

Users can classify each monthly spending category as Core or Adjustable. The financial-health indicator is deterministic, transparent, and explicitly not a credit score.


## v7 multi-currency management
BorderWise supports a user-configured multi-currency wallet. MYR can use a live reference rate or a user-entered scenario rate. Additional currencies (for example USD, CNY, THB, or another 3-letter ISO-style code) can be entered with a rate normalized as 1 unit = S$X. Cross-currency conversions use SGD as the normalization currency, and wallet valuation displays the source/date of each rate. User-entered rates are scenario inputs, not guaranteed bank settlement quotes.


## v7.1.2.1

The dashboard state request is timeout-protected and FX refresh is deferred until after the UI renders, so a slow external FX service cannot leave the dashboard stuck on Loading.

## Automatic multi-currency FX
Additional currencies can use automatic reference FX. BorderWise fetches rates with SGD as the base, normalizes them as 1 unit = S$X, shows source/date metadata, and refreshes them as needed. Users can override a currency with a custom quoted rate for a scenario. Reference data is indicative and not a guaranteed settlement quote.


## v7.2 multi-currency conversion

The dashboard includes a currency conversion studio that lets the user choose any 3-letter currency pair (for example CNY → MYR, USD → SGD, or MYR → SGD). Auto mode fetches the current reference pair directly from Frankfurter; custom mode accepts a user-provided quoted rate. This quote/calculation does not create or execute a transaction. The wallet still uses SGD only as a common valuation base for portfolio comparison.

## Exchange-rate disclaimer

Reference FX data is indicative and may be fetched from Frankfurter. Rates are cached
briefly and may fall back to the last known/demo rate when the network is unavailable.
User-entered rates are scenario inputs and are not guaranteed bank or remittance quotes.

## Team branch roles

BorderWise AI is developed by a 5-person team. Each branch has a clear ownership area
so work can happen in parallel with minimal conflicts.

| Branch | Owner | Responsibility |
|---|---|---|
| `main` | Team | Stable, review-approved integration branch. Do not develop directly here. |
| `agent` | AI Agent Lead | AI reasoning, natural-language understanding, recommendations, agent orchestration, and integration. |
| `backend` | Backend Lead | Financial engine, multi-currency calculations, FX, forecasting, tuition/funding logic, and backend tests. |
| `frontend` | Frontend Lead | Student onboarding, dashboard, multi-currency UI, visualizations, loading/error states, and user experience. |
| `security` | Security Lead | Authorization, policy enforcement, anti-replay, prompt-injection resistance, transaction safety, and red-team testing. |
| `docs-qa` | QA & Submission Lead | Regression testing, CI, README/documentation, architecture evidence, demo materials, and submission readiness. |

## Git workflow

- Work only on your assigned branch.
- Pull the latest `main` before starting major work.
- Do not push directly to `main`.
- Push your branch when it is ready.
- Open a pull request into `main` for review.
- Keep changes focused on your branch's responsibility.

## Shared architecture

The product follows this high-level flow:

`User → AI reasoning → deterministic financial engine → policy/security checks → proposal → explicit authorization → sandbox execution → verification → audit`

The AI layer must not bypass deterministic financial calculations or security controls.

## Collaboration rule

Before changing a file primarily owned by another branch, coordinate with that branch
owner first to reduce merge conflicts.
