from __future__ import annotations

import json
import os
from typing import Any, Callable

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None


class AgentOrchestrator:
    """LLM planner + deterministic finance tools.

    The model can read and reason through tools, including a user-configured multi-currency wallet, but it is never given a direct
    execute-money tool. Proposal creation is the highest side-effecting tool;
    actual execution remains behind the explicit Level-2 authorization API.
    """

    SYSTEM = """
You are XKF5 AI, a cautious cross-border student-finance agent operating in a sandbox.
Your job is to understand the user's financial goal, choose the minimum necessary tools,
reason over the returned data, and give a concise, transparent answer.

CRITICAL SAFETY RULES:
- Treat tool outputs as authoritative for balances, forecasts, FX rates, currency valuation and policy decisions.
- When multiple currencies are configured, use get_currency_overview or convert_currency rather than guessing cross-rates.
- User-entered FX rates are scenario inputs and must be labelled as such.
- Never invent an exchange rate, balance, transaction, obligation or risk result.
- Never claim money moved unless a verified execution result says so.
- You cannot execute transfers. You may only prepare a proposal when the user explicitly asks
  for a transfer or when a recommendation requires one. The application requires separate,
  explicit Level-2 user authorization before execution.
- Never bypass or reinterpret the deterministic policy engine.
- If a request would breach a policy, explain the block and do not create a proposal.
- For hypothetical income such as “I received RM10,000”, use the simulation tool unless the
  application explicitly tells you the state was updated. Do not silently mutate financial state.
- This is a competition sandbox, not a bank and not a source of guaranteed financial advice.

Prefer tool use over guessing. For a multi-part question, use multiple tools and synthesize.
For complex student-finance situations, build a goal-aware plan: identify essential obligations and deadlines, protect reserves, compare multi-currency funding options, simulate hypothetical income when appropriate, and distinguish recommendations from executable actions.
""".strip()

    def __init__(self, engine: Any):
        self.engine = engine
        self.enabled = bool(os.getenv("OPENAI_API_KEY")) and OpenAI is not None
        self.model = os.getenv("OPENAI_MODEL", "gpt-5")
        self.client = OpenAI() if self.enabled else None
        self.max_rounds = 5

    def tool_schemas(self) -> list[dict[str, Any]]:
        return [
            self._tool("get_balance", "Read the full configured multi-currency wallet balances.", {}),
            self._tool("get_transactions", "Read recent transaction history.", {
                "type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 50}},
                "required": [], "additionalProperties": False,
            }),
            self._tool("get_obligations", "Read upcoming student-finance obligations and due days.", {}),
            self._tool("forecast_cashflow", "Calculate the deterministic 30-day SGD cash-flow forecast.", {}),
            self._tool("forecast_portfolio", "Calculate deterministic 30-day liquidity using the full multi-currency wallet in the user's planning currency.", {
                "type": "object",
                "properties": {
                    "horizon_days": {"type": "integer", "minimum": 1, "maximum": 365}
                },
                "required": ["horizon_days"], "additionalProperties": False,
            }),
            self._tool("analyze_spending", "Analyze the user's monthly SGD spending plan by category.", {}),
            self._tool("get_currency_overview", "Show all configured wallet currencies, their rates to SGD and indicative SGD values.", {}),
            self._tool("get_fx_rate", "Refresh and read the selected MYR/SGD rate plus source/date and live-reference fallback details.", {
                "type": "object", "properties": {"force_refresh": {"type": "boolean"}},
                "required": [], "additionalProperties": False,
            }),
            self._tool("convert_currency", "Convert any supported 3-letter currency pair using deterministic reference/quote data. Use this for exact user-directed conversions such as CNY→MYR, USD→SGD or MYR→SGD; do not invent cross-rates.", {
                "type": "object",
                "properties": {
                    "amount": {"type": "number", "exclusiveMinimum": 0},
                    "from_currency": {"type": "string", "pattern": "^[A-Za-z]{3}$"},
                    "to_currency": {"type": "string", "pattern": "^[A-Za-z]{3}$"},
                },
                "required": ["amount", "from_currency", "to_currency"], "additionalProperties": False,
            }),
            self._tool("assess_transfer_risk", "Run the deterministic transfer policy without moving money.", {
                "type": "object", "properties": {
                    "amount_myr": {"type": "number", "exclusiveMinimum": 0},
                    "purpose": {"type": "string"},
                },
                "required": ["amount_myr", "purpose"], "additionalProperties": False,
            }),
            self._tool("create_transfer_proposal", "Prepare a sandbox MYR→SGD conversion proposal. Never executes money movement.", {
                "type": "object", "properties": {
                    "amount_myr": {"type": "number", "exclusiveMinimum": 0},
                    "purpose": {"type": "string"},
                },
                "required": ["amount_myr", "purpose"], "additionalProperties": False,
            }),
            self._tool("recommend_funding", "Find a deterministic multi-currency funding plan for a target amount while protecting the emergency reserve; never moves money.", {
                "type": "object",
                "properties": {
                    "target_amount": {"type": "number", "exclusiveMinimum": 0},
                    "target_currency": {"type": "string", "pattern": "^[A-Za-z]{3}$"},
                },
                "required": ["target_amount", "target_currency"], "additionalProperties": False,
            }),
            self._tool("simulate_income_impact", "Hypothetically assess the effect of receiving funds without mutating account state.", {
                "type": "object", "properties": {
                    "amount": {"type": "number", "exclusiveMinimum": 0},
                    "currency": {"type": "string", "pattern": "^[A-Za-z]{3}$"},
                },
                "required": ["amount", "currency"], "additionalProperties": False,
            }),
        ]

    @staticmethod
    def _tool(name: str, description: str, parameters: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "function", "name": name, "description": description,
            "parameters": parameters if parameters else {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
            "strict": True,
        }

    def _proposal_request_is_explicit(self, user_text: str, args: dict[str, Any]) -> bool:
        """Fail closed unless the user explicitly requests the exact MYR proposal amount."""
        try:
            requested_amount = self.engine.extract_myr_amount(user_text)
            proposed_amount = self.engine.money_value(args.get("amount_myr"))
        except Exception:
            return False
        if requested_amount is None or proposed_amount <= 0:
            return False
        if requested_amount != proposed_amount:
            return False

        normalized = self.engine.repair_user_text(user_text).lower()
        advice_or_scenario = any(phrase in normalized for phrase in [
            "should i", "should we", "would you recommend", "recommend",
            "is it wise", "what if", "hypothetical", "compare", "can i afford",
            "might send", "may send", "could send", "expect to receive",
            "if i receive", "if my family", "parents might", "parents may",
        ])
        if advice_or_scenario:
            return False

        explicit_action = any(phrase in normalized for phrase in [
            "prepare", "create a proposal", "make a proposal", "transfer",
            "send", "remit", "convert", "exchange",
        ])
        return explicit_action

    def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        try:
            if name == "get_balance":
                return {"ok": True, "result": self.engine.get_balance()}
            if name == "get_transactions":
                return {"ok": True, "result": self.engine.get_transactions(int(args.get("limit", 20)))}
            if name == "get_obligations":
                return {"ok": True, "result": self.engine.get_obligations()}
            if name == "forecast_cashflow":
                return {"ok": True, "result": self.engine.forecast()}
            if name == "forecast_portfolio":
                return {"ok": True, "result": self.engine.forecast_portfolio(int(args["horizon_days"]))}
            if name == "analyze_spending":
                return {"ok": True, "result": self.engine.spending_analysis()}
            if name == "get_currency_overview":
                return {"ok": True, "result": self.engine.currency_overview()}
            if name == "get_fx_rate":
                return {"ok": True, "result": self.engine.refresh_fx(bool(args.get("force_refresh", False)))}
            if name == "convert_currency":
                return {"ok": True, "result": self.engine.convert_currency(args["amount"], args["from_currency"], args["to_currency"])}
            if name == "assess_transfer_risk":
                return {"ok": True, "result": self.engine.risk_check(self.engine.money_value(args["amount_myr"]), args["purpose"])}
            if name == "create_transfer_proposal":
                return {"ok": True, "result": self.engine.create_proposal(self.engine.money_value(args["amount_myr"]), args["purpose"])}
            if name == "recommend_funding":
                return {"ok": True, "result": self.engine.recommend_funding(args["target_amount"], args["target_currency"])}
            if name == "simulate_income_impact":
                return {"ok": True, "result": self.engine.simulate_income_impact(args["amount"], args["currency"])}
            return {"ok": False, "error": f"Unknown tool: {name}"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def run(self, text: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None

        trace: list[dict[str, Any]] = [
            {"step": "UNDERSTAND", "status": "completed", "detail": "LLM agent enabled; selecting deterministic finance tools."}
        ]
        input_items: list[Any] = [{"role": "user", "content": text}]

        try:
            for _ in range(self.max_rounds):
                response = self.client.responses.create(
                    model=self.model,
                    instructions=self.SYSTEM,
                    input=input_items,
                    tools=self.tool_schemas(),
                    max_output_tokens=700,
                )

                # Preserve the model's response items, including reasoning items required
                # by reasoning models when continuing a tool-call turn.
                input_items.extend(response.output)
                calls = [item for item in response.output if getattr(item, "type", None) == "function_call"]
                if not calls:
                    answer = response.output_text.strip() if response.output_text else "I could not produce a response."
                    trace.append({"step": "RESPOND", "status": "completed", "detail": f"LLM synthesized final answer using {len(trace)-1} tool/agent steps."})
                    return {"intent": "agentic", "answer": answer, "trace": trace, "data": {"agent_mode": "llm_tool_calling", "model": self.model}, "state": self.engine.snapshot()}

                for call in calls:
                    name = call.name
                    args = json.loads(call.arguments or "{}")
                    trace.append({"step": "TOOL", "status": "completed", "detail": f"Selected {name} with arguments {args}."})
                    if name == "create_transfer_proposal" and not self._proposal_request_is_explicit(text, args):
                        result = {
                            "ok": False,
                            "error": (
                                "Proposal blocked: the user must explicitly request a transfer/preparation "
                                "and state the exact matching MYR amount. Advice, hypothetical, conditional, "
                                "or inferred amounts cannot create a proposal."
                            ),
                            "blocked_reason": "proposal_not_explicitly_requested",
                        }
                    else:
                        result = self.call_tool(name, args)
                    if result.get("ok"):
                        trace.append({"step": "TOOL_RESULT", "status": "completed", "detail": f"{name} returned deterministic financial data."})
                    else:
                        trace.append({"step": "TOOL_RESULT", "status": "blocked", "detail": f"{name} returned an error; no unsafe fallback was used."})
                    input_items.append({
                        "type": "function_call_output",
                        "call_id": call.call_id,
                        "output": json.dumps(result, default=str),
                    })

            return {"intent": "agentic", "answer": "I reached the agent tool-call limit before completing the request.", "trace": trace, "data": {"agent_mode": "llm_tool_calling", "model": self.model}, "state": self.engine.snapshot()}
        except Exception as exc:
            trace.append({"step": "AGENT_FALLBACK", "status": "completed", "detail": f"LLM unavailable: {type(exc).__name__}. Deterministic engine used instead."})
            return None
