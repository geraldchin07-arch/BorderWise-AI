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
import logging
logger = logging.getLogger("borderwise")
import threading
from functools import wraps
from datetime import datetime, timezone, timedelta 



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


def _locked(fn):
    @wraps(fn)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return fn(self, *args, **kwargs)
    return wrapper





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
    PROPOSAL_TTL_MINUTES = 30
    

    def __init__(self) -> None:
        self.reset()
        self._lock = threading.RLock()

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
        for code in balances:
            if code == "SGD":
                continue
            mode = str(raw_modes.get(code, "auto")).strip().lower()
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
        mode = prefs.get("additional_fx_rate_modes", {}).get(code, "custom")
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
        balance = money(self.state["balances"]["MYR"])
        reserve = money(self.state["emergency_reserve_myr"])
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
    #determine expired proposal after some time
    def _expire_if_needed(self, proposal: dict[str, Any]) -> bool:
        """Mark a stale proposal EXPIRED. Returns True if it is expired."""
        if proposal["status"] in {"PENDING_AUTHORIZATION", "AUTHORIZED"}:
            if datetime.fromisoformat(proposal["expires_at"]) <= datetime.now(timezone.utc):
                proposal["status"] = "EXPIRED"
                self.audit("PROPOSAL_EXPIRED", {"proposal_id": proposal["id"]})
        return proposal["status"] == "EXPIRED"
        
    @_locked
    def create_proposal(self, amount_myr: Decimal, purpose: str = "student finance transfer") -> dict[str, Any]:
        amount_myr = money(amount_myr)
        risk = self.risk_check(amount_myr, purpose)
        if risk["status"] == "BLOCKED":
            raise ValueError("; ".join(risk["reasons"]))
        # NEW: reuse an identical pending proposal instead of creating a duplicate
        for existing in self.state["proposals"].values():
            if (existing["status"] == "PENDING_AUTHORIZATION"
                    and money(existing["amount_myr"]) == amount_myr):
                return existing
        if self.state.get("fx_preferences", {}).get("myr_mode") != "custom":
            self.refresh_fx()
        rate = self._selected_myrsgd_rate()
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
            "created_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=self.PROPOSAL_TTL_MINUTES)).isoformat(),
        }
        self.state["proposals"][pid] = proposal
        self.audit("PROPOSAL_CREATED", proposal)
        return proposal
    
    @_locked
    def authorize(self, proposal_id: str, approved: bool) -> dict[str, Any]:
        proposal = self.state["proposals"].get(proposal_id)
        if not proposal:
            raise ValueError("Proposal not found.")
        if self._expire_if_needed(proposal):
            raise ValueError("Proposal has expired; please request a new one.")
        if proposal["status"] != "PENDING_AUTHORIZATION":
            raise ValueError("Proposal is no longer awaiting authorization.")
        proposal["status"] = "AUTHORIZED" if approved else "REJECTED"
        self.audit("AUTHORIZATION", {"proposal_id": proposal_id, "approved": approved})
        if not approved:
            return proposal
        return proposal
    @_locked
    def execute(self, proposal_id: str) -> dict[str, Any]:
        proposal = self.state["proposals"].get(proposal_id)
        if not proposal:
            raise ValueError("Proposal not found.")
        if self._expire_if_needed(proposal):
            raise ValueError("Proposal has expired; please request a new one.")
        if proposal["status"] != "AUTHORIZED":
            raise ValueError("Execution requires explicit Level 2 authorization.")

        amount_myr = money(proposal["amount_myr"])
        amount_sgd = money(proposal["amount_sgd"])
        risk = self.risk_check(amount_myr, proposal["purpose"])
        if risk["status"] == "BLOCKED":
            proposal["status"] = "BLOCKED"
            self.audit("EXECUTION_BLOCKED", {"proposal_id": proposal_id, "risk": risk})
            raise ValueError("; ".join(risk["reasons"]))
        before_myr = money(self.state["balances"]["MYR"])
        before_sgd = money(self.state["balances"]["SGD"])

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
                # NEW: verify the result and roll back if the numbers don't match
        after_myr = money(self.state["balances"]["MYR"])
        after_sgd = money(self.state["balances"]["SGD"])
        verified = (
            after_myr == before_myr - amount_myr
            and after_sgd == before_sgd + amount_sgd
            and self.state["transactions"][-1].id == tx.id
        )
        if not verified:
            self.state["balances"]["MYR"] = before_myr
            self.state["balances"]["SGD"] = before_sgd
            self.state["transactions"].pop()
            proposal["status"] = "BLOCKED"
            self.audit("VERIFICATION_FAILED", {"proposal_id": proposal_id})
            raise ValueError("Post-execution verification failed; the transaction was rolled back.")

        proposal["status"] = "EXECUTED"
        proposal["transaction_id"] = tx.id
        proposal["verified"] = True
        self.audit("VERIFIED", {"proposal_id": proposal_id, "transaction_id": tx.id,
                                "myr_after": float(after_myr), "sgd_after": float(after_sgd)})
        self.audit("EXECUTED", {"proposal_id": proposal_id, "transaction_id": tx.id})
        return {"proposal": proposal, "transaction": asdict(tx),
                "balances": self.get_balance(), "verified": True}

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
        # v5: optional LLM tool-calling planner. The deterministic engine remains the
        # fallback and the authority for calculations, policy and execution.
        try:
            from .agent import AgentOrchestrator
            llm_result = AgentOrchestrator(self).run(text)
            if llm_result is not None:
                return llm_result
        except Exception:
             logger.exception("LLM agent failed")

        # Offline local planner: enables genuine multi-step tool selection without an external API.
        try:
            from .local_agent import LocalAgentPlanner
            local_result = LocalAgentPlanner(self).run(text)
            if local_result is not None:
                return local_result
        except Exception:
              logger.exception("Local planner failed")
          

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
    
    def list_proposals(self) -> list[dict[str, Any]]:
        return sorted(self.state["proposals"].values(),
                      key=lambda p: p["created_at"], reverse=True)
    
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
            "proposals": self.list_proposals(), # NEW
            "audit": self.audit_log()
        }
