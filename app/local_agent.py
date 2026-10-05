from __future__ import annotations

import re
from decimal import Decimal
from typing import Any


class LocalAgentPlanner:
    """Offline agent planner for demos without an external LLM API.

    This is deliberately deterministic. It performs multi-step planning by selecting
    trusted financial tools from the user's natural-language goal, while the FinanceEngine
    remains the authority for calculations, FX, policy and state-changing actions.
    """

    def __init__(self, engine: Any):
        self.engine = engine

    def _amount(self, text: str, currency: str) -> Decimal | None:
        """Extract an amount for a requested currency.

        Supports common currency codes/symbols/aliases without assuming
        MYR and SGD are the only currencies.
        """
        t = text.lower().replace(",", "").strip()
        code = currency.upper().strip()

        aliases = {
            "MYR": ["myr", "rm", "ringgit"],
            "SGD": ["sgd", "s$"],
            "USD": ["usd", "us$", "$", "dollar", "dollars"],
            "CNY": ["cny", "rmb", "yuan", "renminbi", "¥"],
            "JPY": ["jpy", "yen", "¥"],
            "KRW": ["krw", "won", "₩"],
            "THB": ["thb", "baht", "฿"],
            "EUR": ["eur", "€", "euro", "euros"],
            "GBP": ["gbp", "£", "pound", "pounds"],
            "AUD": ["aud", "a$", "australian dollar"],
            "CAD": ["cad", "c$", "canadian dollar"],
            "HKD": ["hkd", "hk$", "hong kong dollar"],
            "TWD": ["twd", "nt$", "taiwan dollar"],
            "INR": ["inr", "₹", "rupee", "rupees"],
        }

        names = aliases.get(code, [code.lower()])

        # Escape aliases so symbols and special characters are handled safely.
        escaped = sorted(
            [re.escape(x) for x in names],
            key=len,
            reverse=True,
        )

        prefix_pattern = r"(?:" + "|".join(escaped) + r")\s*"
        suffix_pattern = r"\s*(?:" + "|".join(escaped) + r")\b"

        patterns = [
            rf"{prefix_pattern}([0-9]+(?:\.[0-9]+)?)",
            rf"([0-9]+(?:\.[0-9]+)?){suffix_pattern}",
        ]

        for pattern in patterns:
            match = re.search(pattern, t, re.IGNORECASE)
            if match:
                return self.engine.money_value(match.group(1))

        return None

    def _result(self, *args) -> dict[str, Any]:
        """Build a local-agent result while supporting both legacy call shapes."""
        if len(args) == 4:
            intent, answer, trace, data = args
        elif len(args) == 3:
            intent, answer, trace, data = "agentic_local", args[0], args[1], args[2]
        else:
            raise TypeError("LocalAgentPlanner._result expects 3 or 4 arguments after self.")
        return {
            "intent": intent,
            "answer": answer,
            "trace": trace,
            "data": {**data, "agent_mode": "local_agent_planner"},
            "state": self.engine.snapshot(),
        }


    def run(self, text: str) -> dict[str, Any] | None:
        t = text.lower().strip()
        myr = self._amount(t, "MYR")
        sgd = self._amount(t, "SGD")

        received = any(k in t for k in ["received", "got", "got paid", "family sent", "sent me", "allowance", "incoming"])
        tuition_context = any(k in t for k in ["tuition", "school fees", "fees", "accommodation", "hostel"])
        conversion_question = any(k in t for k in ["convert", "exchange", "should i", "what should i do", "enough", "need to"])

        # Explicit execution requests are handled before informational FX questions.
        # An execution command may NEVER create a new proposal or reuse an already
        # executed proposal. This is the anti-replay guard for agentic money movement.
        execute_request = any(k in t for k in [
            "execute", "execute the", "make it happen", "complete the transfer",
            "run the transfer", "process the transfer", "send it now",
        ])
        if execute_request and not any(k in t for k in ["ignore all", "ignore previous", "override security"]):
            pending = [p for p in self.engine.state["proposals"].values() if p.get("status") == "PENDING_AUTHORIZATION"]
            authorized = [p for p in self.engine.state["proposals"].values() if p.get("status") == "AUTHORIZED"]
            requested_amount = myr
            if authorized:
                matches = [p for p in authorized if requested_amount is None or abs(float(p["amount_myr"]) - float(requested_amount)) < 0.005]
                if len(matches) == 1:
                    trace = [{"step": "UNDERSTAND", "status": "completed", "detail": "Detected an execution request."},
                             {"step": "SECURITY", "status": "blocked", "detail": "Execution is only allowed through the explicit authorization flow; no direct execution shortcut is exposed to the natural-language agent."}]
                    return self._result("agentic_local", "I can't execute a transfer directly from a chat command. Please explicitly authorize the pending proposal; the execution path is controlled by the transaction state machine.", trace, {"blocked_reason": "direct_execution_not_allowed"})
            trace = [{"step": "UNDERSTAND", "status": "completed", "detail": "Detected an execution request."}]
            trace.append({"step": "SECURITY", "status": "blocked", "detail": "No pending authorized proposal is available for execution; previously executed proposals cannot be replayed."})
            if pending:
                answer = "I can't execute that transaction yet. A proposal is still awaiting Level 2 authorization. No transaction was created."
            else:
                executed_matches = [
                    p for p in self.engine.state["proposals"].values()
                    if p.get("status") == "EXECUTED"
                    and (requested_amount is None or abs(float(p["amount_myr"]) - float(requested_amount)) < 0.005)
                ]
                if executed_matches:
                    prior = executed_matches[-1]
                    prior_tx = prior.get("transaction_id", "the previous transaction")
                    answer = (
                        "I can't execute that transaction. There is no pending authorized proposal. "
                        f"The matching proposal was already executed as {prior_tx} and cannot be replayed. "
                        "No new transaction was created."
                    )
                else:
                    answer = "I can't execute that transaction. There is no pending authorized proposal. No new transaction was created."
            return self._result("agentic_local", answer, trace, {"blocked_reason": "no_pending_authorized_proposal"})

        # Explicit authorization of an existing proposal takes priority over
        # informational FX questions. Authorization is a state-changing command:
        # it must match a pending proposal, and only then may the sandbox execute.
        authorize_request = any(k in t for k in [
            "i authorize", "authorize the", "authorize this", "approve the",
            "approve this", "i approve", "confirm the", "confirm this",
        ])
        if authorize_request:
            pending = [p for p in self.engine.state["proposals"].values() if p.get("status") == "PENDING_AUTHORIZATION"]
            requested_amount = myr
            if requested_amount is not None:
                matches = [p for p in pending if abs(float(p["amount_myr"]) - float(requested_amount)) < 0.005]
            else:
                matches = pending if len(pending) == 1 else []

            trace = [{
                "step": "UNDERSTAND",
                "status": "completed",
                "detail": "Detected an explicit user authorization request for a pending sandbox proposal.",
            }]
            if not matches:
                detail = "No unambiguous pending proposal matched this authorization."
                trace.append({"step": "SECURITY", "status": "blocked", "detail": detail})
                if not pending:
                    answer = "There is no pending proposal to authorize. Prepare an exact MYR amount first."
                else:
                    answer = "I did not authorize anything because the amount did not unambiguously match the pending proposal. Please state the exact MYR amount."
                return self._result("agentic_local", answer, trace, {"blocked_reason": "no_unambiguous_pending_proposal"})

            proposal = matches[0]
            self.engine.authorize(proposal["id"], True)
            trace.append({"step": "AUTHORIZE", "status": "completed", "detail": f"Level 2 authorization recorded for proposal {proposal['id']}.",})
            try:
                executed = self.engine.execute(proposal["id"])
            except ValueError as exc:
                trace.append({"step": "EXECUTE", "status": "blocked", "detail": str(exc)})
                return self._result("agentic_local", f"Authorization was recorded, but sandbox execution was blocked by policy: {exc}", trace, {"proposal": proposal})

            tx = executed["transaction"]
            trace.append({"step": "EXECUTE", "status": "completed", "detail": f"Sandbox transaction {tx['id']} executed; no real money moved."})
            trace.append({"step": "VERIFY", "status": "completed", "detail": "Verified the resulting sandbox balances and completed transaction."})
            trace.append({"step": "AUDIT", "status": "completed", "detail": "Authorization and execution were written to the audit trail."})
            answer = (
                f"Authorization confirmed for RM{proposal['amount_myr']:,.2f}. "
                f"The sandbox conversion executed successfully: RM{proposal['amount_myr']:,.2f} → S${proposal['amount_sgd']:,.2f} "
                f"at the locked proposal rate of {proposal['rate']:.4f}. Transaction {tx['id']} was verified and audited. No real money moved."
            )
            return self._result("agentic_local", answer, trace, {"proposal": executed["proposal"], "transaction": tx, "balances": executed["balances"]})

        # Security-override language is never treated as authorization. The policy
        # layer remains authoritative even if the user asks the agent to ignore it.
        security_override = any(k in t for k in [
            "ignore all previous", "ignore previous security", "ignore the security",
            "override security", "bypass security", "bypass the policy",
            "you are authorized", "execute immediately",
        ])
        if security_override and any(k in t for k in ["transfer", "send", "execute", "prepare", "convert", "remit"]):
            trace = [
                {"step": "UNDERSTAND", "status": "completed", "detail": "Detected a request attempting to override financial security controls."},
                {"step": "SECURITY", "status": "blocked", "detail": "Natural-language instructions cannot grant authorization or override the deterministic policy engine."},
            ]
            return self._result(
                "agentic_local",
                "I can't override the security policy or grant myself authorization. Money movement requires an explicit proposal and Level 2 authorization. No transaction was created.",
                trace,
                {"blocked_reason": "security_policy_override_attempt"},
            )

        # Explicit action requests take priority over informational FX questions.
        # IMPORTANT: words like "conversion" or "convert" alone are not enough to
        # authorize preparation; the user must clearly request an action and provide
        # an exact amount. Never infer an action amount from a forecast.
        explicit_action = any(k in t for k in [
            "prepare", "transfer", "send", "remit", "remittance", "pay",
            "make the transfer", "make a transfer", "create a transfer",
            "set up a transfer", "convert rm", "convert myr", "exchange rm",
            "exchange myr",
        ])
        explicit_all = bool(re.search(r"\ball\b|\beverything\b|\b全部\b", t, re.I))
        if explicit_action and not received:
            trace = [
                {"step": "UNDERSTAND", "status": "completed", "detail": "Identified an explicit transfer/conversion request."},
            ]
            if explicit_all:
                risk = self.engine.risk_check(self.engine.money_value(1), text)
                trace.append({"step": "SECURITY", "status": "blocked", "detail": "Blocked an ambiguous request to move all available MYR; an exact amount is required."})
                return self._result(
                    "agentic_local",
                    "I blocked that request. I will never infer an amount for an 'all my MYR' transfer. Please specify the exact MYR amount; explicit Level 2 authorization is still required before any sandbox execution.",
                    trace,
                    {"risk": risk, "blocked_reason": "ambiguous_all_funds_request"},
                )
            if myr is not None:
                trace.append({"step": "OBSERVE", "status": "completed", "detail": f"Extracted the explicit requested amount: RM{myr:,.2f}."})
                risk = self.engine.risk_check(myr, text)
                trace.append({"step": "SECURITY", "status": "blocked" if risk["status"] == "BLOCKED" else "completed", "detail": f"Risk status: {risk['status']}."})
                if risk["status"] == "BLOCKED":
                    return self._result("agentic_local", "I blocked that transfer because it violates a safety policy: " + " ".join(risk["reasons"]), trace, {"risk": risk})
                proposal = self.engine.create_proposal(myr, text)
                trace.append({"step": "FX", "status": "completed", "detail": f"Calculated the sandbox MYR→SGD conversion at the refreshed reference rate {proposal['rate']:.4f}."})
                trace.append({"step": "AUTHORIZE", "status": "required", "detail": "Level 2 explicit user authorization is required; the request to skip confirmation is ignored."})
                answer = f"I prepared a sandbox conversion of RM{myr:,.2f} to approximately S${proposal['amount_sgd']:,.2f}. I will not execute it until you explicitly authorize it."
                return self._result("agentic_local", answer, trace, {"proposal": proposal, "risk": risk})
            return self._result(
                "agentic_local",
                "I need an exact MYR amount before I can prepare a transfer. I will not infer an amount from your forecast or balances.",
                trace,
                {"blocked_reason": "missing_explicit_amount"},
            )

        # Multi-step incoming-funds scenario: "I received RM10,000 ... tuition ... should I convert?"
        if received and myr is not None and (tuition_context or conversion_question):
            trace = [
                {"step": "UNDERSTAND", "status": "completed", "detail": "Identified an incoming MYR amount and a student-finance decision."},
                {"step": "OBSERVE", "status": "completed", "detail": "Read current MYR/SGD balances."},
            ]
            balance = self.engine.get_balance()
            sim = self.engine.simulate_income_impact(myr, "MYR")
            trace.append({"step": "SIMULATE", "status": "completed", "detail": f"Hypothetically added RM{myr:,.2f}; account state was not changed."})

            obligations = self.engine.get_obligations()
            trace.append({"step": "OBSERVE", "status": "completed", "detail": f"Checked {len(obligations)} upcoming student obligations."})
            forecast = self.engine.forecast()
            trace.append({"step": "REASON", "status": "completed", "detail": f"Calculated the deterministic 30-day SGD forecast: projected shortfall S${forecast['shortfall_sgd']:,.2f}."})

            fx = self.engine.refresh_fx()
            trace.append({"step": "FX", "status": "completed", "detail": f"Refreshed MYR/SGD reference rate: 1 MYR = S${fx['rate']:.4f} ({'live' if fx.get('live') else 'fallback'}; {fx.get('rate_date') or 'date unavailable'})."})

            shortfall_after = Decimal(str(sim["projected_shortfall_after_hypothetical_income_sgd"]))
            recommended_myr = self.engine.money_value(shortfall_after / Decimal(str(fx["rate"]))) if shortfall_after > 0 else self.engine.money_value(0)
            if recommended_myr > myr:
                recommended_myr = myr
            conversion = self.engine.convert_currency(recommended_myr, "MYR", "SGD") if recommended_myr > 0 else None
            if conversion:
                trace.append({"step": "CALCULATE", "status": "completed", "detail": f"Calculated RM{recommended_myr:,.2f} as the maximum amount of the new funds that would address the remaining projected gap."})

            remaining_myr = self.engine.money_value(Decimal(str(balance["MYR"])) + myr - recommended_myr)
            reserve = self.engine.money_value(self.engine.state["emergency_reserve_myr"])
            risk = self.engine.risk_check(recommended_myr, "student obligations after hypothetical incoming funds") if recommended_myr > 0 else {"status": "LOW", "reasons": []}
            trace.append({"step": "SECURITY", "status": "completed" if risk["status"] != "BLOCKED" else "blocked", "detail": f"Checked emergency reserve and transfer policy: {risk['status']}."})

            live_text = "live reference data" if fx.get("live") else "fallback/last-known data"
            if shortfall_after <= 0:
                answer = (
                    f"You received RM{myr:,.2f}. After treating that as hypothetical incoming funds, "
                    f"your 30-day projected SGD shortfall becomes S$0.00, so I would not recommend converting it all automatically. "
                    f"Your current balances are RM{balance['MYR']:,.2f} and S${balance['SGD']:,.2f}; the RM{reserve:,.2f} emergency reserve remains a protected floor. "
                    f"The current MYR/SGD reference rate is 1 MYR = S${fx['rate']:.4f} ({live_text}, rate date {fx.get('rate_date') or 'unavailable'})."
                )
            else:
                answer = (
                    f"You received RM{myr:,.2f}. I checked your balances, upcoming obligations and 30-day forecast before recommending a conversion. "
                    f"After the hypothetical receipt, the projected SGD shortfall is S${shortfall_after:,.2f}. "
                    f"At the current reference rate of 1 MYR = S${fx['rate']:.4f}, that gap would require about RM{recommended_myr:,.2f}. "
                    f"I would convert only about RM{recommended_myr:,.2f}, not the full RM{myr:,.2f}, leaving roughly RM{remaining_myr:,.2f} in MYR and preserving the RM{reserve:,.2f} emergency reserve. "
                    f"This uses {live_text} (rate date {fx.get('rate_date') or 'unavailable'}) and excludes bank/remittance spreads or fees."
                )

            trace.append({"step": "RECOMMEND", "status": "completed", "detail": "Produced a bounded recommendation without creating or executing a transfer."})
            return self._result(answer, trace, {
                "incoming_funds": sim,
                "balances": balance,
                "obligations": obligations,
                "forecast": forecast,
                "forecast_after_income": {
                    "projected_shortfall_sgd": float(shortfall_after),
                    "projected_balance_sgd": float(-shortfall_after if shortfall_after > 0 else Decimal("0")),
                },
                "fx": fx,
                "conversion": conversion,
                "risk": risk,
            })

        # General multi-intent "what should I do" / student-finance planning.
        planning = any(k in t for k in ["what should i do", "help me plan", "plan my", "should i", "what do you recommend"])
        if planning and (tuition_context or "sgd" in t or "myr" in t or "money" in t):
            trace = [
                {"step": "UNDERSTAND", "status": "completed", "detail": "Recognized a financial planning request."},
                {"step": "OBSERVE", "status": "completed", "detail": "Read balances and upcoming obligations."},
            ]
            balance = self.engine.get_balance()
            obligations = self.engine.get_obligations()
            forecast = self.engine.forecast()
            trace.append({"step": "REASON", "status": "completed", "detail": f"Combined balances, obligations and 30-day forecast; shortfall S${forecast['shortfall_sgd']:,.2f}."})
            fx = self.engine.refresh_fx()
            trace.append({"step": "FX", "status": "completed", "detail": f"Checked current reference FX: 1 MYR = S${fx['rate']:.4f}."})
            if forecast["shortfall_sgd"] > 0:
                needed = self.engine.money_value(Decimal(str(forecast["shortfall_sgd"])) / Decimal(str(fx["rate"])))
                risk = self.engine.risk_check(needed, "essential student obligations")
                trace.append({"step": "SECURITY", "status": "completed" if risk["status"] != "BLOCKED" else "blocked", "detail": f"Checked proposed coverage amount: {risk['status']}."})
                answer = f"Based on the current demo state, your main issue is a 30-day SGD shortfall of S${forecast['shortfall_sgd']:,.2f}. At 1 MYR = S${fx['rate']:.4f}, covering it would take about RM{needed:,.2f}. I would not convert automatically; I would prepare that amount only after confirming the obligation timing and keeping the RM{self.engine.state['emergency_reserve_myr']:,.2f} emergency reserve protected."
            else:
                answer = f"Your current 30-day projection does not show an SGD shortfall. I would keep the emergency reserve intact and avoid unnecessary conversion. Current balances are RM{balance['MYR']:,.2f} and S${balance['SGD']:,.2f}."
            trace.append({"step": "RECOMMEND", "status": "completed", "detail": "Recommendation is advisory only; no proposal or execution was created."})
            return self._result(answer, trace, {"balances": balance, "obligations": obligations, "forecast": forecast, "fx": fx})

        return None
