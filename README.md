# BorderWise AI
### Agentic Cross-Border Student Finance Assistant
BorderWise AI is a competition-ready prototype for cross-border student finance.
Instead of acting like a chatbot that simply reads information and gives advice, BorderWise separates:
**Understand → Observe → Reason → Recommend → Protect → Authorize → Execute → Verify → Audit**
The system combines natural-language interaction with deterministic financial calculations, explicit risk controls, multi-currency valuation, and sandbox-only transaction execution.
> **Important:** BorderWise is a simulated finance environment. It does not connect to a real bank and does not move real money.
---
## Why BorderWise?
Cross-border students often manage:
- Multiple currencies
- Tuition and accommodation obligations
- Scholarships and loans
- Monthly spending
- Emergency reserves
- Exchange-rate uncertainty
- International transfer decisions
A normal chatbot can explain these problems, but explanation alone is not enough.
BorderWise is designed as an **agentic financial assistant** that connects natural-language requests to trusted financial tools and policy checks while keeping money movement outside the language model.
### Chatbot vs BorderWise
| Typical chatbot | BorderWise AI |
|---|---|
| Analyze → Advice | Understand → Observe → Reason → Recommend |
| Mostly conversational | Tool-assisted financial workflow |
| Model produces calculations | Deterministic financial engine performs calculations |
| Advice may be ambiguous | Policy and risk checks are explicit |
| Model may appear action-oriented | Model never directly moves money |
| No transaction boundary | Proposal → authorization → sandbox execution |
| Limited traceability | Verification + audit trail |
---
# Core Features
## 1. Currency-first financial profile
BorderWise does not assume that MYR and SGD are the only relevant currencies.
Users can configure:
- A primary planning/reporting currency
- One or more wallet balances
- Monthly income
- Emergency reserve
- Tuition
- Scholarships
- Loans
- Accommodation
- Other obligations
- Monthly spending categories
Financial inputs can be entered in their relevant currencies and normalized internally for calculation.
---
## 2. Multi-currency wallet
The wallet supports multiple user-configured currencies.
Examples include:
- MYR
- SGD
- USD
- CNY
- THB
- Other 3-letter ISO-style currency codes
Each additional currency can use either:
- Automatic reference FX
- User-entered custom FX
Wallet valuation uses **SGD as the internal normalization base** for portfolio comparison.

### Example

| Currency | Balance | FX Rate → SGD | Indicative Value |
|---|---:|---:|---:|
| CNY | 10,000 | 0.18 | SGD 1,800 |
| USD | 500 | 1.28 | SGD 640 |
| MYR | 5,000 | 0.305 | SGD 1,525 |
| SGD | 500 | 1.00 | SGD 500 |
| **Total** | | | **SGD 4,465** |

> User-entered FX rates are scenario inputs and are not guaranteed bank settlement quotes.


## 3. Automatic FX
BorderWise can obtain reference FX data automatically.
The system records:
- Rate
- Source
- Rate date
- Live/fallback state
Automatic reference data is used for indicative calculations rather than guaranteed remittance settlement.
When the external FX source is unavailable, the engine can fall back to a previously cached reference rate when one exists.
## 4. Custom FX scenarios
Users can override automatic FX with their own quoted rate.
Example:
USD 500
Custom USD/SGD rate = 1.30
500 × 1.30 = SGD 650
This allows users to model:
- Bank quotes
- Remittance quotes
- Scenario assumptions
- Manual planning rates
5. Any-currency conversion
The conversion studio supports arbitrary 3-letter currency pairs.
Examples:
CNY → SGD
USD → SGD
MYR → SGD
CNY → MYR
Conversion can use either:
- Automatic reference quotation
- User-provided custom rate
A conversion quote is informational and does not create or execute a transaction.
6. Cash-flow and affordability analysis
BorderWise can analyze:
- Current balances
- Spending
- Tuition obligations
- Scholarships
- Loans
- Accommodation
- Other monthly obligations
- 30-day cash-flow projections
- Tuition affordability
- Potential shortfalls
The financial engine performs the arithmetic deterministically rather than relying on the language model to calculate financial values.
7. Spending and financial-health analysis
Monthly spending categories can be classified as:
- Core
- Adjustable
This supports a transparent financial-health analysis and helps distinguish essential costs from areas where spending may be reduced.
The financial-health indicator is explicitly not a credit score.
8. Agentic natural-language interaction
Users can ask questions such as:
Can I afford my tuition?
How much money do I have?
What are my biggest expenses?
Will I run out of SGD?
What is the current MYR to SGD rate?
Prepare a RM5,000 transfer to Singapore.
I just received RM10,000 from my family. I have tuition coming up.
Should I convert some of it to SGD?
With OPENAI_API_KEY configured, BorderWise can use an LLM planner with tool calling.
Without an API key, the system still provides a deterministic offline/local agent planner for supported multi-step finance requests.
In both modes, the financial tools remain authoritative.
Safety Architecture
The core security principle is:
The language model must never directly move money.
The architecture is:
User
  │
  ▼
