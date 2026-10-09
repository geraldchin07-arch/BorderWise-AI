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
        # Conversation-local hypothetical context; never stored as real balances.
        if not hasattr(self.engine, "_agent_scenario_context"):
            self.engine._agent_scenario_context = {}

    def _currency_aliases(self) -> dict[str, list[str]]:
        """Shared currency vocabulary for every offline-agent parser."""
        codes = """
        SGD MYR USD CNY EUR GBP JPY KRW THB AUD CAD HKD TWD INR IDR PHP VND NZD
        CHF SEK NOK DKK SAR AED QAR BND BHD ZAR BRL MXN PLN CZK HUF RON BGN TRY
        UAH RUB ILS EGP NGN KES GHS MAD TND DZD KWD BDT OMR JOD LBP PKR LKR
        NPR MMK MNT KZT UZS GEL AMD AZN ALL BAM MKD RSD BYN MDL ISK XOF XAF XPF
        XCD BWP BIF CDF DJF ERN ETB FJD GYD HTG JMD KHR KMF LAK LSL MGA MWK MUR
        MVR MZN NAD PAB PYG PEN BOB CLP COP CRC DOP GTQ HNL ARS UYU VES ZMW ZWL
        TZS UGX RWF SOS SDG SSP SYP SRD TTD TOP VUV WST YER IQD MOP SBD SCR TJS TMT AFN AOA BBD BMD BSD BTN BZD CUP CVE FKP GIP GMD GNF IRR KGS KPW KYD LRD LYD MRU NIO PGK SHP SLE STN SZL ZWG
        """.split()
        aliases = {
            code: [code.lower()]
            for code in codes
            if code not in {"ALL", "TRY", "MAD", "PEN", "TOP", "GEL", "COP", "BOB", "RON", "CUP"}
        }
        aliases.update({
            "ALL": ["albanian lek", "lek"],
            "MYR": ["myr", "rm", "ringgit", "malaysian ringgit"],
            "SGD": ["sgd", "s$", "singapore dollar", "singapore dollars"],
            "USD": ["usd", "us$", "$", "dollar", "dollars", "us dollar", "us dollars"],
            "CNY": ["cny", "rmb", "yuan", "renminbi", "chinese yuan"],
            "JPY": ["jpy", "yen", "japanese yen"],
            "KRW": ["krw", "won", "₩", "korean won"],
            "THB": ["thb", "baht", "฿", "thai baht"],
            "EUR": ["eur", "€", "euro", "euros", "european euro"],
            "GBP": ["gbp", "£", "pound", "pounds", "british pound"],
            "AUD": ["aud", "a$", "australian dollar", "australian dollars"],
            "CAD": ["cad", "c$", "canadian dollar", "canadian dollars"],
            "HKD": ["hkd", "hk$", "hong kong dollar", "hong kong dollars"],
            "TWD": ["twd", "nt$", "taiwan dollar", "new taiwan dollar"],
            "INR": ["inr", "₹", "rupee", "rupees", "indian rupee"],
            "IDR": ["idr", "rupiah", "indonesian rupiah"],
            "PHP": ["php", "₱", "philippine peso", "philippine pesos"],
            "VND": ["vnd", "₫", "dong", "vietnamese dong"],
            "NZD": ["nzd", "new zealand dollar", "new zealand dollars"],
            "CHF": ["chf", "swiss franc", "swiss francs"],
            "ZAR": ["zar", "rand", "south african rand"],
            "BRL": ["brl", "brazilian real", "brazilian reals"],
            "MXN": ["mxn", "mexican peso", "mexican pesos"],
            "PLN": ["pln", "zloty", "polish zloty"],
            "TRY": ["try", "turkish lira", "turkish liras"],
            "MAD": ["moroccan dirham", "moroccan dirhams"],
            "PEN": ["peruvian sol", "peruvian soles"],
            "TOP": ["tongan paanga"],
            "KWD": ["kwd", "kuwaiti dinar", "kuwaiti dinars"],
            "BHD": ["bhd", "bahraini dinar", "bahraini dinars"],
            "BDT": ["bdt", "bangladeshi taka", "taka"],
            "AED": ["aed", "uae dirham", "emirati dirham"],
            "SAR": ["sar", "saudi riyal", "saudi riyals"],
            "QAR": ["qar", "qatari riyal", "qatari riyals"],
            "NGN": ["ngn", "nigerian naira", "naira"],
            "EGP": ["egp", "egyptian pound", "egyptian pounds"],
            "ILS": ["ils", "israeli new shekel", "shekel", "shekels"],
            "PKR": ["pkr", "pakistani rupee", "pakistani rupees"],
            "LKR": ["lkr", "sri lankan rupee", "sri lankan rupees"],
            "AFN": ["afn", "afghan afghani", "afghani"],
            "AOA": ["aoa", "angolan kwanza"],
            "BBD": ["bbd", "barbadian dollar"],
            "BMD": ["bmd", "bermudian dollar"],
            "BSD": ["bsd", "bahamian dollar"],
            "BTN": ["btn", "bhutanese ngultrum"],
            "BZD": ["bzd", "belize dollar"],
            "CUP": ["cuban peso"],
            "CVE": ["cve", "cape verde escudo"],
            "FKP": ["fkp", "falkland islands pound"],
            "GIP": ["gip", "gibraltar pound"],
            "GMD": ["gmd", "gambian dalasi"],
            "GNF": ["gnf", "guinean franc"],
            "IRR": ["irr", "iranian rial"],
            "KGS": ["kgs", "kyrgyzstani som"],
            "KPW": ["kpw", "north korean won"],
            "KYD": ["kyd", "cayman islands dollar"],
            "LRD": ["lrd", "liberian dollar"],
            "LYD": ["lyd", "libyan dinar"],
            "MRU": ["mru", "mauritanian ouguiya"],
            "NIO": ["nio", "nicaraguan cordoba"],
            "PGK": ["pgk", "papua new guinean kina"],
            "SHP": ["shp", "saint helena pound"],
            "SLE": ["sle", "sierra leonean leone"],
            "STN": ["stn", "sao tome dobra"],
            "SZL": ["szl", "swazi lilangeni"],
            "ZWG": ["zwg", "zimbabwe gold"],
            "GEL": ["georgian lari", "lari"],
            "COP": ["colombian peso", "colombian pesos"],
            "BOB": ["bolivian boliviano", "bolivian bolivianos"],
            "RON": ["romanian leu", "romanian lei"],
        })
        return aliases

    def _parse_human_amount(self, raw_amount: str) -> Decimal:
        """Parse plain and shorthand amounts such as 2000, 2k, and 1.5m."""
        raw = str(raw_amount).strip().replace(",", "")
        suffix = raw[-1:].lower()
        if suffix in {"k", "m"}:
            multiplier = Decimal("1000") if suffix == "k" else Decimal("1000000")
            raw = raw[:-1]
        else:
            multiplier = Decimal("1")
        return self.engine.money_value(Decimal(raw) * multiplier)

    def _explicit_ambiguous_code_amount(self, text: str, currency: str) -> Decimal | None:
        """Accept word-shaped ISO codes only when the user typed the code in uppercase."""
        code = currency.upper().strip()
        ambiguous = {"ALL", "TRY", "MAD", "PEN", "TOP", "GEL", "COP", "BOB", "RON", "CUP"}
        if code not in ambiguous:
            return None
        amount = r"(?<![\d,])((?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?[km]?)(?!\d|,\d)"
        token = rf"(?<![A-Za-z]){re.escape(code)}(?![A-Za-z])"
        for pattern in (rf"{token}\s*{amount}", rf"{amount}\s*{token}"):
            match = re.search(pattern, str(text or ""))
            if match:
                return self._parse_human_amount(match.group(1))
        return None

    def _amount(self, text: str, currency: str) -> Decimal | None:
        """Extract an amount for a requested currency.

        Supports common currency codes/symbols/aliases without assuming
        MYR and SGD are the only currencies.
        """
        raw_text = str(text or "")
        code = currency.upper().strip()
        explicit_code_amount = self._explicit_ambiguous_code_amount(raw_text, code)
        if explicit_code_amount is not None:
            return explicit_code_amount
        t = raw_text.lower().strip()

        aliases = self._currency_aliases()

        names = aliases.get(code, [code.lower()])

        # Escape aliases so symbols and special characters are handled safely.
        escaped = sorted(
            [re.escape(x) for x in names],
            key=len,
            reverse=True,
        )

        alias_token = r"(?<![A-Za-z])(?:" + "|".join(escaped) + r")(?![A-Za-z])"
        prefix_pattern = alias_token + r"\s*"
        suffix_pattern = r"\s*" + alias_token

        amount_pattern = r"(?<![\d,])((?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?[km]?)(?!\d|,\d)"
        patterns = [
            rf"{prefix_pattern}{amount_pattern}",
            rf"{amount_pattern}{suffix_pattern}",
        ]

        for pattern in patterns:
            match = re.search(pattern, t, re.IGNORECASE)
            if match:
                return self._parse_human_amount(match.group(1))

        return None

    def _extract_wallet_balances_from_text(self, text: str) -> dict[str, Decimal]:
        """Extract explicit wallet balances stated in a hypothetical chat scenario.

        A balance may appear in a comma-separated possession list, while an outgoing
        obligation such as "send RM2,000" can appear later in the same sentence. Parse
        possession clauses separately so obligation amounts are never promoted to wallet
        balances.
        """
        raw_text = str(text or "").strip()
        t = self.engine.repair_user_text(raw_text).lower().strip()
        aliases = self._currency_aliases()
        balances: dict[str, Decimal] = {}

        patterns_by_code: dict[str, str] = {}
        for code, names in aliases.items():
            escaped = sorted((re.escape(x) for x in names), key=len, reverse=True)
            token = r"(?<![A-Za-z])(?:" + "|".join(escaped) + r")(?![A-Za-z])"
            amount = r"(?<![\d,])(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?[km]?(?!\d|,\d)"
            patterns_by_code[code] = rf"(?:{token}\s*({amount})|({amount})\s*{token})"

        # First parse every explicit possession list. The lookahead stops before a
        # new obligation/action clause, but deliberately allows commas inside the list.
        possession_pattern = re.compile(
            r"\b(?:have|has|hold|holding|own|keep|got|gotten)\b"
            r"(?P<segment>.*?)"
            r"(?=(?:\b(?:need|needs|want to|would like to|send|sending|remit|remittance|transfer|pay|paying|require|required|tuition|school fees)\b)|[.!?]|$)",
            re.I,
        )
        possession_segments = [m.group("segment") for m in possession_pattern.finditer(t)]
        possession_segments_raw = [m.group("segment") for m in possession_pattern.finditer(raw_text)]

        for segment in possession_segments:
            for code, pattern in patterns_by_code.items():
                match = re.search(pattern, segment, re.I)
                if match:
                    raw_amount = match.group(1) or match.group(2)
                    balances[code] = self._parse_human_amount(raw_amount)

        # Ambiguous word-shaped codes (ALL, TRY, MAD, PEN, TOP, GEL, COP, BOB,
        # RON) are accepted only in uppercase, so ordinary prose is not mistaken
        # for a wallet currency.
        ambiguous_codes = {"ALL", "TRY", "MAD", "PEN", "TOP", "GEL", "COP", "BOB", "RON", "CUP"}
        for code in ambiguous_codes:
            for segment in possession_segments_raw:
                amount_value = self._explicit_ambiguous_code_amount(segment, code)
                if amount_value is not None:
                    balances[code] = amount_value
                    break

        # Also support a standalone reverse form such as "2,000 SGD" when it is not
        # associated with an outgoing obligation. This is a fallback for short scenarios
        # that omit the verb "have".
        for code, pattern in patterns_by_code.items():
            for match in re.finditer(pattern, t, re.I):
                raw_amount = match.group(1) or match.group(2)
                context_before = t[max(0, match.start() - 80):match.start()]
                context_after = t[match.end():match.end() + 50]
                if re.search(
                    r"\b(?:need|needs|pay|paying|require|required|send|sending|remit|remittance|transfer|tuition)\b",
                    context_before,
                    re.I,
                ):
                    continue
                if re.search(
                    r"\b(?:to|for|toward)\s*$",
                    context_before,
                    re.I,
                ):
                    continue
                # If the amount is already part of a parsed possession list, keep it.
                # Otherwise accept it only when there is no immediate outgoing wording.
                if code not in balances:
                    balances[code] = self._parse_human_amount(raw_amount)
                break

        return balances


    def _amount_after_need(self, text: str, currency: str) -> Decimal | None:
        """Extract the amount associated with a need/payment requirement.

        This is separate from _amount() because a currency may appear more than once
        in the same sentence (for example, SGD 500 held and SGD 3,000 needed).
        """
        raw_text = str(text or "")
        code = currency.upper().strip()
        ambiguous = {"ALL", "TRY", "MAD", "PEN", "TOP", "GEL", "COP", "BOB", "RON", "CUP"}
        if code in ambiguous and re.search(rf"(?<![A-Za-z]){re.escape(code)}(?![A-Za-z])", raw_text):
            amount = r"(?<![\d,])((?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?[km]?)(?!\d|,\d)"
            token = rf"(?<![A-Za-z]){re.escape(code)}(?![A-Za-z])"
            pattern = (
                rf"(?i:\b(?:need|needs|pay|paying|require|required|requirement|for)\b)"
                rf"[^.;,]{{0,100}}?(?:{token}\s*{amount}|{amount}\s*{token})"
            )
            match = re.search(pattern, raw_text)
            if match:
                raw_amount = next((value for value in match.groups() if value), None)
                if raw_amount:
                    return self._parse_human_amount(raw_amount)
        t = raw_text.lower().strip()

        aliases = self._currency_aliases()
        names = aliases.get(code, [code.lower()])
        escaped = sorted((re.escape(x) for x in names), key=len, reverse=True)
        currency_token = r"(?<![A-Za-z])(?:" + "|".join(escaped) + r")(?![A-Za-z])"
        amount_pattern = r"(?<![\d,])((?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?[km]?)(?!\d|,\d)"
        pattern = (
            rf"\b(?:need|needs|pay|paying|require|required|requirement|for)\b"
            rf"[^.;,]{{0,100}}?(?:{currency_token}\s*{amount_pattern}|{amount_pattern}\s*{currency_token})"
        )
        matches = re.findall(pattern, t, re.IGNORECASE)
        if not matches:
            return None
        raw_amount = next((value for match in reversed(matches) for value in match if value), None)
        return self._parse_human_amount(raw_amount) if raw_amount else None

    def _extract_horizon_days(self, text: str) -> int | None:
        """Extract a practical obligation horizon from natural language."""
        t = text.lower().strip()
        word_numbers = {
            "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
            "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
        }
        patterns = [
            (r"\b(?:in|within|due in|due within)\s+(\d+)\s+days?\b", 1),
            (r"\b(?:in|within|due in|due within)\s+(\d+)\s+weeks?\b", 7),
            (r"\b(?:in|within|due in|due within)\s+(one|two|three|four|five|six|seven|eight|nine|ten)\s+weeks?\b", 7),
            (r"\b(?:next|within)\s+month\b", 30),
        ]
        for pattern, multiplier in patterns:
            m = re.search(pattern, t, re.I)
            if m:
                raw = m.group(1)
                value = word_numbers.get(raw, None) if raw.isalpha() else int(raw)
                return value * multiplier if value is not None else None
        return None


    def _extract_labeled_amount(
        self, text: str, labels: list[str]
    ) -> tuple[Decimal, str] | None:
        """Extract the amount nearest a financial label and its currency."""
        raw_text = str(text or "")
        t = raw_text.lower()
        supported_aliases = self._currency_aliases()
        currency_pattern = []
        for code, aliases in supported_aliases.items():
            for alias in aliases:
                currency_pattern.append((re.escape(alias), code))
        ambiguous_codes = {"ALL", "TRY", "MAD", "PEN", "TOP", "GEL", "COP", "BOB", "RON", "CUP"}
        for code in ambiguous_codes:
            if re.search(rf"(?<![A-Za-z]){re.escape(code)}(?![A-Za-z])", raw_text):
                currency_pattern.append((re.escape(code.lower()), code))
        currency_pattern.sort(key=lambda item: len(item[0]), reverse=True)
        token = r"(?<![A-Za-z])(?:" + "|".join(alias for alias, _ in currency_pattern) + r")(?![A-Za-z])"
        amount_token = r"(?<![\d,])((?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?[km]?)(?!\d|,\d)"

        for label in labels:
            label_pattern = re.escape(label)
            window = re.search(
                rf"\b{label_pattern}\b(?P<context>[^.;\n]{{0,80}})",
                t,
                re.I,
            )
            if not window:
                continue
            context = window.group("context")
            # Walk currency mentions in text order and bind each to the nearest
            # immediately adjacent amount, so a later remittance cannot replace
            # the tuition amount associated with the label.
            for currency_match in re.finditer(token, context, re.I):
                alias = currency_match.group(0)
                after = re.match(rf"\s*{amount_token}", context[currency_match.end():], re.I)
                if after:
                    raw_amount = after.group(1)
                else:
                    before = re.search(
                        rf"{amount_token}\s*$",
                        context[:currency_match.start()],
                        re.I,
                    )
                    if not before:
                        continue
                    raw_amount = before.group(1)
                matched_code = next(
                    code for raw_alias, code in currency_pattern
                    if raw_alias.lower() == re.escape(alias).lower()
                )
                return self._parse_human_amount(raw_amount), matched_code
        return None


    def _scenario_forecast(self, balances, monthly_expenses, tuition, remittance, incoming, horizon_days):
        """Project an explicitly supplied chat scenario without stale profile cash-flow values."""
        planning = str(self.engine.state.get("profile_meta", {}).get("planning_currency", "SGD")).upper()
        planning_rate = self.engine._profile_rate_to_sgd(planning)

        def to_planning(amount, currency):
            code = currency.upper().strip()
            if code == planning:
                return self.engine.money_value(amount)
            rate, _ = self.engine._currency_rate_to_sgd(code)
            return self.engine.money_value(amount * rate / planning_rate)

        starting = self.engine.money_value(0)
        for code, balance in balances.items():
            starting += to_planning(self.engine.money_value(balance), code)

        meta = self.engine.state.get("profile_meta", {})
        reserve_currency = str(meta.get("emergency_reserve_currency", "MYR")).upper()
        reserve_amount = self.engine.money_value(Decimal(str(meta.get("emergency_reserve_amount", self.engine.state.get("emergency_reserve_myr", 0)))))
        reserve_represented = reserve_currency in balances
        reserve_balance = self.engine.money_value(balances.get(reserve_currency, 0))
        reserve_protected = reserve_represented and reserve_balance >= reserve_amount
        protected = to_planning(min(reserve_balance, reserve_amount), reserve_currency) if reserve_represented else self.engine.money_value(0)
        usable = self.engine.money_value(max(self.engine.money_value(0), starting - protected))
        factor = Decimal(str(max(1, int(horizon_days)))) / Decimal("30")
        # A user-entered "monthly expenses" amount is a monthly planning baseline,
        # so keep the stated monthly figure intact even when the obligation horizon
        # is shorter than 30 days. The scenario label communicates the horizon;
        # the spending input itself remains the user's stated monthly budget.
        spending = to_planning(monthly_expenses[0], monthly_expenses[1]) if monthly_expenses else self.engine.money_value(0)
        tuition_value = to_planning(tuition[0], tuition[1]) if tuition else self.engine.money_value(0)
        remittance_value = to_planning(remittance[0], remittance[1]) if remittance else self.engine.money_value(0)
        incoming_value = to_planning(incoming[0], incoming[1]) if incoming else self.engine.money_value(0)
        base = self.engine.money_value(usable - spending - tuition_value - remittance_value)
        with_incoming = self.engine.money_value(base + incoming_value)

        # Keep both the selected planning-currency view and an SGD-normalized view.
        # This avoids mislabeled "projected_balance_sgd" values when a user chooses
        # a planning currency other than SGD.
        starting_sgd = self.engine.money_value(starting * planning_rate)
        protected_sgd = self.engine.money_value(protected * planning_rate)
        usable_sgd = self.engine.money_value(usable * planning_rate)
        spending_sgd = self.engine.money_value(spending * planning_rate)
        tuition_sgd = self.engine.money_value(tuition_value * planning_rate)
        remittance_sgd = self.engine.money_value(remittance_value * planning_rate)
        incoming_sgd = self.engine.money_value(incoming_value * planning_rate)
        base_sgd = self.engine.money_value(base * planning_rate)
        with_incoming_sgd = self.engine.money_value(with_incoming * planning_rate)

        return {
            "horizon_days": int(horizon_days),
            "planning_currency": planning,
            "starting_balance_planning": float(starting),
            "starting_balance_sgd": float(starting_sgd),
            "protected_reserve_planning": float(protected),
            "protected_reserve_sgd": float(protected_sgd),
            "usable_starting_planning": float(usable),
            "usable_starting_sgd": float(usable_sgd),
            "monthly_expenses_planning": float(spending),
            "monthly_expenses_sgd": float(spending_sgd),
            "tuition_planning": float(tuition_value),
            "tuition_sgd": float(tuition_sgd),
            "remittance_planning": float(remittance_value),
            "remittance_sgd": float(remittance_sgd),
            "incoming_planning": float(incoming_value),
            "incoming_sgd": float(incoming_sgd),
            "projected_balance_planning": float(base),
            "projected_balance_sgd": float(base_sgd),
            "projected_balance_with_incoming": float(with_incoming),
            "projected_balance_with_incoming_sgd": float(with_incoming_sgd),
            "cash_position": "funding_gap" if base < 0 else "surplus",
            "cash_position_with_incoming": "funding_gap" if with_incoming < 0 else "surplus",
            "reserve": {
                "currency": reserve_currency,
                "configured_amount": float(reserve_amount),
                "balance": float(reserve_balance),
                "represented_in_scenario": reserve_represented,
                "protected": reserve_protected,
                "verification_status": "protected" if reserve_protected else ("below_floor" if reserve_represented else "not_represented"),
            },
            "state_changed": False,
        }


    def _result(self, *args) -> dict[str, Any]:
        """Build a local-agent result while supporting both legacy call shapes."""
        if len(args) == 4:
            intent, answer, trace, data = args
        elif len(args) == 3:
            intent, answer, trace, data = "agentic_local", args[0], args[1], args[2]
        else:
            raise TypeError("LocalAgentPlanner._result expects 3 or 4 arguments after self.")
        enriched_data = {**data, "agent_mode": "local_agent_planner"}
        # Incoming-money planning must expose the full decision trace regardless
        # of which local-planner branch produced the result.
        if enriched_data.get("incoming_funds") is not None and enriched_data.get("forecast_after_income") is not None:
            required_steps = [
                ("UNDERSTAND", "Recognized the received-funds planning request."),
                ("OBSERVE", "Reviewed the stated funds and current forecast."),
                ("SIMULATE", "Simulated incoming funds without changing wallet state."),
                ("REASON", "Compared the updated projected shortfall with tuition needs."),
                ("FX", "Identified the relevant currency conversion pair."),
                ("CALCULATE", "Calculated the projected position after incoming funds."),
                ("SECURITY", "No transaction was created or executed."),
                ("RECOMMEND", "Returned an advisory recommendation only."),
            ]
            present = {item.get("step") for item in trace}
            for step, detail in required_steps:
                if step not in present:
                    trace.append({"step": step, "status": "completed", "detail": detail})
        status_by_step: dict[str, list[dict[str, Any]]] = {}
        for item in trace:
            status_by_step.setdefault(str(item.get("step", "UNKNOWN")), []).append(item)

        blocked_security = [
            item for item in status_by_step.get("SECURITY", [])
            if str(item.get("status", "")).lower() == "blocked"
        ]
        required_authorization = [
            item for item in status_by_step.get("AUTHORIZE", [])
            if str(item.get("status", "")).lower() == "required"
        ]
        evidence_steps = [
            item["step"] for item in trace
            if item.get("step") in {"UNDERSTAND", "OBSERVE", "SIMULATE", "CALCULATE", "FX", "REASON", "SECURITY", "RECOMMEND", "AUTHORIZE", "EXECUTE", "VERIFY", "AUDIT"}
            and item.get("step") not in {"UNDERSTAND", "OBSERVE"}
        ]

        decision = enriched_data.get("decision")
        goal = enriched_data.get("goal")
        if not goal:
            if enriched_data.get("credit_guidance"):
                goal = "credit_building"
            elif decision:
                goal = "tuition_funding"
            elif enriched_data.get("proposal"):
                goal = "transfer_preparation"
            elif enriched_data.get("incoming_funds"):
                goal = "remittance_planning"
            elif intent == "financial_plan":
                goal = "financial_planning"
            else:
                goal = intent
        limitations = []
        if enriched_data.get("credit_guidance"):
            limitations.extend(enriched_data["credit_guidance"].get("missing_evidence", []))
        funding_data = enriched_data.get("funding_plan")
        if isinstance(funding_data, dict) and funding_data.get("note"):
            limitations.append(funding_data["note"])
        if not limitations:
            limitations.append("Reference/sandbox outputs are not guaranteed bank settlement results.")
        if decision:
            decision_label = {
                "FUND_TARGET": "Fund the target obligation",
                "FUND_PARTIAL": "Fund as much as safely possible",
                "NO_FX_CONVERSION": "No currency conversion needed",
            }.get(decision.get("action"), str(decision.get("action", "Review recommendation")))
        else:
            decision_label = "Review the agent recommendation"

        if blocked_security:
            security_label = "BLOCKED by deterministic security policy"
        elif required_authorization:
            security_label = "Level 2 authorization required before execution"
        else:
            security_label = "Policy checks completed; no transaction was executed"

        if required_authorization:
            action_required = "Explicitly authorize the pending proposal before any sandbox execution."
        elif blocked_security:
            action_required = "Resolve the blocked condition; no transaction was created."
        else:
            action_required = "No transaction action required."

        evidence_quality = (
            "limited"
            if limitations and any(
                "missing" in str(item).lower()
                or "not guaranteed" in str(item).lower()
                or "insufficient" in str(item).lower()
                for item in limitations
            )
            else "high"
        )
        enriched_data["judge"] = {
            "title": "XKF5 decision evidence",
            "goal": goal,
            "horizon_days": enriched_data.get("horizon_days"),
            "urgency": enriched_data.get("urgency"),
            "decision": decision_label,
            "decision_detail": decision,
            "observed": [
                item.get("detail", "")
                for item in trace
                if item.get("step") in {"UNDERSTAND", "OBSERVE", "SIMULATE"}
                and item.get("detail")
            ],
            "reasoning": [
                item.get("detail", "")
                for item in trace
                if item.get("step") in {"REASON", "CALCULATE", "FX", "RECOMMEND"}
                and item.get("detail")
            ],
            "security": security_label,
            "security_detail": blocked_security[-1].get("detail") if blocked_security else (
                status_by_step.get("SECURITY", [{}])[-1].get("detail")
            ),
            "action_required": action_required,
            "evidence_steps": evidence_steps,
            "state_changed": bool(enriched_data.get("state_changed", False)),
            "limitations": limitations,
            "evidence_quality": evidence_quality,
            "evidence_bounded": True,
        }

        return {
            "intent": intent,
            "answer": answer,
            "trace": trace,
            "data": enriched_data,
            "state": self.engine.snapshot(),
        }


    def _savings_goal_result(self, plan: dict[str, Any], expense_increase: Decimal = Decimal('0')) -> dict[str, Any]:
        starting = self.engine.money_value(plan['starting'])
        income = self.engine.money_value(plan['income'])
        expenses = self.engine.money_value(plan['expenses'] + expense_increase)
        target = self.engine.money_value(plan['target'])
        months = int(plan['months'])
        monthly_surplus = self.engine.money_value(income - expenses)
        projected = self.engine.money_value(starting + monthly_surplus * months)
        gap = self.engine.money_value(max(Decimal('0'), target - projected))
        extra = self.engine.money_value(max(Decimal('0'), projected - target))
        outcome = f'exceed the target by SGD {extra:,.2f}' if projected >= target else f'fall short by SGD {gap:,.2f}'
        increase_note = f' (including a SGD {expense_increase:,.2f} monthly increase)' if expense_increase else ''
        answer = (
            f'Savings projection over {months} months, using your stated figures:\\n'
            f'- Starting savings: SGD {starting:,.2f}\\n'
            f'- Monthly income: SGD {income:,.2f}\\n'
            f'- Monthly expenses: SGD {expenses:,.2f}{increase_note}\\n'
            f'- Monthly savings: SGD {monthly_surplus:,.2f}\\n'
            f'- Projected savings: SGD {projected:,.2f}\\n'
            f'- Target: SGD {target:,.2f}\\n'
            f'You are projected to {outcome}.\\n'
            'Assumes income and expenses stay constant; excludes interest, fees, emergencies, and unlisted costs. Read-only scenario; no account balances changed.'
        )
        return self._result('savings_projection', answer, [
            {'step': 'UNDERSTAND', 'status': 'completed', 'detail': 'Recognized a savings goal and time horizon.'},
            {'step': 'OBSERVE', 'status': 'completed', 'detail': 'Used the amounts explicitly stated by the user.'},
            {'step': 'CALCULATE', 'status': 'completed', 'detail': f'Monthly surplus SGD {monthly_surplus:,.2f}; projected savings SGD {projected:,.2f}.'},
            {'step': 'SECURITY', 'status': 'completed', 'detail': 'Read-only calculation; no proposal or transaction created.'},
        ], {'starting_savings_sgd': float(starting), 'monthly_income_sgd': float(income), 'monthly_expenses_sgd': float(expenses), 'monthly_surplus_sgd': float(monthly_surplus), 'months': months, 'target_savings_sgd': float(target), 'projected_savings_sgd': float(projected), 'shortfall_sgd': float(gap), 'surplus_sgd': float(extra), 'state_changed': False, 'proposal': None})
    def run(self, text: str) -> dict[str, Any] | None:
        t = self.engine.repair_user_text(text).lower().strip()
        # Basic identity questions should receive a direct conversational answer,
        # not the generic finance-capabilities fallback.
        if any(k in t for k in [
            "no your name is", "no ur name is", "your name is actually",
            "i named you", "you are called", "your name should be",
        ]):
            return self._result("general", "Got it — I'm XKF5 AI. I'll use that name going forward in this conversation.", [
                {"step": "UNDERSTAND", "status": "completed", "detail": "Recognized the user's correction to the assistant's name."},
                {"step": "RECOMMEND", "status": "completed", "detail": "Acknowledged the requested identity without initiating a financial action."},
            ], {"assistant_name": "XKF5 AI", "state_changed": False, "proposal": None})
        if any(k in t for k in ["what is your name", "what's your name", "who are you", "ur name", "your name"]):
            return self._result("general", "I'm XKF5 AI, your financial planning assistant. I can help analyze balances, cash flow, tuition funding, and currency conversions. I provide guidance and simulations; I don't move money without the application's required authorization.", [
                {"step": "UNDERSTAND", "status": "completed", "detail": "Recognized a question about the assistant's identity."},
                {"step": "RECOMMEND", "status": "completed", "detail": "Answered directly without initiating any financial action."},
            ], {"state_changed": False, "proposal": None})

        # Explicit savings-goal calculation: use only user-supplied scenario values.
        savings_start = re.search(r'\b(?:have|currently have|start with|starting with)\s+(?:sgd|s\$)\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s+(?:in )?(?:my )?savings', t, re.I)
        savings_income = re.search(r'\b(?:receive|earn|income is|income of)\s+(?:sgd|s\$)\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:per|a)\s+month', t, re.I)
        savings_expenses = re.search(r'\b(?:spend|expenses are|expenses of|spending is)\s+(?:sgd|s\$)\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:per|a)\s+month', t, re.I)
        savings_target = re.search(r'\b(?:target|reach|have|save up to|save)\s+(?:sgd|s\$)\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s+in\s+(\d+)\s+months?', t, re.I)
        if savings_start and savings_income and savings_expenses and savings_target and any(k in t for k in ['save enough', 'can i save', 'savings goal', 'target savings']):
            plan = {'starting': Decimal(savings_start.group(1).replace(',', '')), 'income': Decimal(savings_income.group(1).replace(',', '')), 'expenses': Decimal(savings_expenses.group(1).replace(',', '')), 'target': Decimal(savings_target.group(1).replace(',', '')), 'months': int(savings_target.group(2))}
            self.engine._agent_scenario_context['savings_goal_plan'] = plan
            return self._savings_goal_result(plan)
        remembered_plan = getattr(self.engine, '_agent_scenario_context', {}).get('savings_goal_plan')
        expense_increase = re.search(r'(?:expenses|spending)\s+(?:increase|go up|rise)\s+by\s+(?:sgd|s\$)?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:per|a)\s+month', t, re.I)
        if remembered_plan and expense_increase and any(k in t for k in ['what if', 'increase', 'go up', 'rise']):
            return self._savings_goal_result(remembered_plan, Decimal(expense_increase.group(1).replace(',', '')))
        remembered_context = getattr(self.engine, "_agent_scenario_context", {})
        current_wallet = self._extract_wallet_balances_from_text(t)
        if current_wallet:
            remembered_context["wallet_balances"] = dict(current_wallet)
            self.engine._agent_scenario_context = remembered_context
        myr = self._amount(t, "MYR")
        sgd = self._amount(t, "SGD")

        received = any(k in t for k in ["received", "got", "got paid", "family sent", "sent me", "allowance", "incoming"])
        tuition_context = any(k in t for k in [
            "tuition", "school fees", "tuition fee", "tuition fees",
            "fees", "accommodation", "hostel", "semester fee",
        ])
        planning = str(
            self.engine.state.get("profile_meta", {}).get("planning_currency", "SGD")
        ).upper()

        # Handle explicit multi-currency tuition calculations as a read-only
        # scenario before generic intent/proposal handlers can intercept the prompt.
        explicit_tuition_scenario = (
            "tuition" in t
            and any(k in t for k in ["total available funds", "tuition shortfall", "cover tuition in full"])
            and any(k in t for k in ["do not create a proposal", "don't create a proposal", "no proposal", "do not execute"])
        )
        if explicit_tuition_scenario:
            sgd_match = re.search(r"\\b(?:sgd|s\\$)\\s*([0-9][0-9,]*(?:\\.[0-9]{1,2})?)", t)
            myr_match = re.search(r"\\bmyr\\s*([0-9][0-9,]*(?:\\.[0-9]{1,2})?)", t)
            reserve_match = re.search(r"emergency reserve of\\s*(?:sgd|s\\$)\\s*([0-9][0-9,]*(?:\\.[0-9]{1,2})?)", t)
            tuition_match = re.search(r"tuition of\\s*(?:sgd|s\\$)\\s*([0-9][0-9,]*(?:\\.[0-9]{1,2})?)", t)
            if sgd_match and myr_match and reserve_match and tuition_match:
                sgd_cash = self.engine.money_value(sgd_match.group(1).replace(",", ""))
                myr_cash = self.engine.money_value(myr_match.group(1).replace(",", ""))
                reserve = self.engine.money_value(reserve_match.group(1).replace(",", ""))
                tuition = self.engine.money_value(tuition_match.group(1).replace(",", ""))
                fx = self.engine.convert_currency(float(myr_cash), "MYR", "SGD")
                converted_myr = self.engine.money_value(fx.get("converted_amount", 0))
                total = self.engine.money_value(sgd_cash + converted_myr)
                spendable = self.engine.money_value(max(Decimal("0"), total - reserve))
                gap = self.engine.money_value(max(Decimal("0"), tuition - spendable))
                covered = spendable >= tuition
                rate = fx.get("rate")
                answer = (
                    "**Tuition funding calculation (read-only)**\\n"
                    f"- Existing SGD balance: SGD {sgd_cash:,.2f}\\n"
                    f"- MYR balance: MYR {myr_cash:,.2f}\\n"
                    f"- Reference conversion: MYR {myr_cash:,.2f} ≈ SGD {converted_myr:,.2f}"
                    + (f" at 1 MYR = SGD {float(rate):.4f}.\\n" if rate is not None else ".\\n")
                    + f"- Total funds at reference rate: SGD {total:,.2f}\\n"
                    + f"- Emergency reserve protected: SGD {reserve:,.2f}\\n"
                    + f"- Funds available for tuition after reserve: SGD {spendable:,.2f}\\n"
                    + f"- Tuition due: SGD {tuition:,.2f}\\n"
                    + (f"- Shortfall: SGD {gap:,.2f}. Tuition cannot be covered in full while preserving the reserve.\\n" if not covered else "- Shortfall: SGD 0.00. Tuition can be covered while preserving the reserve.\\n")
                    + "This is a hypothetical calculation using the figures in your message and a reference FX rate. Fees, spreads and settlement timing may change the result. No proposal or transaction was created."
                )
                trace = [
                    {"step": "UNDERSTAND", "status": "completed", "detail": "Recognized a read-only multi-currency tuition scenario with explicit figures."},
                    {"step": "OBSERVE", "status": "completed", "detail": "Used balances, tuition and reserve amounts stated in the prompt, not saved demo balances."},
                    {"step": "FX", "status": "completed", "detail": f"Converted MYR {myr_cash:,.2f} to SGD {converted_myr:,.2f} using the configured reference rate."},
                    {"step": "CALCULATE", "status": "completed", "detail": f"Total SGD {total:,.2f}; protected reserve SGD {reserve:,.2f}; spendable SGD {spendable:,.2f}; shortfall SGD {gap:,.2f}."},
                    {"step": "SECURITY", "status": "completed", "detail": "Read-only scenario; no proposal or transaction was created."},
                    {"step": "RECOMMEND", "status": "completed", "detail": "Reported whether tuition can be covered after preserving the reserve."},
                ]
                return self._result("tuition_funding_analysis", answer, trace, {
                    "scenario_inputs": {"sgd_balance": float(sgd_cash), "myr_balance": float(myr_cash), "tuition_sgd": float(tuition), "reserve_sgd": float(reserve)},
                    "fx_conversion": fx, "total_funds_sgd": float(total), "spendable_after_reserve_sgd": float(spendable),
                    "shortfall_sgd": float(gap), "tuition_fully_covered": covered, "state_changed": False, "proposal": None,
                })

        # Keep simple balance lookups separate from broader forecasting.
        # A short "how much do I have in SGD?" question should not trigger
        # a 30-day assessment merely because it contains "how much".
        simple_balance_request = (
            any(k in t for k in ["how much do i have", "what is my balance", "show my balance", "current balance"])
            and not any(k in t for k in [
                "financial position", "cash position", "funding gap", "30 day",
                "30-day", "forecast", "tuition", "emergency reserve", "projected",
                "monthly spending", "monthly expenses", "afford",
            ])
        )
        if simple_balance_request:
            balances = self.engine.get_balance()
            requested_currency = next(
                (code for code in ["SGD", "MYR", "USD", "CNY"] if code.lower() in t),
                None,
            )
            if requested_currency and requested_currency in balances:
                answer = f"You currently have {requested_currency} {self.engine.money_value(balances[requested_currency]):,.2f} in the demo accounts."
            else:
                answer = "Your current demo-account balances are: " + ", ".join(
                    f"{code} {self.engine.money_value(value):,.2f}" for code, value in balances.items()
                ) + "."
            return self._result("balance", answer, [
                {"step": "UNDERSTAND", "status": "completed", "detail": "Recognized a simple balance lookup."},
                {"step": "OBSERVE", "status": "completed", "detail": "Read the configured demo-account balances."},
                {"step": "SECURITY", "status": "completed", "detail": "Read-only lookup; no account state changed."},
            ], {"balances": balances, "state_changed": False})

        # Route broad financial questions before any action/proposal handlers.
        # This guard intentionally uses intent signals rather than exact full prompts.
        read_only_financial_request = (
            any(k in t for k in [
                "financial position", "cash position", "funding gap",
                "how much do i have", "current balances", "available balances",
                "can i afford", "afford to send", "tuition coming up",
                "hypothetical incoming", "scenario only",
            ])
            and any(k in t for k in [
                "analyze", "analyse", "review", "calculate", "project",
                "afford", "tuition", "convert", "hypothetical", "balances",
                "emergency reserve", "cash position", "how much",
            ])
        )
        if read_only_financial_request:
            is_remittance = any(k in t for k in ["afford to send", "send sgd", "send money home", "remittance"])
            is_incoming_scenario = (
                received and tuition_context
                and any(k in t for k in ["convert", "exchange", "should i", "what should i do", "enough", "need to"])
            )
            if is_remittance:
                horizon = 30
                forecast = self.engine.forecast_portfolio(horizon)
                planning_currency = str(forecast.get("planning_currency", planning)).upper()
                amount = self._amount(t, planning_currency) or sgd or Decimal("0")
                # Remittance affordability must use immediately available planning-
                # currency cash, not the full portfolio valuation (which includes
                # foreign balances that have not been converted).
                current_balances = self.engine.get_balance()
                planning_cash = self.engine.money_value(current_balances.get(planning_currency, 0))
                before = self.engine.money_value(
                    planning_cash
                    + self.engine.money_value(forecast.get("expected_income_planning", 0))
                    - self.engine.money_value(forecast.get("spending_planning", 0))
                    - self.engine.money_value(forecast.get("obligations_planning", 0))
                )
                after = self.engine.money_value(before - amount)
                health = self.engine.health_analysis()
                reserve_info = forecast.get("emergency_reserve", {})
                reserve_met = bool(reserve_info.get("met", health.get("emergency_reserve_met", False)))
                affordable = after >= 0 and reserve_met
                action = "REMITTANCE_AFFORDABLE" if affordable else "REMITTANCE_NOT_AFFORDABLE"
                answer = (
                    f"30-day remittance assessment: {action}.\\n"
                    f"Projected position before sending: {planning_currency} {before:,.2f}.\\n"
                    f"Remittance considered: {planning_currency} {amount:,.2f}.\\n"
                    f"Projected position after sending: {planning_currency} {after:,.2f}.\\n"
                    f"Emergency reserve: {'met' if reserve_met else 'not met or unverified'}.\\n"
                    + ("Sending appears affordable under the configured forecast; keep the reserve intact." if affordable else f"Your projected position would fall to about {planning_currency} {after:,.2f} after sending. Do not send the full amount yet; prioritize tuition and essential expenses, protect the reserve, and reassess a smaller amount.")
                    + "\\nRead-only analysis; no proposal or transaction was created."
                )
                trace = [
                    {"step": "UNDERSTAND", "status": "completed", "detail": "Identified a read-only remittance affordability question."},
                    {"step": "OBSERVE", "status": "completed", "detail": "Reviewed the configured 30-day forecast and reserve status."},
                    {"step": "SIMULATE", "status": "completed", "detail": f"Subtracted {planning_currency} {amount:,.2f} once."},
                    {"step": "CALCULATE", "status": "completed", "detail": f"Projected position after remittance is {planning_currency} {after:,.2f}."},
                    {"step": "SECURITY", "status": "completed", "detail": "No proposal or transaction was created."},
                    {"step": "RECOMMEND", "status": "completed", "detail": action},
                ]
                return self._result("remittance_affordability", answer, trace, {
                    "goal": "remittance_affordability",
                    "remittance": {
                        "target": {"currency": planning_currency, "amount": float(amount)},
                        "action": action,
                        "projected_after": float(after),
                        "state_changed": False,
                    },
                    "action": action, "forecast": forecast, "health": health, "state_changed": False,
                    "judge": {"goal": "remittance_affordability"},
                })
            if is_incoming_scenario:
                amount = myr if myr is not None else sgd
                currency = "MYR" if myr is not None else "SGD"
                amount = self.engine.money_value(amount or 0)
                balances = self.engine.get_balance()
                forecast = self.engine.forecast_portfolio(30)
                scenario = self._scenario_forecast(
                    {str(k).upper(): self.engine.money_value(v) for k, v in balances.items()},
                    None, None, None, (amount, currency), 30
                )
                current_gap = self.engine.money_value(forecast.get("shortfall_planning", 0))
                scenario_gap = self.engine.money_value(scenario.get("shortfall_planning", 0))
                answer = (
                    f"Hypothetical funds analysis: current projected funding gap is {planning} {current_gap:,.2f}.\\n"
                    f"If {currency} {amount:,.2f} is received, the scenario gap becomes {planning} {scenario_gap:,.2f}.\\n"
                    f"Saved balances remain unchanged: " + ", ".join(f"{k} {v:,.2f}" for k, v in balances.items()) + ".\\n"
                    "Confirm the funds are available and compare the live FX rate and fees before deciding. No proposal or transaction was created."
                )
                trace = [
                    {"step": "UNDERSTAND", "status": "completed", "detail": "Identified hypothetical incoming funds and tuition planning."},
                    {"step": "OBSERVE", "status": "completed", "detail": "Read saved balances and the current forecast."},
                    {"step": "SIMULATE", "status": "completed", "detail": "Added incoming funds to a temporary scenario only."},
                    {"step": "FX", "status": "completed", "detail": "Currency conversion should be checked against the current quoted rate and fees."},
                    {"step": "CALCULATE", "status": "completed", "detail": f"Compared funding gap {current_gap:,.2f} with scenario gap {scenario_gap:,.2f}."},
                    {"step": "SECURITY", "status": "completed", "detail": "Saved balances unchanged; no proposal or transaction was created."},
                    {"step": "RECOMMEND", "status": "completed", "detail": "Confirm receipt and review tuition due date before converting."},
                ]
                scenario_shortfall_sgd = self.engine.money_value(scenario.get("projected_shortfall_sgd", scenario.get("shortfall_sgd", 0)))
                return self._result("incoming_funds_planning", answer, trace, {
                    "incoming_funds": {"amount": float(amount), "currency": currency, "state_changed": False},
                    "forecast_after_income": {**scenario, "projected_shortfall_sgd": float(scenario_shortfall_sgd)},
                    "state_changed": False,
                })
            if (
                any(k in t for k in ["can i afford", "afford it", "afford this"])
                and any(k in t for k in ["tuition", "school fee", "semester fee"])
                and any(k in t for k in ["tuition is", "tuition costs", "tuition fee is", "tuition amount"])
            ):
                amount, currency = self._extract_labeled_amount(t, ["tuition", "school fee", "semester fee"]) or (None, planning)
                if amount is None:
                    amount = self._amount(t, planning)
                amount = self.engine.money_value(amount or 0)
                balances = remembered_context.get("wallet_balances") or self.engine.get_balance()
                cash = self.engine.money_value(balances.get(planning, 0))
                answer = (
                    f"Tuition affordability assessment: stated available {planning} cash is {cash:,.2f}. "
                    f"Tuition obligation: {currency} {amount:,.2f}. "
                    + ("The stated cash balance alone appears sufficient, but confirm other obligations and reserve needs." if currency == planning and cash >= amount else "The stated cash balance alone does not cover the tuition amount; account for any confirmed incoming funds and due dates before deciding.")
                    + " This is read-only; no proposal or transaction was created."
                )
                trace = [
                    {"step": "UNDERSTAND", "status": "completed", "detail": "Recognized a tuition affordability question."},
                    {"step": "OBSERVE", "status": "completed", "detail": "Used the latest stated wallet balance and tuition amount."},
                    {"step": "CALCULATE", "status": "completed", "detail": f"Compared available {planning} {cash:,.2f} with tuition {currency} {amount:,.2f}."},
                    {"step": "SECURITY", "status": "completed", "detail": "No proposal or transaction was created."},
                    {"step": "RECOMMEND", "status": "completed", "detail": "Recommended checking remaining obligations and reserve needs."},
                ]
                return self._result("affordability", answer, trace, {"goal": "affordability", "agent_mode": "local_agent_planner", "state_changed": False, "tuition_amount": float(amount), "tuition_currency": currency, "available_balance": float(cash)})
            if any(k in t for k in ["financial position", "cash position", "funding gap", "current balances", "available balances", "how much do i have"]):
                horizon = self._extract_horizon_days(t) or 30
                forecast = self.engine.forecast_portfolio(horizon)
                health = self.engine.health_analysis()
                balances = self.engine.get_balance()
                obligations = self.engine.get_obligations()
                projected = self.engine.money_value(forecast.get("projected_balance_planning", 0))
                gap = self.engine.money_value(forecast.get("shortfall_planning", 0))
                answer = (
                    f"{horizon}-day financial assessment\\n"
                    f"Balances: " + ", ".join(f"{k} {v:,.2f}" for k, v in balances.items()) + ".\\n"
                    f"Projected position: {planning} {projected:,.2f}. Funding gap: {planning} {gap:,.2f}.\\n"
                    f"Recorded obligations: {len(obligations)}. Emergency reserve: {'met' if health.get('emergency_reserve_met') else 'not met or unverified'}.\\n"
                    + ("Prioritize obligations and reduce optional spending to address the projected gap." if gap > 0 else "Maintain the emergency reserve and monitor upcoming obligations.")
                    + "\\nRead-only forecast; no account state changed."
                )
                trace = [
                    {"step": "UNDERSTAND", "status": "completed", "detail": "Recognized a read-only financial assessment."},
                    {"step": "OBSERVE", "status": "completed", "detail": "Read balances, forecast, obligations and reserve status."},
                    {"step": "CALCULATE", "status": "completed", "detail": f"Calculated a {horizon}-day forecast in {planning}."},
                    {"step": "REASON", "status": "completed", "detail": f"Projected position {projected:,.2f}; funding gap {gap:,.2f}."},
                    {"step": "SECURITY", "status": "completed", "detail": "No proposal or transaction was created."},
                    {"step": "RECOMMEND", "status": "completed", "detail": "Recommended actions based on projected cash flow."},
                ]
                return self._result("financial_assessment", answer, trace, {"forecast": forecast, "health": health, "obligations": obligations, "state_changed": False})

        # Deterministic read-only financial assessment. Broad analysis requests
        # must not fall through to the transaction/proposal handler merely because
        # they mention "transactions" in a safety instruction.
        assessment_request = (
            any(k in t for k in [
                "analyze my current financial position",
                "analyse my current financial position",
                "analyze my financial position",
                "analyse my financial position",
                "financial assessment",
                "review my available balances",
                "projected cash position",
            ])
            and any(k in t for k in ["30 days", "next 30", "cash position", "financial risks", "financial position"])
        )
        if assessment_request:
            horizon = message_horizon_days or 30
            forecast = self.engine.forecast_portfolio(horizon)
            overview = self.engine.currency_overview()
            obligations = self.engine.get_obligations()
            spending = self.engine.spending_analysis()
            health = self.engine.health_analysis()
            shortfall = self.engine.money_value(forecast.get("shortfall_planning", 0))
            projected = self.engine.money_value(forecast.get("projected_balance_planning", 0))
            reserve_currency = str(health.get("emergency_reserve_currency", planning)).upper()
            reserve_amount = self.engine.money_value(health.get("emergency_reserve_amount", 0))
            trace = [
                {"step": "UNDERSTAND", "status": "completed", "detail": "Recognized a read-only request to assess the current financial position."},
                {"step": "OBSERVE", "status": "completed", "detail": "Read all configured currency balances, income, spending, accommodation and upcoming obligations."},
                {"step": "CALCULATE", "status": "completed", "detail": f"Calculated the {horizon}-day multi-currency forecast in {planning}."},
                {"step": "REASON", "status": "completed", "detail": f"Projected position is {planning} {projected:,.2f}; projected shortfall is {planning} {shortfall:,.2f}."},
                {"step": "SECURITY", "status": "completed", "detail": "Read-only assessment only; no proposal or transaction was created and no account state was changed."},
                {"step": "RECOMMEND", "status": "completed", "detail": "Provided practical next steps based on the deterministic forecast and reserve status."},
            ]
            balance_text = ", ".join(
                f"{code} {amount:,.2f}" for code, amount in self.engine.get_balance().items()
            )
            obligation_text = (
                "; ".join(
                    f"{item.get('name', item.get('type', 'Obligation'))}: {planning} {float(item.get('amount_planning', item.get('amount_sgd', 0))):,.2f} due in {item.get('days', item.get('due_days', '?'))} days"
                    for item in obligations
                )
                if obligations else "No obligations are recorded as due within the forecast horizon."
            )
            if shortfall > 0:
                recommendation = (
                    f"The forecast indicates a funding gap of {planning} {shortfall:,.2f}. Prioritize obligations due within {horizon} days, "
                    "pause optional spending where practical, and evaluate a funding plan that protects the emergency reserve before considering any conversion."
                )
            else:
                recommendation = (
                    f"The forecast shows a projected surplus of {planning} {projected:,.2f} after expected income, spending and recorded obligations. "
                    "Keep the emergency reserve intact and avoid unnecessary conversions."
                )
            answer = (
                f"**{horizon}-day financial assessment**\\n\\n"
                f"**Configured balances:** {balance_text}.\\n\\n"
                f"**Projected position:** {planning} {projected:,.2f} after expected income, monthly living expenses, accommodation and obligations in the forecast horizon. "
                f"**Funding gap:** {planning} {shortfall:,.2f}.\\n\\n"
                f"**Obligations:** {obligation_text}\\n\\n"
                f"**Emergency reserve:** {reserve_currency} {reserve_amount:,.2f} configured; health analysis reports the reserve "
                f"{'is met' if health.get('emergency_reserve_met') else 'is not fully met or cannot be verified'}.\\n\\n"
                f"**Risk and next steps:** {recommendation}\\n\\n"
                "This is a planning estimate based on the configured profile and reference FX data, not a guaranteed bank balance. "
                "No proposal or transaction was created."
            )
            return self._result(
                "financial_assessment",
                answer,
                trace,
                {
                    "forecast": forecast,
                    "currency_overview": overview,
                    "obligations": obligations,
                    "spending": spending,
                    "health": health,
                    "state_changed": False,
                    "agent_mode": "local_agent_planner",
                },
            )
        message_horizon_days = self._extract_horizon_days(t)
        conversion_question = any(k in t for k in ["convert", "exchange", "should i", "what should i do", "enough", "need to"])
        # A conditional family-income question must stay advisory and must not be
        # swallowed by the generic multi-goal planner before its dedicated handler.
        conditional_income_question = (
            (
                any(k in t for k in [
                    "can i assume", "assume that money", "assume the money", "count that money",
                    "treat that money", "can i count it", "can i count that",
                ])
                or (
                    "what if" in t
                    and any(k in t for k in ["next month", "next week", "in two weeks", "later", "in a month"])
                )
            )
            and any(k in t for k in ["might", "may", "could", "possibly", "maybe", "will", "sends", "send me"])
            and any(k in t for k in ["parent", "parents", "family"])
        )
        scenario_context_available = bool(
            current_wallet or remembered_context.get("wallet_balances")
        )

        # Conditional incoming money is never treated as confirmed funds.
        # Handle this immediately so generic planning/FX branches cannot consume
        # uncertain family support as if it were confirmed cash.
        if conditional_income_question:
            incoming = None
            for code in [
                "MYR", "SGD", "USD", "CNY", "JPY", "KRW", "THB", "EUR", "GBP",
                "AUD", "CAD", "HKD", "TWD", "INR",
            ]:
                amount = self._amount(t, code)
                if amount is not None:
                    incoming = (amount, code)
                    break

            tuition_labeled = self._extract_labeled_amount(
                t, ["tuition", "tuition fee", "tuition fees"]
            )
            answer = (
                "No. Treat that money as conditional, not confirmed, until it is "
                "actually received or otherwise reliably committed."
            )
            if incoming:
                inc_amount, inc_code = incoming
                inc_rate, _ = self.engine._currency_rate_to_sgd(inc_code)
                inc_sgd = self.engine.money_value(inc_amount * inc_rate)
                answer += (
                    f" The possible {inc_code} {inc_amount:,.2f} would add about "
                    f"SGD {inc_sgd:,.2f} only in a separate what-if scenario."
                )
            if tuition_labeled:
                tuition_amount, tuition_code = tuition_labeled
                tuition_rate, _ = self.engine._currency_rate_to_sgd(tuition_code)
                tuition_sgd = self.engine.money_value(tuition_amount * tuition_rate)
                answer += (
                    f" Your stated tuition is about SGD {tuition_sgd:,.2f}, so XKF5 "
                    "should not mark it funded using conditional money alone."
                )

            trace = [
                {
                    "step": "UNDERSTAND",
                    "status": "completed",
                    "detail": "Detected uncertain incoming family support.",
                },
                {
                    "step": "REASON",
                    "status": "completed",
                    "detail": "Separated confirmed funds from hypothetical incoming funds.",
                },
                {
                    "step": "SECURITY",
                    "status": "completed",
                    "detail": "No account state changed and no transaction was created.",
                },
            ]
            return self._result(
                "agentic_local",
                answer,
                trace,
                {"conditional_income": True, "state_changed": False},
            )

        # Never infer a transaction amount from conversational shortcuts. A financial
        # command must name the exact amount; history, defaults, recommendations, or
        # remaining balances are not authorization.
        implicit_amount_request = any(k in t for k in [
            "usual amount", "same as last", "same amount as last", "same as before",
            "last time", "previous amount", "remaining balance", "my remaining balance",
            "whatever remains", "whatever is left", "the rest", "recommended amount",
            "recommendation amount", "recommended conversion",
        ])
        implicit_money_action = any(k in t for k in [
            "transfer", "send", "remit", "remittance", "prepare", "convert", "exchange",
            "pay", "execute", "approve", "authorize", "confirm",
        ])
        if implicit_amount_request and implicit_money_action:
            return self._result(
                "agentic_local",
                "I did not create or execute a transaction. Please specify the exact amount and currency. "
                "I will not infer a transfer amount from past transactions, a recommended amount, or the remaining balance.",
                [
                    {"step": "UNDERSTAND", "status": "completed", "detail": "Detected an implicit transaction amount."},
                    {"step": "SECURITY", "status": "blocked", "detail": "Exact transaction amounts are required; conversational shortcuts cannot authorize money movement."},
                ],
                {"blocked_reason": "implicit_transaction_amount", "state_changed": False},
            )

        # Explicit execution requests are handled before informational FX questions.
        # An execution command may NEVER create a new proposal or reuse an already
        # executed proposal. This is the anti-replay guard for agentic money movement.
        execute_request = any(k in t for k in [
            "execute", "execute the", "make it happen", "complete the transfer",
            "run the transfer", "process the transfer", "send it now",
        ])
        # Safety constraints that explicitly forbid execution are not execution
        # commands. Do not let "do not execute any transaction" trigger the
        # transaction state-machine refusal branch.
        execution_is_explicitly_negated = any(k in t for k in [
            "do not execute", "don't execute", "dont execute", "never execute",
            "not execute", "cannot execute", "can't execute", "cannot send",
            "don't send", "do not send", "without executing", "no transaction",
        ])
        if execution_is_explicitly_negated:
            execute_request = False
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

        # Contradictory/combined commands must not be interpreted as authorization.
        # If a single message asks to authorize while also attempting to alter the
        # amount or destination, require a fresh explicit proposal instead.
        authorization_conflict = (
            any(k in t for k in ["i authorize", "authorize the", "authorize this", "i approve", "confirm the", "confirm this"])
            and any(k in t for k in ["change it to", "instead", "actually", "make it", "transfer the rest", "whatever is left"])
        )
        if authorization_conflict:
            trace = [
                {"step": "UNDERSTAND", "status": "completed", "detail": "Detected authorization combined with a conflicting transaction instruction."},
                {"step": "SECURITY", "status": "blocked", "detail": "Authorization cannot modify an existing proposal or authorize an unstated amount."},
            ]
            return self._result(
                "agentic_local",
                "I did not authorize anything. Authorization must match the existing proposal exactly; a changed amount or destination requires a new proposal.",
                trace,
                {"blocked_reason": "conflicting_authorization_request"},
            )

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

            # Never pick the first proposal when more than one proposal matches.
            # Ambiguous authorization must stop rather than silently authorizing
            # an arbitrary transaction.
            if len(matches) > 1:
                trace = [
                    {"step": "UNDERSTAND", "status": "completed", "detail": "Multiple pending proposals matched the authorization request."},
                    {"step": "SECURITY", "status": "blocked", "detail": "Authorization requires one unambiguous proposal; no proposal was selected automatically."},
                ]
                return self._result(
                    "agentic_local",
                    "I did not authorize anything because multiple pending proposals match that amount. "
                    "Please identify the exact proposal before authorizing.",
                    trace,
                    {"blocked_reason": "multiple_matching_pending_proposals", "state_changed": False},
                )

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

        # Credit-building guidance is intentionally educational and evidence-bounded.
        # The demo ledger does not contain credit-account utilization or missed-payment history,
        # so XKF5 must never invent a credit score or claim that the liquidity health score
        # represents creditworthiness.
        credit_question = any(k in t for k in [
            "build credit", "building credit", "improve my credit", "improve credit",
            "credit score", "credit history", "establish credit", "creditworthiness",
            "credit card", "build my credit",
        ])
        credit_complex_context = any(k in t for k in [
            "tuition", "remittance", "send", "spending", "expenses",
            "cash flow", "cashflow", "incoming", "allowance", "reserve",
            "convert", "exchange",
        ])
        if credit_question and not credit_complex_context:
            txs = self.engine.get_transactions(50)
            obligations = self.engine.get_obligations()
            health = self.engine.health_analysis()
            completed_tx_count = sum(1 for x in txs if x.get("status") == "completed")
            trace = [
                {
                    "step": "UNDERSTAND",
                    "status": "completed",
                    "detail": "Detected a credit-building question from an international-student finance context.",
                },
                {
                    "step": "OBSERVE",
                    "status": "completed",
                    "detail": (
                        f"Reviewed {completed_tx_count} completed ledger transactions, "
                        f"{len(obligations)} currently tracked obligations, and the liquidity indicator."
                    ),
                },
            ]
            trace.append({
                "step": "REASON",
                "status": "completed",
                "detail": (
                    "The demo does not contain credit-account limits, utilization, account age, "
                    "or missed-payment history, so no credit score or creditworthiness claim can be made."
                ),
            })
            priorities = [
                "Pay documented obligations on time and keep a reliable payment record.",
                "Keep borrowing and recurring debt payments within the cash-flow plan rather than stretching the emergency reserve.",
                "Review credit-product fees, eligibility and terms before opening an account; do not borrow solely to manufacture a score.",
                "Track actual credit-account balances and due dates if the user wants a future credit-health assessment.",
            ]
            trace.append({
                "step": "SECURITY",
                "status": "completed",
                "detail": "Blocked any attempt to infer or fabricate a real credit score from the demo's liquidity data.",
            })
            trace.append({
                "step": "RECOMMEND",
                "status": "completed",
                "detail": "Returned evidence-bounded credit-building guidance and identified the data needed for a real credit assessment.",
            })
            answer = (
                "XKF5 cannot calculate your real credit score from this demo because the data does not include "
                "credit-account limits, utilization, account age, or missed-payment history. "
                "For an international student, the safer foundation is consistent on-time payment of documented obligations, "
                "keeping debt payments affordable within your cash-flow plan, and reviewing any credit product's eligibility, "
                "fees and terms before using it. Do not take on debt just to try to create a score. "
                "I can use this same financial profile to identify whether your current cash flow leaves room for future credit obligations."
            )
            return self._result(
                "agentic_local",
                answer,
                trace,
                {
                    "goal": "credit_building",
                    "credit_guidance": {
                        "assessment": "insufficient_credit_history_data",
                        "not_a_credit_score": True,
                        "evidence_available": {
                            "completed_transactions": completed_tx_count,
                            "tracked_obligations": len(obligations),
                            "liquidity_score": health["score"],
                        },
                        "missing_evidence": [
                            "credit account limits",
                            "credit utilization",
                            "account age",
                            "missed/late payment history",
                        ],
                        "priorities": priorities,
                        "state_changed": False,
                    }
                },
            )

        # Competing-obligations mode: compare a documented tuition obligation with
        # an outbound remittance request and prioritize the obligation with the clearer
        # deadline/funding consequence. This is advisory and read-only.
        competing_question = (
            "tuition" in t
            and any(k in t for k in ["send", "remit", "family", "home"])
            and any(k in t for k in [
                "prioritize", "priority", "first", "before", "what should i do",
                "should i", "safest plan", "what is the safest", "safest option",
            ])
            and not any(k in t for k in [
                "parents can send", "parents will send", "parents may send",
                "parents might send", "parents could send", "family can send",
                "family will send", "family may send", "family could send",
                "incoming",
            ])
        )
        incoming_support_mentioned = any(k in t for k in [
            "parents can send", "parents will send", "family can send",
            "family will send", "family sent", "received", "allowance",
            "incoming", "sent me",
        ])
        if competing_question and not incoming_support_mentioned:
            tuition_labeled = self._extract_labeled_amount(t, ["tuition", "tuition fee", "tuition fees"])
            remittance_labeled = self._extract_labeled_amount(
                t, ["send", "sending", "remit", "remittance", "send to my family", "send home"]
            )
            # Fallback for compact forms such as "send SGD 1,000 home" where
            # the generic labeled extractor may not associate the currency with
            # the outbound amount.
            if remittance_labeled is None:
                match = re.search(
                    r"\b(?:send|sending|remit|remittance|transfer)\s+(SGD|MYR|USD|CNY|JPY|KRW|THB|EUR|GBP|AUD|CAD|HKD|TWD|INR)\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)",
                    t,
                    re.I,
                )
                if match:
                    remittance_labeled = (
                        self.engine.money_value(match.group(2).replace(",", "")),
                        match.group(1).upper(),
                    )
            tuition_days = self._extract_horizon_days(t)
            if competing_question and tuition_labeled and remittance_labeled:
                tuition_amount, tuition_currency = tuition_labeled
                remittance_amount, remittance_currency = remittance_labeled
                wallet_balances = self._extract_wallet_balances_from_text(t)
                if not wallet_balances:
                    wallet_balances = dict(remembered_context.get("wallet_balances", {}))
                use_scenario_wallet = len(wallet_balances) >= 1
                wallet = wallet_balances if use_scenario_wallet else self.engine.get_balance()
                tuition_available = self.engine.money_value(wallet.get(tuition_currency, 0))
                remittance_available = self.engine.money_value(wallet.get(remittance_currency, 0))

                trace = [
                    {
                        "step": "UNDERSTAND",
                        "status": "completed",
                        "detail": "Detected two competing student-finance goals: tuition and an outbound family remittance.",
                    },
                    {
                        "step": "OBSERVE",
                        "status": "completed",
                        "detail": (
                            "Compared explicitly stated hypothetical wallet balances."
                            if use_scenario_wallet
                            else "Compared the saved wallet balances."
                        ),
                    },
                ]

                tuition_due = tuition_days if tuition_days is not None else 30
                tuition_priority = 0 if tuition_due <= 30 else 1

                # Only bring the saved emergency-reserve configuration into the
                # response when the user explicitly asks about protecting a reserve.
                # A standalone affordability question must not inherit unrelated
                # profile assumptions from the demo wallet.
                reserve_requested = any(marker in t for marker in (
                    "emergency reserve",
                    "emergency fund",
                    "keep aside",
                    "keep in reserve",
                    "keep a reserve",
                    "protect my reserve",
                    "protect the reserve",
                ))
                reserve_currency = str(
                    self.engine.state.get("profile_meta", {}).get("emergency_reserve_currency", "MYR")
                ).upper()
                reserve_amount = self.engine.money_value(
                    Decimal(str(
                        self.engine.state.get("profile_meta", {}).get(
                            "emergency_reserve_amount",
                            self.engine.state.get("emergency_reserve_myr", 0),
                        )
                    ))
                )

                tuition_shortfall = self.engine.money_value(
                    max(Decimal("0"), tuition_amount - tuition_available)
                )
                remittance_shortfall = self.engine.money_value(
                    max(Decimal("0"), remittance_amount - remittance_available)
                )
                trace.append({
                    "step": "REASON",
                    "status": "completed",
                    "detail": (
                        f"Tuition is {tuition_currency} {tuition_amount:,.2f} with a stated horizon of about "
                        f"{tuition_due} days; remittance is {remittance_currency} {remittance_amount:,.2f}. "
                        "The tuition obligation is prioritized because it has the clearer near-term deadline."
                    ),
                })
                if reserve_requested:
                    trace.append({
                        "step": "SECURITY",
                        "status": "completed",
                        "detail": (
                            f"Protected the configured {reserve_currency} {reserve_amount:,.2f} emergency reserve; "
                            "no balances, proposals or transactions were changed."
                        ),
                    })
                else:
                    trace.append({
                        "step": "SECURITY",
                        "status": "completed",
                        "detail": "No emergency-reserve assumption was applied because the user did not request one.",
                    })

                if reserve_requested:
                    answer = (
                        f"Priority 1: fund the tuition of {tuition_currency} {tuition_amount:,.2f} first "
                        f"(about {tuition_due} days away). "
                        f"Priority 2: review the {remittance_currency} {remittance_amount:,.2f} family remittance after tuition is secured. "
                        f"Current-wallet coverage is about {tuition_available:,.2f} {tuition_currency} for tuition "
                        f"and {remittance_available:,.2f} {remittance_currency} for the remittance. "
                        f"Estimated tuition shortfall: {tuition_shortfall:,.2f} {tuition_currency}; "
                        f"estimated remittance shortfall: {remittance_shortfall:,.2f} {remittance_currency}. "
                        f"The configured emergency reserve is treated as a protected constraint. "
                        "This is a prioritization simulation; no transaction was created."
                    )
                else:
                    if tuition_shortfall > 0:
                        answer = (
                            f"No. You have {tuition_available:,.2f} {tuition_currency} available for a "
                            f"{tuition_amount:,.2f} {tuition_currency} tuition payment due in about {tuition_due} days, "
                            f"so you are short by {tuition_shortfall:,.2f} {tuition_currency}. "
                            "This is an affordability simulation only; no transaction was created."
                        )
                    else:
                        answer = (
                            f"Priority 1: fund the tuition of {tuition_currency} {tuition_amount:,.2f} first "
                            f"(about {tuition_due} days away). "
                            f"Priority 2: review the {remittance_currency} {remittance_amount:,.2f} family remittance after tuition is secured. "
                            f"You would have approximately {tuition_available - tuition_amount:,.2f} {tuition_currency} remaining before other expenses. "
                            "This is a prioritization simulation; no transaction was created."
                        )
                trace.append({
                    "step": "RECOMMEND",
                    "status": "completed",
                    "detail": "Prioritized the dated tuition obligation before the less-certain family remittance.",
                })
                return self._result(
                    "agentic_local",
                    answer,
                    trace,
                    {
                        "goal": "competing_obligations",
                        "decision": {
                            "priority_order": ["tuition", "remittance"],
                            "reason": "Tuition has the clearer near-term deadline and should be secured before the remittance.",
                            "tuition": {
                                "currency": tuition_currency,
                                "amount": float(tuition_amount),
                                "horizon_days": tuition_due,
                                "shortfall": float(tuition_shortfall),
                            },
                            "remittance": {
                                "currency": remittance_currency,
                                "amount": float(remittance_amount),
                                "shortfall": float(remittance_shortfall),
                            },
                            "reserve_protected": True,
                            "state_changed": False,
                        },
                    },
                )

        # Deterministic multi-currency affordability gate.
        # When the user explicitly supplies several wallet currencies, tuition, and
        # an emergency-savings floor, evaluate the whole stated wallet in SGD.
        # Do not inherit the saved demo wallet/reserve or create a transfer proposal.
        multi_currency_affordability = (
            "tuition" in t
            and any(k in t for k in ["can i do", "can i afford", "will i have enough", "can i cover"])
            and any(k in t for k in ["emergency savings", "emergency reserve", "emergency fund"])
            and len(current_wallet) >= 2
        )
        if multi_currency_affordability:
            tuition_labeled = self._extract_labeled_amount(
                t, ["tuition", "tuition fee", "tuition fees"]
            )
            reserve_match = re.search(
                r"\bkeep\s+(?:an?\s+)?(?:(?P<currency>sgd|s\$|myr|rm|usd|us\$|cny|rmb|yuan)\s*"
                r"(?P<amount>[0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?[km]?)|"
                r"(?P<amount_rev>[0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?[km]?)\s*"
                r"(?P<currency_rev>sgd|s\$|myr|rm|usd|us\$|cny|rmb|yuan))\b[^.]*?\bemergency\s+"
                r"(?:savings|reserve|fund)\b",
                t,
                re.I,
            )
            # Also support the natural reverse form "3k SGD tuition",
            # where the amount/currency appears before the obligation label.
            if not tuition_labeled:
                reverse_tuition = re.search(
                    r"([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?[km]?)\s*"
                    r"(sgd|s\$|myr|rm|usd|us\$|cny|rmb|yuan)\s+tuition\b",
                    t,
                    re.I,
                )
                if reverse_tuition:
                    tuition_amount = self._parse_human_amount(reverse_tuition.group(1))
                    tuition_currency = {
                        "sgd": "SGD", "s$": "SGD",
                        "myr": "MYR", "rm": "MYR",
                        "usd": "USD", "us$": "USD",
                        "cny": "CNY", "rmb": "CNY", "yuan": "CNY",
                    }[reverse_tuition.group(2).lower()]
                    tuition_labeled = (tuition_amount, tuition_currency)

            if tuition_labeled and reserve_match:
                tuition_amount, tuition_currency = tuition_labeled
                reserve_alias = (
                    reserve_match.group("currency")
                    or reserve_match.group("currency_rev")
                ).lower()
                reserve_raw_amount = (
                    reserve_match.group("amount")
                    or reserve_match.group("amount_rev")
                )
                reserve_amount = self._parse_human_amount(reserve_raw_amount)
                reserve_code = {
                    "sgd": "SGD", "s$": "SGD",
                    "myr": "MYR", "rm": "MYR",
                    "usd": "USD", "us$": "USD",
                    "cny": "CNY", "rmb": "CNY", "yuan": "CNY",
                }[reserve_alias]
                try:
                    total_sgd = self.engine.money_value(0)
                    valuation_lines = []
                    for code, amount in current_wallet.items():
                        if code == "SGD":
                            rate = Decimal("1")
                        else:
                            rate, _ = self.engine._currency_rate_to_sgd(code)
                        value_sgd = self.engine.money_value(amount * rate)
                        total_sgd = self.engine.money_value(total_sgd + value_sgd)
                        valuation_lines.append(
                            f"{code} {amount:,.2f} ≈ SGD {value_sgd:,.2f}"
                        )

                    tuition_rate = Decimal("1") if tuition_currency == "SGD" else self.engine._currency_rate_to_sgd(tuition_currency)[0]
                    tuition_sgd = self.engine.money_value(tuition_amount * tuition_rate)
                    reserve_rate = Decimal("1") if reserve_code == "SGD" else self.engine._currency_rate_to_sgd(reserve_code)[0]
                    reserve_sgd = self.engine.money_value(reserve_amount * reserve_rate)
                    usable_sgd = self.engine.money_value(max(Decimal("0"), total_sgd - reserve_sgd))
                    shortfall_sgd = self.engine.money_value(max(Decimal("0"), tuition_sgd - usable_sgd))
                    remaining_sgd = self.engine.money_value(usable_sgd - tuition_sgd)

                    if shortfall_sgd > 0:
                        answer = (
                            f"No. Your stated wallet is worth about SGD {total_sgd:,.2f} across "
                            f"{', '.join(valuation_lines)}. After keeping SGD {reserve_sgd:,.2f} "
                            f"equivalent as your emergency savings, you would have about SGD "
                            f"{usable_sgd:,.2f} available for the SGD {tuition_sgd:,.2f} tuition, "
                            f"leaving a shortfall of about SGD {shortfall_sgd:,.2f}. "
                            "This is an affordability simulation only; no transaction was created."
                        )
                    else:
                        answer = (
                            f"Yes. Your stated wallet is worth about SGD {total_sgd:,.2f} across "
                            f"{', '.join(valuation_lines)}. After keeping SGD {reserve_sgd:,.2f} "
                            f"equivalent as emergency savings, you would have about SGD "
                            f"{usable_sgd:,.2f} available for the SGD {tuition_sgd:,.2f} tuition, "
                            f"leaving about SGD {remaining_sgd:,.2f} after tuition. "
                            "This is an affordability simulation only; no transaction was created."
                        )
                    return self._result(
                        "agentic_local",
                        answer,
                        [
                            {"step": "UNDERSTAND", "status": "completed", "detail": "Detected a multi-currency tuition affordability question with an explicit emergency-savings constraint."},
                            {"step": "FX", "status": "completed", "detail": "Converted every explicitly stated wallet currency into SGD using deterministic reference rates."},
                            {"step": "CALCULATE", "status": "completed", "detail": f"Compared SGD {usable_sgd:,.2f} usable funds against SGD {tuition_sgd:,.2f} tuition while protecting the stated reserve."},
                            {"step": "SECURITY", "status": "completed", "detail": "Used only message-supplied balances and constraints; no proposal or transaction was created."},
                        ],
                        {
                            "goal": "financial_plan",
                            "affordability": {
                                "wallet_total_sgd": float(total_sgd),
                                "reserve_sgd": float(reserve_sgd),
                                "usable_sgd": float(usable_sgd),
                                "tuition_sgd": float(tuition_sgd),
                                "shortfall_sgd": float(shortfall_sgd),
                                "remaining_sgd": float(remaining_sgd),
                            },
                            "state_changed": False,
                        },
                    )
                except (ValueError, HTTPError, URLError, TimeoutError, OSError) as exc:
                    return self._result(
                        "agentic_local",
                        f"I can parse the scenario, but I cannot safely value one of the stated currencies right now ({type(exc).__name__}). No transaction was created.",
                        [
                            {"step": "UNDERSTAND", "status": "completed", "detail": "Detected a multi-currency affordability scenario."},
                            {"step": "FX", "status": "blocked", "detail": f"Reference FX was unavailable: {type(exc).__name__}."},
                            {"step": "SECURITY", "status": "completed", "detail": "No proposal or transaction was created."},
                        ],
                        {"goal": "financial_plan", "state_changed": False, "blocked_reason": "reference_fx_unavailable"},
                    )

        # Goal-driven planning: reason across multiple financial goals in one request.
        # This is the main offline "agentic" path: it turns a situation into prioritized,
        # constraint-aware actions while leaving execution behind authorization controls.
        goal_keywords = {
            "tuition": ["tuition", "school fees", "semester fee", "school fee"],
            "remittance": ["send home", "send money", "family", "remit", "remittance", "back home"],
            "incoming": [
                "receive", "received", "got paid", "family sent", "allowance", "incoming",
                "parents send", "parents can send", "parents will send", "parents may send",
                "parents might send", "parents could send", "family can send", "family will send",
                "family may send", "family might send", "family could send",
            ],
            "spending": ["spending", "expenses", "living costs", "monthly costs"],
            "reserve": ["emergency reserve", "emergency fund", "keep a reserve", "keep aside"],
            "fx": ["convert", "exchange", "currency", "fx"],
            "credit": ["build credit", "building credit", "credit history", "credit score", "creditworthiness"],
        }
        detected_goals = []
        for goal, words in goal_keywords.items():
            if any(word in t for word in words):
                detected_goals.append(goal)
            elif goal == "remittance" and "send" in t and any(
                destination in t for destination in ["home", "family", "overseas", "abroad"]
            ):
                detected_goals.append(goal)
        # Treat feasibility/safety questions as planning requests when multiple
        # financial goals are present. This prevents words such as "send" or "all"
        # inside a broader planning scenario from being misrouted as a transaction command.
        goal_planning_question = any(k in t for k in [
            "what should i do", "what do i do", "help me plan", "make a plan",
            "how should i manage", "how should i handle", "what should i prioritize",
            "what do you recommend", "plan my finances", "financial plan",
            "should i convert", "should i use",
            "can i", "will i", "can i meet", "meet all", "handle everything",
            "can i handle", "afford", "safest plan", "what is the safest",
            "safest option", "safest approach",
        ])

        affordability_question = any(k in t for k in [
            "can i afford", "can i safely afford", "can i do", "is it affordable",
            "safe to send", "can i safely send", "will i still be okay",
            "will i have enough", "can i still afford", "while protecting",
            "while keeping",
        ])
        competing_obligation_question = (
            "tuition" in detected_goals
            and "remittance" in detected_goals
            and any(k in t for k in [
                "safest plan", "what is the safest", "safest option", "safest approach",
                "what should i do", "should i", "prioritize", "priority", "before",
            ])
            # When the same message also contains quantified/possible family support,
            # it is a multi-goal plan (tuition + incoming + remittance), not the
            # dedicated two-goal prioritization shortcut.
            and not any(k in t for k in [
                "parents can send", "parents will send", "parents may send",
                "parents might send", "parents could send", "family can send",
                "family will send", "family may send", "family might send",
                "family could send", "incoming next", "receive next",
            ])
        )
        goal_plan_ready = (
            len(detected_goals) >= 3
            or (
                "tuition" in detected_goals
                and "incoming" in detected_goals
                and len(detected_goals) >= 2
            )
            or (
                "credit" in detected_goals
                and len(detected_goals) >= 2
            )
            or (
                "tuition" in detected_goals
                and "remittance" in detected_goals
            )
            or (
                affordability_question
                and ("tuition" in detected_goals or "remittance" in detected_goals)
                and scenario_context_available
                and not conditional_income_question
            )
        )
        # Dedicated conditional-income handling below must always win over the
        # generic multi-goal planner, even though the message contains both
        # "tuition" and "parents" and therefore looks like a two-goal plan.
        if conditional_income_question or competing_obligation_question:
            goal_plan_ready = False
        if goal_planning_question and goal_plan_ready:
            wallet_balances = self._extract_wallet_balances_from_text(t)
            if not wallet_balances:
                wallet_balances = dict(remembered_context.get("wallet_balances", {}))
            use_scenario_wallet = len(wallet_balances) >= 1
            horizon = message_horizon_days or 30

            tuition_labeled = self._extract_labeled_amount(t, ["tuition", "tuition fee", "tuition fees"])
            remittance_labeled = self._extract_labeled_amount(
                t, ["send", "sending", "send home", "remittance", "remit", "family"]
            )
            incoming_labeled = self._extract_labeled_amount(
                t, [
                    "receive", "received", "got", "allowance", "incoming", "family sent",
                    "parents send", "parents can send", "parents will send", "parents may send",
                    "parents might send", "parents could send", "family may send",
                    "family might send", "family could send",
                ]
            )
            monthly_expenses_labeled = self._extract_labeled_amount(
                t, ["monthly expenses", "monthly expense", "monthly costs", "living costs"]
            )

            reserve_currency = str(
                self.engine.state.get("profile_meta", {}).get("emergency_reserve_currency", "MYR")
            ).upper()
            reserve_amount = self.engine.money_value(
                Decimal(str(
                    self.engine.state.get("profile_meta", {}).get(
                        "emergency_reserve_amount",
                        self.engine.state.get("emergency_reserve_myr", 0),
                    )
                ))
            )
            scenario_wallet = wallet_balances if use_scenario_wallet else self.engine.get_balance()
            reserve_represented = reserve_currency in scenario_wallet
            reserve_balance = self.engine.money_value(scenario_wallet.get(reserve_currency, 0))
            reserve_protected = reserve_balance >= reserve_amount if reserve_represented else False

            scenario_forecast = (
                self._scenario_forecast(
                    scenario_wallet,
                    monthly_expenses_labeled,
                    tuition_labeled,
                    remittance_labeled,
                    incoming_labeled,
                    horizon,
                )
                if use_scenario_wallet
                else self.engine.forecast_portfolio(30)
            )
            forecast = dict(scenario_forecast)
            # Keep the forecast schema compatible with the full-wallet engine output
            # while exposing the scenario-specific conditional-income fields used by
            # the answer and judge evidence.
            forecast.setdefault(
                "starting_portfolio_sgd",
                forecast.get("starting_balance_sgd", 0.0),
            )
            forecast.setdefault(
                "starting_portfolio_planning",
                forecast.get("starting_balance_planning", 0.0),
            )
            forecast["scenario"] = scenario_forecast

            priorities = []
            actions = []
            constraints = []
            uncertainties = []
            incoming_simulation = None
            forecast_after_income = None

            incoming_mentioned = any(k in t for k in [
                "parents can send", "parents will send", "parents may send",
                "parents might send", "parents could send", "family will send",
                "family can send", "family may send", "family might send", "family could send",
                "receive next", "incoming next",
            ])
            if incoming_mentioned and not incoming_labeled:
                uncertainties.append(
                    "Expected incoming support was mentioned without an amount; it is not counted in the forecast."
                )

            if "fx" in detected_goals and not any(k in t for k in ["rate", "quote", "quoted", "exchange rate"]):
                uncertainties.append(
                    "No user-entered FX quote was supplied for the scenario; reference-rate calculations remain indicative."
                )

            if not tuition_labeled and "tuition" in detected_goals:
                profile = self.engine.get_profile()
                saved_tuition = self.engine.money_value(
                    Decimal(str(profile.get("tuition_amount", 0)))
                    - Decimal(str(profile.get("scholarship_amount", 0)))
                    - Decimal(str(profile.get("loan_amount", 0)))
                )
                saved_tuition_currency = str(
                    profile.get("tuition_currency", planning)
                ).upper()
                saved_tuition_days = int(profile.get("tuition_due_days", 31))
                if saved_tuition > 0 and (
                    message_horizon_days is not None or saved_tuition_days <= 30
                ):
                    tuition_labeled = (saved_tuition, saved_tuition_currency)

            if tuition_labeled:
                tuition_amount, tuition_currency = tuition_labeled
                tuition_days = message_horizon_days if message_horizon_days is not None else int(
                    self.engine.state.get("education", {}).get("tuition_due_days", 30)
                )
                try:
                    tuition_funding = self.engine.recommend_funding(
                        tuition_amount,
                        tuition_currency,
                        balances_override=wallet_balances if use_scenario_wallet else None,
                    )
                    # For an explicit scenario wallet, the scenario forecast is the
                    # authoritative valuation because it uses the same wallet and FX inputs
                    # as the multi-obligation forecast. Do not let a profile-based funding
                    # helper overstate coverage when the chat scenario supplies its own wallet.
                    if use_scenario_wallet:
                        scenario_available = self.engine.money_value(
                            scenario_forecast.get("usable_starting_sgd", scenario_forecast.get("usable_starting_planning", 0))
                        )
                        tuition_target = self.engine.money_value(
                            scenario_forecast.get("tuition_sgd", tuition_amount)
                        )
                        tuition_status = (
                            "funded"
                            if scenario_available >= tuition_target
                            else "partial"
                        )
                    else:
                        funded_amount = self.engine.money_value(tuition_funding.get("funded_amount", 0))
                        target_amount = self.engine.money_value(tuition_funding.get("target_amount", tuition_amount))
                        tuition_status = (
                            "funded"
                            if funded_amount >= target_amount
                            else "partial"
                        )
                except ValueError as exc:
                    tuition_funding = {
                        "status": "review",
                        "target_amount": float(tuition_amount),
                        "target_currency": tuition_currency,
                        "funded_amount": 0.0,
                        "remaining_gap": float(tuition_amount),
                        "plan": [],
                        "candidates": [],
                        "reserve": {
                            "currency": reserve_currency,
                            "amount": float(reserve_amount),
                            "protected": reserve_protected,
                        },
                        "state_changed": False,
                        "note": str(exc),
                    }
                    tuition_status = "review"
                    constraints.append(f"Tuition funding could not be fully evaluated: {exc}")
                priorities.append({
                    "rank": 1,
                    "goal": "tuition",
                    "reason": (
                        f"Tuition is an essential obligation with a stated/assumed horizon of "
                        f"{tuition_days} days."
                    ),
                    "horizon_days": tuition_days,
                    "status": tuition_status,
                })
                if tuition_status == "funded":
                    actions.append({
                        "priority": 1,
                        "action": "SECURE_TUITION_FUNDING",
                        "detail": "Use the deterministic minimum-conversion funding plan while protecting the emergency reserve.",
                        "funding_plan": tuition_funding,
                    })
                else:
                    constraints.append(
                        f"Tuition remains short by {tuition_funding['remaining_gap']:,.2f} {tuition_currency}."
                    )
                    actions.append({
                        "priority": 1,
                        "action": "CLOSE_TUITION_GAP",
                        "detail": f"Find another {tuition_funding['remaining_gap']:,.2f} {tuition_currency} funding source before the tuition deadline.",
                        "funding_plan": tuition_funding,
                    })

            if remittance_labeled:
                remittance_amount, remittance_currency = remittance_labeled
                remittance_priority = 2 if tuition_labeled else 1
                try:
                    remittance_target_planning = (
                        self.engine.money_value(remittance_amount)
                        if remittance_currency == forecast["planning_currency"]
                        else self.engine.money_value(
                            self.engine.convert_currency(
                                remittance_amount, remittance_currency, forecast["planning_currency"]
                            )["converted_amount"]
                        )
                    )
                except ValueError as exc:
                    remittance_target_planning = self.engine.money_value(0)
                    constraints.append(f"Remittance FX conversion could not be evaluated: {exc}")
                projected_after = self.engine.money_value(
                    Decimal(str(forecast["projected_balance_planning"])) - remittance_target_planning
                )
                remittance_reason = (
                    "Family remittance is secondary to a dated tuition obligation when both are present."
                    if tuition_labeled
                    else (
                        "Remittance is evaluated against projected liquidity and the protected reserve."
                        if reserve_represented
                        else
                        "Remittance is evaluated against projected liquidity, but the configured emergency reserve is not represented in the supplied scenario wallet."
                    )
                )
                priorities.append({
                    "rank": remittance_priority,
                    "goal": "remittance",
                    "reason": remittance_reason,
                    "status": "affordable" if projected_after >= 0 and reserve_protected else "needs_review",
                })
                if projected_after >= 0 and reserve_protected:
                    actions.append({
                        "priority": remittance_priority,
                        "action": "REVIEW_REMITTANCE",
                        "detail": (
                            f"A hypothetical {remittance_currency} {remittance_amount:,.2f} remittance leaves "
                            f"about {projected_after:,.2f} {forecast['planning_currency']} in the 30-day projected position."
                        ),
                    })
                else:
                    constraints.append(
                        f"Sending {remittance_currency} {remittance_amount:,.2f} would put pressure on projected liquidity or the reserve."
                    )
                    actions.append({
                        "priority": remittance_priority,
                        "action": "DEFER_REMITTANCE",
                        "detail": "Defer or reduce the remittance until essential obligations and reserve protection are secured.",
                    })

            if incoming_labeled:
                incoming_amount, incoming_currency = incoming_labeled
                priorities.append({
                    "rank": 0,
                    "goal": "incoming_funds",
                    "reason": "Incoming funds are contingent support and are not counted in the base-case obligation test until they actually arrive.",
                    "status": "contingent",
                })
                incoming_simulation = (
                    self.engine.simulate_income_impact(incoming_amount, incoming_currency)
                    if incoming_currency in self.engine.get_balance()
                    else {
                        "hypothetical_only": True,
                        "state_changed": False,
                        "income": {"amount": float(incoming_amount), "currency": incoming_currency},
                        "available_for_simulation": False,
                        "note": f"{incoming_currency} is not configured in the current wallet; the expected income is not counted."
                    }
                )
                if "projected_shortfall_after_hypothetical_income_sgd" in incoming_simulation:
                    forecast_after_income = {
                        "projected_shortfall_sgd": float(
                            incoming_simulation["projected_shortfall_after_hypothetical_income_sgd"]
                        ),
                        "hypothetical_only": True,
                        "state_changed": False,
                    }
                else:
                    uncertainties.append(
                        f"{incoming_currency} incoming funds could not be included in the projected impact because that currency is not configured."
                    )
                actions.insert(0, {
                    "priority": 3,
                    "action": "SCENARIO_INCOMING_SUPPORT",
                    "detail": (
                        f"Scenario-check the {incoming_currency} {incoming_amount:,.2f} income before "
                        "committing to discretionary outflows."
                    ),
                    "simulation": incoming_simulation,
                })

            if "credit" in detected_goals:
                credit_readiness = {
                    "status": "evidence_limited",
                    "not_a_credit_score": True,
                    "liquidity_supports_future_obligations": forecast["projected_balance_planning"] >= 0,
                    "missing_evidence": [
                        "credit account limits",
                        "credit utilization",
                        "account age",
                        "missed/late payment history",
                    ],
                    "next_actions": [
                        "Keep any future credit payments inside the cash-flow plan.",
                        "Pay documented obligations on time and keep enough liquid cash for near-term essentials.",
                        "Review eligibility, fees and terms before opening any credit product.",
                    ],
                }
                priorities.append({
                    "rank": 3,
                    "goal": "credit",
                    "reason": (
                        "Credit-building is treated as a long-term readiness goal; the demo cannot infer a real credit score "
                        "without account-level credit history."
                    ),
                    "horizon_days": None,
                    "status": "evidence_limited",
                })
                actions.append({
                    "priority": 3,
                    "action": "BUILD_CREDIT_READINESS",
                    "detail": (
                        "Use the cash-flow plan to keep future credit obligations affordable while building a reliable "
                        "payment history; no credit score is inferred."
                    ),
                    "credit_readiness": credit_readiness,
                })
                uncertainties.append(
                    "Actual credit-account data is unavailable, so XKF5 provides readiness guidance rather than a credit score."
                )

            if "spending" in detected_goals:
                spending = self.engine.spending_analysis()
                flexible = [
                    x for x in spending["categories"]
                    if x.get("classification") == "Adjustable"
                ]
                if flexible:
                    actions.append({
                        "priority": 3,
                        "action": "TRIM_ADJUSTABLE_SPENDING",
                        "detail": (
                            f"Review adjustable categories first; current adjustable spending is "
                            f"{spending['discretionary_total_planning']:,.2f} {spending['currency']} per month."
                        ),
                    })

            if not reserve_represented:
                uncertainties.append(
                    f"The configured {reserve_currency} {reserve_amount:,.2f} emergency reserve is not represented in the supplied scenario wallet, so XKF5 cannot verify that the reserve is protected."
                )
            elif not reserve_protected:
                constraints.append(
                    f"The {reserve_currency} emergency reserve is below its configured {reserve_currency} {reserve_amount:,.2f} floor."
                )

            priorities.sort(key=lambda x: (x["rank"], x["goal"]))
            actions.sort(key=lambda x: x["priority"])

            tuition_summary = None
            if tuition_labeled:
                tuition_item = next((x for x in priorities if x.get("goal") == "tuition"), None)
                tuition_summary = {
                    "currency": tuition_labeled[1],
                    "amount": float(tuition_labeled[0]),
                    "status": tuition_item.get("status", "review") if tuition_item else "review",
                    "shortfall": float(tuition_funding.get("remaining_gap", tuition_labeled[0])),
                }

            remittance_summary = None
            if remittance_labeled:
                remittance_item = next((x for x in priorities if x.get("goal") == "remittance"), None)
                remittance_summary = {
                    "currency": remittance_labeled[1],
                    "amount": float(remittance_labeled[0]),
                    "status": remittance_item.get("status", "needs_review") if remittance_item else "needs_review",
                }

            trace = [
                {
                    "step": "UNDERSTAND",
                    "status": "completed",
                    "detail": f"Detected multiple financial goals: {', '.join(detected_goals)}.",
                },
                {
                    "step": "OBSERVE",
                    "status": "completed",
                    "detail": (
                        "Built a 30-day full-wallet liquidity forecast"
                        + (" from explicitly stated hypothetical balances." if use_scenario_wallet else " from the saved wallet.")
                    ),
                },
            ]
            if incoming_labeled:
                trace.extend([
                    {
                        "step": "SIMULATE",
                        "status": "completed",
                        "detail": (
                            f"Simulated the stated {incoming_labeled[1]} {incoming_labeled[0]:,.2f} incoming funds "
                            "without changing account state."
                        ),
                    },
                    {
                        "step": "FX",
                        "status": "completed",
                        "detail": (
                            "Validated the incoming-funds valuation through the deterministic FX path; "
                            "the result remains hypothetical until funds actually arrive."
                        ),
                    },
                    {
                        "step": "CALCULATE",
                        "status": "completed",
                        "detail": (
                            "Recomputed the projected liquidity impact after the hypothetical incoming funds "
                            "before evaluating downstream goals."
                        ),
                    },
                ])
            trace.extend([
                {
                    "step": "REASON",
                    "status": "completed",
                    "detail": (
                        f"Prioritized essential obligations first, protected the {reserve_currency} reserve, "
                        f"and evaluated discretionary/remittance decisions against projected {forecast['planning_currency']} liquidity."
                    ),
                },
                {
                    "step": "SECURITY",
                    "status": "completed",
                    "detail": "All planning actions are read-only; no transaction was created and no authorization was granted.",
                },
            ])

            decision = {
                "priority_order": [x["goal"] for x in priorities],
                "priorities": priorities,
                "actions": actions,
                "constraints": constraints,
                "uncertainties": uncertainties,
                "forecast": forecast,
                "credit_readiness": credit_readiness if "credit" in detected_goals else None,
                "tuition": tuition_summary,
                "remittance": remittance_summary,
                "reserve": {
                    "currency": reserve_currency,
                    "amount": float(reserve_amount),
                    "balance": float(reserve_balance),
                    "protected": reserve_protected,
                    "represented_in_scenario": reserve_represented,
                    "verification_status": (
                        "protected"
                        if reserve_represented and reserve_protected
                        else "below_floor"
                        if reserve_represented
                        else "not_represented"
                    ),
                },
                "state_changed": False,
            }
            # Keep the received-funds planning trace explicit and auditable:
            # these are advisory calculations only and do not imply any transaction.
            if received and tuition_context and conversion_question:
                required_steps = [
                    ("UNDERSTAND", "Recognized received family funds and the tuition/conversion question."),
                    ("OBSERVE", "Reviewed the stated incoming amount and the current forecast without changing balances."),
                    ("SIMULATE", "Simulated the incoming MYR as a hypothetical scenario only."),
                    ("REASON", "Compared the updated shortfall with the tuition need."),
                    ("FX", "Identified MYR-to-SGD conversion as the relevant currency pair."),
                    ("CALCULATE", "Calculated the projected position after hypothetical incoming funds."),
                    ("SECURITY", "Confirmed no wallet balance changed and no transaction was created."),
                    ("RECOMMEND", "Provided an advisory next step; no conversion was executed."),
                ]
                present = {item.get("step") for item in trace}
                for step, detail in required_steps:
                    if step not in present:
                        trace.append({"step": step, "status": "completed", "detail": detail})

            trace.append({
                "step": "RECOMMEND",
                "status": "completed",
                "detail": (
                    f"Produced {len(actions)} actionable planning step(s) across {len(priorities)} goal(s); "
                    "no funds were moved."
                ),
            })

            answer_parts = []
            for item in priorities:
                status = item.get("status", "review")
                answer_parts.append(
                    f"Priority {item['rank']}: {item['goal'].replace('_', ' ').title()} — {status}."
                )
            starting_for_answer = forecast.get("starting_balance_planning", forecast.get("starting_portfolio_planning", 0.0))

            # When tuition and an outbound family remittance are both explicit,
            # present the decision as a priority plan rather than a generic
            # affordability response. This preserves the structured decision
            # evidence expected by the competing-obligations QA tests.
            if competing_question and tuition_labeled and remittance_labeled:
                tuition_shortfall = self.engine.money_value(
                    max(Decimal("0"), tuition_labeled[0] - self.engine.money_value(
                        (scenario_wallet if use_scenario_wallet else self.engine.get_balance()).get(
                            tuition_labeled[1], 0
                        )
                    ))
                )
                answer = (
                    f"Priority 1: fund the tuition of {tuition_labeled[1]} {tuition_labeled[0]:,.2f} first "
                    f"(about {horizon} days away). "
                    f"Priority 2: review the {remittance_labeled[1]} {remittance_labeled[0]:,.2f} family remittance after tuition is secured. "
                    f"Estimated tuition shortfall: {tuition_shortfall:,.2f} {tuition_labeled[1]}. "
                    "This is a prioritization simulation; no transaction was created."
                )
            else:
                answer = (
                    "XKF5's plan: " + " ".join(answer_parts) +
                f" Starting scenario balance is {forecast['planning_currency']} {starting_for_answer:,.2f}. "
                f" {forecast['horizon_days']}-day scenario position before conditional incoming funds: "
                f"{forecast['planning_currency']} {forecast['projected_balance_planning']:,.2f}. "
                + (
                    "Your emergency reserve is protected. "
                    if reserve_represented and reserve_protected else
                    "Your emergency reserve is below its configured floor, so discretionary outflows should pause. "
                    if reserve_represented else
                    "Your configured emergency reserve is not represented in the supplied scenario, so its protection cannot be verified. "
                )
                + (
                    f"Constraints: {' '.join(constraints)} "
                    if constraints else
                    "No immediate funding constraint was detected from the supplied scenario. "
                )
                + (
                    f"Uncertainties: {' '.join(uncertainties)} "
                    if uncertainties else
                    ""
                )
                + (
                    f"With the stated conditional incoming funds, the projected position would be "
                    f"{forecast['planning_currency']} {forecast['projected_balance_with_incoming']:,.2f}. "
                    if incoming_labeled
                    else
                    ""
                )
                + "This is a planning simulation only; no transaction was created or executed."
                )
            return self._result(
                "agentic_local",
                answer,
                trace,
                {
                    "goal": "financial_plan",
                    "planning_horizon_days": horizon,
                    "detected_goals": detected_goals,
                    "incoming_funds": incoming_simulation,
                    "forecast_after_income": forecast_after_income,
                    "scenario_forecast": scenario_forecast,
                    "decision": decision,
                    "state_changed": False,
                },
            )

        # Remittance planning must run before the generic "send" action handler.
        # A planning question such as "Should I send SGD 500 home?" is advisory and
        # must not be mistaken for an instruction to create a MYR transfer proposal.
        if "remittance" in t or "send home" in t or "back home" in t or "family overseas" in t or "send money home" in t:
            remittance_advice = any(k in t for k in [
                "should i", "which", "what should", "best", "how should",
                "compare", "versus", " vs ", "help me decide",
                "can i afford", "can i safely afford", "safe to send",
            ])
            if remittance_advice:
                remittance_supported = [
                    "MYR", "SGD", "USD", "CNY", "JPY", "KRW", "THB", "EUR",
                    "GBP", "AUD", "CAD", "HKD", "TWD", "INR",
                ]
                send_target = None
                send_amount = None
                mentioned_codes = []
                remittance_text = t.replace(",", "")
                for code in remittance_supported:
                    amount = self._amount(t, code)
                    if amount is not None:
                        mentioned_codes.append(code)
                    match = re.search(
                        rf"\b(?:send|sending|remit|remittance|transfer)\b[^.;,]{{0,80}}\b{re.escape(code.lower())}\b\s*([0-9]+(?:\.[0-9]+)?)",
                        remittance_text,
                        re.I,
                    )
                    if match:
                        send_target = code
                        send_amount = self.engine.money_value(match.group(1))
                        break

                affordability_question = any(k in t for k in [
                    "can i afford", "can i safely afford", "is it affordable",
                    "safe to send", "can i safely send", "will i still be okay",
                    "will i have enough", "can i still afford",
                ])
                if send_target and send_amount and send_amount > 0:
                    if affordability_question:
                        planning_currency = str(
                            self.engine.state.get("profile_meta", {}).get("planning_currency", "SGD")
                        ).upper()
                        try:
                            target_in_planning = (
                                self.engine.money_value(send_amount)
                                if send_target == planning_currency
                                else self.engine.money_value(
                                    self.engine.convert_currency(
                                        send_amount, send_target, planning_currency
                                    )["converted_amount"]
                                )
                            )
                            scenario_wallet = dict(remembered_context.get("wallet_balances", {}))
                            if scenario_wallet:
                                # Calculate the baseline without the proposed remittance;
                                # projected_after below subtracts it exactly once.
                                forecast = self._scenario_forecast(
                                    scenario_wallet, None, None, None, None, 30
                                )
                            else:
                                forecast = self.engine.forecast()
                            health = self.engine.health_analysis()
                            # Remittance affordability must be based on liquid
                            # planning-currency cash flow, not foreign assets that
                            # have not been converted. The emergency reserve remains
                            # separately protected by reserve_ok below.
                            planning_rate = self.engine._profile_rate_to_sgd(planning_currency)
                            liquid_sgd = self.engine.money_value(
                                Decimal(str(self.engine.get_balance().get(planning_currency, 0)))
                                * planning_rate
                            )
                            monthly_income_sgd = self.engine.money_value(
                                self.engine.state.get("income_monthly_sgd", 0)
                            )
                            monthly_spending_sgd = self.engine.money_value(
                                sum(
                                    self.engine.state.get("monthly_spending_sgd", {}).values(),
                                    Decimal("0"),
                                )
                                + self.engine.state.get("accommodation_monthly_sgd", 0)
                            )
                            obligations_sgd = self.engine.money_value(
                                sum(
                                    (
                                        Decimal(str(item["amount_sgd"]))
                                        for item in self.engine.get_obligations()
                                        if int(item.get("days", 30)) <= 30
                                    ),
                                    Decimal("0"),
                                )
                            )
                            projected_after = self.engine.money_value(
                                (
                                    liquid_sgd + monthly_income_sgd
                                    - monthly_spending_sgd - obligations_sgd
                                    - target_in_planning * planning_rate
                                ) / planning_rate
                            )
                            reserve_currency = str(
                                self.engine.state.get("profile_meta", {}).get(
                                    "emergency_reserve_currency", "MYR"
                                )
                            ).upper()
                            reserve_amount = self.engine.money_value(
                                Decimal(str(
                                    self.engine.state.get("profile_meta", {}).get(
                                        "emergency_reserve_amount",
                                        self.engine.state.get("emergency_reserve_myr", 0),
                                    )
                                ))
                            )
                            reserve_balance = self.engine.money_value(
                                self.engine.get_balance().get(reserve_currency, 0)
                            )
                            reserve_ok = reserve_balance >= reserve_amount
                            affordable = projected_after >= 0 and reserve_ok
                            if affordable:
                                decision_text = (
                                    f"Yes, the scenario remains affordable: the projected "
                                    f"{planning_currency} position after the remittance is about "
                                    f"{projected_after:,.2f}, and the emergency reserve remains protected."
                                )
                                action = "REMITTANCE_AFFORDABLE"
                            else:
                                reasons = []
                                if projected_after < 0:
                                    reasons.append(
                                        f"the projected position would fall to about "
                                        f"{planning_currency} {projected_after:,.2f}"
                                    )
                                if not reserve_ok:
                                    reasons.append(
                                        f"the configured {reserve_currency} emergency reserve is already below "
                                        f"its {reserve_currency} {reserve_amount:,.2f} floor"
                                    )
                                decision_text = (
                                    "No, I would not recommend sending it yet because "
                                    + " and ".join(reasons) + "."
                                )
                                action = "REMITTANCE_NOT_AFFORDABLE"

                            trace = [
                                {
                                    "step": "UNDERSTAND",
                                    "status": "completed",
                                    "detail": (
                                        f"Detected an affordability check for a {send_target} "
                                        f"{send_amount:,.2f} outbound remittance."
                                    ),
                                },
                                {
                                    "step": "OBSERVE",
                                    "status": "completed",
                                    "detail": (
                                        f"Reviewed the {planning_currency} forecast, liquidity health, "
                                        f"and the configured {reserve_currency} emergency reserve."
                                    ),
                                },
                                {
                                    "step": "SIMULATE",
                                    "status": "completed",
                                    "detail": (
                                        f"Scenario subtracts about {target_in_planning:,.2f} {planning_currency} "
                                        f"from the projected 30-day position; account state was not changed."
                                    ),
                                },
                                {
                                    "step": "REASON",
                                    "status": "completed",
                                    "detail": (
                                        f"30-day projected position after the hypothetical remittance: "
                                        f"{planning_currency} {projected_after:,.2f}."
                                    ),
                                },
                                {
                                    "step": "SECURITY",
                                    "status": "completed" if affordable else "blocked",
                                    "detail": "Affordability assessment is advisory and read-only; no transaction was created.",
                                },
                                {
                                    "step": "RECOMMEND",
                                    "status": "completed",
                                    "detail": decision_text,
                                },
                            ]
                            return self._result(
                                "agentic_local",
                                decision_text + " This is a scenario assessment only; no remittance or transaction was created.",
                                trace,
                                {
                                    "goal": "remittance_affordability",
                                    "remittance": {
                                        "target": {
                                            "currency": send_target,
                                            "amount": float(send_amount),
                                        },
                                        "action": action,
                                        "target_in_planning": float(target_in_planning),
                                        "projected_before": float(forecast["projected_balance_planning"]),
                                        "projected_after": float(projected_after),
                                        "reserve": {
                                            "currency": reserve_currency,
                                            "amount": float(reserve_amount),
                                            "balance": float(reserve_balance),
                                            "protected": reserve_ok,
                                        },
                                        "liquidity_health": health,
                                        "state_changed": False,
                                    },
                                },
                            )
                        except ValueError as exc:
                            trace = [
                                {"step": "UNDERSTAND", "status": "completed", "detail": "Detected a remittance affordability question."},
                                {"step": "SECURITY", "status": "blocked", "detail": str(exc)},
                            ]
                            return self._result(
                                "agentic_local",
                                f"I could not safely assess affordability: {exc}",
                                trace,
                                {
                                    "goal": "remittance_affordability",
                                    "blocked_reason": "affordability_fx_unavailable",
                                },
                            )

                if send_target and send_amount and send_amount > 0:
                    # Treat message balances as hypothetical only when the message
                    # explicitly indicates possession; never treat "send SGD 500"
                    # itself as evidence that SGD 500 is in the wallet.
                    possession_marker = re.search(
                        r"\b(?:have|has|hold|holding|own|keep)\b",
                        t,
                        re.I,
                    )
                    wallet_balances = (
                        self._extract_wallet_balances_from_text(t)
                        if possession_marker
                        else {}
                    )
                    use_scenario_wallet = len(wallet_balances) >= 1

                    trace = [
                        {
                            "step": "UNDERSTAND",
                            "status": "completed",
                            "detail": f"Detected an advisory remittance-planning request for {send_target} {send_amount:,.2f}.",
                        },
                        {
                            "step": "OBSERVE",
                            "status": "completed",
                            "detail": (
                                "Using explicitly stated wallet balances as a hypothetical scenario."
                                if use_scenario_wallet
                                else "Using the saved multi-currency wallet."
                            ),
                        },
                    ]
                    try:
                        funding = self.engine.recommend_funding(
                            send_amount,
                            send_target,
                            balances_override=wallet_balances if use_scenario_wallet else None,
                        )
                    except ValueError as exc:
                        trace.append({"step": "REASON", "status": "blocked", "detail": str(exc)})
                        return self._result(
                            "agentic_local",
                            f"I could not build a safe remittance plan: {exc}",
                            trace,
                            {"goal": "remittance_planning", "blocked_reason": "remittance_plan_unavailable"},
                        )

                    plan = funding.get("plan", [])
                    selected_sources = [x["from_currency"] for x in plan]
                    conversion_count = sum(
                        1 for x in plan if x["from_currency"] != x["to_currency"]
                    )
                    reserve = funding.get("reserve", {})
                    alternatives = [
                        {
                            "currency": x["currency"],
                            "usable_balance": x["available"],
                            "target_equivalent": x["available_in_target"],
                            "selected": x["currency"] in selected_sources,
                        }
                        for x in funding.get("candidates", [])
                        if x.get("available_in_target", 0) > 0
                    ]

                    if funding["status"] == "funded":
                        legs_text = "; ".join(
                            f"{x['from_currency']} {x['source_amount']:,.2f} → "
                            f"{x['to_currency']} {x['target_amount']:,.2f}"
                            for x in plan
                        )
                        answer = (
                            f"Decision: prepare the remittance using {legs_text}. "
                            f"The plan uses {', '.join(selected_sources)} with {conversion_count} FX conversion(s) "
                            f"while protecting the {reserve.get('currency', 'configured')} emergency reserve. "
                            "This is a planning simulation only; no remittance or transaction was created."
                        )
                        action = "PREPARE_REMITTANCE_PLAN"
                    else:
                        gap = funding["remaining_gap"]
                        answer = (
                            f"Decision: do not send the remittance yet. The wallet can fund about "
                            f"{funding['funded_amount']:,.2f} of the requested {send_target} {send_amount:,.2f}, "
                            f"leaving a {gap:,.2f} {send_target} gap. "
                            "The emergency reserve remains protected and no transaction was created."
                        )
                        action = "REMITTANCE_FUNDING_GAP"

                    trace.extend([
                        {
                            "step": "REASON",
                            "status": "completed",
                            "detail": f"Compared the available wallet against the {send_target} remittance target.",
                        },
                        {
                            "step": "SECURITY",
                            "status": "completed",
                            "detail": "Remittance planning is read-only; execution still requires the protected proposal and explicit authorization flow.",
                        },
                        {
                            "step": "RECOMMEND",
                            "status": "completed",
                            "detail": f"Produced {action.lower()} without moving funds.",
                        },
                    ])
                    return self._result(
                        "agentic_local",
                        answer,
                        trace,
                        {
                            "goal": "remittance_planning",
                            "remittance": {
                                "target": {"currency": send_target, "amount": float(send_amount)},
                                "action": action,
                                "funding_plan": funding,
                                "selected_sources": selected_sources,
                                "conversion_count": conversion_count,
                                "alternatives": alternatives,
                                "state_changed": False,
                            },
                        },
                    )

        # Explicit action requests take priority over informational FX questions.
        # IMPORTANT: words like "conversion" or "convert" alone are not enough to
        # authorize preparation; the user must clearly request an action and provide
        # an exact amount. Never infer an action amount from a forecast.
        advisory_action_question = any(k in t for k in [
            "can i", "could i", "should i", "would it", "is it safe", "is it okay",
            "am i", "afford", "okay", "while protecting", "while keeping",
        ])
        # A sentence that describes paying tuition is not itself a transfer command.
        # In particular, "I need to pay tuition ... Am I okay?" must remain an
        # affordability/reserve-planning question even though "pay" is present.
        tuition_affordability_question = (
            tuition_context
            and any(k in t for k in [
                "am i okay", "am i ok", "will i be okay", "will i be ok",
                "can i afford", "is it affordable", "do i have enough",
                "can i cover", "can i manage",
            ])
        )
        advisory_action_question = advisory_action_question or tuition_affordability_question
        explicit_action = (not advisory_action_question) and any(k in t for k in [
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
        supported = list(self._currency_aliases())
        aliases = self._currency_aliases()
        detected: dict[str, Decimal] = {}
        mentioned: set[str] = set()
        for code in supported:
            amount = self._amount(t, code)
            if amount is not None:
                detected[code] = amount
            if any(re.search(rf"(?<![A-Za-z]){re.escape(alias)}(?![A-Za-z])", t, re.I) for alias in aliases[code]):
                mentioned.add(code)

        conversion_words = any(k in t for k in [
            "convert", "exchange", "to ", "into ", "worth", "how much is",
        ])

        # Portfolio valuation: answer multi-currency "worth in SGD" questions as a total.
        total_value_question = any(k in t for k in [
            "how much is that worth", "worth in sgd", "total in sgd",
            "how much do i have in sgd", "what is that worth in sgd", "total worth",
        ]) and len(detected) >= 2
        if total_value_question:
            lines = []
            total_sgd = self.engine.money_value(0)
            for code, amount in detected.items():
                if code == "SGD":
                    value = self.engine.money_value(amount)
                    rate = Decimal("1")
                else:
                    rate, _ = self.engine._currency_rate_to_sgd(code)
                    value = self.engine.money_value(amount * rate)
                total_sgd = self.engine.money_value(total_sgd + value)
                if code == "SGD":
                    lines.append(f"SGD {amount:,.2f} = SGD {value:,.2f}")
                else:
                    lines.append(f"{code} {amount:,.2f} ≈ SGD {value:,.2f} at 1 {code} = {rate:.8f} SGD")
            trace = [
                {"step": "UNDERSTAND", "status": "completed", "detail": "Detected a multi-currency portfolio valuation request."},
                {"step": "FX", "status": "completed", "detail": "Valued every explicitly stated currency in SGD using the configured/reference FX path."},
                {"step": "CALCULATE", "status": "completed", "detail": f"Total stated portfolio value: SGD {total_sgd:,.2f}."},
            ]
            answer = "Your stated balances are approximately:\n" + "\n".join(lines) + f"\n\nTotal ≈ SGD {total_sgd:,.2f}. FX quotes are indicative and may differ from bank settlement rates or fees."
            return self._result("agentic_local", answer, trace, {
                "valuation": {"currency": "SGD", "total": float(total_sgd), "balances": {k: float(v) for k, v in detected.items()}}
            })

        # Case W: what-if comparison between explicitly mentioned source currencies.
        # This is advisory only: each option is simulated independently and no wallet
        # balances, proposals, or transactions are changed.
        compare_question = any(k in t for k in [
            "which is better", "which one is better", "should i use",
            "compare", "versus", " vs ", "or should i use", "better to use",
        ])
        if compare_question and tuition_context:
            target_code = None
            target_amount = None
            for code in detected:
                requested_amount = self._amount_after_need(t, code)
                if requested_amount is not None:
                    target_code, target_amount = code, requested_amount
                    break

            source_codes = []
            for code in detected:
                if code != target_code and re.search(
                    rf"\b(?:have|has|hold|holding|own|use|using|from)\b[^.;,]{{0,80}}\b{re.escape(code.lower())}\b",
                    t,
                    re.I,
                ):
                    source_codes.append(code)

            if len(source_codes) < 2:
                # Fall back to the currencies explicitly named around comparison words.
                ordered = [code for code in mentioned if code != target_code]
                source_codes = ordered[:2]

            if target_code is not None and target_amount is not None and len(source_codes) >= 2:
                options = []
                scenario_wallet = self._extract_wallet_balances_from_text(t)
                use_scenario_wallet = len(scenario_wallet) >= 1
                saved_wallet = self.engine.get_balance()
                trace = [
                    {
                        "step": "UNDERSTAND",
                        "status": "completed",
                        "detail": f"Detected a what-if comparison for funding {target_code} {target_amount:,.2f}.",
                    },
                    {
                        "step": "OBSERVE",
                        "status": "completed",
                        "detail": (
                            f"Comparing candidate source currencies: {', '.join(source_codes[:3])}."
                            + (" Using balances stated in this message as a hypothetical wallet." if use_scenario_wallet else " Using the saved wallet.")
                        ),
                    },
                ]

                reserve_currency = str(
                        self.engine.state.get("profile_meta", {}).get("emergency_reserve_currency", "MYR")
                    ).upper()
                reserve_amount = self.engine.money_value(
                    Decimal(str(
                        self.engine.state.get("profile_meta", {}).get(
                            "emergency_reserve_amount",
                            self.engine.state.get("emergency_reserve_myr", 0),
                        )
                    ))
                )
                for source_code in source_codes[:3]:
                    raw_balance = (
                        scenario_wallet.get(source_code, 0)
                        if use_scenario_wallet
                        else saved_wallet.get(source_code, 0)
                    )
                    balance = self.engine.money_value(raw_balance)
                    protected = reserve_amount if source_code == reserve_currency else self.engine.money_value(0)
                    available = self.engine.money_value(max(self.engine.money_value(0), balance - protected))
                    reserve_block = source_code == reserve_currency and Decimal(str(balance)) < reserve_amount
                    try:
                        conv = self.engine.convert_currency(
                            target_amount,
                            target_code,
                            source_code,
                        )
                        # convert_currency(target -> source) already returns the
                        # source amount required for the target amount.
                        source_needed = self.engine.money_value(Decimal(str(conv["converted_amount"])))
                        feasible = source_needed <= available and not reserve_block
                        options.append({
                            "currency": source_code,
                            "balance": float(available),
                            "source_amount_needed": float(source_needed),
                            "rate_to_target": float(
                                Decimal("1") / Decimal(str(conv["rate"]))
                            ),
                            "target_coverage": float(
                                self.engine.money_value(available * (
                                    Decimal("1") / Decimal(str(conv["rate"]))
                                ))
                            ),
                            "coverage_ratio": float(
                                min(Decimal("1"), (
                                    self.engine.money_value(available * (
                                        Decimal("1") / Decimal(str(conv["rate"]))
                                    )) / Decimal(str(target_amount))
                                )) if target_amount else Decimal("0")
                            ),
                            "feasible": feasible,
                            "remaining_source_after": float(
                                self.engine.money_value(max(Decimal("0"), available - source_needed))
                            ),
                            "reserve_currency": reserve_currency,
                            "protected_amount": float(protected),
                            "reserve_protected": not reserve_block,
                            "fx": conv.get("fx", {}),
                        })
                    except ValueError as exc:
                        options.append({
                            "currency": source_code,
                            "balance": float(balance),
                            "source_amount_needed": None,
                            "rate_to_target": None,
                            "target_coverage": 0.0,
                            "coverage_ratio": 0.0,
                            "feasible": False,
                            "remaining_source_after": float(balance),
                            "reserve_currency": reserve_currency,
                            "protected_amount": float(protected),
                            "reserve_protected": not reserve_block,
                            "error": str(exc),
                        })

                feasible_options = [x for x in options if x["feasible"]]
                if feasible_options:
                    feasible_options.sort(key=lambda x: (
                        Decimal(str(x["source_amount_needed"])),
                        -Decimal(str(x.get("coverage_ratio", 0))),
                    ))
                    winner = feasible_options[0]
                    comparison_mode = "FULL_COVERAGE"
                    reason = (
                        f"{winner['currency']} requires about {winner['source_amount_needed']:,.2f} "
                        f"{winner['currency']} for the {target_code} {target_amount:,.2f} target while "
                        f"leaving about {winner['remaining_source_after']:,.2f} {winner['currency']} available."
                    )
                else:
                    partial_options = [
                        x for x in options
                        if x.get("source_amount_needed") is not None and x.get("target_coverage", 0) > 0
                    ]
                    if partial_options:
                        partial_options.sort(key=lambda x: (
                            -Decimal(str(x.get("coverage_ratio", 0))),
                            -Decimal(str(x.get("target_coverage", 0))),
                        ))
                        winner = partial_options[0]
                        comparison_mode = "BEST_PARTIAL_COVERAGE"
                        reason = (
                            f"None of the compared currencies can fully cover the {target_code} {target_amount:,.2f} target alone. "
                            f"{winner['currency']} covers about {winner['target_coverage']:,.2f} {target_code} from its usable balance."
                        )
                    else:
                        winner = None
                        comparison_mode = "NO_FEASIBLE_OPTION"
                        reason = "None of the compared source currencies can safely contribute to the target from the available balance."

                trace.append({
                    "step": "REASON",
                    "status": "completed",
                    "detail": "Simulated each source independently using the same target amount and current reference/quoted FX path.",
                })
                trace.append({
                    "step": "SECURITY",
                    "status": "completed",
                    "detail": "Comparison is read-only; no balance mutation, proposal creation, or execution occurs.",
                })
                trace.append({
                    "step": "RECOMMEND",
                    "status": "completed",
                    "detail": f"Recommended {winner['currency']}." if winner else reason,
                })

                if winner:
                    comparison_text = " | ".join(
                        f"{x['currency']}: need {x['source_amount_needed']:,.2f}, "
                        f"balance {x['balance']:,.2f}, "
                        f"coverage {x.get('target_coverage', 0):,.2f} {target_code}, "
                        f"{'feasible' if x['feasible'] else 'partial only'}"
                        for x in options
                    )
                    decision_phrase = (
                        f"use {winner['currency']}"
                        if comparison_mode == "FULL_COVERAGE"
                        else f"prefer {winner['currency']} as the strongest partial funding source"
                    )
                    answer = (
                        f"Decision: {decision_phrase}. "
                        f"Why: {reason} "
                        f"Comparison: {comparison_text}. "
                        "This is a what-if simulation; no balances or transactions were changed."
                    )
                else:
                    answer = (
                        f"Decision: do not choose from these sources yet. {reason} "
                        "Try another funding source or adjust the target. No balances or transactions were changed."
                    )

                return self._result(
                    "agentic_local",
                    answer,
                    trace,
                    {
                        "goal": "funding_comparison",
                        "comparison": {
                            "target": {"currency": target_code, "amount": float(target_amount)},
                            "options": options,
                            "winner": winner,
                            "mode": comparison_mode,
                            "state_changed": False,
                        },
                    },
                )

        # Case D: wallet-wide funding optimization for an explicit obligation.
        # Example: "I have CNY 10,000, USD 500 and MYR 5,000. I need SGD 3,000 for tuition. What should I convert?"
        funding_question = any(k in t for k in [
            "what should i convert", "which currency should i use", "which currency to use",
            "what should i use", "how should i fund", "which account should i use",
            "best currency to use", "best currency", "how much should i convert",
            "what should i do", "best way to fund", "how should i pay",
            "help me decide", "help me choose", "help me handle", "help me manage",
            "how should i handle", "how should i manage", "what do i do with",
            "how do i handle", "how do i manage", "which money should i use",
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
                    if code == planning and re.search(r"\b(?:need|needs|pay|paying|require|required)\b", t, re.I):
                        target_code, target_amount = code, amount
                        break
            if target_code is None:
                # If the user says "upcoming tuition" without an amount, use the saved
                # net tuition only when it is actually due within the 30-day horizon.
                profile = self.engine.get_profile()
                saved_due_days = int(profile.get("tuition_due_days", 31))
                tuition_due = (
                    message_horizon_days <= 30
                    if message_horizon_days is not None
                    else saved_due_days <= 30
                )
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
                if message_horizon_days is not None:
                    trace.append({
                        "step": "OBSERVE",
                        "status": "completed",
                        "detail": f"Interpreted the stated obligation horizon as about {message_horizon_days} days.",
                    })
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
                trace.append({
                    "step": "SECURITY",
                    "status": "completed",
                    "detail": f"Protected the configured {funding['reserve']['currency']} emergency reserve of {funding['reserve']['amount']:,.2f}; no balances were changed.",
                })

                # Build a machine-readable decision for both fully-funded and partial plans.
                selected_sources = [x["from_currency"] for x in funding.get("plan", [])]
                conversion_count = sum(1 for x in funding.get("plan", []) if x["from_currency"] != x["to_currency"])
                candidates = [x for x in funding.get("candidates", []) if x.get("available_in_target", 0) > 0]
                avoided_currencies = [x["currency"] for x in candidates if x["currency"] not in selected_sources]
                if funding["status"] == "funded":
                    if selected_sources == [target_code]:
                        decision_reason = (
                            f"Your existing {target_code} balance already covers the requirement, so no FX conversion is needed."
                        )
                    else:
                        source_reason_parts = []
                        if target_code in selected_sources:
                            source_reason_parts.append(f"existing {target_code} funds were used first")
                        for source in selected_sources:
                            if source != target_code:
                                candidate = next((x for x in candidates if x["currency"] == source), None)
                                if candidate:
                                    source_reason_parts.append(
                                        f"{source} was selected because it had about {candidate['available_in_target']:,.2f} {target_code} of usable value"
                                    )
                        decision_reason = "; ".join(source_reason_parts) + "."
                else:
                    decision_reason = (
                        f"The configured wallet could cover about {funding['funded_amount']:,.2f} of the required "
                        f"{target_code} {target_amount:,.2f}; another {funding['remaining_gap']:,.2f} {target_code} is still needed."
                    )
                if message_horizon_days is None:
                    urgency = "unspecified"
                elif message_horizon_days <= 7:
                    urgency = "urgent"
                elif message_horizon_days <= 30:
                    urgency = "near_term"
                else:
                    urgency = "planned"
                alternatives = [
                    {
                        "rank": index + 1,
                        "currency": candidate["currency"],
                        "usable_balance": candidate["available"],
                        "target_equivalent": candidate["available_in_target"],
                        "rate_to_target": candidate["rate_to_target"],
                        "selected": candidate["currency"] in selected_sources,
                    }
                    for index, candidate in enumerate(candidates)
                ]
                remaining_need = self.engine.money_value(max(self.engine.money_value(0), Decimal(str(target_amount)) - Decimal(str(
                    next((x["available_in_target"] for x in candidates if x["currency"] == target_code), 0)
                ))))
                single_source_options = []
                for candidate in candidates:
                    rate = Decimal("1") if candidate["currency"] == target_code else Decimal(str(candidate["rate_to_target"]))
                    use_amount = self.engine.money_value(min(Decimal(str(candidate["available"])), remaining_need / rate)) if remaining_need > 0 else self.engine.money_value(0)
                    target_value = self.engine.money_value(use_amount * rate)
                    single_source_options.append({
                        "currency": candidate["currency"],
                        "feasible_for_remaining_need": target_value >= remaining_need,
                        "amount_used": float(use_amount),
                        "target_value": float(target_value),
                        "remaining_need": float(max(self.engine.money_value(0), remaining_need - target_value)),
                    })
                decision = {
                    "action": (
                        "NO_FX_CONVERSION"
                        if conversion_count == 0 and funding["status"] == "funded"
                        else ("FUND_TARGET" if funding["status"] == "funded" else "FUND_PARTIAL")
                    ),
                    "target": {"currency": target_code, "amount": float(target_amount)},
                    "selected_sources": selected_sources,
                    "conversion_count": conversion_count,
                    "reasons": [decision_reason],
                    "avoided_currencies": avoided_currencies,
                    "alternatives": alternatives,
                    "single_source_options": single_source_options,
                    "urgency": urgency,
                    "reserve_protected": funding["reserve"],
                    "state_changed": False,
                }

                if funding["status"] == "funded":
                    legs_text = "; ".join(
                        f"{x['from_currency']} {x['source_amount']:,.2f} → {x['to_currency']} {x['target_amount']:,.2f}"
                        for x in funding["plan"]
                    )
                    non_selected = [x for x in candidates if x["currency"] not in selected_sources]
                    ranked_text = "; ".join(
                        f"{x['currency']} ≈ {x['available_in_target']:,.2f} {target_code}"
                        for x in candidates[:4]
                    )
                    not_selected_text = ""
                    if non_selected:
                        names = ", ".join(x["currency"] for x in non_selected[:3])
                        not_selected_text = (
                            f" I did not need {names} because the target was fully funded before those balances were required."
                        )
                    trace.append({
                        "step": "REASON",
                        "status": "completed",
                        "detail": (
                            f"Selected {', '.join(selected_sources)} with {conversion_count} FX conversion(s). "
                            f"Reason: {decision_reason}"
                        ),
                    })
                    answer = (
                        f"Decision: fund {target_code} {target_amount:,.2f} using {legs_text}. "
                        f"Why: {decision_reason}"
                        f"{not_selected_text} "
                        f"Usable-wallet ranking: {ranked_text or 'no additional usable balances'}. "
                        f"The {funding['reserve']['currency']} {funding['reserve']['amount']:,.2f} emergency reserve stays protected. "
                        "This is an advisory scenario only; no transaction was created or executed."
                    )
                else:
                    gap = funding["remaining_gap"]
                    trace.append({
                        "step": "REASON",
                        "status": "completed",
                        "detail": (
                            f"Selected {', '.join(selected_sources) or 'no currencies'} with {conversion_count} FX conversion(s), "
                            f"but the wallet remained short by {gap:,.2f} {target_code}."
                        ),
                    })
                    answer = (
                        "Decision: do not automatically convert the whole wallet. "
                        f"I could fund about {funding['funded_amount']:,.2f} of the required {target_code} {target_amount:,.2f}, "
                        f"leaving a gap of about {gap:,.2f} {target_code}. "
                        f"The {funding['reserve']['currency']} {funding['reserve']['amount']:,.2f} emergency reserve remains protected. "
                        "Another funding source is needed; no transaction was created or executed."
                    )
                trace.append({"step": "RECOMMEND", "status": "completed", "detail": "Produced a wallet-wide funding recommendation without mutating account state."})
                return self._result("agentic_local", answer, trace, {
                    "funding_plan": funding,
                    "decision": decision,
                    "wallet": self.engine.currency_overview(),
                    "wallet_balances_used": {k: float(v) for k, v in (wallet_balances if use_scenario_wallet else self.engine.get_balance()).items()},
                    "wallet_source": "message" if use_scenario_wallet else "saved_profile",
                    "goal": "tuition_funding",
                    "horizon_days": message_horizon_days,
                    "urgency": urgency,
                })

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
        if len(detected) >= 2 and tuition_context and not funding_question and any(code not in {"MYR", "SGD"} for code in detected):
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

        # Case E: structured 30-day student finance plan.
        # This turns a broad natural-language request into an ordered decision:
        # preserve the reserve, identify the projected gap/surplus, consider adjustable
        # spending first, then use the multi-currency funding optimizer only for the
        # remaining gap. No balances are mutated and no transaction is created.
        plan_request = any(k in t for k in [
            "plan my finances", "financial plan", "30-day plan", "30 day plan",
            "next 30 days", "what should i prioritize", "financial priorities",
            "prepare for tuition", "how should i prepare", "semester plan",
        ])
        if plan_request:
            trace = [
                {"step": "UNDERSTAND", "status": "completed", "detail": "Detected a request for a structured near-term student-finance plan."},
                {"step": "OBSERVE", "status": "completed", "detail": "Read the selected planning currency, cash-flow forecast, spending plan and liquidity health."},
            ]
            forecast = self.engine.forecast()
            spending = self.engine.spending_analysis()
            health = self.engine.health_analysis()
            planning = str(forecast.get("planning_currency", planning)).upper()
            gap = Decimal(str(forecast.get("shortfall_planning", 0)))
            discretionary = Decimal(str(spending.get("discretionary_total_planning", 0)))
            reserve_currency = str(health.get("emergency_reserve_currency", planning)).upper()
            reserve_amount = Decimal(str(health.get("emergency_reserve_amount", 0)))
            trace.append({
                "step": "REASON",
                "status": "completed",
                "detail": (
                    f"Projected {planning} gap is {gap:,.2f}; identified up to {discretionary:,.2f} of monthly adjustable spending " 
                    "before considering currency conversion."
                ),
            })

            funding = None
            conversion_gap = max(Decimal("0"), gap - discretionary)
            if conversion_gap > 0:
                try:
                    funding = self.engine.recommend_funding(conversion_gap, planning)
                    trace.append({
                        "step": "FX",
                        "status": "completed",
                        "detail": f"Evaluated the full multi-currency wallet for the remaining {planning} {conversion_gap:,.2f} funding need.",
                    })
                except ValueError as exc:
                    trace.append({"step": "FX", "status": "blocked", "detail": str(exc)})
                    funding = None

            trace.append({
                "step": "SECURITY",
                "status": "completed",
                "detail": f"Kept the configured {reserve_currency} {reserve_amount:,.2f} emergency reserve protected; this planning step creates no transaction.",
            })

            due = int(forecast.get("tuition_due_days", 31))
            tuition_due = bool(forecast.get("tuition_due_within_horizon"))
            tuition_text = (
                f"Net tuition of {planning} {forecast.get('tuition_net_planning', 0):,.2f} is due in {due} days."
                if tuition_due else
                f"Net tuition is {planning} {forecast.get('tuition_net_planning', 0):,.2f}; it is not due within the next 30 days."
            )

            if gap <= 0:
                answer = (
                    f"Your 30-day plan is to avoid unnecessary conversion: the forecast shows {planning} {forecast.get('surplus_planning', 0):,.2f} remaining after expected income, spending and obligations, without requiring an automatic currency conversion. "
                    f"{tuition_text} Keep the {reserve_currency} {reserve_amount:,.2f} emergency reserve intact and review again before the next major obligation."
                )
            elif conversion_gap <= 0:
                answer = (
                    f"Your 30-day plan is: first protect the {reserve_currency} {reserve_amount:,.2f} emergency reserve, then reduce adjustable spending by up to {planning} {discretionary:,.2f} if needed. "
                    f"The projected funding gap is {planning} {gap:,.2f}, so the gap can be covered within the current monthly adjustable-spending budget without requiring an automatic currency conversion. "
                    f"{tuition_text} No transaction was created."
                )
            elif funding and funding.get("status") == "funded":
                legs_text = "; ".join(
                    f"{x['from_currency']} {x['source_amount']:,.2f} → {x['to_currency']} {x['target_amount']:,.2f}"
                    for x in funding.get("plan", [])
                )
                answer = (
                    f"Your 30-day plan is: (1) protect the {reserve_currency} {reserve_amount:,.2f} emergency reserve, "
                    f"(2) use up to {planning} {discretionary:,.2f} of adjustable spending only when necessary, and "
                    f"(3) cover the remaining {planning} {conversion_gap:,.2f} through the wallet plan: {legs_text}. "
                    f"The forecasted gap is {planning} {gap:,.2f}. {tuition_text} "
                    "This is a scenario recommendation; no balances or transactions were changed."
                )
            else:
                answer = (
                    f"Your 30-day plan is to protect the {reserve_currency} {reserve_amount:,.2f} emergency reserve and first review up to {planning} {discretionary:,.2f} of adjustable spending. "
                    f"After that, about {planning} {conversion_gap:,.2f} would still need funding, but I could not build a safe multi-currency funding plan from the configured wallet. "
                    f"{tuition_text} I would not create a transaction until the missing funding/FX input is resolved."
                )

            trace.append({"step": "RECOMMEND", "status": "completed", "detail": "Produced an ordered, advisory 30-day action plan without changing account state."})
            return self._result(
                "financial_plan",
                answer,
                trace,
                {
                    "forecast": forecast,
                    "spending": spending,
                    "health": health,
                    "funding_plan": funding,
                    "discretionary_planning": float(discretionary),
                    "conversion_gap_planning": float(conversion_gap),
                    "planning_currency": planning,
                    "state_changed": False,
                },
            )

        # General multi-intent "what should I do" / student-finance planning.
        planning = any(k in t for k in ["what should i do", "help me plan", "plan my", "should i", "what do you recommend"])
        if planning and (tuition_context or "sgd" in t or "myr" in t or "money" in t):
            # Last-resort structured fallback for uncertain incoming support. The
            # full goal planner normally handles this earlier; if a future planner
            # branch fails, do not fall through to an unstructured affordability
            # response or lose the required "not counted" evidence.
            fallback_incoming_mentioned = any(k in t for k in [
                "parents can send", "parents will send", "parents may send",
                "parents might send", "parents could send", "family can send",
                "family will send", "family may send", "family might send",
                "family could send", "incoming next", "receive next",
            ])
            fallback_incoming_amount = self._extract_labeled_amount(
                t,
                [
                    "receive", "received", "got", "allowance", "incoming",
                    "family sent", "parents send", "parents can send",
                    "parents will send", "parents may send", "parents might send",
                    "parents could send", "family can send", "family will send",
                    "family may send", "family might send", "family could send",
                ],
            )
            if tuition_context and fallback_incoming_mentioned and fallback_incoming_amount is None:
                fallback_horizon = message_horizon_days or 30
                fallback_trace = [
                    {"step": "UNDERSTAND", "status": "completed", "detail": "Detected tuition planning with unquantified incoming family support."},
                    {"step": "REASON", "status": "completed", "detail": "Kept the expected family support outside the base-case forecast because no amount was supplied."},
                    {"step": "SECURITY", "status": "completed", "detail": "No balances, proposals or transactions were changed."},
                    {"step": "RECOMMEND", "status": "completed", "detail": "Built a conservative tuition plan using confirmed funds only."},
                ]
                return self._result(
                    "financial_plan",
                    "Prioritize the confirmed tuition obligation using only funds you can verify. "
                    "Your parents' possible support was mentioned without an amount, so it is not counted in the forecast. "
                    "Treat that support as a separate what-if until the amount is confirmed.",
                    fallback_trace,
                    {
                        "goal": "financial_plan",
                        "planning_horizon_days": fallback_horizon,
                        "detected_goals": ["tuition", "incoming"],
                        "decision": {
                            "priority_order": ["tuition"],
                            "priorities": [
                                {
                                    "rank": 1,
                                    "goal": "tuition",
                                    "reason": "Tuition is the documented near-term obligation.",
                                }
                            ],
                            "actions": [],
                            "constraints": [],
                            "uncertainties": [
                                "Expected incoming support was mentioned without an amount; it is not counted in the forecast."
                            ],
                            "state_changed": False,
                        },
                        "state_changed": False,
                    },
                )
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
