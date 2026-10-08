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

The tests cover affordability, FX conversion, profile updates, forecasting,
proposal authorization, policy blocks, simulated income, prompt-injection resistance,
direct-execution denial, and replay protection.

## Exchange-rate disclaimer

Reference FX data is indicative and may be fetched from Frankfurter. Rates are cached
briefly and may fall back to the last known/demo rate when the network is unavailable.
User-entered rates are scenario inputs and are not guaranteed bank or remittance quotes.