Agent / Planner
  │
  ▼
Deterministic Financial Tools
  │
  ├── Balances
  ├── Spending
  ├── Forecast
  ├── FX
  └── Conversion
  │
  ▼
Policy / Risk Engine
  │
  ▼
Transaction Proposal
  │
  ▼
Explicit Level-2 Authorization
  │
  ▼
Sandbox Execution
  │
  ▼
Verification
  │
  ▼
Audit Trail
Financial arithmetic and policy checks live in the application engine rather than inside the language model. GitHub
Permission Model
Level   Capability  Authorization
Level 0 Read balances, transactions, forecasts  None
Level 1 Prepare a transaction proposal  None
Level 2 Execute a transaction   Explicit user approval
A model-generated recommendation is therefore not equivalent to an executed financial action.
Security Guardrails
BorderWise implements multiple safeguards:
1. Financial calculations are deterministic.
2. The model cannot directly mutate balances.
3. Transactions pass through risk checks before execution.
4. Emergency reserves are protected.
5. High-value actions can be flagged for review.
6. A proposal cannot execute without explicit authorization.
7. Rejected proposals do not change balances.
8. Proposals, authorizations, blocks, executions and related events are auditable.
9. Sandbox mode is clearly separated from real banking.
10. The demo can be reset for reproducible testing.
Example blocked scenarios include:
Transfer without authorization
Transfer exceeding emergency-reserve policy
Negative or zero transfer amount
Repeated execution of an already executed proposal
Request to transfer everything
Rejected transaction proposal
See:
[`SECURITY_SELF_ASSESSMENT.md`](SECURITY_SELF_ASSESSMENT.md)
for the detailed security self-assessment. GitHub
Architecture
The main application is a FastAPI service backed by a deterministic FinanceEngine.
Application layers
Frontend
  │
  ▼
FastAPI API
  │
  ▼
FinanceEngine
  │
  ├── Profile & Wallet
  ├── FX & Conversion
  ├── Forecasting
  ├── Spending Analysis
  ├── Health Analysis
  ├── Agent Planner
  ├── Risk Policy
  ├── Proposal Handling
  └── Audit
