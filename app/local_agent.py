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

    def _extract_wallet_balances_from_text(self, text: str) -> dict[str, Decimal]:
        """Extract explicit wallet balances stated in a hypothetical chat scenario."""
        t = text.lower().replace(",", "").strip()
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
        balances: dict[str, Decimal] = {}

        for code, names in aliases.items():
            escaped = sorted((re.escape(x) for x in names), key=len, reverse=True)
            token = "(?:" + "|".join(escaped) + ")"

            # Prefer amounts explicitly associated with possession/holding language.
            possession = re.search(
                rf"\b(?:have|has|hold|holding|own|keep)\b[^.;,]*?{token}\s*([0-9]+(?:\.[0-9]+)?)",
                t,
                re.I,
            )
            if possession:
                balances[code] = self.engine.money_value(possession.group(1))
                continue

            # Also support compact forms such as "CNY 10,000" before an obligation.
            compact = re.search(
                rf"{token}\s*([0-9]+(?:\.[0-9]+)?)",
                t,
                re.I,
            )
            if compact:
                balances[code] = self.engine.money_value(compact.group(1))
                continue

            reverse = re.search(
                rf"([0-9]+(?:\.[0-9]+)?)\s*{token}\b",
                t,
                re.I,
            )
            if reverse:
                balances[code] = self.engine.money_value(reverse.group(1))

        return balances

    def _amount_after_need(self, text: str, currency: str) -> Decimal | None:
        """Extract the amount associated with a need/payment requirement.

        This is separate from _amount() because a currency may appear more than once
        in the same sentence (for example, SGD 500 held and SGD 3,000 needed).
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
        escaped = sorted((re.escape(x) for x in names), key=len, reverse=True)
        currency_token = "(?:" + "|".join(escaped) + ")"
        pattern = rf"\b(?:need|needs|pay|paying|require|required|requirement|for)\b[^.;,]{{0,100}}?{currency_token}\s*([0-9]+(?:\.[0-9]+)?)"
        matches = re.findall(pattern, t, re.IGNORECASE)
        if not matches:
            return None
        return self.engine.money_value(matches[-1])

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

        # Generic multi-currency reasoning: handle currencies beyond MYR/SGD before
        # falling back to the legacy demo-specific planner below.
        supported = [
            "MYR", "SGD", "USD", "CNY", "JPY", "KRW", "THB", "EUR", "GBP",
            "AUD", "CAD", "HKD", "TWD", "INR",
        ]
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
        detected: dict[str, Decimal] = {}
        mentioned: set[str] = set()
        for code in supported:
            amount = self._amount(t, code)
            if amount is not None:
                detected[code] = amount
            if any(re.search(rf"(?<![A-Za-z]){re.escape(alias)}(?![A-Za-z])", t, re.I) for alias in aliases[code]):
                mentioned.add(code)

        planning = str(self.engine.state.get("profile_meta", {}).get("planning_currency", "SGD")).upper()
        conversion_words = any(k in t for k in [
            "convert", "exchange", "to ", "into ", "worth", "how much is",
        ])

        # Case D: wallet-wide funding optimization for an explicit obligation.
        # Example: "I have CNY 10,000, USD 500 and MYR 5,000. I need SGD 3,000 for tuition. What should I convert?"
        funding_question = any(k in t for k in [
            "what should i convert", "which currency should i use", "which currency to use",
            "what should i use", "how should i fund", "which account should i use",
            "best currency to use", "best currency", "how much should i convert",
        ])
        if funding_question and tuition_context:
            target_code = None
            target_amount = None
            for code in detected:
                requested_amount = self._amount_after_need(t, code)
                if requested_amount is not None:
                    target_code, target_amount = code, requested_amount
                    break
            if target_code is None:
                for code, amount in detected.items():
                    if code == planning and re.search(r"\\b(?:need|needs|pay|paying|require|required)\\b", t, re.I):
                        target_code, target_amount = code, amount
                        break
            if target_code is None:
                # If the user says "upcoming tuition" without an amount, use the saved
                # net tuition only when it is actually due within the 30-day horizon.
                profile = self.engine.get_profile()
                tuition_due = int(profile.get("tuition_due_days", 31)) <= 30
                tuition_value = self.engine.money_value(
                    Decimal(str(profile.get("tuition_amount", 0)))
                    - Decimal(str(profile.get("scholarship_amount", 0)))
                    - Decimal(str(profile.get("loan_amount", 0)))
                )
                saved_tuition_currency = str(profile.get("tuition_currency", planning)).upper()
                if tuition_due and tuition_value > 0:
                    target_code, target_amount = saved_tuition_currency, tuition_value

            if target_code and target_amount and target_amount > 0:
                # When the user explicitly supplies wallet balances in the request,
                # use those values as a hypothetical scenario instead of silently
                # mixing them with stale saved-profile balances. State is never mutated.
                first_need = re.search(r"\b(?:need|needs|require|required|pay|paying)\b", t, re.I)
                wallet_text = t[:first_need.start()] if first_need else t
                wallet_balances = self._extract_wallet_balances_from_text(wallet_text)
                use_scenario_wallet = len(wallet_balances) >= 1

                trace = [
                    {"step": "UNDERSTAND", "status": "completed", "detail": f"Detected a funding-optimization request for {target_code} {target_amount:,.2f}."},
                    {"step": "OBSERVE", "status": "completed", "detail": (
                        "Used the wallet balances explicitly supplied in this message as a hypothetical scenario."
                        if use_scenario_wallet
                        else "Inspected the entire saved multi-currency wallet."
                    )},
                ]
                try:
                    funding = self.engine.recommend_funding(
                        target_amount,
                        target_code,
                        balances_override=wallet_balances if use_scenario_wallet else None,
                    )
                except ValueError as exc:
                    trace.append({"step": "REASON", "status": "blocked", "detail": str(exc)})
                    return self._result("agentic_local", f"I could not build a safe funding plan: {exc}", trace, {"blocked_reason": "funding_plan_unavailable"})

                for leg in funding["plan"]:
                    trace.append({
                        "step": "FX" if leg["from_currency"] != leg["to_currency"] else "OBSERVE",
                        "status": "completed",
                        "detail": (
                            f"Use {leg['from_currency']} {leg['source_amount']:,.2f} → {leg['to_currency']} {leg['target_amount']:,.2f} at {leg['rate']:.8f}."
                        ),
                    })
                trace.append({"step": "SECURITY", "status": "completed", "detail": f"Protected the configured {funding['reserve']['currency']} emergency reserve of {funding['reserve']['amount']:,.2f}; no balances were changed."})

                if funding["status"] == "funded":
                    legs_text = "; ".join(
                        f"{x['from_currency']} {x['source_amount']:,.2f} → {x['to_currency']} {x['target_amount']:,.2f}"
                        for x in funding["plan"]
                    )
                    answer = (
                        f"To fund {target_code} {target_amount:,.2f}, I would use the saved wallet rather than convert everything. "
                        f"Recommended funding: {legs_text}. "
                        f"This covers the target with the fewest source-currency conversions under the current indicative rates while protecting the emergency reserve. "
                        "No transaction was created or executed."
                    )
                else:
                    gap = funding["remaining_gap"]
                    answer = (
                        f"I checked the full saved wallet for the {target_code} {target_amount:,.2f} requirement. "
                        f"The available balances can fund about {funding['funded_amount']:,.2f} {target_code}, leaving a gap of about {gap:,.2f} {target_code}. "
                        "I would not automatically convert the entire wallet; another funding source is still needed. No transaction was created."
                    )
                trace.append({"step": "RECOMMEND", "status": "completed", "detail": "Produced a wallet-wide funding recommendation without mutating account state."})
                return self._result("agentic_local", answer, trace, {"funding_plan": funding, "wallet": self.engine.currency_overview(), "wallet_balances_used": {k: float(v) for k, v in (wallet_balances if use_scenario_wallet else self.engine.get_balance()).items()}, "wallet_source": "message" if use_scenario_wallet else "saved_profile"})

        # Case A: explicit source/target conversion, e.g. "USD 500 to SGD".
        # Prefer semantic phrases such as "have/received USD 500" for the source and
        # "need/pay SGD 3,000" for the target. This avoids selecting a currency
        # merely because its code appears earlier in the supported-currency list.
        # When the request contains an obligation amount (for example, tuition), let the
        # obligation-aware path compare the source funds against the required target amount.
        if detected and conversion_words and not received and not (len(detected) >= 2 and tuition_context):
            source_candidates = list(detected.items())

            source_code = None
            source_amount = None
            target_code = None

            for code, amount in source_candidates:
                if re.search(
                    rf"\b(?:have|has|hold|holding|own|got|received)\s+(?:about\s+)?(?:{re.escape(code.lower())})\s*[0-9]",
                    t,
                    re.I,
                ):
                    source_code, source_amount = code, amount
                    break

            if source_code is None:
                source_code, source_amount = source_candidates[0]

            for code in detected:
                if code == source_code:
                    continue
                if re.search(
                    rf"\b(?:need|needs|pay|paying|require|required|want|worth|to|into)\s+(?:about\s+)?(?:{re.escape(code.lower())})\s*[0-9]",
                    t,
                    re.I,
                ):
                    target_code = code
                    break

            if target_code is None:
                target_candidates = [code for code in mentioned if code != source_code]
                if target_candidates:
                    target_code = target_candidates[0]
                elif re.search(r"\bto\s+(?:usd)\b", t, re.I):
                    target_code = "USD"
                elif re.search(r"\bto\s+(?:cny|rmb)\b", t, re.I):
                    target_code = "CNY"
                elif re.search(r"\bto\s+(?:myr|rm)\b", t, re.I):
                    target_code = "MYR"
                elif re.search(r"\bto\s+(?:sgd|s\$)\b|\binto\s+(?:sgd|s\$)\b", t, re.I):
                    target_code = "SGD"
                else:
                    target_code = planning

            if target_code != source_code:
                trace = [
                    {"step": "UNDERSTAND", "status": "completed", "detail": f"Detected a {source_code}→{target_code} currency question."},
                    {"step": "FX", "status": "completed", "detail": f"Requested the direct reference rate for {source_code}→{target_code}."},
                ]
                try:
                    conv = self.engine.convert_currency(source_amount, source_code, target_code)
                except ValueError as exc:
                    trace.append({"step": "FX", "status": "blocked", "detail": str(exc)})
                    return self._result("agentic_local", f"I could not calculate that conversion safely: {exc}", trace, {"blocked_reason": "fx_unavailable"})
                fx = conv.get("fx", {})
                rate = conv["rate"]
                trace.append({"step": "REASON", "status": "completed", "detail": f"Applied 1 {source_code} = {rate:.8f} {target_code} using the selected reference/quote path."})
                answer = (
                    f"At the current {fx.get('source', 'reference')} rate, 1 {source_code} = {rate:.8f} {target_code}. "
                    f"{source_code} {source_amount:,.2f} is approximately {target_code} {conv['converted_amount']:,.2f}. "
                    f"Rate date: {fx.get('rate_date') or 'unavailable'}. This is an indicative reference/quote and may differ from a bank's settlement rate or fees."
                )
                trace.append({"step": "RECOMMEND", "status": "completed", "detail": "Provided the conversion without changing account state."})
                return self._result("agentic_local", answer, trace, {"conversion": conv, "currency_overview": self.engine.currency_overview()})

        # Case B: incoming funds + student decision, e.g. "I received RMB 10,000. What should I do?"
        received_currency = next((code for code in supported if code in detected and any(k in t for k in [
            "received", "got ", "got paid", "family sent", "sent me", "allowance", "incoming", "from my family",
        ])), None)
        if received_currency and received_currency not in {"MYR", "SGD"} and (tuition_context or conversion_question or "what should i do" in t or "plan" in t):
            incoming_amount = detected[received_currency]
            target_currency = next((code for code in mentioned if code != received_currency), planning)
            trace = [
                {"step": "UNDERSTAND", "status": "completed", "detail": f"Detected hypothetical incoming {received_currency} funds and a student-finance planning request."},
                {"step": "OBSERVE", "status": "completed", "detail": "Read the saved multi-currency wallet and upcoming obligations."},
            ]
            overview = self.engine.currency_overview()
            balance = self.engine.get_balance()
            forecast = self.engine.forecast()
            try:
                to_target = self.engine.convert_currency(incoming_amount, received_currency, target_currency)
                to_sgd = self.engine.convert_currency(incoming_amount, received_currency, "SGD") if received_currency != "SGD" else {
                    "converted_amount": float(incoming_amount), "rate": 1.0, "from_currency": "SGD", "to_currency": "SGD",
                    "fx": {"source": "Same currency", "rate_date": None, "live": False}
                }
            except ValueError as exc:
                trace.append({"step": "FX", "status": "blocked", "detail": str(exc)})
                return self._result("agentic_local", f"I cannot safely evaluate those funds right now: {exc}", trace, {"blocked_reason": "fx_unavailable"})

            trace.append({"step": "SIMULATE", "status": "completed", "detail": f"Hypothetically valued {received_currency} {incoming_amount:,.2f}; account state was not changed."})
            explicit_target_amount = None
            if target_currency in detected and target_currency != received_currency:
                explicit_target_amount = detected[target_currency]

            if explicit_target_amount is not None and target_currency != received_currency:
                needed_source = self.engine.money_value(Decimal(str(explicit_target_amount)) / Decimal(str(to_target["rate"])))
                source_available = incoming_amount
                trace.append({"step": "CALCULATE", "status": "completed", "detail": f"Calculated the source amount needed for the stated {target_currency} obligation."})
                if needed_source <= source_available:
                    answer = (
                        f"You have {received_currency} {incoming_amount:,.2f} and a stated {target_currency} need of {target_currency} {explicit_target_amount:,.2f}. "
                        f"At the current reference rate of 1 {received_currency} = {to_target['rate']:.8f} {target_currency}, that need would require about "
                        f"{received_currency} {needed_source:,.2f}. I would not convert the full amount automatically; converting about {received_currency} {needed_source:,.2f} would cover the stated need and leave roughly "
                        f"{received_currency} {money(incoming_amount - needed_source):,.2f} unconverted. "
                        f"This is a scenario calculation only; rate date {to_target.get('fx', {}).get('rate_date') or 'unavailable'}, excluding bank/remittance spreads and fees."
                    )
                else:
                    gap = self.engine.money_value(needed_source - source_available)
                    answer = (
                        f"At the current reference rate, {received_currency} {incoming_amount:,.2f} converts to about {target_currency} {to_target['converted_amount']:,.2f}, which is short of the stated "
                        f"{target_currency} {explicit_target_amount:,.2f} need by about {target_currency} {money(explicit_target_amount - Decimal(str(to_target['converted_amount']))):,.2f}. "
                        f"I would not recommend converting the full amount automatically; the remaining gap is roughly {received_currency} {gap:,.2f}, before fees/spread."
                    )
            else:
                added_sgd = Decimal(str(to_sgd["converted_amount"]))
                projected_after = self.engine.money_value(Decimal(str(forecast["projected_balance_sgd"])) + added_sgd)
                if projected_after < 0:
                    answer = (
                        f"You received {received_currency} {incoming_amount:,.2f}. At the current reference rate that is about S$ {added_sgd:,.2f}. "
                        f"Even after treating the receipt as hypothetical income, the 30-day projection remains a funding gap of about S$ {abs(projected_after):,.2f}. "
                        f"I would convert only the amount needed for the documented gap, not the entire {received_currency} balance, and keep the remaining funds available as a buffer."
                    )
                else:
                    answer = (
                        f"You received {received_currency} {incoming_amount:,.2f}. Its indicative value is about S$ {added_sgd:,.2f} at the current reference rate. "
                        f"With that hypothetical receipt, the 30-day projection becomes about S$ {projected_after:,.2f}. "
                        f"I would not convert it all automatically; keep the source currency unless you have a specific SGD obligation, then convert only what that obligation requires."
                    )
            trace.append({"step": "RECOMMEND", "status": "completed", "detail": "Produced a multi-currency recommendation without mutating the user's balances or creating a transaction."})
            return self._result("agentic_local", answer, trace, {
                "currency_overview": overview,
                "balances": balance,
                "forecast": forecast,
                "incoming_currency": received_currency,
                "incoming_amount": float(incoming_amount),
                "conversion_to_target": to_target,
                "conversion_to_sgd": to_sgd,
            })

        # Case C: "I have CNY 10,000 and need SGD 3,000 of tuition".
        # Infer source/target from the sentence semantics, not the order of the
        # supported-currency list. This is critical because the list contains SGD
        # before CNY.
        if len(detected) >= 2 and tuition_context and any(code not in {"MYR", "SGD"} for code in detected):
            source_code = None
            source_amount = None
            target_code = None
            target_amount = None

            for code, amount in detected.items():
                if re.search(
                    rf"\b(?:have|has|hold|holding|own)\s+(?:about\s+)?(?:{re.escape(code.lower())})\s*[0-9]",
                    t,
                    re.I,
                ):
                    source_code, source_amount = code, amount
                    break

            for code, amount in detected.items():
                if code == source_code:
                    continue
                if re.search(
                    rf"\b(?:need|needs|pay|paying|require|required)\s+(?:about\s+)?(?:{re.escape(code.lower())})\s*[0-9]",
                    t,
                    re.I,
                ):
                    target_code, target_amount = code, amount
                    break

            # Safe fallback only when the semantic wording is absent.
            if source_code is None:
                source_code, source_amount = next(iter(detected.items()))
            if target_code is None:
                remaining = [(code, amount) for code, amount in detected.items() if code != source_code]
                if remaining:
                    target_code, target_amount = remaining[0]

            if source_code and target_code and source_code != target_code and target_amount is not None:
                try:
                    conv = self.engine.convert_currency(source_amount, source_code, target_code)
                    needed_source = self.engine.money_value(Decimal(str(target_amount)) / Decimal(str(conv["rate"])))
                    answer = (
                        f"{source_code} {source_amount:,.2f} is approximately {target_code} {conv['converted_amount']:,.2f} at 1 {source_code} = {conv['rate']:.8f} {target_code}. "
                    )
                    if conv["converted_amount"] >= float(target_amount):
                        answer += (
                            f"That is enough for your stated {target_code} {target_amount:,.2f} tuition amount. I would convert only about {source_code} {needed_source:,.2f}, rather than the full balance. "
                            f"The quote is indicative and excludes bank/remittance fees or spread."
                        )
                    else:
                        gap_target = self.engine.money_value(Decimal(str(target_amount)) - Decimal(str(conv["converted_amount"])))
                        answer += f"That leaves a gap of about {target_code} {gap_target:,.2f}; the remaining funding would need another source."
                    trace = [
                        {"step": "UNDERSTAND", "status": "completed", "detail": f"Detected {source_code} funds and a {target_code} tuition requirement."},
                        {"step": "FX", "status": "completed", "detail": f"Fetched the direct {source_code}→{target_code} reference quote."},
                        {"step": "REASON", "status": "completed", "detail": "Compared converted funds with the stated tuition amount."},
                        {"step": "RECOMMEND", "status": "completed", "detail": "Recommended converting only the amount required rather than the full source balance."},
                    ]
                    return self._result("agentic_local", answer, trace, {"conversion": conv, "tuition": {"currency": target_code, "amount": float(target_amount)}})
                except ValueError as exc:
                    return self._result("agentic_local", f"I could not safely compare those currencies: {exc}", [{"step":"FX","status":"blocked","detail":str(exc)}], {"blocked_reason":"fx_unavailable"})

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
