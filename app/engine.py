from __future__ import annotations

from dataclasses import dataclass, asdict
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone
from typing import Any
import copy
import re
import uuid
import json
import time
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError


Q = Decimal("0.01")


def money(x: Decimal | float | int | str) -> Decimal:
    return Decimal(str(x)).quantize(Q, rounding=ROUND_HALF_UP)


FXQ = Decimal("0.00000001")

def fxrate(x: Decimal | float | int | str) -> Decimal:
    return Decimal(str(x)).quantize(FXQ, rounding=ROUND_HALF_UP)


def fmt_money(x: Decimal | float | int | str, currency: str = "") -> str:
    v = money(x)
    sign = "-" if v < 0 else ""
    n = f"{abs(v):,.2f}"
    return f"{sign}{currency}{n}"


@dataclass
class Transaction:
    id: str
    timestamp: str
    type: str
    from_currency: str
    to_currency: str
    amount: str
    description: str
    status: str


class FinanceEngine:
    """Deterministic financial engine. The AI may plan; this layer calculates and enforces policy.

    FX is refreshed from Frankfurter's public API with a short cache. If the
    network is unavailable, the engine safely falls back to the last known/demo
    rate and labels the quote accordingly.
    """

    FX_APIS = [
        "https://api.frankfurter.dev/v2/rate/myr/sgd",
        "https://api.frankfurter.dev/v2/rate/myr/sgd?providers=bnm",
        "https://api.frankfurter.dev/v2/rate/myr/sgd?providers=mas",
    ]
    FX_TTL_SECONDS = 900  # refresh at most every 15 minutes
    FX_FAILURE_COOLDOWN_SECONDS = 30  # avoid hammering a provider when offline
    FX_PAIR_TTL_SECONDS = 900

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.state = {
            "balances": {"MYR": money("30000"), "SGD": money("5000")},
            # Optional additional currency balances are user-configurable. FX for these
            # currencies is normalized as 1 UNIT = S$X so every scenario can use the
            # same cross-currency calculation engine.
            "fx_preferences": {
                "myr_mode": "live",
                "custom_myrsgd": None,
                "custom_fx_rates_to_sgd": {},
                "custom_fx_sources": {},
                "custom_fx_dates": {},
                "additional_fx_rate_modes": {},
                "auto_fx_rates_to_sgd": {},
                "auto_fx_sources": {},
                "auto_fx_dates": {},
                "auto_fx_updated_at": {},
                "auto_fx_live": {},
            },
            # Demo defaults are fully editable by the user. Real users should replace
            # these with their own balances, funding and monthly spending.
            "income_monthly_sgd": money("2576"),
            "emergency_reserve_myr": money("5000"),
            "education": {
                "tuition_semester_sgd": money("9025"),
                "scholarship_semester_sgd": money("0"),
                "loan_semester_sgd": money("0"),
                "tuition_due_days": 30,
            },
            "accommodation_monthly_sgd": money("1550"),
            "other_monthly_obligations_sgd": money("0"),
            "monthly_spending_sgd": {
                "Food & dining": money("350"),
                "Groceries": money("250"),
                "Transport": money("100"),
                "Utilities": money("100"),
                "Study materials": money("100"),
                "Personal / other": money("100"),
            },
            "spending_classifications": {
                "Food & dining": "Adjustable",
                "Groceries": "Core",
                "Transport": "Core",
                "Utilities": "Core",
                "Study materials": "Core",
                "Personal": "Adjustable",
            },
            "fx": {
                "MYRSGD": Decimal("0.3220"),
                "SGDMYR": Decimal("1") / Decimal("0.3220"),
                "source": "demo fallback",
                "rate_date": "2026-10-04",
                "updated_at": None,
                "live": False,
            },
            "fx_pair_cache": {},
            "profile_meta": {
                "planning_currency": "SGD",
                "monthly_income_amount": money("2576"),
                "monthly_income_currency": "SGD",
                "emergency_reserve_amount": money("5000"),
                "emergency_reserve_currency": "MYR",
                "tuition_amount": money("9025"),
                "tuition_currency": "SGD",
                "scholarship_amount": money("0"),
                "loan_amount": money("0"),
                "accommodation_amount": money("1550"),
                "accommodation_currency": "SGD",
                "other_obligations_amount": money("0"),
                "other_obligations_currency": "SGD",
                "monthly_spending_currency": "SGD",
            },
            # Representative 30-day SGD spending history for the demo.
            # This is intentionally richer than a handful of one-off transactions so
            # the dashboard's category analysis looks like a real student ledger.
            "transactions": [
                Transaction("TX1001", "2026-09-06T08:30:00+08:00", "expense", "SGD", "SGD", "420.00", "Accommodation", "completed"),
                Transaction("TX1002", "2026-09-08T12:10:00+08:00", "expense", "SGD", "SGD", "72.00", "Food & dining", "completed"),
                Transaction("TX1003", "2026-09-10T17:40:00+08:00", "expense", "SGD", "SGD", "45.00", "Transport", "completed"),
                Transaction("TX1004", "2026-09-12T09:00:00+08:00", "expense", "SGD", "SGD", "95.00", "Groceries", "completed"),
                Transaction("TX1005", "2026-09-13T14:00:00+08:00", "expense", "SGD", "SGD", "120.00", "Study materials", "completed"),
                Transaction("TX1006", "2026-09-15T19:15:00+08:00", "expense", "SGD", "SGD", "88.00", "Food & dining", "completed"),
                Transaction("TX1007", "2026-09-17T10:20:00+08:00", "expense", "SGD", "SGD", "80.00", "Groceries", "completed"),
                Transaction("TX1008", "2026-09-19T18:30:00+08:00", "expense", "SGD", "SGD", "65.00", "Transport", "completed"),
                Transaction("TX1009", "2026-09-21T13:10:00+08:00", "expense", "SGD", "SGD", "90.00", "Food & dining", "completed"),
                Transaction("TX1010", "2026-09-23T09:45:00+08:00", "expense", "SGD", "SGD", "100.00", "Utilities", "completed"),
                Transaction("TX1011", "2026-09-25T16:00:00+08:00", "expense", "SGD", "SGD", "75.00", "Groceries", "completed"),
                Transaction("TX1012", "2026-09-27T20:10:00+08:00", "expense", "SGD", "SGD", "100.00", "Food & dining", "completed"),
                Transaction("TX1013", "2026-09-29T17:40:00+08:00", "expense", "SGD", "SGD", "30.00", "Transport", "completed"),
                Transaction("TX1014", "2026-10-01T11:30:00+08:00", "expense", "SGD", "SGD", "50.00", "Personal", "completed"),
                Transaction("TX1015", "2026-10-03T11:15:00+08:00", "expense", "MYR", "MYR", "300.00", "Malaysia family expense", "completed"),
            ],
            "proposals": {},
            "audit": [],
        }

    def money_value(self, value: Any) -> Decimal:
        return money(value)


    def get_profile(self) -> dict[str, Any]:
        prefs = self.state.get("fx_preferences", {})
        extra = {k: float(v) for k, v in self.state["balances"].items() if k not in {"MYR", "SGD"}}
        meta = self.state.get("profile_meta", {})
        return {
            "myr_balance": float(self.state["balances"].get("MYR", 0)),
            "sgd_balance": float(self.state["balances"].get("SGD", 0)),
            "planning_currency": meta.get("planning_currency", "SGD"),
            "balances": {k: float(v) for k, v in self.state["balances"].items()},
            "monthly_income_amount": float(meta.get("monthly_income_amount", self.state["income_monthly_sgd"])),
            "monthly_income_currency": meta.get("monthly_income_currency", "SGD"),
            "emergency_reserve_amount": float(meta.get("emergency_reserve_amount", self.state["emergency_reserve_myr"])),
            "emergency_reserve_currency": meta.get("emergency_reserve_currency", "MYR"),
            "tuition_amount": float(meta.get("tuition_amount", self.state["education"]["tuition_semester_sgd"])),
            "tuition_currency": meta.get("tuition_currency", "SGD"),
            "scholarship_amount": float(meta.get("scholarship_amount", self.state["education"]["scholarship_semester_sgd"])),
            "loan_amount": float(meta.get("loan_amount", self.state["education"]["loan_semester_sgd"])),
            "accommodation_amount": float(meta.get("accommodation_amount", self.state["accommodation_monthly_sgd"])),
            "accommodation_currency": meta.get("accommodation_currency", "SGD"),
            "other_obligations_amount": float(meta.get("other_obligations_amount", self.state["other_monthly_obligations_sgd"])),
            "other_obligations_currency": meta.get("other_obligations_currency", "SGD"),
            "monthly_spending_currency": meta.get("monthly_spending_currency", "SGD"),
            "monthly_spending": {k: float(v) for k, v in (meta.get("monthly_spending") or {}).items()},
            "additional_currencies": extra,
            "monthly_income_sgd": float(self.state["income_monthly_sgd"]),
            "emergency_reserve_myr": float(self.state["emergency_reserve_myr"]),
            "tuition_semester_sgd": float(self.state["education"]["tuition_semester_sgd"]),
            "scholarship_semester_sgd": float(self.state["education"]["scholarship_semester_sgd"]),
            "loan_semester_sgd": float(self.state["education"]["loan_semester_sgd"]),
            "tuition_due_days": int(self.state["education"]["tuition_due_days"]),
            "accommodation_monthly_sgd": float(self.state["accommodation_monthly_sgd"]),
            "other_monthly_obligations_sgd": float(self.state["other_monthly_obligations_sgd"]),
            "monthly_spending_sgd": {k: float(v) for k, v in self.state["monthly_spending_sgd"].items()},
            "spending_classifications": dict(self.state.get("spending_classifications", {})),
            "myr_mode": prefs.get("myr_mode", "live"),
            "custom_myrsgd": float(prefs["custom_myrsgd"]) if prefs.get("custom_myrsgd") is not None else None,
            "custom_fx_rates_to_sgd": {k: float(v) for k, v in prefs.get("custom_fx_rates_to_sgd", {}).items()},
            "custom_fx_sources": dict(prefs.get("custom_fx_sources", {})),
            "custom_fx_dates": dict(prefs.get("custom_fx_dates", {})),
            "additional_fx_rate_modes": dict(prefs.get("additional_fx_rate_modes", {})),
            "auto_fx_rates_to_sgd": {k: float(v) for k, v in prefs.get("auto_fx_rates_to_sgd", {}).items()},
            "auto_fx_sources": dict(prefs.get("auto_fx_sources", {})),
            "auto_fx_dates": dict(prefs.get("auto_fx_dates", {})),
            "auto_fx_live": dict(prefs.get("auto_fx_live", {})),
        }

    def update_profile(self, myr_balance: Any, sgd_balance: Any, monthly_income_sgd: Any,
                       emergency_reserve_myr: Any, tuition_semester_sgd: Any,
                       scholarship_semester_sgd: Any, loan_semester_sgd: Any,
                       tuition_due_days: Any, accommodation_monthly_sgd: Any,
                       other_monthly_obligations_sgd: Any, monthly_spending_sgd: dict[str, Any],
                       spending_classifications: dict[str, Any] | None = None,
                       additional_currencies: dict[str, Any] | None = None,
                       myr_mode: str = "live", custom_myrsgd: Any | None = None,
                       custom_fx_rates_to_sgd: dict[str, Any] | None = None,
                       custom_fx_sources: dict[str, Any] | None = None,
                       custom_fx_dates: dict[str, Any] | None = None,
                       additional_fx_rate_modes: dict[str, Any] | None = None) -> dict[str, Any]:
        values = {
            "MYR": money(myr_balance), "SGD": money(sgd_balance),
            "income": money(monthly_income_sgd), "reserve": money(emergency_reserve_myr),
            "tuition": money(tuition_semester_sgd), "scholarship": money(scholarship_semester_sgd),
            "loan": money(loan_semester_sgd), "accommodation": money(accommodation_monthly_sgd),
            "other_obligations": money(other_monthly_obligations_sgd),
        }
        myr_mode = str(myr_mode or "live").strip().lower()
        if myr_mode not in {"live", "custom"}:
            raise ValueError("MYR/SGD FX mode must be live or custom.")
        custom_myr = None if custom_myrsgd in (None, "") else fxrate(custom_myrsgd)
        if myr_mode == "custom" and (custom_myr is None or custom_myr <= 0):
            raise ValueError("Enter a positive custom MYR→SGD rate when using custom mode.")
        clean_extra: dict[str, Decimal] = {}
        for raw_code, raw_balance in (additional_currencies or {}).items():
            code = str(raw_code).strip().upper()
            if code in {"MYR", "SGD"}:
                raise ValueError("MYR and SGD are already built in; use another currency for additional entries.")
            if not re.fullmatch(r"[A-Z]{3}", code):
                raise ValueError(f"Currency code '{code}' must be exactly three letters.")
            bal = money(raw_balance)
            if bal < 0:
                raise ValueError("Currency balances cannot be negative.")
            clean_extra[code] = bal
        clean_rates: dict[str, Decimal] = {}
        clean_sources: dict[str, str] = {}
        clean_dates: dict[str, str] = {}
        clean_modes: dict[str, str] = {}
        for code in clean_extra:
            raw_mode = str((additional_fx_rate_modes or {}).get(code, "custom")).strip().lower()
            if raw_mode not in {"auto", "custom"}:
                raise ValueError(f"FX mode for {code} must be auto or custom.")
            clean_modes[code] = raw_mode
            if raw_mode == "custom":
                raw_rate = (custom_fx_rates_to_sgd or {}).get(code)
                if raw_rate in (None, "", 0):
                    raise ValueError(f"Enter a positive custom SGD-normalized FX rate for {code}, or use Auto current reference.")
                rate = fxrate(raw_rate)
                if rate <= 0:
                    raise ValueError(f"FX rate for {code} must be positive.")
                clean_rates[code] = rate
                clean_sources[code] = str((custom_fx_sources or {}).get(code, "User-entered"))[:80] or "User-entered"
                clean_dates[code] = str((custom_fx_dates or {}).get(code, datetime.now().date().isoformat()))[:20]
        # Auto-mode currencies do not require a manually supplied rate. They are fetched
        # from a public reference-rate service after the profile is saved.
        due_days = int(tuition_due_days)
        if due_days < 0 or due_days > 365:
            raise ValueError("Tuition due days must be between 0 and 365.")
        if any(v < 0 for v in values.values()):
            raise ValueError("Financial profile values cannot be negative.")
        clean_spending: dict[str, Decimal] = {}
        for raw_name, raw_amount in (monthly_spending_sgd or {}).items():
            name = str(raw_name).strip()[:50]
            if not name:
                continue
            amount = money(raw_amount)
            if amount < 0:
                raise ValueError("Monthly spending values cannot be negative.")
            clean_spending[name] = amount
        if not clean_spending:
            raise ValueError("Enter at least one monthly spending category.")
        if values["scholarship"] + values["loan"] > values["tuition"]:
            raise ValueError("Scholarship plus loan cannot exceed semester tuition.")

        allowed_classes = {"Core", "Adjustable"}
        defaults = self.state.get("spending_classifications", {})
        clean_classes: dict[str, str] = {}
        for name in clean_spending:
            raw_class = (spending_classifications or {}).get(name, defaults.get(name, "Adjustable"))
            classification = str(raw_class).strip().title()
            if classification not in allowed_classes:
                raise ValueError(f"Spending classification for '{name}' must be Core or Adjustable.")
            clean_classes[name] = classification

        self.state["balances"]["MYR"] = values["MYR"]
        self.state["balances"]["SGD"] = values["SGD"]
        self.state["income_monthly_sgd"] = values["income"]
        self.state["emergency_reserve_myr"] = values["reserve"]
        self.state["education"] = {
            "tuition_semester_sgd": values["tuition"],
            "scholarship_semester_sgd": values["scholarship"],
            "loan_semester_sgd": values["loan"],
            "tuition_due_days": due_days,
        }
        self.state["accommodation_monthly_sgd"] = values["accommodation"]
        self.state["other_monthly_obligations_sgd"] = values["other_obligations"]
        self.state["monthly_spending_sgd"] = clean_spending
        self.state["spending_classifications"] = clean_classes
        self.state["balances"] = {"MYR": values["MYR"], "SGD": values["SGD"], **clean_extra}
        previous_prefs = self.state.get("fx_preferences", {})
        self.state["fx_preferences"] = {
            "myr_mode": myr_mode,
            "custom_myrsgd": custom_myr,
            "custom_fx_rates_to_sgd": clean_rates,
            "custom_fx_sources": clean_sources,
            "custom_fx_dates": clean_dates,
            "additional_fx_rate_modes": clean_modes,
            "auto_fx_rates_to_sgd": dict(previous_prefs.get("auto_fx_rates_to_sgd", {})),
            "auto_fx_sources": dict(previous_prefs.get("auto_fx_sources", {})),
            "auto_fx_dates": dict(previous_prefs.get("auto_fx_dates", {})),
            "auto_fx_updated_at": dict(previous_prefs.get("auto_fx_updated_at", {})),
            "auto_fx_live": dict(previous_prefs.get("auto_fx_live", {})),
        }
        for key in ("auto_fx_rates_to_sgd", "auto_fx_sources", "auto_fx_dates", "auto_fx_updated_at", "auto_fx_live"):
            self.state["fx_preferences"][key] = {k: v for k, v in self.state["fx_preferences"][key].items() if k in clean_extra}
        if any(mode == "auto" for mode in clean_modes.values()):
            self.refresh_auto_fx(force=True)
        self.audit("PROFILE_UPDATED", {"profile": self.get_profile(), "source": "manual user input"})
        return {"ok": True, "profile": self.get_profile(), "state": self.snapshot()}

    def _profile_rate_to_sgd(self, currency: str) -> Decimal:
        code = str(currency or "SGD").strip().upper()
        if code == "SGD":
            return Decimal("1")
        if code == "MYR":
            return self._selected_myrsgd_rate()
        prefs = self.state.get("fx_preferences", {})
        if prefs.get("additional_fx_rate_modes", {}).get(code) == "custom":
            rate = prefs.get("custom_fx_rates_to_sgd", {}).get(code)
            if rate is None:
                raise ValueError(f"No custom FX rate to SGD is configured for {code}.")
            return fxrate(rate)
        if code in self.state.get("balances", {}):
            rate, _ = self._currency_rate_to_sgd(code)
            return rate
        meta = self._fetch_reference_pair(code, "SGD")
        return fxrate(meta["rate"])

    def update_profile_general(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Currency-first profile update.

        The selected planning currency is the user's reporting/forecast currency. Balances
        may contain arbitrary three-letter currencies. Trusted calculations are normalized
        internally to SGD and then presented back in the planning currency.
        """
        def clean_code(value: Any, label: str) -> str:
            code = str(value or "").strip().upper()
            if not re.fullmatch(r"[A-Z]{3}", code):
                raise ValueError(f"{label} must be a 3-letter ISO currency code.")
            return code

        planning = clean_code(payload.get("planning_currency", "SGD"), "Planning currency")
        raw_balances = payload.get("balances") or {}
        if not isinstance(raw_balances, dict) or not raw_balances:
            raise ValueError("Add at least one currency balance.")
        balances: dict[str, Decimal] = {}
        for raw_code, raw_balance in raw_balances.items():
            code = clean_code(raw_code, "Currency code")
            bal = money(raw_balance)
            if bal < 0:
                raise ValueError("Currency balances cannot be negative.")
            balances[code] = bal
        if planning not in balances:
            raise ValueError(f"Your planning currency ({planning}) must have a balance row.")

        raw_modes = payload.get("balance_fx_modes") or {}
        raw_custom_rates = payload.get("custom_fx_rates_to_sgd") or {}
        raw_sources = payload.get("custom_fx_sources") or {}
        raw_dates = payload.get("custom_fx_dates") or {}
        fx_modes: dict[str, str] = {}
        custom_rates: dict[str, Decimal] = {}
        custom_sources: dict[str, str] = {}
        custom_dates: dict[str, str] = {}
        # Wallet currencies always get a normal FX mode. Also preserve explicitly
        # supplied custom quotes for scenario-only currencies: local-agent messages may
        # introduce CNY/USD/etc. that are not part of the saved wallet, while tests and
        # demos may intentionally provide deterministic quotes for those hypothetical
        # currencies. These quotes must not be silently discarded.
        fx_codes = set(balances) | set(raw_modes) | set(raw_custom_rates)
        for code in fx_codes:
            code = clean_code(code, "Currency code")
            if code == "SGD":
                continue
            mode = str(raw_modes.get(code, "custom" if code in raw_custom_rates else "auto")).strip().lower()
            if mode not in {"auto", "custom"}:
                raise ValueError(f"FX mode for {code} must be auto or custom.")
            fx_modes[code] = mode
            if mode == "custom":
                raw_rate = raw_custom_rates.get(code)
                if raw_rate in (None, "") or fxrate(raw_rate) <= 0:
                    raise ValueError(f"Enter a positive quoted FX rate for {code}, or switch to Auto current reference.")
                custom_rates[code] = fxrate(raw_rate)
                custom_sources[code] = str(raw_sources.get(code, "User-entered"))[:80] or "User-entered"
                custom_dates[code] = str(raw_dates.get(code, datetime.now().date().isoformat()))[:20]
        myr_mode = fx_modes.get("MYR", "auto") if "MYR" in balances else "auto"
        custom_myr = custom_rates.get("MYR") if myr_mode == "custom" else None
        self.state["balances"] = balances
        self.state["fx_preferences"] = {
            "myr_mode": "live" if myr_mode == "auto" else "custom",
            "custom_myrsgd": custom_myr,
            "custom_fx_rates_to_sgd": {k: v for k, v in custom_rates.items() if k != "MYR"},
            "custom_fx_sources": custom_sources,
            "custom_fx_dates": custom_dates,
            "additional_fx_rate_modes": {k: v for k, v in fx_modes.items() if k not in {"MYR", "SGD"}},
            "auto_fx_rates_to_sgd": {},
            "auto_fx_sources": {},
            "auto_fx_dates": {},
            "auto_fx_updated_at": {},
            "auto_fx_live": {},
        }
        if myr_mode == "custom":
            self.state["fx"]["MYRSGD"] = custom_myr
            self.state["fx"]["SGDMYR"] = Decimal("1") / custom_myr
            self.state["fx"]["source"] = custom_sources.get("MYR", "User-entered")
            self.state["fx"]["rate_date"] = custom_dates.get("MYR")
            self.state["fx"]["live"] = False
        else:
            self.refresh_fx(force=True)
        if any(v == "auto" for k, v in fx_modes.items() if k not in {"MYR", "SGD"}):
            self.refresh_auto_fx(force=True)

        def amount_field(name: str, default: float = 0.0) -> Decimal:
            value_d = money(payload.get(name, default))
            if value_d < 0:
                raise ValueError(f"{name} cannot be negative.")
            return value_d

        income_amount = amount_field("monthly_income_amount")
        income_currency = clean_code(payload.get("monthly_income_currency", planning), "Income currency")
        reserve_amount = amount_field("emergency_reserve_amount")
        reserve_currency = clean_code(payload.get("emergency_reserve_currency", planning), "Emergency reserve currency")
        tuition_amount = amount_field("tuition_amount")
        tuition_currency = clean_code(payload.get("tuition_currency", planning), "Tuition currency")
        scholarship_amount = amount_field("scholarship_amount")
        loan_amount = amount_field("loan_amount")
        accommodation_amount = amount_field("accommodation_amount")
        accommodation_currency = clean_code(payload.get("accommodation_currency", planning), "Accommodation currency")
        other_amount = amount_field("other_obligations_amount")
        other_currency = clean_code(payload.get("other_obligations_currency", planning), "Other obligations currency")
        due_days = int(payload.get("tuition_due_days", 30))
        if due_days < 0 or due_days > 365:
            raise ValueError("Tuition due days must be between 0 and 365.")
        if scholarship_amount + loan_amount > tuition_amount:
            raise ValueError("Scholarship plus loan cannot exceed semester tuition.")

        def to_sgd(amount: Decimal, currency: str) -> Decimal:
            return money(amount * self._profile_rate_to_sgd(currency))

        self.state["income_monthly_sgd"] = to_sgd(income_amount, income_currency)
        reserve_sgd = to_sgd(reserve_amount, reserve_currency)
        myr_rate = self._profile_rate_to_sgd("MYR")
        self.state["emergency_reserve_myr"] = money(reserve_sgd / myr_rate)
        self.state["education"] = {
            "tuition_semester_sgd": to_sgd(tuition_amount, tuition_currency),
            "scholarship_semester_sgd": to_sgd(scholarship_amount, tuition_currency),
            "loan_semester_sgd": to_sgd(loan_amount, tuition_currency),
            "tuition_due_days": due_days,
        }
        self.state["accommodation_monthly_sgd"] = to_sgd(accommodation_amount, accommodation_currency)
        self.state["other_monthly_obligations_sgd"] = to_sgd(other_amount, other_currency)

        raw_spending = payload.get("monthly_spending") or {}
        if not isinstance(raw_spending, dict) or not raw_spending:
            raise ValueError("Enter at least one monthly spending category.")
        spend_currency = clean_code(payload.get("monthly_spending_currency", planning), "Monthly spending currency")
        clean_spending: dict[str, Decimal] = {}
        for raw_name, raw_amount in raw_spending.items():
            name = str(raw_name).strip()[:50]
            if not name:
                continue
            amount_d = money(raw_amount)
            if amount_d < 0:
                raise ValueError("Monthly spending values cannot be negative.")
            clean_spending[name] = to_sgd(amount_d, spend_currency)
        if not clean_spending:
            raise ValueError("Enter at least one monthly spending category.")
        allowed_classes = {"Core", "Adjustable"}
        incoming_classes = payload.get("spending_classifications") or {}
        clean_classes: dict[str, str] = {}
        for name in clean_spending:
            classification = str(incoming_classes.get(name, "Adjustable")).strip().title()
            if classification not in allowed_classes:
                raise ValueError(f"Spending classification for '{name}' must be Core or Adjustable.")
            clean_classes[name] = classification
        self.state["monthly_spending_sgd"] = clean_spending
        self.state["spending_classifications"] = clean_classes
        self.state["profile_meta"] = {
            "planning_currency": planning,
            "monthly_income_amount": income_amount,
            "monthly_income_currency": income_currency,
            "emergency_reserve_amount": reserve_amount,
            "emergency_reserve_currency": reserve_currency,
            "tuition_amount": tuition_amount,
            "tuition_currency": tuition_currency,
            "scholarship_amount": scholarship_amount,
            "loan_amount": loan_amount,
            "accommodation_amount": accommodation_amount,
            "accommodation_currency": accommodation_currency,
            "other_obligations_amount": other_amount,
            "other_obligations_currency": other_currency,
            "monthly_spending_currency": spend_currency,
            "monthly_spending": {k: money(v) for k, v in (raw_spending or {}).items()},
        }
        self.audit("PROFILE_UPDATED", {"profile": self.get_profile(), "source": "currency-first manual user input"})
        return {"ok": True, "profile": self.get_profile(), "state": self.snapshot()}

    def get_obligations(self) -> list[dict[str, Any]]:
        edu = self.state["education"]
        meta = self.state.get("profile_meta", {})
        planning = str(meta.get("planning_currency", "SGD")).upper()
        planning_rate = self._profile_rate_to_sgd(planning)
        net_tuition = money(edu["tuition_semester_sgd"] - edu["scholarship_semester_sgd"] - edu["loan_semester_sgd"])
        obligations = []
        if edu["tuition_due_days"] <= 30 and net_tuition > 0:
            obligations.append({"id": "TUITION-USER", "name": "Next semester tuition (net of funding)", "amount_sgd": net_tuition, "amount_planning": money(net_tuition / planning_rate), "currency": planning, "days": edu["tuition_due_days"], "critical": True})
        other = money(self.state["other_monthly_obligations_sgd"])
        if other > 0:
            obligations.append({"id": "OTHER-MONTHLY", "name": "Other monthly obligations", "amount_sgd": other, "amount_planning": money(other / planning_rate), "currency": planning, "days": 30, "critical": True})
        return obligations


    def recommend_funding(self, target_amount: float | Decimal, target_currency: str, balances_override: dict[str, Any] | None = None) -> dict[str, Any]:
        """Recommend a minimum-conversion funding plan from the saved multi-currency wallet.

        The engine is deterministic: use the target-currency balance first, protect the
        configured emergency reserve, then draw from the largest remaining currency values
        until the target is covered. No account balances are mutated.
        """
        target = target_currency.upper().strip()
        required = money(target_amount)
        if required <= 0:
            raise ValueError("Target amount must be positive.")
        if not re.fullmatch(r"[A-Z]{3}", target):
            raise ValueError("Target currency must be a 3-letter ISO code.")

        meta = self.state.get("profile_meta", {})
        reserve_currency = str(meta.get("emergency_reserve_currency", "MYR")).upper()
        reserve_amount = money(meta.get("emergency_reserve_amount", self.state.get("emergency_reserve_myr", 0)))
        balances = self.state.get("balances", {}) if balances_override is None else {str(k).upper().strip(): money(v) for k, v in balances_override.items()}

        candidates: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []

        for code, balance in balances.items():
            bal = money(balance)
            if bal <= 0:
                continue

            protected = reserve_amount if code == reserve_currency else money(0)
            available = money(max(money(0), bal - protected))
            if available <= 0:
                continue

            try:
                if code == target:
                    rate = Decimal("1")
                    conversion = {
                        "amount": float(available),
                        "from_currency": code,
                        "to_currency": target,
                        "converted_amount": float(available),
                        "rate": 1.0,
                        "fx": {"source": "Existing target-currency balance", "rate_date": None, "live": False, "mode": "same_currency"},
                    }
                else:
                    from_rate, from_meta = self._currency_rate_to_sgd(code)
                    target_rate, target_meta = self._currency_rate_to_sgd(target)
                    rate = fxrate(from_rate / target_rate)
                    conversion = {
                        "amount": float(available),
                        "from_currency": code,
                        "to_currency": target,
                        "converted_amount": float(money(available * rate)),
                        "rate": float(rate),
                        "fx": {
                            "source_from": from_meta.get("source"),
                            "source_to": target_meta.get("source"),
                            "date_from": from_meta.get("rate_date"),
                            "date_to": target_meta.get("rate_date"),
                            "live_from": from_meta.get("live", False),
                            "live_to": target_meta.get("live", False),
                            "method": "cross-rate via SGD",
                        },
                    }
                value = money(conversion["converted_amount"])
            except ValueError as exc:
                skipped.append({"currency": code, "reason": str(exc)})
                continue

            candidates.append({
                "currency": code,
                "balance": float(bal),
                "protected_reserve": float(protected),
                "available": float(available),
                "available_in_target": float(value),
                "rate_to_target": float(rate),
                "fx": conversion.get("fx", {}),
            })

        # Prefer funds already denominated in the target currency, then the largest
        # remaining target-equivalent balances. This reduces the number of conversions.
        candidates.sort(key=lambda x: (x["currency"] != target, -x["available_in_target"]))

        remaining = required
        plan: list[dict[str, Any]] = []
        for candidate in candidates:
            if remaining <= 0:
                break
            source = candidate["currency"]
            if source == target:
                source_needed = money(min(Decimal(str(candidate["available"])), remaining))
                target_value = source_needed
                rate = Decimal("1")
            else:
                rate = fxrate(candidate["rate_to_target"])
                source_needed = money(min(
                    Decimal(str(candidate["available"])),
                    remaining / rate,
                ))
                target_value = money(source_needed * rate)

            if source_needed <= 0 or target_value <= 0:
                continue

            plan.append({
                "from_currency": source,
                "source_amount": float(source_needed),
                "to_currency": target,
                "target_amount": float(target_value),
                "rate": float(rate),
                "remaining_target_after": float(money(max(money(0), remaining - target_value))),
                "fx": candidate.get("fx", {}) if source != target else {
                    "source": "Existing target-currency balance",
                    "rate_date": None,
                    "live": False,
                    "mode": "same_currency",
                },
            })
            remaining = money(max(money(0), remaining - target_value))

        funded = money(required - remaining)
        available_total = sum((money(x["available_in_target"]) for x in candidates), money(0))
        status = "funded" if remaining <= 0 else "partial"

        return {
            "target_amount": float(required),
            "target_currency": target,
            "status": status,
            "funded_amount": float(funded),
            "remaining_gap": float(remaining),
            "available_total_in_target": float(available_total),
            "plan": plan,
            "candidates": candidates,
            "skipped": skipped,
            "reserve": {
                "currency": reserve_currency,
                "amount": float(reserve_amount),
                "protected": True,
            },
            "strategy": "Use target-currency funds first, protect the emergency reserve, then minimize the number of source-currency conversions using largest available target-equivalent balances.",
            "state_changed": False,
            "note": "Indicative FX scenario only; no balances are mutated and no transaction is created.",
        }

    def convert_currency(self, amount: float | Decimal, from_currency: str, to_currency: str) -> dict[str, Any]:
        """Scenario conversion using the selected wallet rates when available, otherwise a direct reference pair."""
        base = from_currency.upper().strip()
        quote = to_currency.upper().strip()
        if base == quote:
            return self.quote_conversion(amount, base, quote, custom_rate=1)
        # Prefer user-selected/custom wallet rates whenever both currencies are in the
        # user's wallet. This keeps scenario conversions consistent with the profile.
        if base in self.state["balances"] and quote in self.state["balances"]:
            from_rate, from_meta = self._currency_rate_to_sgd(base)
            to_rate, to_meta = self._currency_rate_to_sgd(quote)
            rate = fxrate(from_rate / to_rate)
            amount_d = money(amount)
            return {
                "amount": float(amount_d), "from_currency": base, "to_currency": quote,
                "converted_amount": float(money(amount_d * rate)), "rate": float(rate),
                "rate_to_sgd_from": float(from_rate), "rate_to_sgd_to": float(to_rate),
                "fx": {"source_from": from_meta["source"], "source_to": to_meta["source"],
                       "date_from": from_meta.get("rate_date"), "date_to": to_meta.get("rate_date"),
                       "live_from": from_meta.get("live", False), "live_to": to_meta.get("live", False),
                       "method": "cross-rate via SGD"}
            }
        # Otherwise fetch the exact pair directly; this allows requests such as CNY → MYR
        # even when the user has not added CNY to their wallet yet.
        return self.quote_conversion(amount, base, quote)


    def _fetch_reference_pair(self, from_currency: str, to_currency: str, force: bool = False) -> dict[str, Any]:
        """Fetch/cache a direct reference FX quote for any 3-letter currency pair."""
        base = from_currency.upper().strip()
        quote = to_currency.upper().strip()
        if not re.fullmatch(r"[A-Z]{3}", base) or not re.fullmatch(r"[A-Z]{3}", quote):
            raise ValueError("Currency codes must be 3-letter ISO codes.")
        if base == quote:
            return {"base": base, "quote": quote, "rate": 1.0, "date": None, "source": "Same currency", "live": False,
                    "updated_at": datetime.now(timezone.utc).isoformat()}
        key = f"{base}/{quote}"
        cache = self.state.setdefault("fx_pair_cache", {})
        cached = cache.get(key)
        now = time.time()
        if cached and not force:
            try:
                age = now - datetime.fromisoformat(cached.get("updated_at", "")).timestamp()
                if age < self.FX_PAIR_TTL_SECONDS:
                    return dict(cached)
            except (ValueError, TypeError, OSError):
                pass
        api = f"https://api.frankfurter.dev/v2/rate/{base.lower()}/{quote.lower()}"
        last_error = None
        try:
            req = Request(api, headers={"User-Agent": "BorderWise-AI/7.3"})
            with urlopen(req, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
            raw = payload.get("rate")
            rate = fxrate(Decimal(str(raw)))
            if rate <= 0:
                raise ValueError("non-positive FX rate")
            data = {
                "base": base,
                "quote": quote,
                "rate": float(rate),
                "date": payload.get("date"),
                "source": "Frankfurter reference rate",
                "live": True,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            cache[key] = data
            self.audit("FX_PAIR_REFRESH", {"pair": key, "rate": float(rate), "rate_date": data.get("date"), "source": data["source"]})
            return data
        except (HTTPError, URLError, TimeoutError, OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
            last_error = exc
        if cached:
            fallback = dict(cached)
            fallback["live"] = False
            fallback["source"] = "last known reference rate"
            fallback["error"] = type(last_error).__name__ if last_error else "unknown"
            return fallback

        # Offline resilience for common currencies used in the judge/demo flows.
        # These are explicitly non-live indicative references, not settlement quotes.
        # The live provider remains the preferred source whenever reachable.
        bundled_fallbacks = {
            ("CNY", "SGD"): (0.1908, "2026-10-06"),
            ("USD", "SGD"): (1.2771, "2026-10-06"),
            ("MYR", "SGD"): (0.3220, "2026-10-04"),
        }
        bundled = bundled_fallbacks.get((base, quote))
        if bundled is not None:
            rate, date = bundled
            data = {
                "base": base,
                "quote": quote,
                "rate": rate,
                "date": date,
                "source": "bundled demo reference fallback",
                "live": False,
                "mode": "bundled_fallback",
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "error": type(last_error).__name__ if last_error else "unknown",
            }
            cache[key] = data
            return data

        raise ValueError(f"Reference FX for {base}→{quote} is currently unavailable. Try again or enter a quoted rate.")

    def quote_conversion(self, amount: float | Decimal, from_currency: str, to_currency: str,
                         custom_rate: float | Decimal | None = None, force: bool = False) -> dict[str, Any]:
        amount_d = money(amount)
        base = from_currency.upper().strip()
        quote = to_currency.upper().strip()
        if amount_d <= 0:
            raise ValueError("Conversion amount must be positive.")
        if custom_rate is not None:
            rate = fxrate(custom_rate)
            if rate <= 0:
                raise ValueError("Custom FX rate must be positive.")
            meta = {"base": base, "quote": quote, "rate": float(rate), "date": datetime.now().date().isoformat(),
                    "source": "User-entered quoted rate", "live": False, "updated_at": None}
            mode = "custom"
        else:
            meta = self._fetch_reference_pair(base, quote, force=force)
            rate = fxrate(meta["rate"])
            mode = "auto_reference"
        converted = money(amount_d * rate)
        return {
            "amount": float(amount_d),
            "from_currency": base,
            "to_currency": quote,
            "rate": float(rate),
            "converted_amount": float(converted),
            "fx": {
                "source": meta.get("source"),
                "rate_date": meta.get("date"),
                "live": bool(meta.get("live")),
                "mode": mode,
                "updated_at": meta.get("updated_at"),
            },
        }

    def simulate_income_impact(self, amount: float | Decimal, currency: str) -> dict[str, Any]:
        amount_d = money(amount)
        currency = currency.upper().strip()
        if amount_d <= 0:
            raise ValueError("Income amount must be positive.")
        if currency not in self.state["balances"]:
            raise ValueError(f"Currency {currency} is not configured in the user's wallet.")
        before = self.forecast()
        if currency == "SGD":
            added_sgd = amount_d
            converted = None
        else:
            conv = self.convert_currency(amount_d, currency, "SGD")
            added_sgd = money(conv["converted_amount"])
            converted = conv
        after_projected = money(Decimal(str(before["projected_balance_sgd"])) + added_sgd)
        return {
            "hypothetical_only": True,
            "state_changed": False,
            "income": {"amount": float(amount_d), "currency": currency},
            "forecast_before": before,
            "projected_added_sgd": float(added_sgd),
            "projected_balance_after_hypothetical_income_sgd": float(after_projected),
            "projected_shortfall_after_hypothetical_income_sgd": float(max(money(0), -after_projected)),
            "conversion_if_non_sgd": converted,
        }

        # ---------- read tools ----------
    def get_balance(self) -> dict[str, float]:
        return {k: float(v) for k, v in self.state["balances"].items()}

    def get_transactions(self, limit: int = 20) -> list[dict[str, Any]]:
        return [asdict(t) for t in self.state["transactions"][-limit:]][::-1]

    def forecast(self) -> dict[str, Any]:
        meta = self.state.get("profile_meta", {})
        planning = str(meta.get("planning_currency", "SGD")).upper()
        planning_rate = self._profile_rate_to_sgd(planning)
        start = money(self.state["balances"].get(planning, money(0)) * planning_rate)
        income = money(self.state["income_monthly_sgd"])
        variable_spending = sum(self.state["monthly_spending_sgd"].values(), money(0))
        accommodation = money(self.state["accommodation_monthly_sgd"])
        monthly_spending = money(variable_spending + accommodation)
        obligations = sum((money(x["amount_sgd"]) for x in self.get_obligations()), money(0))
        projected = money(start + income - monthly_spending - obligations)
        shortfall = max(money(0), -projected)
        surplus = max(money(0), projected)
        edu = self.state["education"]
        net_tuition = money(edu["tuition_semester_sgd"] - edu["scholarship_semester_sgd"] - edu["loan_semester_sgd"])
        tuition_due_within_horizon = int(edu["tuition_due_days"]) <= 30 and net_tuition > 0
        display = lambda x: money(Decimal(str(x)) / planning_rate)
        return {
            "horizon_days": 30,
            "planning_currency": planning,
            "starting_sgd": float(start), "starting_planning": float(display(start)),
            "expected_income_sgd": float(income), "expected_income_planning": float(display(income)),
            "variable_spending_sgd": float(variable_spending), "variable_spending_planning": float(display(variable_spending)),
            "accommodation_sgd": float(accommodation), "accommodation_planning": float(display(accommodation)),
            "monthly_spending_sgd": float(monthly_spending), "monthly_spending_planning": float(display(monthly_spending)),
            "obligations_sgd": float(obligations), "obligations_planning": float(display(obligations)),
            "tuition_gross_sgd": float(edu["tuition_semester_sgd"]), "tuition_gross_planning": float(display(edu["tuition_semester_sgd"])),
            "tuition_funding_sgd": float(edu["scholarship_semester_sgd"] + edu["loan_semester_sgd"]), "tuition_funding_planning": float(display(edu["scholarship_semester_sgd"] + edu["loan_semester_sgd"])),
            "tuition_net_sgd": float(net_tuition), "tuition_net_planning": float(display(net_tuition)),
            "tuition_due_days": int(edu["tuition_due_days"]), "tuition_due_within_horizon": tuition_due_within_horizon,
            "projected_balance_sgd": float(projected), "projected_balance_planning": float(display(projected)),
            "shortfall_sgd": float(shortfall), "shortfall_planning": float(display(shortfall)),
            "surplus_sgd": float(surplus), "surplus_planning": float(display(surplus)),
            "cash_position": "funding_gap" if shortfall > 0 else "surplus",
            "calculation": f"starting {planning} balance + expected 30-day income − 30-day spending − obligations due within 30 days, normalized for arithmetic.",
        }

    def forecast_portfolio(self, horizon_days: int = 30, balances_override: dict[str, Any] | None = None) -> dict[str, Any]:
        """Forecast liquidity using the full multi-currency wallet, not only the planning-currency balance."""
        horizon = int(horizon_days)
        if horizon <= 0 or horizon > 365:
            raise ValueError("Forecast horizon must be between 1 and 365 days.")

        meta = self.state.get("profile_meta", {})
        planning = str(meta.get("planning_currency", "SGD")).upper()
        planning_rate = self._profile_rate_to_sgd(planning)

        balances = (
            self.state.get("balances", {})
            if balances_override is None
            else {str(k).upper().strip(): money(v) for k, v in balances_override.items()}
        )
        reserve_currency = str(meta.get("emergency_reserve_currency", "MYR")).upper()
        reserve_amount = money(meta.get("emergency_reserve_amount", self.state.get("emergency_reserve_myr", 0)))
        starting_sgd = money(0)
        protected_reserve_sgd = money(0)
        valuation_rows: list[dict[str, Any]] = []
        for code, balance in balances.items():
            bal = money(balance)
            if bal <= 0:
                continue
            rate, fx_meta = self._currency_rate_to_sgd(code)
            value_sgd = money(bal * rate)
            starting_sgd += value_sgd
            if code == reserve_currency and reserve_amount > 0:
                protected_reserve_sgd = money(
                    min(bal, reserve_amount) * rate
                )
            valuation_rows.append({
                "currency": code,
                "balance": float(bal),
                "sgd_value": float(value_sgd),
                "rate_to_sgd": float(rate),
                "fx_source": fx_meta.get("source"),
                "fx_date": fx_meta.get("rate_date"),
                "fx_live": bool(fx_meta.get("live", False)),
            })

        # Monthly income/spending are stored as normalized SGD values.
        monthly_income_sgd = money(self.state.get("income_monthly_sgd", 0))
        monthly_spending_sgd = money(
            sum(self.state.get("monthly_spending_sgd", {}).values(), money(0))
            + self.state.get("accommodation_monthly_sgd", 0)
        )
        obligations_sgd = sum(
            (
                money(x["amount_sgd"])
                for x in self.get_obligations()
                if int(x.get("days", horizon)) <= horizon
            ),
            money(0),
        )

        # Scale recurring income and spending proportionally when a horizon differs from 30 days.
        horizon_factor = Decimal(str(horizon)) / Decimal("30")
        usable_starting_sgd = money(
            max(money(0), starting_sgd - protected_reserve_sgd)
        )
        projected_sgd = money(
            usable_starting_sgd
            + monthly_income_sgd * horizon_factor
            - monthly_spending_sgd * horizon_factor
            - obligations_sgd
        )
        display = lambda x: money(Decimal(str(x)) / planning_rate)

        return {
            "horizon_days": horizon,
            "planning_currency": planning,
            "starting_portfolio_sgd": float(starting_sgd),
            "starting_portfolio_planning": float(display(starting_sgd)),
            "protected_reserve_sgd": float(protected_reserve_sgd),
            "protected_reserve_planning": float(display(protected_reserve_sgd)),
            "usable_starting_sgd": float(usable_starting_sgd),
            "usable_starting_planning": float(display(usable_starting_sgd)),
            "expected_income_sgd": float(money(monthly_income_sgd * horizon_factor)),
            "expected_income_planning": float(display(monthly_income_sgd * horizon_factor)),
            "spending_sgd": float(money(monthly_spending_sgd * horizon_factor)),
            "spending_planning": float(display(monthly_spending_sgd * horizon_factor)),
            "obligations_sgd": float(obligations_sgd),
            "obligations_planning": float(display(obligations_sgd)),
            "projected_balance_sgd": float(projected_sgd),
            "projected_balance_planning": float(display(projected_sgd)),
            "cash_position": "funding_gap" if projected_sgd < 0 else "surplus",
            "emergency_reserve": {
                "currency": reserve_currency,
                "configured_amount": float(reserve_amount),
                "protected_value_sgd": float(protected_reserve_sgd),
                "met": money(balances.get(reserve_currency, 0)) >= reserve_amount,
            },
            "wallet_valuation": valuation_rows,
            "method": (
                "Full-wallet indicative valuation in the selected planning currency, "
                "plus expected income, minus proportional living costs and obligations within the horizon."
            ),
            "note": "Scenario planning only; FX rates and bank settlement outcomes may differ.",
        }


    def spending_analysis(self) -> dict[str, Any]:
        meta = self.state.get("profile_meta", {})
        planning = str(meta.get("planning_currency", "SGD")).upper()
        planning_rate = self._profile_rate_to_sgd(planning)
        categories = {k: money(v) for k, v in self.state["monthly_spending_sgd"].items()}
        accommodation = money(self.state["accommodation_monthly_sgd"])
        if accommodation > 0:
            categories["Accommodation"] = accommodation
        total = sum(categories.values(), money(0))
        classifications = dict(self.state.get("spending_classifications", {})); classifications["Accommodation"] = "Core"
        core_total = sum((v for k, v in categories.items() if classifications.get(k, "Adjustable") == "Core"), money(0))
        adjustable_total = money(total - core_total)
        ranked = sorted(categories.items(), key=lambda kv: kv[1], reverse=True)
        return {
            "period_days": 30, "source": "manual monthly user estimates", "currency": planning,
            "total_sgd": float(total), "total_planning": float(money(total / planning_rate)),
            "daily_average_sgd": float(money(total / Decimal(30))) if total else 0.0,
            "daily_average_planning": float(money(total / planning_rate / Decimal(30))) if total else 0.0,
            "core_total_sgd": float(core_total), "core_total_planning": float(money(core_total / planning_rate)),
            "discretionary_total_sgd": float(adjustable_total), "discretionary_total_planning": float(money(adjustable_total / planning_rate)),
            "core_share": round(float(core_total / total * 100), 1) if total else 0.0,
            "discretionary_share": round(float(adjustable_total / total * 100), 1) if total else 0.0,
            "categories": [
                {"category": k, "amount_sgd": float(v), "amount_planning": float(money(v / planning_rate)),
                 "share": round(float(v / total * 100), 1) if total else 0.0,
                 "classification": classifications.get(k, "Adjustable"),
                 "classification_source": "user" if k != "Accommodation" and k in self.state.get("spending_classifications", {}) else "default"}
                for k, v in ranked
            ],
        }

    def health_analysis(self) -> dict[str, Any]:
        """Transparent, deterministic liquidity health indicator; not a credit score."""
        f = self.forecast()
        start_plus_income = money(Decimal(str(f["starting_sgd"])) + Decimal(str(f["expected_income_sgd"])))
        monthly_spending = money(f["monthly_spending_sgd"])
        projected = money(f["projected_balance_sgd"])
        reserve = money(self.state["emergency_reserve_myr"])
        profile_meta = self.state.get("profile_meta", {})
        reserve_currency = str(profile_meta.get("emergency_reserve_currency", "MYR")).upper()
        reserve_amount = money(profile_meta.get("emergency_reserve_amount", reserve))
        reserve_balance = money(self.state["balances"].get(reserve_currency, money(0)))
        obligations = money(f["obligations_sgd"])

        if projected < 0:
            liquidity_penalty = min(45, 28 + float(abs(projected) / max(monthly_spending, money(1)) * 17))
            liquidity_label = "Funding gap"
        elif monthly_spending <= 0:
            liquidity_penalty = 0
            liquidity_label = "No planned monthly spending"
        else:
            buffer_months = float(projected / monthly_spending)
            if buffer_months < 0.5:
                liquidity_penalty, liquidity_label = 28, "Very thin buffer"
            elif buffer_months < 1:
                liquidity_penalty, liquidity_label = 18, "Thin buffer"
            elif buffer_months < 1.5:
                liquidity_penalty, liquidity_label = 10, "Moderate buffer"
            elif buffer_months < 2:
                liquidity_penalty, liquidity_label = 5, "Healthy buffer"
            else:
                liquidity_penalty, liquidity_label = 0, "Strong buffer"

        reserve_penalty = 20 if reserve_balance < reserve_amount else 0
        available_ratio = float(obligations / max(start_plus_income, money(1))) if start_plus_income > 0 else 1.0
        obligation_penalty = min(12.0, max(0.0, available_ratio * 12.0))
        score = max(0, min(100, int(round(100 - liquidity_penalty - reserve_penalty - obligation_penalty))))
        if score >= 80:
            label = "Strong liquidity position"
        elif score >= 65:
            label = "Healthy, but watch near-term needs"
        elif score >= 50:
            label = "Watch upcoming cash needs"
        else:
            label = "Action recommended: funding gap or reserve pressure"
        return {
            "score": score,
            "label": label,
            "liquidity_penalty": round(liquidity_penalty, 1),
            "reserve_penalty": reserve_penalty,
            "obligation_penalty": round(obligation_penalty, 1),
            "buffer_months": round(float(projected / monthly_spending), 2) if monthly_spending > 0 else None,
            "buffer_label": liquidity_label,
            "emergency_reserve_met": reserve_balance >= reserve_amount,
            "emergency_reserve_currency": reserve_currency,
            "emergency_reserve_amount": float(reserve_amount),
            "emergency_reserve_balance": float(reserve_balance),
            "projected_balance_sgd": float(projected),
            "monthly_spending_sgd": float(monthly_spending),
            "obligations_sgd": float(obligations),
            "method": "100 minus transparent liquidity, reserve and obligation-pressure penalties; not a credit score.",
        }


    def _selected_myrsgd_rate(self) -> Decimal:
        prefs = self.state.get("fx_preferences", {})
        if prefs.get("myr_mode") == "custom" and prefs.get("custom_myrsgd") is not None:
            return fxrate(prefs["custom_myrsgd"])
        return fxrate(self.state["fx"]["MYRSGD"])

    def _currency_rate_to_sgd(self, currency: str) -> tuple[Decimal, dict[str, Any]]:
        code = currency.upper().strip()
        if code == "SGD":
            return Decimal("1"), {"source": "Base currency", "rate_date": None, "live": False}
        if code == "MYR":
            prefs = self.state.get("fx_preferences", {})
            if prefs.get("myr_mode") == "custom":
                return self._selected_myrsgd_rate(), {
                    "source": prefs.get("custom_fx_sources", {}).get("MYR", "User-entered"),
                    "rate_date": prefs.get("custom_fx_dates", {}).get("MYR"),
                    "live": False,
                }
            fx = self.state["fx"]
            return fxrate(fx["MYRSGD"]), {"source": fx.get("source", "Frankfurter reference rate"), "rate_date": fx.get("rate_date"), "live": bool(fx.get("live"))}
        prefs = self.state.get("fx_preferences", {})
        additional_modes = prefs.get("additional_fx_rate_modes", {})
        additional_custom = prefs.get("custom_fx_rates_to_sgd", {})
        # Currencies that appear only in a hypothetical chat scenario have no
        # saved per-currency configuration. Fetch a direct reference pair for
        # those scenario-only currencies instead of requiring a profile row.
        mode = additional_modes.get(code, "auto")
        if code not in additional_modes and code not in additional_custom:
            meta = self._fetch_reference_pair(code, "SGD")
            return fxrate(meta["rate"]), {
                "source": meta.get("source", "Frankfurter reference rate"),
                "rate_date": meta.get("date"),
                "live": bool(meta.get("live", False)),
                "mode": "scenario_reference",
            }
        if mode == "auto":
            self.refresh_auto_fx(codes=[code])
            rate = prefs.get("auto_fx_rates_to_sgd", {}).get(code)
            if rate is None:
                raise ValueError(f"Live reference FX for {code}/SGD is currently unavailable. Choose a custom rate or retry later.")
            return fxrate(rate), {
                "source": prefs.get("auto_fx_sources", {}).get(code, "Frankfurter reference rate"),
                "rate_date": prefs.get("auto_fx_dates", {}).get(code),
                "live": bool(prefs.get("auto_fx_live", {}).get(code, False)),
                "mode": "auto",
            }
        rate = prefs.get("custom_fx_rates_to_sgd", {}).get(code)
        if rate is None:
            raise ValueError(f"No FX rate to SGD is configured for {code}.")
        return fxrate(rate), {
            "source": prefs.get("custom_fx_sources", {}).get(code, "User-entered"),
            "rate_date": prefs.get("custom_fx_dates", {}).get(code),
            "live": False,
            "mode": "custom",
        }

    def currency_overview(self) -> dict[str, Any]:
        meta = self.state.get("profile_meta", {})
        planning = str(meta.get("planning_currency", "SGD")).upper()
        planning_rate = self._profile_rate_to_sgd(planning)
        rows=[]; total_sgd=money(0)
        for code, bal in self.state["balances"].items():
            rate, meta_rate = self._currency_rate_to_sgd(code)
            value_sgd=money(bal*rate); total_sgd += value_sgd
            rows.append({"currency": code, "balance": float(bal), "rate_to_sgd": float(rate), "rate_to_planning": float(fxrate(rate / planning_rate)), "sgd_value": float(value_sgd),
                         "planning_value": float(money(value_sgd / planning_rate)), "planning_currency": planning, **meta_rate})
        return {
            "base_currency": planning, "planning_currency": planning,
            "total_indicative_sgd": float(total_sgd), "total_indicative_planning": float(money(total_sgd / planning_rate)),
            "currencies": rows,
            "method": f"Each currency is valued in SGD, then converted to the user's planning currency ({planning}) for comparison.",
            "note": "Indicative scenario valuation only; actual bank/remittance settlement rates and fees may differ.",
        }

    def refresh_fx(self, force: bool = False) -> dict[str, Any]:
        """Refresh MYR→SGD reference rate from Frankfurter when cache is stale."""
        fx = self.state["fx"]
        now = time.time()
        updated_at = fx.get("updated_at")
        if not force and updated_at:
            try:
                age = now - datetime.fromisoformat(updated_at).timestamp()
                if fx.get("live") and age < self.FX_TTL_SECONDS:
                    return self.fx_quote()
                if not fx.get("live") and age < self.FX_FAILURE_COOLDOWN_SECONDS:
                    return self.fx_quote()
            except (ValueError, TypeError, OSError):
                pass

        last_error = None
        for api in self.FX_APIS:
            try:
                req = Request(api, headers={"User-Agent": "BorderWise-AI/4.1"})
                with urlopen(req, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                rate = fxrate(Decimal(str(payload["rate"])))
                if rate <= 0:
                    raise ValueError("non-positive FX rate")
                fx["MYRSGD"] = rate
                fx["SGDMYR"] = Decimal("1") / rate
                fx["live_source"] = "Frankfurter reference rate" if "providers=" not in api else api.split("providers=")[-1].upper() + " provider via Frankfurter"
                fx["source"] = fx["live_source"]
                fx["rate_date"] = payload.get("date")
                fx["updated_at"] = datetime.now(timezone.utc).isoformat()
                fx["live"] = True
                fx.pop("error", None)
                self.audit("FX_REFRESH", {
                    "pair": "MYR/SGD",
                    "rate": float(rate),
                    "rate_date": fx["rate_date"],
                    "source": fx["source"],
                })
                return self.fx_quote()
            except (HTTPError, URLError, TimeoutError, OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
                last_error = exc
                continue
        # Keep the last known rate. Never fabricate a new rate when the provider is unavailable.
        fx["source"] = "last known/demo fallback"
        fx["live"] = False
        fx["updated_at"] = datetime.now(timezone.utc).isoformat()
        fx["error"] = type(last_error).__name__ if last_error else "unknown"
        return self.fx_quote()


    def refresh_auto_fx(self, force: bool = False, codes: list[str] | None = None) -> dict[str, Any]:
        """Fetch current reference rates for additional auto currencies in one batch.

        Frankfurter's rates endpoint can request multiple quotes at once. We use SGD as
        the base and invert each quote so BorderWise stores 1 UNIT = S$X.
        """
        prefs = self.state.get("fx_preferences", {})
        balances = self.state.get("balances", {})
        modes = prefs.get("additional_fx_rate_modes", {})
        targets = [c for c in balances if c not in {"MYR", "SGD"} and modes.get(c) == "auto"]
        if codes is not None:
            wanted = {c.upper().strip() for c in codes}
            targets = [c for c in targets if c in wanted]
        if not targets:
            return {"ok": True, "rates": {}, "source": "No auto currencies configured", "live": False}
        now = time.time(); due=[]
        for code in targets:
            updated = prefs.get("auto_fx_updated_at", {}).get(code)
            try: age = now - datetime.fromisoformat(updated).timestamp() if updated else float("inf")
            except (ValueError, TypeError, OSError): age = float("inf")
            if force or not prefs.get("auto_fx_live", {}).get(code, False) or age >= self.FX_TTL_SECONDS:
                due.append(code)
        if not due:
            return {"ok": True, "rates": {c: float(prefs["auto_fx_rates_to_sgd"][c]) for c in targets if c in prefs.get("auto_fx_rates_to_sgd", {})}, "source": "cached reference rates", "live": True}
        api="https://api.frankfurter.dev/v2/rates?base=sgd&quotes=" + ",".join(sorted(due))
        try:
            req=Request(api, headers={"User-Agent":"BorderWise-AI/7.1"})
            with urlopen(req, timeout=5) as response:
                payload=json.loads(response.read().decode("utf-8"))
            rows=payload if isinstance(payload,list) else []
            by_code={str(row.get("quote","")).upper():row for row in rows if isinstance(row,dict)}
            refreshed={}; missing=[]
            for code in due:
                row=by_code.get(code); raw=row.get("rate") if row else None
                if raw in (None,0): missing.append(code); continue
                sgd_per_unit=fxrate(Decimal("1")/Decimal(str(raw)))
                if sgd_per_unit <= 0: missing.append(code); continue
                prefs.setdefault("auto_fx_rates_to_sgd",{})[code]=sgd_per_unit
                prefs.setdefault("auto_fx_sources",{})[code]="Frankfurter reference rate"
                prefs.setdefault("auto_fx_dates",{})[code]=row.get("date")
                prefs.setdefault("auto_fx_updated_at",{})[code]=datetime.now(timezone.utc).isoformat()
                prefs.setdefault("auto_fx_live",{})[code]=True
                refreshed[code]=float(sgd_per_unit)
                self.audit("AUTO_FX_REFRESH", {"pair":f"{code}/SGD","rate_to_sgd":float(sgd_per_unit),"rate_date":row.get("date"),"source":"Frankfurter reference rate"})
            for code in missing: prefs.setdefault("auto_fx_live",{})[code]=False
            return {"ok":True,"rates":refreshed,"missing":missing,"source":"Frankfurter reference rate","live":bool(refreshed)}
        except (HTTPError, URLError, TimeoutError, OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
            for code in due: prefs.setdefault("auto_fx_live",{})[code]=False
            return {"ok":True,"rates":{c:float(prefs.get("auto_fx_rates_to_sgd",{}).get(c,0)) for c in targets if c in prefs.get("auto_fx_rates_to_sgd",{})},"source":"last known reference rate","live":False,"error":type(exc).__name__}


    def fx_quote(self, amount_myr: Decimal | None = None) -> dict[str, Any]:
        prefs = self.state.get("fx_preferences", {})
        rate = self._selected_myrsgd_rate()
        fx = self.state["fx"]
        amount = amount_myr or money("1000")
        custom = prefs.get("myr_mode") == "custom"
        source = prefs.get("custom_fx_sources", {}).get("MYR", "User-entered") if custom else fx.get("source", "demo fallback")
        date = prefs.get("custom_fx_dates", {}).get("MYR") if custom else fx.get("rate_date")
        return {
            "pair": "MYR/SGD",
            "rate": float(rate),
            "inverse_rate_sgd_myr": float((Decimal("1") / rate).quantize(FXQ, rounding=ROUND_HALF_UP)),
            "example_myr": float(amount),
            "example_sgd": float(money(amount * rate)),
            "source": source,
            "rate_date": date,
            "updated_at": fx.get("updated_at"),
            "live": bool(fx.get("live")) and not custom,
            "mode": "custom" if custom else "live_reference",
            "live_reference_rate": float(fxrate(fx.get("MYRSGD", rate))),
            "live_reference_source": fx.get("live_source", fx.get("source", "demo fallback")),
            "live_reference_date": fx.get("rate_date"),
            "note": "Reference/mid-market or user-entered scenario rate; actual bank or remittance rates may differ.",
        }

        # ---------- safety / transaction tools ----------
    def risk_check(self, amount_myr: Decimal, purpose: str) -> dict[str, Any]:
        amount_myr = money(amount_myr)
        # A multi-currency wallet may legitimately contain no MYR balance.
        # Treat that as zero available MYR instead of raising a KeyError.
        balance = money(self.state.get("balances", {}).get("MYR", 0))
        reserve = money(self.state.get("emergency_reserve_myr", 0))
        reasons: list[str] = []
        risk = "LOW"

        if amount_myr <= 0:
            reasons.append("Amount must be positive.")
            risk = "BLOCKED"
        if amount_myr > balance:
            reasons.append("Amount exceeds MYR balance.")
            risk = "BLOCKED"
        if balance - amount_myr < reserve:
            reasons.append(f"Transfer would breach the RM{reserve:,.2f} emergency reserve.")
            risk = "BLOCKED"
        if amount_myr > money("15000"):
            reasons.append("Amount exceeds the demo high-value threshold.")
            if risk != "BLOCKED":
                risk = "REVIEW"
        if re.search(r"\ball\b|\beverything\b|\b全部\b", purpose, re.I):
            reasons.append("Requests to transfer all available funds are blocked; specify an exact amount.")
            risk = "BLOCKED"

        return {
            "status": risk,
            "amount_myr": float(amount_myr),
            "remaining_myr": float(balance - amount_myr),
            "reserve_myr": float(reserve),
            "reasons": reasons,
            "requires_level": 2,
        }

    def create_proposal(self, amount_myr: Decimal, purpose: str = "student finance transfer") -> dict[str, Any]:
        amount_myr = money(amount_myr)
        risk = self.risk_check(amount_myr, purpose)
        if risk["status"] == "BLOCKED":
            raise ValueError("; ".join(risk["reasons"]))
        self.refresh_fx()
        rate = self.state["fx"]["MYRSGD"]
        amount_sgd = money(amount_myr * rate)
        pid = "P-" + uuid.uuid4().hex[:8].upper()
        proposal = {
            "id": pid,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "from": "MYR",
            "to": "SGD",
            "amount_myr": float(amount_myr),
            "amount_sgd": float(amount_sgd),
            "rate": float(rate),
            "purpose": purpose,
            "risk": risk,
            "permission_level": 2,
            "status": "PENDING_AUTHORIZATION",
        }
        self.state["proposals"][pid] = proposal
        self.audit("PROPOSAL_CREATED", proposal)
        return proposal

    def authorize(self, proposal_id: str, approved: bool) -> dict[str, Any]:
        proposal = self.state["proposals"].get(proposal_id)
        if not proposal:
            raise ValueError("Proposal not found.")
        if proposal["status"] != "PENDING_AUTHORIZATION":
            raise ValueError("Proposal is no longer awaiting authorization.")
        proposal["status"] = "AUTHORIZED" if approved else "REJECTED"
        self.audit("AUTHORIZATION", {"proposal_id": proposal_id, "approved": approved})
        if not approved:
            return proposal
        return proposal

    def execute(self, proposal_id: str) -> dict[str, Any]:
        proposal = self.state["proposals"].get(proposal_id)
        if not proposal:
            raise ValueError("Proposal not found.")
        if proposal["status"] != "AUTHORIZED":
            raise ValueError("Execution requires explicit Level 2 authorization.")

        amount_myr = money(proposal["amount_myr"])
        amount_sgd = money(proposal["amount_sgd"])
        risk = self.risk_check(amount_myr, proposal["purpose"])
        if risk["status"] == "BLOCKED":
            proposal["status"] = "BLOCKED"
            self.audit("EXECUTION_BLOCKED", {"proposal_id": proposal_id, "risk": risk})
            raise ValueError("; ".join(risk["reasons"]))

        self.state["balances"]["MYR"] = money(self.state["balances"]["MYR"] - amount_myr)
        self.state["balances"]["SGD"] = money(self.state["balances"]["SGD"] + amount_sgd)

        tx = Transaction(
            "TX-" + uuid.uuid4().hex[:8].upper(),
            datetime.now(timezone.utc).isoformat(),
            "conversion",
            "MYR",
            "SGD",
            f"{amount_myr:.2f}",
            proposal["purpose"],
            "completed",
        )
        self.state["transactions"].append(tx)
        proposal["status"] = "EXECUTED"
        proposal["transaction_id"] = tx.id
        self.audit("EXECUTED", {"proposal_id": proposal_id, "transaction_id": tx.id})
        return {"proposal": proposal, "transaction": asdict(tx), "balances": self.get_balance()}

    def audit(self, event: str, details: dict[str, Any]) -> None:
        self.state["audit"].append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "details": details,
        })

    def audit_log(self) -> list[dict[str, Any]]:
        return list(reversed(self.state["audit"]))

    # ---------- agent ----------
    def detect_intent(self, text: str) -> str:
        t = text.lower().strip()
        if any(k in t for k in ["help", "what can you do", "capabilities"]):
            return "help"
        if any(k in t for k in ["biggest expense", "spending", "spend", "expenses", "where did i spend"]):
            return "spending"
        if any(k in t for k in ["exchange rate", "fx", "convert", "conversion", "exchange myr", "exchange sgd", "how much myr do i need", "myr do i need", "sgd to myr"]):
            return "fx"
        if any(k in t for k in ["transfer", "send money", "remit", "remittance", "send myr", "send sgd", "pay"]):
            return "transfer"
        if any(k in t for k in ["afford", "tuition", "fees", "enough money", "enough for"]):
            return "affordability"
        if any(k in t for k in ["forecast", "run out", "cash flow", "cashflow", "next month", "future balance"]):
            return "forecast"
        if any(k in t for k in ["balance", "how much money", "how much do i have", "account"]):
            return "balance"
        if any(k in t for k in ["transaction", "recent payment", "recent transactions", "history"]):
            return "transactions"
        return "general"

    def extract_myr_amount(self, text: str) -> Decimal | None:
        patterns = [
            r"(?:rm|myr)\s*([0-9][0-9,]*(?:\.[0-9]+)?)",
            r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:rm|myr)\b",
        ]
        for p in patterns:
            m = re.search(p, text.lower())
            if m:
                return money(m.group(1).replace(",", ""))
        return None

    def extract_sgd_amount(self, text: str) -> Decimal | None:
        patterns = [
            r"(?:s\$|sgd)\s*([0-9][0-9,]*(?:\.[0-9]+)?)",
            r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:s\$|sgd)\b",
        ]
        for p in patterns:
            m = re.search(p, text.lower())
            if m:
                return money(m.group(1).replace(",", ""))
        return None

    def extract_generic_currency_amount(self, text: str) -> tuple[Decimal, str] | None:
        m = re.search(r"(?:^|\s)([A-Za-z]{3})\s*([0-9][0-9,]*(?:\.[0-9]+)?)\b|(?:^|\s)([0-9][0-9,]*(?:\.[0-9]+)?)\s*([A-Za-z]{3})(?:\s|$)", text)
        if not m:
            return None
        code = (m.group(1) or m.group(4)).upper()
        value = m.group(2) or m.group(3)
        return money(value.replace(',', '')), code

    def extract_conversion_pair(self, text: str) -> tuple[str, str] | None:
        t = text.upper()
        patterns = [
            r"\b([A-Z]{3})\s*(?:TO|→|->)\s*([A-Z]{3})\b",
            r"\b([A-Z]{3})\s+(?:INTO|IN)\s+([A-Z]{3})\b",
            r"\bFROM\s+([A-Z]{3})\s+TO\s+([A-Z]{3})\b",
        ]
        for p in patterns:
            m = re.search(p, t)
            if m:
                return m.group(1), m.group(2)
        names = {"RMB":"CNY", "YUAN":"CNY", "RENMINBI":"CNY", "RINGGIT":"MYR", "SINGAPORE DOLLARS":"SGD", "DOLLARS":"USD"}
        for a,b in names.items():
            for c,d in names.items():
                if a == c: continue
                if re.search(rf"\b{re.escape(a)}\b.*\b{re.escape(c)}\b", t):
                    return b,d
        return None

    def agent(self, text: str) -> dict[str, Any]:
        # Safety-critical deterministic gate: uncertain family support must never
        # reach an LLM planner as if it were confirmed cash. Keep this path
        # self-contained so a local-agent exception cannot silently fall through.
        normalized = str(text).lower().strip()
        conditional_income_question = (
            any(k in normalized for k in [
                "can i assume", "assume that money", "assume the money", "count that money",
                "treat that money", "can i count it", "can i count that",
            ])
            and any(k in normalized for k in ["might", "may", "could", "possibly", "maybe"])
            and any(k in normalized for k in ["parent", "parents", "family"])
        )
        if conditional_income_question:
            return self._result(
                "agentic_local",
                "No. Treat that money as conditional, not confirmed, until it is actually received or otherwise reliably committed. "
                "For tuition planning, BorderWise should not count conditional family support as available funds. "
                "You can model the possible amount separately as a what-if scenario, but it must not be treated as confirmed cash.",
                [
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
                ],
                {
                    "conditional_income": True,
                    "state_changed": False,
                    "agent_mode": "deterministic_safety_gate",
                },
            )

        # Deterministic portfolio-valuation gate.
        # Simple explicit multi-currency valuation questions must never depend on
        # the optional LLM or the broader local planner.
        valuation_markers = [
            "how much is that worth", "worth in sgd", "total in sgd",
            "total worth", "total wealth", "what is that worth in sgd",
            "how much do i have in sgd",
        ]
        currency_aliases = {
            "SGD": ["sgd"],
            "CNY": ["cny", "rmb", "yuan"],
            "USD": ["usd", "us$"],
            "MYR": ["myr", "rm"],
            "JPY": ["jpy", "yen"],
            "KRW": ["krw", "won"],
            "THB": ["thb", "baht"],
            "EUR": ["eur", "euro", "euros"],
            "GBP": ["gbp", "pound", "pounds"],
            "AUD": ["aud"],
            "CAD": ["cad"],
            "HKD": ["hkd"],
            "TWD": ["twd"],
            "INR": ["inr"],
        }
        explicit_wallet = {}
        for code, aliases in currency_aliases.items():
            escaped = sorted((re.escape(x) for x in aliases), key=len, reverse=True)
            alias_pattern = "|".join(escaped)
            match = re.search(
                rf"(?:\b(?:{alias_pattern})\b|(?:{alias_pattern}))\s*([0-9][0-9,]*(?:\.[0-9]+)?)",
                normalized,
                re.IGNORECASE,
            )
            if not match:
                match = re.search(
                    rf"([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:\b(?:{alias_pattern})\b|(?:{alias_pattern}))",
                    normalized,
                    re.IGNORECASE,
                )
            if match:
                explicit_wallet[code] = money(match.group(1).replace(",", ""))

        if any(marker in normalized for marker in valuation_markers) and len(explicit_wallet) >= 2:
            total_sgd = money(0)
            lines = []
            try:
                for code, amount in explicit_wallet.items():
                    if code == "SGD":
                        rate = Decimal("1")
                        value = amount
                    else:
                        rate, _ = self._currency_rate_to_sgd(code)
                        value = money(amount * rate)
                    total_sgd = money(total_sgd + value)
                    if code == "SGD":
                        lines.append(f"SGD {amount:,.2f} = SGD {value:,.2f}")
                    else:
                        lines.append(
                            f"{code} {amount:,.2f} ≈ SGD {value:,.2f} at 1 {code} = {rate:.8f} SGD"
                        )
            except (ValueError, HTTPError, URLError, TimeoutError, OSError) as exc:
                return self._result(
                    "agentic_local",
                    f"I can see all of the balances, but I cannot safely calculate the SGD total right now because the reference FX quote for one of the currencies is unavailable ({type(exc).__name__}). No account state was changed. Add a quoted FX rate for the missing currency or retry when reference FX is available.",
                    [
                        {"step": "UNDERSTAND", "status": "completed", "detail": "Detected an explicit multi-currency portfolio valuation request."},
                        {"step": "FX", "status": "blocked", "detail": f"Reference FX was unavailable: {type(exc).__name__}."},
                        {"step": "SECURITY", "status": "completed", "detail": "No state was changed and no transaction was created."},
                    ],
                    {
                        "valuation": {
                            "currency": "SGD",
                            "balances": {k: float(v) for k, v in explicit_wallet.items()},
                            "state_changed": False,
                        },
                        "blocked_reason": "reference_fx_unavailable",
                        "agent_mode": "deterministic_portfolio_valuation",
                    },
                )

            trace = [
                {
                    "step": "UNDERSTAND",
                    "status": "completed",
                    "detail": "Detected an explicit multi-currency portfolio valuation request.",
                },
                {
                    "step": "FX",
                    "status": "completed",
                    "detail": "Valued every explicitly stated currency using the deterministic SGD reference-rate path.",
                },
                {
                    "step": "CALCULATE",
                    "status": "completed",
                    "detail": f"Total stated portfolio value: SGD {total_sgd:,.2f}.",
                },
            ]
            answer = (
                "Your stated balances are approximately:\n"
                + "\n".join(lines)
                + f"\n\nTotal ≈ SGD {total_sgd:,.2f}. "
                "FX quotes are indicative and may differ from bank settlement rates or fees."
            )
            return self._result(
                "agentic_local",
                answer,
                trace,
                {
                    "valuation": {
                        "currency": "SGD",
                        "total": float(total_sgd),
                        "balances": {k: float(v) for k, v in explicit_wallet.items()},
                    },
                    "state_changed": False,
                    "agent_mode": "deterministic_portfolio_valuation",
                },
            )

        # Deterministic contradictory-transfer gate.
        # If the same message explicitly says not to transfer and then asks for
        # a transfer, do not choose the later/dangerous fragment. Require the
        # user to resolve the contradiction before creating any proposal.
        contradictory_transfer = (
            any(k in normalized for k in [
                "don't transfer", "do not transfer", "dont transfer",
                "don't send", "do not send", "dont send",
                "don't remit", "do not remit", "dont remit",
            ])
            and any(k in normalized for k in [
                "transfer rm", "send rm", "remit rm", "transfer myr",
                "send myr", "remit myr",
            ])
        )
        if contradictory_transfer:
            return self._result(
                "agentic_local",
                "Your message contains conflicting transfer instructions: it says not to transfer anything and also asks for a transfer. I will not create a proposal until you clearly confirm which instruction you want. No transaction or proposal was created.",
                [
                    {"step": "UNDERSTAND", "status": "completed", "detail": "Detected contradictory transfer instructions."},
                    {"step": "REASON", "status": "completed", "detail": "Refused to resolve the contradiction by choosing the more permissive or later instruction."},
                    {"step": "SECURITY", "status": "blocked", "detail": "No proposal or transaction was created while the instruction remained ambiguous."},
                ],
                {
                    "contradictory_instruction": True,
                    "state_changed": False,
                    "agent_mode": "deterministic_contradiction_gate",
                },
            )

        # Deterministic tuition + emergency-reserve affordability gate.
        # This must run before any action/transfer planner because wording such as
        # "I need to pay tuition" describes an obligation, not an instruction to
        # execute a transfer. If the user asks whether they are okay while naming
        # an explicit reserve target, answer the planning question directly.
        tuition_reserve_question = (
            "tuition" in normalized
            and "emergency reserve" in normalized
            and any(k in normalized for k in [
                "am i okay", "am i ok", "will i be okay", "will i be ok",
                "can i afford", "is it affordable", "do i have enough",
                "can i cover", "can i manage",
            ])
        )
        if tuition_reserve_question:
            sgd_values = [
                money(m.replace(",", ""))
                for m in re.findall(
                    r"(?:sgd|s\$)\s*([0-9][0-9,]*(?:\.[0-9]+)?)",
                    normalized,
                    re.IGNORECASE,
                )
            ]
            if len(sgd_values) >= 3:
                # In this phrasing the first amount is the wallet, the second is
                # tuition, and the third is the requested emergency reserve.
                starting_balance, tuition_amount, reserve_target = sgd_values[:3]
                remaining = money(starting_balance - tuition_amount)
                reserve_gap = money(max(Decimal("0"), reserve_target - remaining))
                reserve_met = reserve_gap == 0
                if reserve_met:
                    answer = (
                        f"Yes. You can cover the SGD {tuition_amount:,.2f} tuition and "
                        f"still have SGD {remaining:,.2f} left, meeting your SGD {reserve_target:,.2f} emergency-reserve target."
                    )
                else:
                    answer = (
                        f"Not fully. You can cover the SGD {tuition_amount:,.2f} tuition, "
                        f"but you would have SGD {remaining:,.2f} left, which is "
                        f"SGD {reserve_gap:,.2f} below your SGD {reserve_target:,.2f} emergency-reserve target."
                    )
                return self._result(
                    "agentic_local",
                    answer + " This is an affordability simulation only; no transaction was created or executed.",
                    [
                        {"step": "UNDERSTAND", "status": "completed", "detail": "Detected a tuition affordability question with an explicit emergency-reserve target."},
                        {"step": "CALCULATE", "status": "completed", "detail": f"Compared SGD {remaining:,.2f} remaining after tuition against the SGD {reserve_target:,.2f} reserve target."},
                        {"step": "SECURITY", "status": "completed", "detail": "No transfer, proposal, authorization or account-state change was performed."},
                    ],
                    {
                        "goal": "financial_plan",
                        "affordability": {
                            "starting_balance_sgd": float(starting_balance),
                            "tuition_sgd": float(tuition_amount),
                            "remaining_sgd": float(remaining),
                            "reserve_target_sgd": float(reserve_target),
                            "reserve_gap_sgd": float(reserve_gap),
                            "reserve_met": reserve_met,
                        },
                        "state_changed": False,
                        "agent_mode": "deterministic_tuition_reserve_gate",
                    },
                )

        # Deterministic cross-currency transfer safety gate.
        # A request such as "I have SGD 2,000. Send RM10,000 home while
        # protecting my emergency reserve" must be evaluated against the stated
        # SGD wallet before any proposal is created. The legacy risk_check()
        # operates on MYR balances, so it cannot safely assess an SGD-funded
        # remittance by itself.
        risk_aware_transfer = (
            any(k in normalized for k in ["send", "transfer", "remit", "remittance"])
            and any(k in normalized for k in ["emergency reserve", "emergency fund", "protecting my reserve", "protect the reserve"])
        )
        explicit_myr = self.extract_myr_amount(text)
        explicit_sgd = self.extract_sgd_amount(text)
        if risk_aware_transfer and explicit_myr is not None and explicit_sgd is not None:
            try:
                myr_to_sgd, _ = self._currency_rate_to_sgd("MYR")
                required_sgd = money(explicit_myr * myr_to_sgd)
                if required_sgd > explicit_sgd:
                    shortfall_sgd = money(required_sgd - explicit_sgd)
                    return self._result(
                        "agentic_local",
                        f"Blocked. RM{explicit_myr:,.2f} would require approximately SGD {required_sgd:,.2f} "
                        f"at the current reference rate, but you stated only SGD {explicit_sgd:,.2f}. "
                        f"That leaves a funding shortfall of about SGD {shortfall_sgd:,.2f}, so XKF5 will not prepare the transfer. "
                        "No transaction or proposal was created.",
                        [
                            {"step": "UNDERSTAND", "status": "completed", "detail": "Detected a remittance request with an explicit SGD funding wallet and emergency-reserve protection constraint."},
                            {"step": "CALCULATE", "status": "completed", "detail": f"Compared the SGD cost of RM{explicit_myr:,.2f} against the stated SGD {explicit_sgd:,.2f} wallet."},
                            {"step": "SECURITY", "status": "blocked", "detail": "Transfer was blocked before proposal creation because the stated wallet cannot fund the requested amount."},
                        ],
                        {
                            "risk": {
                                "status": "BLOCKED",
                                "requested_myr": float(explicit_myr),
                                "required_sgd": float(required_sgd),
                                "stated_sgd": float(explicit_sgd),
                                "shortfall_sgd": float(shortfall_sgd),
                            },
                            "state_changed": False,
                            "agent_mode": "deterministic_cross_currency_transfer_gate",
                        },
                    )
            except (ValueError, HTTPError, URLError, TimeoutError, OSError):
                return self._result(
                    "agentic_local",
                    "I cannot safely prepare that transfer because the required MYR→SGD reference quote is unavailable. No transaction or proposal was created.",
                    [
                        {"step": "UNDERSTAND", "status": "completed", "detail": "Detected a cross-currency remittance with a reserve-protection constraint."},
                        {"step": "SECURITY", "status": "blocked", "detail": "Blocked proposal creation because the funding conversion could not be verified safely."},
                    ],
                    {"state_changed": False, "agent_mode": "deterministic_cross_currency_transfer_gate"},
                )

        # v5: optional LLM tool-calling planner. The deterministic engine remains the
        # fallback and the authority for calculations, policy and execution.
        try:
            from .agent import AgentOrchestrator
            llm_result = AgentOrchestrator(self).run(text)
            if llm_result is not None:
                return llm_result
        except Exception:
            pass

        # Offline local planner: enables genuine multi-step tool selection without an external API.
        try:
            from .local_agent import LocalAgentPlanner
            local_result = LocalAgentPlanner(self).run(text)
            if local_result is not None:
                return local_result
        except Exception:
            pass

        intent = self.detect_intent(text)
        trace = []
        trace.append({"step": "UNDERSTAND", "status": "completed", "detail": f"Detected intent: {intent}"})

        if intent == "balance":
            b = self.get_balance()
            trace.append({"step": "OBSERVE", "status": "completed", "detail": "Retrieved MYR and SGD balances."})
            answer = f"You currently have RM{b['MYR']:,.2f} and S${b['SGD']:,.2f} in the demo accounts."
            return self._result(intent, answer, trace, {"balances": b})

        if intent == "transactions":
            tx = self.get_transactions()
            trace.append({"step": "OBSERVE", "status": "completed", "detail": "Retrieved recent transaction history."})
            answer = "Here are your latest transactions: " + "; ".join(f"{x['description']} {x['from_currency']}{float(x['amount']):,.2f}" for x in tx[:6])
            return self._result(intent, answer, trace, {"transactions": tx})

        if intent == "spending":
            data = self.spending_analysis()
            trace.append({"step": "OBSERVE", "status": "completed", "detail": f"Grouped the user's monthly spending plan in {data.get('currency','SGD')}."})
            top = data["categories"][0] if data["categories"] else None
            cur = data.get("currency", "SGD")
            answer = f"Your planned monthly spending is {cur}{data['total_planning']:,.2f}."
            if top:
                answer += f" Your largest category is {top['category']} at {cur}{top['amount_planning']:,.2f} ({top['share']:.1f}%)."
            return self._result(intent, answer, trace, {"spending": data})

        if intent == "forecast":
            f = self.forecast()
            trace += [
                {"step": "OBSERVE", "status": "completed", "detail": f"Retrieved balance, income and obligations in {f.get('planning_currency','SGD')}."},
                {"step": "REASON", "status": "completed", "detail": "Calculated the 30-day projected liquidity in the selected planning currency."},
            ]
            cur = f.get("planning_currency", "SGD")
            if f["shortfall_sgd"] > 0:
                answer = f"Your 30-day projection shows a {cur}{f['shortfall_planning']:,.2f} funding gap. Projected balance after obligations is {cur}{f['projected_balance_planning']:,.2f}."
            else:
                answer = f"Your 30-day projection is healthy, with {cur}{f['projected_balance_planning']:,.2f} remaining after expected income, living costs and obligations."
            return self._result(intent, answer, trace, {"forecast": f})

        if intent == "fx":
            q = self.refresh_fx()
            trace.append({"step": "OBSERVE", "status": "completed", "detail": f"Retrieved MYR/SGD reference rate from {q['source']}."})
            freshness = f"rate date {q['rate_date']}" if q.get('rate_date') else "rate date unavailable"
            status = "live reference data" if q.get("live") else "fallback/last-known data"
            sgd_amount = self.extract_sgd_amount(text)
            myr_amount = self.extract_myr_amount(text)
            pair = self.extract_conversion_pair(text)
            generic_amount = self.extract_generic_currency_amount(text)
            if pair and generic_amount:
                amount_generic, generic_currency = generic_amount
                base, quote = pair
                # Prefer the explicit amount currency when the pair was stated as text.
                if generic_currency != base and generic_currency in {base, "RMB", "YUAN"}:
                    base = generic_currency
                if base == "RMB": base = "CNY"
                if quote == "RMB": quote = "CNY"
                try:
                    conv = self.quote_conversion(amount_generic, base, quote)
                    trace.append({"step":"CALCULATE","status":"completed","detail":f"Converted {amount_generic:,.2f} {base} to approximately {conv['converted_amount']:,.2f} {quote} using the selected reference rate."})
                    freshness = f"rate date {conv['fx'].get('rate_date')}" if conv['fx'].get('rate_date') else "rate date unavailable"
                    answer = (f"At the current reference rate, 1 {base} = {conv['rate']:.6f} {quote} ({freshness}), "
                              f"{amount_generic:,.2f} {base} is approximately {conv['converted_amount']:,.2f} {quote}. "
                              f"Source: {conv['fx']['source']}. This excludes bank/remittance spreads or fees.")
                    return self._result(intent, answer, trace, {"conversion": conv})
                except ValueError as exc:
                    return self._result(intent, str(exc), trace)
            if sgd_amount is not None and any(k in text.lower() for k in ["how much myr", "myr do i need", "sgd to myr", "convert sgd to myr"]):
                required_myr = money(sgd_amount * Decimal(str(q["inverse_rate_sgd_myr"])))
                trace.append({"step": "CALCULATE", "status": "completed", "detail": f"Converted S${sgd_amount:,.2f} to approximately RM{required_myr:,.2f}."})
                answer = f"At the {status} reference rate of 1 MYR = S${q['rate']:.4f} ({freshness}), S${sgd_amount:,.2f} is approximately RM{required_myr:,.2f}. This excludes any bank/remittance spread or fees."
                return self._result(intent, answer, trace, {"fx": q, "conversion": {"sgd": float(sgd_amount), "myr": float(required_myr)}})
            if myr_amount is not None and any(k in text.lower() for k in ["how much sgd", "sgd do i get", "myr to sgd", "convert myr to sgd"]):
                converted_sgd = money(myr_amount * Decimal(str(q["rate"])))
                trace.append({"step": "CALCULATE", "status": "completed", "detail": f"Converted RM{myr_amount:,.2f} to approximately S${converted_sgd:,.2f}."})
                answer = f"At the {status} reference rate of 1 MYR = S${q['rate']:.4f} ({freshness}), RM{myr_amount:,.2f} is approximately S${converted_sgd:,.2f}. This excludes any bank/remittance spread or fees."
                return self._result(intent, answer, trace, {"fx": q, "conversion": {"myr": float(myr_amount), "sgd": float(converted_sgd)}})
            answer = f"The reference rate is 1 MYR = S${q['rate']:.4f} ({status}, {freshness}). RM1,000 would convert to approximately S${q['example_sgd']:,.2f}. This is a reference/mid-market rate, not a guaranteed bank quote."
            return self._result(intent, answer, trace, {"fx": q})

        if intent == "transfer":
            amount = self.extract_myr_amount(text)
            if amount is None:
                f = self.forecast()
                if f["shortfall_sgd"] > 0:
                    q = self.refresh_fx()
                    amount = money(Decimal(str(f["shortfall_sgd"])) / Decimal(str(q["rate"])))
                else:
                    return self._result(intent, "Tell me the MYR amount you want to transfer, for example: “Prepare a RM5,000 transfer to Singapore.”", trace)
            risk = self.risk_check(amount, text)
            trace.append({"step": "SECURITY", "status": "completed" if risk["status"] != "BLOCKED" else "blocked", "detail": f"Risk status: {risk['status']}"})
            if risk["status"] == "BLOCKED":
                return self._result(intent, "I blocked that transfer because it violates a safety policy: " + " ".join(risk["reasons"]), trace, {"risk": risk})
            proposal = self.create_proposal(amount, text)
            trace.append({"step": "AUTHORIZE", "status": "required", "detail": "Level 2 explicit user authorization is required."})
            answer = f"I prepared a sandbox conversion of RM{amount:,.2f} to approximately S${proposal['amount_sgd']:,.2f}. I will not execute it until you explicitly authorize it."
            return self._result(intent, answer, trace, {"proposal": proposal, "risk": risk})

        if intent == "affordability":
            f = self.forecast()
            trace += [
                {"step": "OBSERVE", "status": "completed", "detail": "Retrieved balances, income, living costs and obligations."},
                {"step": "REASON", "status": "completed", "detail": "Forecasted 30-day liquidity."},
            ]
            cur = f.get("planning_currency", "SGD")
            if f["shortfall_sgd"] <= 0:
                answer = f"Yes. Your 30-day projected balance after obligations is {cur}{f['projected_balance_planning']:,.2f}; no conversion is currently required."
                return self._result(intent, answer, trace, {"forecast": f})
            if cur != "SGD":
                answer = (f"Your 30-day projection shows a {cur}{f['shortfall_planning']:,.2f} funding gap. "
                          "BorderWise will not force a MYR→SGD action when your planning currency is different; use the any-currency conversion tool to choose the funding pair you actually want.")
                trace.append({"step": "RECOMMEND", "status": "completed", "detail": "Identified a funding gap but left conversion direction to the user because the planning currency is not SGD."})
                return self._result(intent, answer, trace, {"forecast": f})
            q = self.refresh_fx()
            amount = money(Decimal(str(f["shortfall_sgd"])) / Decimal(str(q["rate"])))
            risk = self.risk_check(amount, "tuition and essential student obligations")
            trace += [
                {"step": "RECOMMEND", "status": "completed", "detail": f"Calculated RM{amount:,.2f} MYR→SGD using the refreshed reference rate {q['rate']:.4f}."},
                {"step": "SECURITY", "status": "completed" if risk["status"] != "BLOCKED" else "blocked", "detail": f"Risk status: {risk['status']}"},
            ]
            answer = (
                f"You have a projected S${f['shortfall_sgd']:,.2f} shortfall over 30 days. "
                f"I recommend converting approximately RM{amount:,.2f} to SGD at the current reference rate of {q['rate']:.4f}, "
                f"while preserving your RM{self.state['emergency_reserve_myr']:,.2f} emergency reserve."
            )
            proposal = self.create_proposal(amount, "tuition and essential student obligations")
            trace.append({"step": "AUTHORIZE", "status": "required", "detail": "Level 2 authorization required before execution."})
            return self._result(intent, answer, trace, {"forecast": f, "proposal": proposal, "risk": risk})

        if intent == "help":
            return self._result(intent, "I can analyze balances, forecast cash flow, analyze spending, compare FX, prepare transfers, enforce risk limits, require authorization, execute sandbox transactions, verify them and maintain an audit trail.", trace)

        return self._result(
            intent,
            "I can help with balances, spending, cash-flow forecasts, FX, transfers, tuition affordability and transaction history. Try: “How much can I safely spend?”, “Will I run out of SGD?”, or “Prepare a RM5,000 transfer.”",
            trace,
        )

    def _result(self, intent: str, answer: str, trace: list[dict[str, Any]], data: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"intent": intent, "answer": answer, "trace": trace, "data": data or {}, "state": self.snapshot()}

    def snapshot(self, refresh_fx: bool = False) -> dict[str, Any]:
        f = self.forecast()
        q = self.refresh_fx() if refresh_fx else self.fx_quote()
        return {
            "balances": self.get_balance(),
            "currency_overview": self.currency_overview(),
            "profile": self.get_profile(),
            "forecast": f,
            "spending": self.spending_analysis(),
            "health": self.health_analysis(),
            "fx": q,
            "obligations": self.get_obligations(),
            "audit": self.audit_log(),
        }