Important API endpoints
Endpoint    Purpose
GET /   Web interface
GET /api/health Service health/version
GET /api/state  Current application state
POST /api/chat  Natural-language agent interaction
POST /api/profile   Create/update financial profile
POST /api/proposals Prepare a transfer proposal
POST /api/authorize Explicit authorization
POST /api/execute   Sandbox execution
POST /api/reset Reset demo state
GET /api/audit  Audit events
GET /api/fx/quote   FX quotation
POST /api/fx/convert    Currency conversion
POST /api/fx/refresh    Refresh FX data
POST /api/fx/refresh-all    Refresh automatic FX pairs
GET /api/capabilities   Supported capabilities
Technology Stack
- Python 3.14+
- FastAPI
- Uvicorn
- Pydantic
- Python dotenv
- OpenAI API (optional)
- Pytest
Dependencies are pinned in:
requirements.txt
The FastAPI application currently exposes a v7.3.0 currency-first service. GitHub
Getting Started
1. Clone the repository
git clone https://github.com/geraldchin07-arch/BorderWise-AI.git
cd BorderWise-AI
2. Create a virtual environment
macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
Windows
python -m venv .venv
.venv\Scripts\activate
3. Install dependencies
pip install -r requirements.txt
4. Optional: configure the LLM
Create a .env file:
OPENAI_API_KEY=your_api_key_here
The OpenAI integration is optional. Without the key, the offline/local planner remains available for supported workflows.
5. Start the application
uvicorn app.main:app --reload
Open:
http://127.0.0.1:8000
Testing
Run the complete test suite:
python -m pytest -q
The repository includes coverage for:
- Profile creation
- Planning currencies
- Multi-currency balances
- Currency conversion
- Same-currency conversion
- Custom FX
- Automatic FX
- FX fallback behavior
- Wallet valuation
- Forecasting
- Tuition affordability
- Spending analysis
- Financial health
- Agent behavior
- Transaction authorization
- Risk controls
- Sandbox execution
- Audit behavior
The QA branch used for this documentation work was validated with:
41 passed
Demo
For a reproducible judge/demo flow:
1. Click Reset judge demo.
2. Ask:Can I afford my tuition?
3. Review the agent trace.
4. Review the affordability result and recommendation.
5. Review the Level-2 transaction proposal.
6. Explicitly authorize the proposal.
7. Observe sandbox execution.
8. Observe verification.
9. Inspect the audit trail.
Additional demo prompts:
How much money do I have?
What are my biggest expenses?
Will I run out of SGD?
What is the current MYR to SGD exchange rate?
Prepare a RM5,000 transfer to Singapore.
Show my recent transactions.
A security demonstration can use:
Prepare a RM26,000 transfer.
which should be blocked by the emergency-reserve policy in the standard demo scenario. GitHub
See:
[`DEMO_SCRIPT.md`](DEMO_SCRIPT.md)
for the exact demonstration sequence.
Project Structure
BorderWise-AI/
├── app/
│   ├── engine.py
│   └── main.py
├── static/
│   └── ...
├── tests/
│   └── test_engine.py
├── .github/
│   └── workflows/
├── DEMO_SCRIPT.md
├── SECURITY_SELF_ASSESSMENT.md
├── PRESENTATION_OUTLINE.md
├── requirements.txt
└── README.md
QA Highlights
The QA suite specifically verifies important multi-currency scenarios such as:
CNY → SGD
CNY 10,000 × 0.18 = SGD 1,800
USD → SGD
USD 500 × 1.28 = SGD 640
Four-currency wallet valuation
CNY 10,000 → SGD 1,800
USD    500 → SGD   640
MYR  5,000 → SGD 1,525
SGD    500 → SGD   500
-------------------------
Total       = SGD 4,465
Additional QA coverage verifies:
- Same-currency conversion
- Automatic FX failure and cached-rate fallback
- Custom FX override
- USD planning currency
- CNY planning currency
- Multi-currency wallet valuation
Current Behavioral Note
The multi-currency wallet can display an indicative combined valuation across currencies.
For forecasting, the current engine uses the balance held in the selected planning currency as the starting planning balance. A non-planning-currency holding should therefore be interpreted as available portfolio value rather than assumed converted liquidity unless the user actually performs or models the conversion.
This distinction is intentional in the current prototype and should be considered during financial planning demos.
Limitations
BorderWise is a prototype and should not be treated as a production banking system.
A production deployment would require, at minimum:
- Bank-grade authentication
- Secure secrets management
- KYC / AML controls
- Transaction signing
- Stronger rate limiting
- Immutable external audit storage
- Production-grade real-time FX data
- Model monitoring
- Human escalation
- Formal security review
- Real bank integration and settlement controls
Reference FX values are indicative and are not guaranteed execution or remittance quotes. GitHub
Competition Positioning
BorderWise is designed around a clear separation of concerns:
LLM
= understand, plan, reason, explain
Deterministic engine
= calculate, validate, forecast, convert
Policy engine
= protect, block, approve
Transaction layer
= execute only after explicit authorization
Audit layer
= record what happened
The result is an agentic finance assistant that is useful without giving the language model unrestricted financial authority.
Evidence for Evaluation
Recommended evaluation evidence includes:
- Architecture diagram
- Multi-currency calculations
- Successful sandbox execution
- Blocked high-risk transaction
- Explicit authorization flow
- Verification output
- Audit trail
- Automated test results
- Demo recording
- Security self-assessment
See:
- [`DEMO_SCRIPT.md`](DEMO_SCRIPT.md)
- [`SECURITY_SELF_ASSESSMENT.md`](SECURITY_SELF_ASSESSMENT.md)
- [`PRESENTATION_OUTLINE.md`](PRESENTATION_OUTLINE.md)
Disclaimer
BorderWise AI is a competition/demo prototype using simulated financial accounts.
It is not a banking product, financial institution, remittance service, investment adviser, or source of guaranteed FX settlement rates.
No real money is moved by the sandbox transaction flow.