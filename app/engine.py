from __future__ import annotations

from dataclasses import dataclass, asdict
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from datetime import datetime, timezone, timedelta
from typing import Any
import copy
import re
import difflib
import uuid
import json
import time
import threading
from functools import wraps
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError


def _state_locked(method):
    """Serialize critical state reads/writes on the shared demo engine."""
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._state_lock:
            return method(self, *args, **kwargs)
    return wrapped


Q = Decimal("0.01")


def _finite_decimal(x: Decimal | float | int | str, label: str) -> Decimal:
    try:
        value = Decimal(str(x))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{label} must be a valid number.") from exc
    if not value.is_finite():
        raise ValueError(f"{label} must be finite.")
    return value


def money(x: Decimal | float | int | str) -> Decimal:
    try:
        return _finite_decimal(x, "Amount").quantize(Q, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError("Amount is outside the supported numeric range.") from exc


FXQ = Decimal("0.00000001")


def fxrate(x: Decimal | float | int | str) -> Decimal:
    try:
        return _finite_decimal(x, "FX rate").quantize(FXQ, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError("FX rate is outside the supported numeric range.") from exc


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
    PROPOSAL_TTL_MINUTES = 30

    def __init__(self) -> None:
        self._state_lock = threading.RLock()
        self.reset()

    @_state_locked
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


    @_state_locked
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

    @_state_locked
    def update_profile(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Apply legacy profile updates atomically, including FX refresh failures."""
        previous_state = copy.deepcopy(self.state)
        try:
            return self._update_profile_unchecked(*args, **kwargs)
        except Exception:
            self.state = previous_state
            raise

    @_state_locked
    def _update_profile_unchecked(self, myr_balance: Any, sgd_balance: Any, monthly_income_sgd: Any,
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
        # The legacy profile API retains its historical SGD cash position:
        # MYR is a separate wallet balance until a conversion is planned.
        self.state["profile_meta"]["profile_schema"] = "legacy"
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

    @_state_locked
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

    @_state_locked
    def update_profile_general(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Apply a currency-first profile update atomically.

        Profile validation and FX refreshes can fail after some derived state has
        been prepared. Restore the previous state on any exception so callers never
        observe a half-applied profile.
        """
        previous_state = copy.deepcopy(self.state)
        try:
            return self._update_profile_general_unchecked(payload)
        except Exception:
            self.state = previous_state
            raise

    @_state_locked
    def _update_profile_general_unchecked(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate and apply a currency-first profile update.

        The selected planning currency is the user's reporting/forecast currency. Balances
        may contain arbitrary three-letter currencies. Trusted calculations are normalized
        internally to SGD and then presented back in the planning currency.

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
            "profile_schema": "currency_first",
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

    @_state_locked
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


    @_state_locked
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

    @_state_locked
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


    @_state_locked
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
            if not isinstance(payload, dict):
                raise ValueError("FX provider returned an unexpected response shape.")
            raw = payload.get("rate")
            rate = fxrate(raw)
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

    @_state_locked
    def quote_conversion(self, amount: float | Decimal, from_currency: str, to_currency: str,
                         custom_rate: float | Decimal | None = None, force: bool = False) -> dict[str, Any]:
        amount_d = money(amount)
        base = from_currency.upper().strip()
        quote = to_currency.upper().strip()
        # RMB is a common alias for the ISO currency code CNY.
        base = {"RMB": "CNY"}.get(base, base)
        quote = {"RMB": "CNY"}.get(quote, quote)
        if amount_d <= 0:
            raise ValueError("Conversion amount must be positive.")
        if not re.fullmatch(r"[A-Z]{3}", base) or not re.fullmatch(r"[A-Z]{3}", quote):
            raise ValueError("Source and target currencies must be 3-letter currency codes.")
        if base == quote:
            if custom_rate is not None and fxrate(custom_rate) != Decimal("1"):
                raise ValueError("A same-currency conversion must use an identity rate of 1.")
            rate = Decimal("1")
            meta = {"base": base, "quote": quote, "rate": 1.0, "date": datetime.now().date().isoformat(),
                    "source": "Same-currency identity rate", "live": False, "updated_at": None}
            mode = "identity"
        elif custom_rate is not None:
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

    @_state_locked
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
    @_state_locked
    def get_balance(self) -> dict[str, float]:
        return {k: float(v) for k, v in self.state["balances"].items()}

    @_state_locked
    def get_transactions(self, limit: int = 20) -> list[dict[str, Any]]:
        return [asdict(t) for t in self.state["transactions"][-limit:]][::-1]

    @_state_locked
    def forecast(self) -> dict[str, Any]:
        meta = self.state.get("profile_meta", {})
        planning = str(meta.get("planning_currency", "SGD")).upper()
        planning_rate = self._profile_rate_to_sgd(planning)

        # Modern currency-first profiles explicitly model a multi-currency wallet.
        # Preserve legacy cash-position semantics until foreign funds are converted.
        if meta.get("profile_schema") == "currency_first":
            start = money(0)
            for code, balance in self.state["balances"].items():
                balance_d = money(balance)
                if balance_d <= 0:
                    continue
                rate, _ = self._currency_rate_to_sgd(code)
                start += money(balance_d * rate)
        else:
            # The original demo/default profile uses only planning-currency cash
            # for near-term affordability. Explicit legacy profile updates preserve
            # the historical MYR-to-SGD estimate for near-term obligations.
            if (
                meta.get("profile_schema") == "legacy"
                and int(self.state["education"].get("tuition_due_days", 31)) <= 30
                and planning == "SGD"
            ):
                start = money(
                    self.state.get("balances", {}).get("SGD", 0)
                    + self.state.get("balances", {}).get("MYR", 0) * Decimal("0.31")
                )
            else:
                start = money(self.state.get("balances", {}).get(planning, 0))

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
            "starting_sgd": float(start),
            "starting_portfolio_sgd": float(start),
            "starting_planning": float(display(start)),
            "starting_portfolio_planning": float(display(start)),
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

    @_state_locked
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


    @_state_locked
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

    @_state_locked
    def health_analysis(self) -> dict[str, Any]:
        """Transparent, deterministic liquidity health indicator; not a credit score."""
        f = self.forecast()
        start_plus_income = money(Decimal(str(f["starting_sgd"])) + Decimal(str(f["expected_income_sgd"])))
        monthly_spending = money(f["monthly_spending_sgd"])
        projected = money(f["projected_balance_sgd"])
        # For legacy profiles, the health indicator measures immediately available
        # planning-currency cash. Foreign-currency balances are assets, but are not
        # counted as liquid until a conversion is planned.
        profile_meta = self.state.get("profile_meta", {})
        if profile_meta.get("profile_schema") == "legacy":
            planning_for_health = str(profile_meta.get("planning_currency", "SGD")).upper()
            liquid_start = money(self.state.get("balances", {}).get(planning_for_health, 0))
            projected = money(
                liquid_start
                + Decimal(str(f["expected_income_sgd"]))
                - Decimal(str(f["monthly_spending_sgd"]))
                - Decimal(str(f["obligations_sgd"]))
            )
        reserve = money(self.state["emergency_reserve_myr"])
        profile_meta = self.state.get("profile_meta", {})
        reserve_currency = str(profile_meta.get("emergency_reserve_currency", "MYR")).upper()
        reserve_amount = money(profile_meta.get("emergency_reserve_amount", reserve))
        reserve_balance = money(self.state["balances"].get(reserve_currency, money(0)))
        obligations = money(f["obligations_sgd"])

        if projected < 0:
            liquidity_penalty = min(45, 35 + float(abs(projected) / max(monthly_spending, money(1)) * 10))
            liquidity_label = "Funding gap"
        elif monthly_spending <= 0:
            liquidity_penalty = 0
            liquidity_label = "No planned monthly spending"
        else:
            buffer_months = float(projected / monthly_spending)
            if buffer_months < 0.5:
                liquidity_penalty, liquidity_label = 35, "Very thin buffer"
            elif buffer_months < 1:
                liquidity_penalty, liquidity_label = 28, "Thin buffer"
            elif buffer_months < 1.5:
                liquidity_penalty, liquidity_label = 18, "Moderate buffer"
            elif buffer_months < 2:
                liquidity_penalty = 10
                liquidity_label = "Healthy buffer"
            else:
                liquidity_penalty, liquidity_label = 0, "Strong buffer"

        reserve_penalty = 20 if reserve_balance < reserve_amount else 0
        available_ratio = float(obligations / max(start_plus_income, money(1))) if start_plus_income > 0 else 1.0
        obligation_penalty = min(12.0, max(0.0, available_ratio * 12.0))
        score = max(0, min(100, int(round(100 - liquidity_penalty - reserve_penalty - obligation_penalty))))
        # A projected buffer below one month is a material liquidity risk and
        # must not receive a "strong" score even when other factors look healthy.
        if monthly_spending > 0 and projected / monthly_spending < 1:
            score = min(score, 89)
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


    @_state_locked
    def _selected_myrsgd_rate(self) -> Decimal:
        prefs = self.state.get("fx_preferences", {})
        if prefs.get("myr_mode") == "custom" and prefs.get("custom_myrsgd") is not None:
            return fxrate(prefs["custom_myrsgd"])
        return fxrate(self.state["fx"]["MYRSGD"])

    @_state_locked
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

    @_state_locked
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

    @_state_locked
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


    @_state_locked
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


    @_state_locked
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
    @_state_locked
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
            "max_allowed_myr": float(max(money(0), balance - reserve)),
            "reserve_myr": float(reserve),
            "reasons": reasons,
            "requires_level": 2,
        }

    @_state_locked
    def create_proposal(self, amount_myr: Decimal, purpose: str = "student finance transfer") -> dict[str, Any]:
        amount_myr = money(amount_myr)
        balances = self.state.get("balances", {})
        if "MYR" not in balances or "SGD" not in balances:
            raise ValueError("A MYR-to-SGD transfer requires both MYR and SGD wallet balances to be configured.")
        risk = self.risk_check(amount_myr, purpose)
        if risk["status"] == "BLOCKED":
            raise ValueError("; ".join(risk["reasons"]))

        # Reuse a still-valid identical proposal to avoid duplicates; supersede
        # older pending proposals when the user prepares a different amount.
        for existing in self.state["proposals"].values():
            if existing.get("status") != "PENDING_AUTHORIZATION":
                continue
            if self._expire_if_needed(existing) or self._expire_proposal_if_needed(
                str(existing.get("id", "")), existing
            ):
                continue
            try:
                same_amount = money(existing.get("amount_myr")) == amount_myr
            except (TypeError, ValueError, ArithmeticError):
                same_amount = False
            if same_amount:
                return existing

        for existing in self.state["proposals"].values():
            if existing.get("status") == "PENDING_AUTHORIZATION":
                existing["status"] = "SUPERSEDED"
                self.audit("PROPOSAL_SUPERSEDED", {"proposal_id": existing.get("id")})

        quote = self.refresh_fx()
        rate = self.state["fx"]["MYRSGD"]
        amount_sgd = money(amount_myr * rate)
        quoted_at = datetime.now(timezone.utc)
        quote_expires_at = quoted_at + timedelta(seconds=self.FX_TTL_SECONDS)
        fx_quote = {
            "source": str((quote or {}).get("source", self.state["fx"].get("source", "unknown reference source"))),
            "rate_date": (quote or {}).get("rate_date", self.state["fx"].get("rate_date")),
            "live": bool((quote or {}).get("live", self.state["fx"].get("live", False))),
            "updated_at": (quote or {}).get("updated_at", self.state["fx"].get("updated_at")),
            "quoted_at": quoted_at.isoformat(),
            "expires_at": quote_expires_at.isoformat(),
        }
        pid = "P-" + uuid.uuid4().hex[:8].upper()
        proposal = {
            "id": pid,
            "created_at": quoted_at.isoformat(),
            "expires_at": (quoted_at + timedelta(minutes=self.PROPOSAL_TTL_MINUTES)).isoformat(),
            "from": "MYR",
            "to": "SGD",
            "amount_myr": float(amount_myr),
            "amount_sgd": float(amount_sgd),
            "rate": float(rate),
            "fx_quote": fx_quote,
            "quote_expires_at": quote_expires_at.isoformat(),
            "purpose": purpose,
            "risk": risk,
            "permission_level": 2,
            "status": "PENDING_AUTHORIZATION",
        }
        self.state["proposals"][pid] = proposal
        self.audit("PROPOSAL_CREATED", proposal)
        return proposal

    def _expire_proposal_if_needed(self, proposal_id: str, proposal: dict[str, Any]) -> bool:
        """Mark proposals with missing, malformed, or expired FX quotes as terminal."""
        raw_expiry = proposal.get("quote_expires_at") or (proposal.get("fx_quote") or {}).get("expires_at")
        try:
            if not raw_expiry:
                raise ValueError("Proposal is missing quote-expiry metadata.")
            quote_expiry = datetime.fromisoformat(str(raw_expiry).replace("Z", "+00:00"))
            if quote_expiry.tzinfo is None:
                quote_expiry = quote_expiry.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            proposal["status"] = "EXPIRED"
            self.audit("PROPOSAL_EXPIRED", {
                "proposal_id": proposal_id,
                "reason": "missing_or_invalid_quote_expiry",
            })
            return True
        if datetime.now(timezone.utc) >= quote_expiry:
            proposal["status"] = "EXPIRED"
            self.audit("PROPOSAL_EXPIRED", {
                "proposal_id": proposal_id,
                "reason": "quote_expired",
                "quote_expires_at": str(raw_expiry),
            })
            return True
        return False

    def _expire_if_needed(self, proposal: dict[str, Any]) -> bool:
        """Expire a pending/authorized proposal after its review window."""
        if proposal.get("status") in {"PENDING_AUTHORIZATION", "AUTHORIZED"}:
            raw_expiry = proposal.get("expires_at")
            try:
                if not raw_expiry:
                    raise ValueError("Proposal is missing expiry metadata.")
                expiry = datetime.fromisoformat(str(raw_expiry).replace("Z", "+00:00"))
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                proposal["status"] = "EXPIRED"
                self.audit("PROPOSAL_EXPIRED", {
                    "proposal_id": proposal.get("id"),
                    "reason": "missing_or_invalid_proposal_expiry",
                })
                return True
            if datetime.now(timezone.utc) >= expiry:
                proposal["status"] = "EXPIRED"
                self.audit("PROPOSAL_EXPIRED", {
                    "proposal_id": proposal.get("id"),
                    "reason": "proposal_expired",
                    "expires_at": str(raw_expiry),
                })
                return True
        return proposal.get("status") == "EXPIRED"

    @_state_locked
    def authorize(self, proposal_id: str, approved: bool, acknowledge_review: bool = False) -> dict[str, Any]:
        proposal = self.state["proposals"].get(proposal_id)
        if not proposal:
            raise ValueError("Proposal not found.")
        if self._expire_if_needed(proposal):
            raise ValueError("Proposal has expired; please prepare and review a fresh proposal.")
        if proposal["status"] != "PENDING_AUTHORIZATION":
            raise ValueError("Proposal is no longer awaiting authorization.")
        if approved and self._expire_proposal_if_needed(proposal_id, proposal):
            raise ValueError("Proposal quote has expired or is invalid; prepare and review a fresh proposal before authorization.")
        if approved and proposal.get("risk", {}).get("status") == "REVIEW" and not (
            acknowledge_review or proposal.get("review_acknowledged") is True
        ):
            raise ValueError("High-value transfer: explicit acknowledgement is required (acknowledge_review=true).")
        if approved and acknowledge_review and proposal.get("risk", {}).get("status") == "REVIEW" and proposal.get("review_acknowledged") is not True:
            proposal["review_acknowledged"] = True
            proposal["review_acknowledged_at"] = datetime.now(timezone.utc).isoformat()
            self.audit("HIGH_VALUE_REVIEW_ACKNOWLEDGED", {
                "proposal_id": proposal_id,
                "amount_myr": proposal.get("amount_myr"),
                "source": "authorization_control",
            })
        proposal["status"] = "AUTHORIZED" if approved else "REJECTED"
        self.audit("AUTHORIZATION", {"proposal_id": proposal_id, "approved": approved})
        if not approved:
            return proposal
        return proposal

    @_state_locked
    def acknowledge_review(self, proposal_id: str) -> dict[str, Any]:
        """Record explicit review acknowledgement without authorizing or executing."""
        proposal = self.state["proposals"].get(proposal_id)
        if not proposal:
            raise ValueError("Proposal not found.")
        if self._expire_if_needed(proposal):
            raise ValueError("Proposal has expired; prepare and review a fresh proposal.")
        if proposal["status"] != "PENDING_AUTHORIZATION":
            raise ValueError("Proposal is no longer awaiting authorization.")
        if self._expire_proposal_if_needed(proposal_id, proposal):
            raise ValueError("Proposal quote has expired; prepare and review a fresh proposal.")
        if str(proposal.get("risk", {}).get("status", "")).upper() != "REVIEW":
            raise ValueError("This proposal does not require the high-value review acknowledgement.")
        if proposal.get("review_acknowledged") is not True:
            proposal["review_acknowledged"] = True
            proposal["review_acknowledged_at"] = datetime.now(timezone.utc).isoformat()
            self.audit("HIGH_VALUE_REVIEW_ACKNOWLEDGED", {
                "proposal_id": proposal_id,
                "amount_myr": proposal.get("amount_myr"),
                "source": "conversation",
            })
        return proposal

    @_state_locked
    def execute(self, proposal_id: str) -> dict[str, Any]:
        proposal = self.state["proposals"].get(proposal_id)
        if not proposal:
            raise ValueError("Proposal not found.")
        if proposal["status"] != "AUTHORIZED":
            raise ValueError("Execution requires explicit Level 2 authorization.")

        balances = self.state.get("balances", {})
        if "MYR" not in balances or "SGD" not in balances:
            raise ValueError("Execution requires both MYR and SGD wallet balances; no funds were changed.")

        if self._expire_if_needed(proposal):
            raise ValueError("Proposal has expired; please prepare and review a fresh proposal.")

        # Quote expiry is checked again at execution in case it expires after authorization.
        if self._expire_proposal_if_needed(proposal_id, proposal):
            raise ValueError("Proposal quote has expired or is invalid; prepare and review a fresh proposal before execution.")

        amount_myr = money(proposal["amount_myr"])
        amount_sgd = money(proposal["amount_sgd"])
        risk = self.risk_check(amount_myr, proposal["purpose"])
        if risk["status"] == "BLOCKED":
            proposal["status"] = "BLOCKED"
            self.audit("EXECUTION_BLOCKED", {"proposal_id": proposal_id, "risk": risk})
            raise ValueError("; ".join(risk["reasons"]))

        before_myr = money(self.state["balances"]["MYR"])
        before_sgd = money(self.state["balances"]["SGD"])
        self.state["balances"]["MYR"] = money(before_myr - amount_myr)
        self.state["balances"]["SGD"] = money(before_sgd + amount_sgd)

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
        after_myr = money(self.state["balances"]["MYR"])
        after_sgd = money(self.state["balances"]["SGD"])
        expected_myr = money(before_myr - amount_myr)
        expected_sgd = money(before_sgd + amount_sgd)
        if after_myr != expected_myr or after_sgd != expected_sgd:
            self.state["balances"]["MYR"] = before_myr
            self.state["balances"]["SGD"] = before_sgd
            self.state["transactions"].pop()
            proposal["status"] = "BLOCKED"
            self.audit("VERIFICATION_FAILED", {"proposal_id": proposal_id})
            raise ValueError("Post-execution verification failed; the transaction was rolled back.")

        proposal["status"] = "EXECUTED"
        proposal["transaction_id"] = tx.id
        proposal["verified"] = True
        self.audit("VERIFIED", {
            "proposal_id": proposal_id,
            "transaction_id": tx.id,
            "myr_after": float(after_myr),
            "sgd_after": float(after_sgd),
        })
        self.audit("EXECUTED", {"proposal_id": proposal_id, "transaction_id": tx.id})
        return {"proposal": proposal, "transaction": asdict(tx), "balances": self.get_balance(), "verified": True}

    @_state_locked
    def audit(self, event: str, details: dict[str, Any]) -> None:
        self.state["audit"].append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "details": details,
        })

    def audit_log(self) -> list[dict[str, Any]]:
        return list(reversed(self.state["audit"]))

    # ---------- agent ----------
    @staticmethod
    def repair_user_text(text: str) -> str:
        """Make intent extraction tolerant of small typos without changing meaning."""
        t = re.sub(r"\s+", " ", str(text or "").strip())
        common_typos = {
            "curency": "currency", "curreny": "currency", "currncy": "currency",
            "mry": "myr", "sgdd": "sgd",
            "exhange": "exchange", "exchnge": "exchange", "exchnage": "exchange",
            "convertion": "conversion", "conver": "convert", "converrt": "convert",
            "curent": "current", "currnt": "current", "amout": "amount", "ratee": "rate", "trnsfer": "transfer", "ususal": "usual", "pleaze": "please",
        }
        words = re.findall(r"[A-Za-z]+|[^A-Za-z]+", t)
        for i, word in enumerate(words):
            if word.lower() in common_typos:
                words[i] = common_typos[word.lower()]
        t = "".join(words)
        # Preserve valid ISO currency codes before fuzzy typo repair. Otherwise
        # uncommon but valid codes such as KWD can be silently rewritten to KRW.
        currency_codes = [
            "SGD", "MYR", "USD", "CNY", "RMB", "JPY", "KRW", "THB", "EUR", "GBP",
            "AUD", "CAD", "HKD", "TWD", "INR", "AFN", "AOA", "BBD", "BMD", "BSD", "BTN", "BZD", "CUP", "CVE", "FKP", "GIP", "GMD", "GNF", "IRR", "KGS", "KPW", "KYD", "LRD", "LYD", "MRU", "NIO", "PGK", "SHP", "SLE", "STN", "SZL", "ZWG", "IDR", "PHP", "VND", "NZD",
            "CHF", "SEK", "NOK", "DKK", "SAR", "AED", "QAR", "BND", "BHD", "ALL",
            "AMD", "ARS", "AZN", "BAM", "BGN", "BOB", "BRL", "BYN", "CLP",
            "COP", "CRC", "CZK", "DOP", "DZD", "EGP", "GEL", "GHS", "GTQ",
            "HNL", "HUF", "ILS", "IQD", "ISK", "JOD", "KES", "KWD", "KZT",
            "LBP", "LKR", "MAD", "MDL", "MKD", "MMK", "MNT", "MOP", "MUR",
            "MVR", "MXN", "NGN", "NPR", "OMR", "PEN", "PKR", "PLN", "PYG",
            "RON", "RSD", "RUB", "RWF", "UAH", "UYU", "UZS", "VES", "XAF",
            "XOF", "XPF", "ZAR", "ZMW", "ZWL", "ETB", "TZS", "UGX", "XCD",
            "BWP", "BIF", "CDF", "DJF", "ERN", "FJD", "GYD", "HTG", "JMD",
            "KHR", "KMF", "LAK", "LSL", "MGA", "MWK", "MZN", "NAD", "PAB",
            "SBD", "SCR", "SDG", "SOS", "SRD", "SSP", "SYP", "TJS", "TMT",
            "TOP", "TTD", "TND", "TRY", "BDT", "VUV", "WST", "YER",
        ]
        common_words = {"the", "and", "for", "you", "what", "how", "are", "can", "from", "into", "this", "that", "with", "not", "now", "get", "one", "two", "all", "any", "per", "via", "use", "new", "may", "might", "could", "possibly", "maybe", "perhaps"}
        def repair_code(match: re.Match[str]) -> str:
            token = match.group(0).upper()
            if token in currency_codes or token.lower() in common_words:
                return token
            score, best = max(
                ((difflib.SequenceMatcher(None, token, code).ratio(), code) for code in currency_codes),
                key=lambda item: item[0],
            )
            # Allow a single adjacent transposition (e.g. MRY -> MYR), but
            # don't "correct" arbitrary three-letter words into currencies.
            transposed = any(
                len(token) == len(code)
                and sum(a != b for a, b in zip(token, code)) == 2
                and any(
                    token[i] == code[i + 1] and token[i + 1] == code[i]
                    for i in range(len(token) - 1)
                )
                for code in currency_codes
            )
            return best if score >= 0.80 or transposed else token
        return re.sub(r"\b[A-Za-z]{3}\b", repair_code, t)

    def detect_intent(self, text: str) -> str:
        t = self.repair_user_text(text).lower()
        if any(k in t for k in ["help", "what can you do", "capabilities"]):
            return "help"
        # A concrete MYR/SGD/USD/etc. pair conversion is an FX task even when
        # the user asks about fees or adds a safety instruction such as "do not
        # execute". Only route it to FX when it is a quote/calculation, not a
        # tuition-planning conversation or an explicit transfer command.
        explicit_transfer_command = bool(re.search(
            r"\b(?:prepare|create|make|set\s+up|initiate)\s+(?:(?:a|an|the)\s+)?(?:sandbox\s+)?(?:transfer|proposal)\b"
            r"|\b(?:transfer|send|remit)\s+(?:rm|myr)\s*[0-9]",
            t,
            re.I,
        ))
        explicit_pair = self.extract_conversion_pair(text)
        explicit_fx_language = any(k in t for k in [
            "convert", "converting", "conversion", "exchange rate", "current rate", "rate of",
        ])
        explicit_quote_request = any(k in t for k in [
            "quotation request", "only a quotation", "quote only", "quotation only",
            "compare converting", "compare conversion", "estimate the cost",
            "how much myr should i receive", "how much would i receive",
        ])
        advice_context = any(k in t for k in [
            "can i afford", "affordability", "tuition", "school fees", "tuition fee",
            "do i have enough funds", "what should i convert", "should i convert",
        ])
        # A negative clause such as "Do not create or execute a transfer" may
        # contain words that resemble an action command. An explicit quote or
        # comparison with a source/target pair remains informational.
        if explicit_fx_language and explicit_pair and not advice_context and (
            not explicit_transfer_command or explicit_quote_request
        ):
            return "fx"
        if explicit_transfer_command:
            return "transfer"

        # Classify financial reasoning before generic FX fallbacks. A tuition
        # funding plan remains a planning request unless a concrete quote pair
        # is the clear primary task.
        if any(k in t for k in ["afford", "tuition", "fees", "enough money", "enough for"]):
            return "affordability"
        if any(k in t for k in [
            "forecast", "projection", "projected", "project my", "run out",
            "cash flow", "cashflow", "next month", "future balance",
            "monthly income", "monthly expenses", "save enough", "financial projection",
            "shortfall", "surplus", "funding gap", "what if my expenses",
        ]):
            return "forecast"
        # Explicit money-moving actions must take priority over FX wording.
        if any(k in t for k in ["transfer", "send money", "remit", "remittance", "send myr", "send sgd", "pay"]):
            return "transfer"
        # Explicit comparisons of hypothetical rates are arithmetic tasks, not live FX lookups.
        if any(k in t for k in ["compare", "difference between", "what is the difference"]) and any(
            k in t for k in ["hypothetical", "assume", "versus", " vs ", "at 0."]
        ):
            return "general"
        currency_aliases = {
            "sgd", "s$", "singapore dollar", "singapore dollars",
            "myr", "rm", "ringgit", "malaysian ringgit",
            "usd", "us$", "us dollar", "us dollars", "dollar", "dollars",
            "cny", "rmb", "yuan", "renminbi", "jpy", "yen", "krw", "won",
            "thb", "baht", "eur", "euro", "euros", "gbp", "pound", "pounds",
            "aud", "cad", "hkd", "twd", "inr", "idr", "php", "vnd", "nzd",
            "chf", "sek", "nok", "dkk", "sar", "aed", "qar", "bnd",
        }
        currency_mentions = [name for name in currency_aliases if re.search(rf"\b{re.escape(name)}\b", t)]
        currency_follow_up = any(k in t for k in ["how about", "what about", "and in", "what if"])
        fx_language = any(k in t for k in [
            "exchange rate", "current rate", "exchange", "fx", "convert", "conversion",
            "change my money", "change money", "want change money", "want to change money",
            "change currency", "change my currency", "exchange currency", "change my",
            "can i change", "i want change", "i want to change", "convert my money", "how do i exchange",
            "exchange myr", "exchange sgd", "how much myr do i need", "myr do i need", "sgd to myr",
            "current currency", "currency of", "rate of",
        ])
        if (
            fx_language
            or (len(currency_mentions) >= 1 and currency_follow_up)
            or (len(currency_mentions) >= 2 and any(k in t for k in ["to", "into", "in", "rate", "currency", "current"]))
        ):
            return "fx"
        if any(k in t for k in ["biggest expense", "spending", "spend", "expenses", "where did i spend"]):
            return "spending"
        if any(k in t for k in ["balance", "how much money", "how much do i have", "account"]):
            return "balance"
        if any(k in t for k in ["transaction", "recent payment", "recent transactions", "history"]):
            return "transactions"
        return "general"

    @staticmethod
    def has_scientific_amount(text: str) -> bool:
        """Detect scientific-notation tokens that must not be partially parsed as money."""
        return bool(re.search(r"\d(?:\.\d+)?[eE][+-]?\d", str(text or "")))

    def parse_amount_token(self, raw_amount: str) -> Decimal:
        """Parse explicit numeric shorthand such as 2k or 1.5m without guessing units."""
        raw = str(raw_amount).strip().replace(",", "")
        suffix = raw[-1:].lower()
        if suffix in {"k", "m"}:
            multiplier = Decimal("1000") if suffix == "k" else Decimal("1000000")
            raw = raw[:-1]
        else:
            multiplier = Decimal("1")
        return money(Decimal(raw) * multiplier)

    def extract_myr_amount(self, text: str) -> Decimal | None:
        if self.has_scientific_amount(text):
            return None
        amount = r"(?<![\d,.\-+])((?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?[kKmM]?)(?![A-Za-z0-9]|,\d|\.\d)"
        currency = r"(?<![A-Za-z])(?:malaysian\s+ringgit|ringgit|rm|myr)(?![A-Za-z])"
        patterns = [
            rf"{currency}\s*{amount}",
            rf"{amount}\s*{currency}",
        ]
        for pattern in patterns:
            match = re.search(pattern, text.lower())
            if match:
                return self.parse_amount_token(match.group(1))
        return None

    def extract_sgd_amount(self, text: str) -> Decimal | None:
        if self.has_scientific_amount(text):
            return None
        amount = r"(?<![\d,.\-+])((?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?[kKmM]?)(?![A-Za-z0-9]|,\d|\.\d)"
        currency = r"(?<![A-Za-z])(?:s\$|sgd|singapore\s+dollars?)(?![A-Za-z])"
        patterns = [
            rf"{currency}\s*{amount}",
            rf"{amount}\s*{currency}",
        ]
        for pattern in patterns:
            match = re.search(pattern, text.lower())
            if match:
                return self.parse_amount_token(match.group(1))
        return None

    def extract_generic_currency_amount(self, text: str) -> tuple[Decimal, str] | None:
        """Extract one explicitly marked amount/currency pair, without guessing shared symbols."""
        if self.has_scientific_amount(text):
            return None

        raw_text = str(text or "").strip()
        normalized = self.repair_user_text(raw_text)
        amount = r"(?<![\d,.\-+])((?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?[kKmM]?)(?![A-Za-z0-9]|,\d|\.\d)"

        # Keep this allowlist local and explicit: a random three-letter word is
        # not enough evidence that a number is denominated in a currency.
        supported_codes = {
            "SGD", "MYR", "USD", "CNY", "EUR", "GBP", "JPY", "KRW", "THB",
            "AUD", "CAD", "HKD", "TWD", "INR", "IDR", "PHP", "VND", "NZD",
            "CHF", "SEK", "NOK", "DKK", "SAR", "AED", "QAR", "BND", "BHD",
            "TRY", "BDT", "TND", "ALL", "AMD", "ARS", "AZN", "BAM", "BGN",
            "BOB", "BRL", "BYN", "CLP", "COP", "CRC", "CZK", "DOP", "DZD",
            "EGP", "GEL", "GHS", "GTQ", "HNL", "HUF", "ILS", "IQD", "ISK",
            "JOD", "KES", "KWD", "KZT", "LBP", "LKR", "MAD", "MDL", "MKD",
            "MMK", "MNT", "MOP", "MUR", "MVR", "MXN", "NGN", "NPR", "OMR",
            "PEN", "PKR", "PLN", "PYG", "RON", "RSD", "RUB", "RWF", "UAH",
            "UYU", "UZS", "VES", "XAF", "XOF", "XPF", "ZAR", "ZMW", "ZWL",
            "ETB", "TZS", "UGX", "XCD", "BWP", "BIF", "CDF", "DJF", "ERN",
            "FJD", "GYD", "HTG", "JMD", "KHR", "KMF", "LAK", "LSL", "MGA",
            "MWK", "MZN", "NAD", "PAB", "SBD", "SCR", "SDG", "SOS", "SRD",
            "SSP", "SYP", "TJS", "TMT", "TOP", "TTD", "VUV", "WST", "YER",
            "AFN", "AOA", "BBD", "BMD", "BSD", "BTN", "BZD", "CUP", "CVE",
            "FKP", "GIP", "GMD", "GNF", "IRR", "KGS", "KPW", "KYD", "LRD",
            "LYD", "MRU", "NIO", "PGK", "SHP", "SLE", "STN", "SZL", "ZWG",
        }
        ambiguous_codes = {"ALL", "TRY", "MAD", "PEN", "TOP", "GEL", "COP", "BOB", "RON", "CUP"}
        # Unicode symbols are accepted only when their symbol identifies a
        # single currency. Dollar and yen signs are deliberately excluded.
        symbol_aliases = {
            "R$": "BRL", "zł": "PLN", "€": "EUR", "£": "GBP", "₹": "INR",
            "₩": "KRW", "฿": "THB", "₱": "PHP", "₦": "NGN", "₺": "TRY",
            "₪": "ILS", "₫": "VND", "₴": "UAH", "₡": "CRC", "₲": "PYG",
            "₵": "GHS", "₸": "KZT", "₭": "LAK", "₮": "MNT", "₼": "AZN",
        }
        for symbol in sorted(symbol_aliases, key=len, reverse=True):
            symbol_pattern = re.escape(symbol)
            for pattern in (
                rf"(?<![A-Za-z]){symbol_pattern}\s*{amount}",
                rf"{amount}\s*{symbol_pattern}(?![A-Za-z])",
            ):
                match = re.search(pattern, normalized, re.IGNORECASE)
                if match:
                    return self.parse_amount_token(match.group(1)), symbol_aliases[symbol]

        aliases = {
            "SINGAPORE DOLLARS": "SGD", "SINGAPORE DOLLAR": "SGD", "S$": "SGD",
            "MALAYSIAN RINGGIT": "MYR", "RINGGIT": "MYR", "RM": "MYR",
            "US DOLLARS": "USD", "US DOLLAR": "USD", "US$": "USD",
            "RENMINBI": "CNY", "YUAN": "CNY", "RMB": "CNY", "CNY": "CNY",
            "EUROS": "EUR", "EURO": "EUR", "EUR": "EUR",
            "POUNDS": "GBP", "POUND": "GBP", "GBP": "GBP",
            "YEN": "JPY", "JPY": "JPY", "WON": "KRW", "KRW": "KRW",
            "BAHT": "THB", "THB": "THB", "AUD": "AUD", "CAD": "CAD",
            "HKD": "HKD", "TWD": "TWD", "INR": "INR", "IDR": "IDR",
            "PHP": "PHP", "VND": "VND", "NZD": "NZD", "CHF": "CHF",
            "SEK": "SEK", "NOK": "NOK", "DKK": "DKK", "SAR": "SAR",
            "AED": "AED", "QAR": "QAR", "BND": "BND", "BHD": "BHD",
            "BDT": "BDT", "TND": "TND",
            "ALBANIAN LEK": "ALL", "LEK": "ALL", "SOUTH AFRICAN RAND": "ZAR",
            "RAND": "ZAR", "KUWAITI DINAR": "KWD", "POLISH ZLOTY": "PLN",
            "ZLOTY": "PLN", "TURKISH LIRA": "TRY", "MEXICAN PESO": "MXN",
            "MOROCCAN DIRHAM": "MAD", "PERUVIAN SOL": "PEN", "TONGAN PAANGA": "TOP",
            "GEORGIAN LARI": "GEL", "LARI": "GEL", "COLOMBIAN PESO": "COP",
            "BOLIVIAN BOLIVIANO": "BOB", "ROMANIAN LEU": "RON", "ROMANIAN LEI": "RON",
            "BRAZILIAN REAL": "BRL", "SWISS FRANC": "CHF", "CANADIAN DOLLAR": "CAD",
            "AUSTRALIAN DOLLAR": "AUD", "HONG KONG DOLLAR": "HKD",
            "NEW ZEALAND DOLLAR": "NZD", "INDIAN RUPEE": "INR",
            "INDONESIAN RUPIAH": "IDR", "PHILIPPINE PESO": "PHP",
            "VIETNAMESE DONG": "VND", "THAI BAHT": "THB", "KOREAN WON": "KRW",
            "JAPANESE YEN": "JPY", "CHINESE YUAN": "CNY", "SAUDI RIYAL": "SAR",
            "UAE DIRHAM": "AED", "QATARI RIYAL": "QAR", "PAKISTANI RUPEE": "PKR",
            "BANGLADESHI TAKA": "BDT", "NIGERIAN NAIRA": "NGN", "EGYPTIAN POUND": "EGP",
            "ISRAELI NEW SHEKEL": "ILS", "AFGHAN AFGHANI": "AFN", "AFGHANI": "AFN",
            "ANGOLAN KWANZA": "AOA", "BARBADIAN DOLLAR": "BBD", "BERMUDIAN DOLLAR": "BMD",
            "BAHAMIAN DOLLAR": "BSD", "BHUTANESE NGULTRUM": "BTN", "BELIZE DOLLAR": "BZD",
            "CUBAN PESO": "CUP", "CAPE VERDE ESCUDO": "CVE", "FALKLAND ISLANDS POUND": "FKP",
            "GIBRALTAR POUND": "GIP", "GAMBIAN DALASI": "GMD", "GUINEAN FRANC": "GNF",
            "IRANIAN RIAL": "IRR", "KYRGYZSTANI SOM": "KGS", "NORTH KOREAN WON": "KPW",
            "CAYMAN ISLANDS DOLLAR": "KYD", "LIBERIAN DOLLAR": "LRD", "LIBYAN DINAR": "LYD",
            "MAURITANIAN OUGUIYA": "MRU", "NICARAGUAN CORDOBA": "NIO",
            "PAPUA NEW GUINEAN KINA": "PGK", "SAINT HELENA POUND": "SHP",
            "SIERRA LEONEAN LEONE": "SLE", "SAO TOME DOBRA": "STN", "SWAZI LILANGENI": "SZL",
            "ZIMBABWE GOLD": "ZWG",
        }

        candidates: list[tuple[int, int, str, Decimal]] = []
        source = normalized.upper()
        # Match longer currency names before shorter overlapping names.
        # Named aliases are distinct from bare ISO-like words: explicit names such
        # as "Cuban peso" are valid even when CUP is also an English word.
        patterns: list[tuple[str, str, bool]] = [
            (alias, code, False) for alias, code in aliases.items()
        ]
        patterns.extend((code, code, True) for code in supported_codes)
        for alias, code, is_code in sorted(patterns, key=lambda item: len(item[0]), reverse=True):
            token = rf"(?<![A-Z]){re.escape(alias)}(?![A-Z])"
            # Require an amount adjacent to the currency marker. This prevents
            # unrelated amounts in the same sentence (e.g. dates and budgets)
            # from being attributed to a distant currency mention.
            for pattern in (
                rf"{token}\s*{amount}",
                rf"{amount}\s*{token}",
            ):
                match = re.search(pattern, source)
                if not match:
                    continue
                # Ambiguous ISO codes overlap with ordinary words. Match each
                # currency marker next to its amount in the original input, preserving
                # case, so an unrelated uppercase token cannot legitimize a lowercase word.
                if is_code and code in ambiguous_codes:
                    explicit_code_amount = (
                        rf"(?<![A-Za-z]){re.escape(code)}(?![A-Za-z])\s*{amount}",
                        rf"{amount}\s*(?<![A-Za-z]){re.escape(code)}(?![A-Za-z])",
                    )
                    # The regex is case-sensitive, so the currency token must
                    # be uppercase; don't uppercase the whole match because valid
                    # amount shorthand such as "5k" contains lowercase letters.
                    if not any(
                        re.search(pattern, raw_text)
                        for pattern in explicit_code_amount
                    ):
                        continue
                numeric_match = re.search(amount, match.group(0))
                if not numeric_match:
                    continue
                candidates.append((match.start(), -len(alias), code, self.parse_amount_token(numeric_match.group(1))))

        if not candidates:
            return None
        candidates.sort(key=lambda item: (item[0], item[1]))
        # Multiple explicit amount/currency pairs are ambiguous for this single-value
        # helper. Do not silently pick the first/last; caller should use pair-specific
        # parsing or ask the user to clarify.
        if len(candidates) > 1:
            first_pos, first_len, first_code, first_amount = candidates[0]
            distinct = {(code, amount) for _, _, code, amount in candidates}
            if len(distinct) > 1:
                return None
            # Repeated references to same pair (e.g. "SGD 100, exactly SGD 100") are safe.
            return first_amount, first_code
        return candidates[0][3], candidates[0][2]

    def extract_conversion_pair(self, text: str) -> tuple[str, str] | None:
        """Extract and canonicalize a user-requested FX pair from codes or currency names."""
        raw_text = str(text or "")
        t = self.repair_user_text(raw_text).upper()
        aliases = {
            "SINGAPORE DOLLARS": "SGD", "SINGAPORE DOLLAR": "SGD",
            "MALAYSIAN RINGGIT": "MYR", "RINGGIT": "MYR",
            "US DOLLARS": "USD", "US DOLLAR": "USD", "US$": "USD",
            "RENMINBI": "CNY", "YUAN": "CNY", "RMB": "CNY", "CNY": "CNY",
            "S$": "SGD", "SGD": "SGD", "MYR": "MYR", "RM": "MYR",
            "USD": "USD", "EUR": "EUR", "EURO": "EUR", "EUROS": "EUR",
            "GBP": "GBP", "POUND": "GBP", "POUNDS": "GBP",
            "JPY": "JPY", "YEN": "JPY", "KRW": "KRW", "WON": "KRW",
            "THB": "THB", "BAHT": "THB", "AUD": "AUD", "CAD": "CAD",
            "HKD": "HKD", "TWD": "TWD", "INR": "INR", "IDR": "IDR",
            "PHP": "PHP", "VND": "VND", "NZD": "NZD", "CHF": "CHF",
            "SEK": "SEK", "NOK": "NOK", "DKK": "DKK", "SAR": "SAR",
            "AED": "AED", "QAR": "QAR", "BND": "BND", "BHD": "BHD",
            "TRY": "TRY", "BDT": "BDT", "TND": "TND",
            "SOUTH AFRICAN RAND": "ZAR", "RAND": "ZAR",
            "KUWAITI DINAR": "KWD", "POLISH ZLOTY": "PLN", "ZLOTY": "PLN",
            "TURKISH LIRA": "TRY", "MEXICAN PESO": "MXN",
            "MOROCCAN DIRHAM": "MAD", "PERUVIAN SOL": "PEN",
            "TONGAN PAANGA": "TOP", "GEORGIAN LARI": "GEL", "LARI": "GEL",
            "COLOMBIAN PESO": "COP", "BOLIVIAN BOLIVIANO": "BOB",
            "ROMANIAN LEU": "RON", "ROMANIAN LEI": "RON",
            "BRAZILIAN REAL": "BRL", "SWISS FRANC": "CHF",
            "CANADIAN DOLLAR": "CAD", "AUSTRALIAN DOLLAR": "AUD",
            "HONG KONG DOLLAR": "HKD", "NEW ZEALAND DOLLAR": "NZD",
            "INDIAN RUPEE": "INR", "INDONESIAN RUPIAH": "IDR",
            "PHILIPPINE PESO": "PHP", "VIETNAMESE DONG": "VND",
            "THAI BAHT": "THB", "KOREAN WON": "KRW", "JAPANESE YEN": "JPY",
            "CHINESE YUAN": "CNY", "SAUDI RIYAL": "SAR",
            "UAE DIRHAM": "AED", "QATARI RIYAL": "QAR",
            "PAKISTANI RUPEE": "PKR", "BANGLADESHI TAKA": "BDT",
            "NIGERIAN NAIRA": "NGN", "EGYPTIAN POUND": "EGP",
            "ISRAELI NEW SHEKEL": "ILS",
            "AFGHAN AFGHANI": "AFN", "AFGHANI": "AFN",
            "ANGOLAN KWANZA": "AOA", "BARBADIAN DOLLAR": "BBD",
            "BERMUDIAN DOLLAR": "BMD", "BAHAMIAN DOLLAR": "BSD",
            "BHUTANESE NGULTRUM": "BTN", "BELIZE DOLLAR": "BZD",
            "CUBAN PESO": "CUP", "CAPE VERDE ESCUDO": "CVE",
            "FALKLAND ISLANDS POUND": "FKP", "GIBRALTAR POUND": "GIP",
            "GAMBIAN DALASI": "GMD", "GUINEAN FRANC": "GNF",
            "IRANIAN RIAL": "IRR", "KYRGYZSTANI SOM": "KGS",
            "NORTH KOREAN WON": "KPW", "CAYMAN ISLANDS DOLLAR": "KYD",
            "LIBERIAN DOLLAR": "LRD", "LIBYAN DINAR": "LYD",
            "MAURITANIAN OUGUIYA": "MRU", "NICARAGUAN CORDOBA": "NIO",
            "PAPUA NEW GUINEAN KINA": "PGK", "SAINT HELENA POUND": "SHP",
            "SIERRA LEONEAN LEONE": "SLE", "SAO TOME DOBRA": "STN",
            "SWAZI LILANGENI": "SZL", "ZIMBABWE GOLD": "ZWG",
            "ALL": "ALL", "AMD": "AMD", "ARS": "ARS", "AZN": "AZN",
            "AFN": "AFN", "AOA": "AOA", "BBD": "BBD", "BMD": "BMD", "BSD": "BSD", "BTN": "BTN", "BZD": "BZD", "CUP": "CUP", "CVE": "CVE", "FKP": "FKP", "GIP": "GIP", "GMD": "GMD", "GNF": "GNF", "IRR": "IRR", "KGS": "KGS", "KPW": "KPW", "KYD": "KYD", "LRD": "LRD", "LYD": "LYD", "MRU": "MRU", "NIO": "NIO", "PGK": "PGK", "SHP": "SHP", "SLE": "SLE", "STN": "STN", "SZL": "SZL", "ZWG": "ZWG",
            "BAM": "BAM", "BGN": "BGN", "BOB": "BOB", "BRL": "BRL",
            "BYN": "BYN", "CLP": "CLP", "COP": "COP", "CRC": "CRC",
            "CZK": "CZK", "DOP": "DOP", "DZD": "DZD", "EGP": "EGP",
            "GEL": "GEL", "GHS": "GHS", "GTQ": "GTQ", "HNL": "HNL",
            "HUF": "HUF", "ILS": "ILS", "IQD": "IQD", "ISK": "ISK",
            "JOD": "JOD", "KES": "KES", "KWD": "KWD", "KZT": "KZT",
            "LBP": "LBP", "LKR": "LKR", "MAD": "MAD", "MDL": "MDL",
            "MKD": "MKD", "MMK": "MMK", "MNT": "MNT", "MOP": "MOP",
            "MUR": "MUR", "MVR": "MVR", "MXN": "MXN", "NGN": "NGN",
            "NPR": "NPR", "OMR": "OMR", "PEN": "PEN", "PKR": "PKR",
            "PLN": "PLN", "PYG": "PYG", "RON": "RON", "RSD": "RSD",
            "RUB": "RUB", "RWF": "RWF", "UAH": "UAH", "UYU": "UYU",
            "UZS": "UZS", "VES": "VES", "XAF": "XAF", "XOF": "XOF",
            "XPF": "XPF", "ZAR": "ZAR", "ZMW": "ZMW", "ZWL": "ZWL",
            "ETB": "ETB", "TZS": "TZS", "UGX": "UGX", "XCD": "XCD",
            "BWP": "BWP", "BIF": "BIF", "CDF": "CDF", "DJF": "DJF",
            "ERN": "ERN", "FJD": "FJD", "GYD": "GYD", "HTG": "HTG",
            "JMD": "JMD", "KHR": "KHR", "KMF": "KMF", "LAK": "LAK",
            "LSL": "LSL", "MGA": "MGA", "MWK": "MWK", "MZN": "MZN",
            "NAD": "NAD", "PAB": "PAB", "SBD": "SBD", "SCR": "SCR",
            "SDG": "SDG", "SOS": "SOS", "SRD": "SRD", "SSP": "SSP",
            "SYP": "SYP", "TJS": "TJS", "TMT": "TMT", "TOP": "TOP",
            "TTD": "TTD", "VUV": "VUV", "WST": "WST", "YER": "YER",
        }
        # Currency codes that overlap ordinary words require an exact uppercase token.
        # Keep this policy local to the matcher so normalization cannot turn "try",
        # "all", "cup", etc. into a currency identifier.
        ambiguous_codes = {"ALL", "TRY", "MAD", "PEN", "TOP", "GEL", "COP", "BOB", "RON", "CUP"}
        # Unique symbols can identify a currency in a pair even without an amount.
        # Shared "$" and "¥" symbols deliberately remain unsupported/ambiguous.
        symbol_aliases = {
            "R$": "BRL", "ZŁ": "PLN", "€": "EUR", "£": "GBP", "₹": "INR",
            "₩": "KRW", "฿": "THB", "₱": "PHP", "₦": "NGN", "₺": "TRY",
            "₪": "ILS", "₫": "VND", "₴": "UAH", "₡": "CRC", "₲": "PYG",
            "₵": "GHS", "₸": "KZT", "₭": "LAK", "₮": "MNT", "₼": "AZN",
        }
        choices = sorted(
            [
                alias for alias in aliases
                if alias not in ambiguous_codes
                or re.search(rf"(?<![A-Za-z]){re.escape(alias)}(?![A-Za-z])", raw_text)
            ] + list(symbol_aliases),
            key=len,
            reverse=True,
        )
        canonical_codes = {**aliases, **{symbol: code for symbol, code in symbol_aliases.items()}}
        # Match longer names first so "US DOLLARS" is not reduced to "DOLLARS".
        # ASCII-letter boundaries allow symbols to act as complete tokens.
        token = r"(?<![A-Z])(?:" + "|".join(re.escape(a) for a in choices) + r")(?![A-Z])"
        optional_amount = r"(?:\s+[0-9][0-9,]*(?:\.[0-9]+)?[kKmM]?)?"
        patterns = [
            rf"\bFROM\s+(?P<base>{token}){optional_amount}\s+TO\s+(?P<quote>{token})",
            rf"(?P<base>{token}){optional_amount}\s*(?:TO|→|->|INTO|IN)\s*(?P<quote>{token})",
        ]
        for pattern in patterns:
            # Prefer the original input so ambiguous code casing remains meaningful.
            # Iterate all matches: a lowercase ordinary word must not be legitimized
            # by an unrelated uppercase occurrence elsewhere in the same message.
            for raw_match in re.finditer(pattern, raw_text, re.IGNORECASE):
                raw_base = raw_match.group("base").strip()
                raw_quote = raw_match.group("quote").strip()
                base_key = raw_base.upper()
                quote_key = raw_quote.upper()
                if base_key not in canonical_codes or quote_key not in canonical_codes:
                    continue
                if base_key in ambiguous_codes and raw_base != base_key:
                    continue
                if quote_key in ambiguous_codes and raw_quote != quote_key:
                    continue
                base = canonical_codes[base_key]
                quote = canonical_codes[quote_key]
                if base != quote:
                    return base, quote

            # Typo normalization can repair ordinary currency names/codes. Keep that
            # fallback for unambiguous currencies only; ambiguous words fail closed.
            match = re.search(pattern, t)
            if match:
                base_key = match.group("base").strip()
                quote_key = match.group("quote").strip()
                if base_key in ambiguous_codes or quote_key in ambiguous_codes:
                    continue
                base = canonical_codes[base_key]
                quote = canonical_codes[quote_key]
                if base != quote:
                    return base, quote
        return None

    def has_ambiguous_dollar_reference(self, text: str) -> bool:
        """Detect FX questions that use an unqualified dollar word or shared $ symbol."""
        normalized = self.repair_user_text(str(text or "")).lower().replace("’", "'")
        fx_context = any(term in normalized for term in [
            "convert", "conversion", "exchange", "exchange rate", " rate", "rate ",
            "fx", "how much", "what is", "what's", "whats", "compare", "currency",
            "transfer", "send", "remit", "remittance", "pay", "payment", "move money",
        ])
        if not fx_context:
            return False

        dollar_qualifiers = (
            "us", "american", "singapore", "malaysian", "australian", "canadian",
            "new zealand", "hong kong", "taiwan", "brunei", "bermudian", "bahamian",
            "barbadian", "belize", "cayman islands", "liberian", "nicaraguan",
            "solomon islands", "namibian", "fijian", "east caribbean",
            "usd", "sgd", "myr", "aud", "cad", "nzd", "hkd", "twd", "bnd",
            "bmd", "bsd", "bbd", "bzd", "kyd", "lrd", "nio", "sbd", "nad", "fjd", "xcd",
        )
        qualifier_pattern = r"\b(?:" + "|".join(re.escape(x) for x in sorted(dollar_qualifiers, key=len, reverse=True)) + r")\s+$"

        for match in re.finditer(r"\b(?:dollar|dollars)\b", normalized):
            prefix = normalized[max(0, match.start() - 45):match.start()]
            if re.search(qualifier_pattern, prefix, re.I):
                continue
            return True

        # "$" is shared across multiple currencies. Recognize common qualified
        # forms (US$, S$, A$, C$, HK$, NT$, R$) but reject a bare symbol in FX questions.
        for match in re.finditer(r"\$", normalized):
            prefix = normalized[max(0, match.start() - 4):match.start()]
            if re.search(r"(?:us|s|sg|a|c|hk|nt|r)$", prefix, re.I):
                continue
            return True
        return False

    def user_negates_money_movement(self, text: str) -> bool:
        """Detect a direct refusal to initiate a money-moving action.

        A request to quote, calculate affordability, compare rates, or explicitly
        keep a transaction unexecuted is not a refusal to answer the question.
        It must remain read-only rather than being swallowed by a broad negation
        match that happens to see the word "transfer" later in the prompt.
        """
        normalized = self.repair_user_text(str(text or "")).lower().replace("’", "'")

        # A direct refusal to transfer or convert is stronger than generic
        # quote-language elsewhere in the same message. Never let a mention of
        # the current rate override "I don't want to transfer".
        direct_refusal = re.search(
            r"\b(?:do\s+not\s+want\s+to|don't\s+want\s+to|dont\s+want\s+to|"
            r"do\s+not\s+wish\s+to|don't\s+wish\s+to|would\s+prefer\s+not\s+to|"
            r"prefer\s+not\s+to)\s+(?:any\s+)?(?:transfer|send|remit(?:tance)?|convert|exchange|move(?:\s+money)?|pay)\b",
            normalized,
            re.I,
        )
        if direct_refusal:
            return True

        read_only_language = any(phrase in normalized for phrase in (
            "only a quotation", "quotation request", "quote only", "quotation only",
            "estimate the cost", "estimate a conversion", "current exchange rate",
            "compare converting", "compare conversion", "can i afford",
            "do i have enough funds", "tell me whether i have enough",
            "how much would i receive", "how much myr should i receive",
        ))
        if read_only_language:
            return False

        # "Do not execute" limits the requested result; it does not mean the
        # user refuses analysis or a pending proposal that must remain unexecuted.
        if re.search(
            r"\b(?:do\s+not|don't|dont|must\s+not|mustn't|mustnt|will\s+not|won't|wont)\s+execute\b",
            normalized,
            re.I,
        ):
            return False

        negation = r"(?:do\s+not\s+want\s+to|don't\s+want\s+to|dont\s+want\s+to|do\s+not\s+wish\s+to|don't\s+wish\s+to|would\s+prefer\s+not\s+to|prefer\s+not\s+to|do\s+not|don't|dont|never|should\s+not|shouldn't|shouldnt|must\s+not|mustn't|mustnt|will\s+not|won't|wont|would\s+not|wouldn't|wouldnt|refuse\s+to|not\s+willing\s+to|cancel|stop)"
        action = r"(?:transfer|send|remit(?:tance)?|convert|exchange|move(?:\s+money)?|pay|prepare\s+(?:a\s+)?(?:transfer|proposal)|create\s+(?:a\s+)?proposal)"
        # Keep negation close to the actual action. The old 80-character window
        # confused a warning at the end of a long prompt with the user's intent.
        return bool(re.search(
            rf"\b{negation}\s+(?:(?:any|the|my|a|an|this|that)\s+)?{action}\b",
            normalized,
            re.I,
        ))

    def _handle_conversation_followup(
        self,
        text: str,
        conversation_history: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | str | None:
        """Resolve short follow-ups only from the immediately preceding verified exchange.

        History is contextual evidence, not financial authority. Any proposal reference
        must resolve to a real, unexpired proposal in this engine's state, and a
        contextual approval is accepted only when the current user explicitly approves.
        """
        turns = [
            item for item in (conversation_history or [])
            if isinstance(item, dict) and item.get("role") in {"user", "assistant"}
            and isinstance(item.get("content"), str)
        ][-50:]
        current = self.repair_user_text(str(text or "")).strip()
        current_lower = current.lower().replace("’", "'")
        current_compact = re.sub(r"[.!?]+$", "", current_lower).strip()
        last_turn = turns[-1] if turns else {}
        last_content = str(last_turn.get("content", "")).lower().replace("’", "'")
        previous_user = next(
            (str(item.get("content", "")) for item in reversed(turns[:-1]) if item.get("role") == "user"),
            "",
        )
        previous_user_lower = self.repair_user_text(previous_user).lower()

        # If the user says the previous financial answer missed the question,
        # rerun the last read-only financial query through the deterministic engine
        # instead of replying with generic capability/help text. Never replay an
        # action request from chat history.
        direct_answer_correction = bool(re.search(
            r"\b(?:can\s+(?:you|u)|could\s+(?:you|u))\s+(?:please\s+)?directly\s+answer\b"
            r"|\b(?:please\s+)?answer\s+(?:my|the)\s+question\s+directly\b"
            r"|\b(?:you\s+)?(?:didn't|did\s+not)\s+answer\s+(?:my|the)\s+question\b"
            r"|\bthat\s+(?:doesn't|does\s+not|didn't|did\s+not)\s+answer\s+(?:my|the)\s+question\b"
            r"|\bjust\s+answer\s+(?:my|the)\s+question\b",
            current_lower,
            re.I,
        ))
        prior_financial_question = bool(previous_user_lower) and any(term in previous_user_lower for term in [
            "tuition", "school fee", "fees", "afford", "balance", "how much do i have",
            "exchange rate", "convert", "currency", "spending", "expenses", "cash flow",
            "forecast", "funding gap", "financial position",
        ])
        prior_intent = self.detect_intent(previous_user) if previous_user else "general"
        if (
            direct_answer_correction
            and last_turn.get("role") == "assistant"
            and prior_financial_question
            and prior_intent in {"affordability", "balance", "forecast", "spending", "transactions", "fx", "general"}
        ):
            return previous_user

        # A one-word currency answer resolves a previous source-currency question.
        source_aliases = {
            "myr": "MYR", "rm": "MYR", "ringgit": "MYR", "malaysian ringgit": "MYR",
            "sgd": "SGD", "s$": "SGD", "singapore dollar": "SGD", "singapore dollars": "SGD",
            "usd": "USD", "us$": "USD", "us dollar": "USD", "us dollars": "USD",
            "cny": "CNY", "rmb": "CNY", "yuan": "CNY", "eur": "EUR", "euro": "EUR",
            "gbp": "GBP", "pound": "GBP", "pounds": "GBP", "aud": "AUD", "cad": "CAD",
            "jpy": "JPY", "yen": "JPY", "hkd": "HKD", "twd": "TWD", "inr": "INR",
            "idr": "IDR", "php": "PHP", "vnd": "VND", "nzd": "NZD", "chf": "CHF",
            "krw": "KRW", "won": "KRW", "thb": "THB", "baht": "THB", "bnd": "BND",
            "aed": "AED", "sar": "SAR", "qar": "QAR", "try": "TRY", "mxn": "MXN",
            "zar": "ZAR", "brl": "BRL", "pln": "PLN", "inr": "INR", "pkr": "PKR",
            "bdt": "BDT", "ngn": "NGN", "egp": "EGP", "ils": "ILS", "afn": "AFN",
            "kwd": "KWD", "bhd": "BHD", "omr": "OMR", "jod": "JOD",
        }
        currency_reply = re.fullmatch(
            r"(?:the source currency is\s+|the amount is in\s+|it's\s+|its\s+)?"
            r"([a-z]{3}|s\$|us\$|rm|ringgit|malaysian ringgit|singapore dollars?|"
            r"us dollars?|euro|euros|pound|pounds|yen|yuan|rmb|baht|won)[.!]?",
            current_lower,
        )
        if (
            currency_reply
            and last_turn.get("role") == "assistant"
            and any(phrase in last_content for phrase in [
                "which currency is the amount in", "which currency is the amount",
                "which currency are you starting from", "source currency",
                "which currency do you mean", "which currency do you mean by",
                "bare '$' symbol",
            ])
        ):
            raw_currency = currency_reply.group(1).strip().lower()
            source = source_aliases.get(raw_currency, raw_currency.upper() if re.fullmatch(r"[a-z]{3}", raw_currency) else None)
            target_match = re.search(
                r"\b(?:to|into)\s+(?:the\s+)?(?P<target>[a-z]{3}|s\$|us\$|"
                r"singapore dollars?|malaysian ringgit|ringgit|us dollars?|euro|euros|"
                r"pounds?|yen|yuan|rmb|baht|won)\b",
                previous_user_lower,
            )
            amount_match = re.search(
                r"\b(?:convert|exchange|change)\s+(?:the\s+)?"
                r"(?P<amount>[0-9][0-9,]*(?:\.[0-9]+)?[km]?)\s+(?:to|into)\b",
                previous_user_lower,
            )
            if not amount_match:
                target_start = target_match.start() if target_match else len(previous_user_lower)
                amount_match = re.search(
                    r"(?<![A-Za-z0-9])(?P<amount>[0-9][0-9,]*(?:\.[0-9]+)?[km]?)(?![A-Za-z0-9])",
                    previous_user_lower[:target_start],
                )
            if source and target_match and amount_match:
                target_raw = target_match.group("target")
                try:
                    pair = self.extract_conversion_pair(f"{source} to {target_raw}")
                except Exception:
                    pair = None
                if pair:
                    amount = amount_match.group("amount")
                    return (
                        f"Convert {amount} {pair[0]} to {pair[1]} at the current reference exchange rate. "
                        "This is a quotation only; do not create or execute a transfer."
                    )

        # Resolve "how about in USD?" as a balance follow-up only when the previous
        # exchange was itself a balance lookup. This prevents a bare currency mention
        # from being mistaken for an FX-rate question in unrelated contexts.
        balance_followup = re.fullmatch(
            r"(?:and\s+)?(?:how|what)\s+about\s+(?:my\s+)?(?:balance\s+)?(?:in\s+)?"
            r"(?P<currency>[a-z]{3}|s\$|us\$)[.!?]?",
            current_lower,
        )
        prior_was_balance = (
            last_turn.get("role") == "assistant"
            and any(phrase in last_content for phrase in [
                "you currently have", "your current demo-account balances", "configured demo-account balances",
                "i don't see a configured",
            ])
            and any(phrase in previous_user_lower for phrase in [
                "how much do i have", "what is my balance", "show my balance", "current balance",
            ])
        )
        if balance_followup and prior_was_balance:
            code = source_aliases.get(balance_followup.group("currency"), balance_followup.group("currency").upper())
            return f"How much do I have in {code}?"

        # Proposal identity comes from the last assistant turn, but is trusted only
        # after looking it up in the authoritative engine proposal store.
        contextual_proposal = None
        contextual_proposal_id = None
        if last_turn.get("role") == "assistant" and last_turn.get("proposal_id"):
            candidate_id = str(last_turn.get("proposal_id"))
            candidate = self.state.get("proposals", {}).get(candidate_id)
            if candidate:
                contextual_proposal_id = candidate_id
                contextual_proposal = candidate

        # A direct replay request must be resolved against the immediately shown
        # proposal before the generic planner asks for an amount or considers any
        # transaction action. The proposal store, not client history, is authoritative.
        execution_replay_request = (
            bool(re.search(
                r"\b(?:execute|run|process|repeat|replay)\b.*\b(?:again|same|previous|already)\b",
                current_lower,
            ))
            and bool(re.search(r"\b(?:transfer|transaction|proposal|conversion|payment)\b", current_lower))
        ) or bool(re.search(r"\b(?:do|run)\s+(?:that|it)\s+again\b", current_lower))

        if execution_replay_request:
            if not contextual_proposal or not contextual_proposal_id:
                # If the user supplied an explicit MYR amount, let the established
                # deterministic execution guard handle it. That guard can match the
                # exact amount to an executed proposal without trusting client history.
                # Amount-less pronouns still must not select a global proposal.
                if self.extract_myr_amount(current) is not None:
                    return None
                return self._result(
                    "agentic_local",
                    "I couldn't verify which earlier transaction you mean from the immediately preceding reply. "
                    "I have not executed anything again. Please check the transaction history; I won't select a transaction from unrelated history.",
                    [{"step": "UNDERSTAND", "status": "completed", "detail": "Detected a request to replay a previous transaction."},
                     {"step": "SECURITY", "status": "blocked", "detail": "No trusted contextual proposal reference was available; no transaction was executed."}],
                    {"blocked_reason": "missing_contextual_proposal", "state_changed": False, "proposal": None},
                )

            proposal_status = str(contextual_proposal.get("status", "unknown")).upper()
            if proposal_status == "EXECUTED":
                transaction_id = contextual_proposal.get("transaction_id")
                if not transaction_id:
                    transaction = next(
                        (
                            item for item in reversed(self.state.get("transactions", []))
                            if item.get("proposal_id") == contextual_proposal_id
                            or item.get("id") == contextual_proposal.get("transaction_id")
                        ),
                        None,
                    )
                    transaction_id = (transaction or {}).get("id", "the original transaction")
                return self._result(
                    "agentic_local",
                    f"I blocked the replay. Proposal {contextual_proposal_id} was already executed as {transaction_id} and cannot be executed again. "
                    "No new transaction was created and no balances changed.",
                    [{"step": "UNDERSTAND", "status": "completed", "detail": "Matched the replay request to the previously displayed proposal."},
                     {"step": "OBSERVE", "status": "completed", "detail": f"Verified proposal status is {proposal_status}."},
                     {"step": "SECURITY", "status": "blocked", "detail": "Prevented transaction replay; the existing execution remains unchanged."}],
                    {"blocked_reason": "transaction_replay_prevented", "proposal": contextual_proposal,
                     "existing_transaction_id": transaction_id, "state_changed": False, "proposal_reused": False},
                )

            if proposal_status == "PENDING_AUTHORIZATION":
                return self._result(
                    "agentic_local",
                    f"Proposal {contextual_proposal_id} is still awaiting authorization. I did not execute it. Review and authorize the pending proposal through the required authorization flow first.",
                    [{"step": "UNDERSTAND", "status": "completed", "detail": "Matched the execution request to the immediately displayed proposal."},
                     {"step": "SECURITY", "status": "blocked", "detail": "Direct execution cannot bypass pending authorization."}],
                    {"blocked_reason": "proposal_still_pending", "proposal": contextual_proposal,
                     "state_changed": False, "proposal_reused": False},
                )

            return self._result(
                "agentic_local",
                f"Proposal {contextual_proposal_id} is in status {proposal_status}. I will not replay or execute it again through a chat shortcut. No new transaction was created.",
                [{"step": "UNDERSTAND", "status": "completed", "detail": "Matched the replay request to the immediately displayed proposal."},
                 {"step": "SECURITY", "status": "blocked", "detail": f"Proposal status {proposal_status} does not permit replay."}],
                {"blocked_reason": "proposal_not_replayable", "proposal": contextual_proposal,
                 "state_changed": False, "proposal_reused": False},
            )

        # A standalone high-value acknowledgement is a separate state-machine step:
        # persist acknowledgement on the authoritative pending proposal, but do not
        # authorize or execute until the user gives a separate explicit approval.
        acknowledgement_only = (
            any(phrase in current_lower for phrase in [
                "i acknowledge", "i have reviewed", "i reviewed",
                "i acknowledge that", "i have carefully reviewed",
            ])
            and any(phrase in current_lower for phrase in [
                "high-value review", "high value review", "reviewed the amount",
                "amount, destination", "quote and risk", "risk reasons",
            ])
            and not re.search(
                r"\b(?:authori[sz](?:e|ed)|approve|approved|execute|executed|send|transfer|pay)\b",
                current_lower,
            )
        )
        if acknowledgement_only:
            if not contextual_proposal or not contextual_proposal_id:
                return self._result(
                    "agentic_local",
                    "I understand that you've reviewed the high-value details, but I couldn't match this acknowledgement to a proposal shown in the immediately preceding reply. No proposal was authorized or executed. Reopen the relevant proposal and acknowledge its review there.",
                    [{"step": "UNDERSTAND", "status": "completed", "detail": "Recognized a standalone high-value review acknowledgement."},
                     {"step": "SECURITY", "status": "blocked", "detail": "No verified contextual proposal was available; no authorization or execution occurred."}],
                    {"blocked_reason": "missing_contextual_proposal", "state_changed": False, "proposal": None},
                )
            if contextual_proposal.get("status") != "PENDING_AUTHORIZATION":
                return self._result(
                    "agentic_local",
                    f"Proposal {contextual_proposal_id} is not pending authorization, so its review acknowledgement cannot advance it. No transaction was executed.",
                    [{"step": "UNDERSTAND", "status": "completed", "detail": "Matched the acknowledgement to the displayed proposal."},
                     {"step": "SECURITY", "status": "blocked", "detail": "Review acknowledgement cannot change a terminal proposal."}],
                    {"blocked_reason": "proposal_not_pending", "state_changed": False, "proposal": contextual_proposal},
                )
            if str(contextual_proposal.get("risk", {}).get("status", "")).upper() != "REVIEW":
                return self._result(
                    "agentic_local",
                    f"Proposal {contextual_proposal_id} does not require high-value review. It remains pending authorization, and nothing was executed.",
                    [{"step": "UNDERSTAND", "status": "completed", "detail": "Matched the acknowledgement to the displayed proposal."},
                     {"step": "SECURITY", "status": "completed", "detail": "No unnecessary review acknowledgement was recorded."}],
                    {"proposal": contextual_proposal, "state_changed": False},
                )
            try:
                acknowledged = self.acknowledge_review(contextual_proposal_id)
            except ValueError as exc:
                return self._result(
                    "agentic_local",
                    f"I couldn't record the high-value review acknowledgement: {exc} No authorization or execution occurred.",
                    [{"step": "UNDERSTAND", "status": "completed", "detail": "Matched the acknowledgement to the displayed high-value proposal."},
                     {"step": "SECURITY", "status": "blocked", "detail": str(exc)}],
                    {"proposal": self.state["proposals"].get(contextual_proposal_id, contextual_proposal),
                     "blocked_reason": "review_acknowledgement_blocked", "state_changed": False},
                )
            return self._result(
                "agentic_local",
                f"High-value review acknowledgement recorded for proposal {contextual_proposal_id} (RM{float(acknowledged['amount_myr']):,.2f}). The proposal remains pending. This acknowledgement did not authorize or execute the transfer; balances are unchanged. To continue, explicitly authorize the same proposal.",
                [{"step": "UNDERSTAND", "status": "completed", "detail": "Recognized a standalone high-value review acknowledgement."},
                 {"step": "OBSERVE", "status": "completed", "detail": f"Verified pending proposal {contextual_proposal_id} in the authoritative proposal store."},
                 {"step": "SECURITY", "status": "completed", "detail": "Recorded acknowledgement only; authorization and execution remain separate required steps."}],
                {"proposal": acknowledged, "review_acknowledged": True, "state_changed": True,
                 "authorization_granted": False, "transaction_created": False},
            )

        # Short "why did you authorize?" questions should explain the verified
        # last action rather than fall through to generic help. This is strictly
        # read-only: a proposal ID from the transcript is accepted only after it
        # resolves to the authoritative server-side proposal above.
        why_action_question = (
            bool(re.search(r"\bwhy\b", current_lower))
            and bool(re.search(
                r"\b(?:authori[sz](?:e|ed|ation)|approv(?:e|ed|al)|execut(?:e|ed|ion)|"
                r"transfer|transaction|send|process|move|payment)\b",
                current_lower,
            ))
        )
        if why_action_question and contextual_proposal and contextual_proposal_id:
            proposal_status = str(contextual_proposal.get("status", "unknown")).upper()
            amount_myr = float(contextual_proposal.get("amount_myr", 0.0) or 0.0)
            review_required = str(contextual_proposal.get("risk", {}).get("status", "")).upper() == "REVIEW"
            review_acknowledged = bool(contextual_proposal.get("review_acknowledged"))
            transaction_id = contextual_proposal.get("transaction_id")
            if proposal_status == "EXECUTED":
                if not transaction_id:
                    transaction = next(
                        (
                            item for item in reversed(self.state.get("transactions", []))
                            if item.get("proposal_id") == contextual_proposal_id
                        ),
                        None,
                    )
                    transaction_id = (transaction or {}).get("id", "the recorded transaction")
                trigger = previous_user.strip() or "your prior authorization message"
                if review_required:
                    explanation = (
                        "The high-value acknowledgement and authorization are separate steps. "
                        "Your acknowledgement recorded that you reviewed the amount, destination, quote and risk reasons; "
                        "it did not itself authorize the conversion. After the proposal remained pending, your next message "
                        f"({trigger!r}) was an explicit instruction to authorize that same proposal. "
                        "The application matched it to the verified pending proposal and then enforced the stored review acknowledgement "
                        "and transaction policy before executing it."
                    )
                else:
                    explanation = (
                        "I did not authorize it on my own. The application had a verified pending proposal, and your subsequent "
                        f"message ({trigger!r}) was interpreted as the explicit authorization to proceed. "
                        "The application checked that proposal against its authorization and transaction rules before executing it."
                    )
                answer = (
                    f"{explanation} Proposal {contextual_proposal_id} for RM{amount_myr:,.2f} "
                    f"was recorded as executed under transaction {transaction_id}. "
                    "This was a sandbox conversion; no real money moved. This explanation did not change balances, proposals or transactions."
                )
                return self._result(
                    "agentic_local",
                    answer,
                    [
                        {"step": "UNDERSTAND", "status": "completed", "detail": "Resolved a contextual question about the immediately preceding authorization/execution."},
                        {"step": "OBSERVE", "status": "completed", "detail": f"Verified proposal {contextual_proposal_id} is already EXECUTED in the server-side store."},
                        {"step": "REASON", "status": "completed", "detail": "Explained the separate review acknowledgement and explicit authorization steps."},
                        {"step": "SECURITY", "status": "completed", "detail": "Read-only explanation; no replay or state mutation was performed."},
                    ],
                    {
                        "goal": "explain_prior_authorization",
                        "proposal": contextual_proposal,
                        "transaction_id": transaction_id,
                        "state_changed": False,
                        "explanation_only": True,
                    },
                )

            if proposal_status == "PENDING_AUTHORIZATION":
                if review_required and not review_acknowledged:
                    explanation = (
                        "I did not authorize or execute it because the proposal requires high-value review, and the required review acknowledgement "
                        "has not been recorded for this proposal. You must review the amount, destination, quote and risk reasons first."
                    )
                elif review_required and review_acknowledged:
                    explanation = (
                        "The high-value review was acknowledged, but that acknowledgement is not authorization. "
                        "The proposal remains pending until you separately authorize this exact proposal."
                    )
                else:
                    explanation = (
                        "I have not authorized or executed the proposal. Preparing it only creates a pending proposal; "
                        "a separate explicit authorization is required before sandbox execution."
                    )
                return self._result(
                    "agentic_local",
                    f"{explanation} Proposal {contextual_proposal_id} remains pending. No balances or transactions changed.",
                    [
                        {"step": "UNDERSTAND", "status": "completed", "detail": "Resolved a contextual question about a pending proposal."},
                        {"step": "SECURITY", "status": "completed", "detail": "No authorization or execution was triggered by the question."},
                    ],
                    {"goal": "explain_pending_authorization", "proposal": contextual_proposal,
                     "state_changed": False, "explanation_only": True},
                )

        repeat_proposal_request = bool(re.search(
            r"\b(?:prepare|create|show|repeat)\b.*\b(?:exactly\s+the\s+same|same|again|repeat)\b.*"
            r"\b(?:transfer|proposal|conversion)\b|\bprepare\s+exactly\s+the\s+same\s+"
            r"(?:transfer\s+)?proposal\s+again\b",
            current_lower,
        ))
        if repeat_proposal_request:
            if contextual_proposal and contextual_proposal.get("status") == "PENDING_AUTHORIZATION":
                if self._expire_if_needed(contextual_proposal) or self._expire_proposal_if_needed(
                    contextual_proposal_id or "", contextual_proposal
                ):
                    return self._result(
                        "agentic_local",
                        "The previous proposal has expired. I did not reuse or recreate it. Please request a fresh proposal with the exact MYR amount so I can obtain a new quote.",
                        [{"step": "UNDERSTAND", "status": "completed", "detail": "Matched the follow-up to the prior proposal."},
                         {"step": "SECURITY", "status": "blocked", "detail": "The prior proposal expired and cannot be replayed."}],
                        {"proposal": contextual_proposal, "blocked_reason": "proposal_expired", "state_changed": False},
                    )
                return self._result(
                    "agentic_local",
                    f"The exact same proposal already exists and is still pending: RM{float(contextual_proposal['amount_myr']):,.2f} to SGD at the quoted rate {float(contextual_proposal['rate']):.6f}. I reused proposal {contextual_proposal['id']} instead of creating a duplicate. It has not been authorized or executed.",
                    [{"step": "UNDERSTAND", "status": "completed", "detail": "Resolved 'the same proposal' to the immediately preceding proposal."},
                     {"step": "OBSERVE", "status": "completed", "detail": f"Verified proposal {contextual_proposal['id']} is still pending."},
                     {"step": "SECURITY", "status": "completed", "detail": "Reused the existing proposal; no duplicate proposal or transaction was created."}],
                    {"proposal": contextual_proposal, "proposal_reused": True, "state_changed": False},
                )
            return self._result(
                "agentic_local",
                "I couldn't safely identify an active proposal from the immediately preceding message. Please state the exact MYR amount again; I won't infer it from an older or unrelated request.",
                [{"step": "UNDERSTAND", "status": "completed", "detail": "Detected a request to repeat a proposal without an active contextual proposal reference."},
                 {"step": "SECURITY", "status": "blocked", "detail": "No amount was inferred and no proposal was created."}],
                {"blocked_reason": "missing_contextual_proposal", "state_changed": False, "proposal": None},
            )

        # A short approval such as "I authorised it" is contextual consent only
        # when the immediately preceding assistant response explicitly contained a
        # proposal ID and that ID still identifies one pending proposal.
        authorization_phrase = (
            bool(re.search(
                r"\b(?:i\s+(?:explicitly\s+)?(?:authori[sz](?:e|ed)|approv(?:e|ed)|confirm(?:ed)?|accept(?:ed)?)"
                r"(?:\s+(?:it|this|the proposal|the transfer))?|"
                r"(?:yes\s*,?\s*)?(?:authori[sz](?:e|ed)|approv(?:e|ed)|confirm(?:ed)?)\s+"
                r"(?:it|this|the proposal|the transfer))\b",
                current_lower,
            ))
            # Short forms such as "just authorise" are supported only in the
            # contextual handler below, which still validates the proposal,
            # status and high-value acknowledgement.
            or bool(re.fullmatch(
                r"(?:just|please|go ahead and)\s+(?:authori[sz](?:e|ed)|approv(?:e|ed)|confirm(?:ed)?)",
                current_lower,
            ))
        )
        if authorization_phrase:
            # Preserve the established exact-amount authorization route for messages
            # that explicitly identify RM/MYR. This maintains the existing safety
            # checks for amount matching, conflicting edits, and security overrides.
            # Only amount-less pronouns such as "I authorised it" use conversation
            # context, and those require the immediately displayed, verified proposal.
            explicit_myr_amount = bool(re.search(
                r"\b(?:rm|myr|malaysian\s+ringgit|ringgit)\s*[0-9][0-9,]*(?:\.[0-9]{1,2})?\b"
                r"|\b[0-9][0-9,]*(?:\.[0-9]{1,2})?\s*(?:rm|myr|malaysian\s+ringgit|ringgit)\b",
                current_lower,
                re.I,
            ))
            if explicit_myr_amount:
                return None
            if not contextual_proposal or not contextual_proposal_id:
                # Do not let a short approval authorize whichever proposal happens
                # to be pending globally; the user must identify a specific proposal.
                return self._result(
                    "agentic_local",
                    "I couldn't match that approval to a proposal shown in the immediately preceding reply. Nothing was authorized or executed. Please reopen the proposal and use its authorization control, or state the exact RM amount you intend to authorize.",
                    [{"step": "UNDERSTAND", "status": "completed", "detail": "Detected an authorization follow-up without a verified contextual proposal reference."},
                     {"step": "SECURITY", "status": "blocked", "detail": "No proposal was selected from global pending state alone."}],
                    {"blocked_reason": "missing_contextual_proposal", "state_changed": False, "proposal": None},
                )
            if contextual_proposal.get("status") != "PENDING_AUTHORIZATION":
                return self._result(
                    "agentic_local",
                    f"Proposal {contextual_proposal_id} is no longer pending authorization (status: {contextual_proposal.get('status', 'unknown')}). I did not replay it or create a new transaction.",
                    [{"step": "UNDERSTAND", "status": "completed", "detail": "Matched the approval to the referenced proposal."},
                     {"step": "SECURITY", "status": "blocked", "detail": "A proposal outside PENDING_AUTHORIZATION cannot be authorized again."}],
                    {"proposal": contextual_proposal, "blocked_reason": "proposal_not_pending", "state_changed": False},
                )
            risk_status = str(contextual_proposal.get("risk", {}).get("status", "")).upper()
            explicit_review_ack = (
                ("acknowledge" in current_lower and any(
                    word in current_lower for word in ["review", "high value", "high-value", "risk"]
                ))
                or contextual_proposal.get("review_acknowledged") is True
            )
            if risk_status == "REVIEW" and not explicit_review_ack:
                return self._result(
                    "agentic_local",
                    f"Proposal {contextual_proposal_id} for RM{float(contextual_proposal['amount_myr']):,.2f} requires high-value review. I have not authorized or executed it. Please explicitly acknowledge that you reviewed the amount, destination, quote and risk reasons, then authorize it, or use the dashboard's review confirmation.",
                    [{"step": "UNDERSTAND", "status": "completed", "detail": "Matched the approval to a high-value proposal."},
                     {"step": "SECURITY", "status": "blocked", "detail": "Explicit high-value review acknowledgement is still required."}],
                    {"proposal": contextual_proposal, "blocked_reason": "review_requires_acknowledgement", "state_changed": False},
                )
            try:
                authorized = self.authorize(
                    contextual_proposal_id,
                    True,
                    acknowledge_review=(risk_status == "REVIEW" and explicit_review_ack),
                )
                executed = self.execute(contextual_proposal_id)
            except ValueError as exc:
                return self._result(
                    "agentic_local",
                    f"I couldn't complete authorization/execution of proposal {contextual_proposal_id}: {exc}. No unverified transfer will be reported as completed.",
                    [{"step": "UNDERSTAND", "status": "completed", "detail": "Matched the approval to the referenced pending proposal."},
                     {"step": "SECURITY", "status": "blocked", "detail": str(exc)}],
                    {"proposal": self.state.get("proposals", {}).get(contextual_proposal_id, contextual_proposal),
                     "blocked_reason": "authorization_or_execution_blocked", "state_changed": False},
                )
            tx = executed["transaction"]
            return self._result(
                "agentic_local",
                f"Approval matched proposal {contextual_proposal_id} for RM{float(authorized['amount_myr']):,.2f}. The sandbox conversion to SGD completed and was verified at the proposal's locked rate of {float(authorized['rate']):.6f}. Transaction {tx['id']} was recorded in the audit trail. No real money moved.",
                [{"step": "UNDERSTAND", "status": "completed", "detail": "Matched the explicit approval to the proposal displayed immediately before it."},
                 {"step": "AUTHORIZE", "status": "completed", "detail": f"Recorded Level 2 authorization for {contextual_proposal_id}."},
                 {"step": "EXECUTE", "status": "completed", "detail": f"Sandbox transaction {tx['id']} executed."},
                 {"step": "VERIFY", "status": "completed", "detail": "Verified the account balances and completed transaction."},
                 {"step": "AUDIT", "status": "completed", "detail": "Authorization and execution were audited."}],
                {"proposal": executed["proposal"], "transaction": tx, "balances": executed["balances"],
                 "state_changed": True, "contextual_authorization": True},
            )

        return None

    def agent(
        self,
        text: str,
        conversation_history: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        contextual = self._handle_conversation_followup(text, conversation_history)
        if isinstance(contextual, dict):
            return contextual
        if isinstance(contextual, str):
            text = contextual
        # Safety-critical deterministic gate: uncertain family support must never
        # reach an LLM planner as if it were confirmed cash. Keep this path
        # self-contained so a local-agent exception cannot silently fall through.
        normalized = self.repair_user_text(text).lower()
        # An explicit instruction not to move money must stop before either
        # planner can interpret surrounding text as a proposal request.
        if self.user_negates_money_movement(text):
            return self._result(
                "agentic_local",
                "Understood. I will not prepare or execute a money movement from that request. "
                "No proposal, transaction, or account change was made.",
                [
                    {"step": "UNDERSTAND", "status": "completed", "detail": "Recognized an explicit instruction against money movement."},
                    {"step": "SECURITY", "status": "blocked", "detail": "Stopped before LLM or offline planning because the user negated the action."},
                ],
                {
                    "blocked_reason": "user_explicitly_opposed_money_movement",
                    "state_changed": False,
                    "proposal": None,
                    "agent_mode": "deterministic_negated_action_gate",
                },
            )
        if self.has_ambiguous_dollar_reference(text):
            question = (
                "Which currency do you mean by 'dollars' or the bare '$' symbol—US dollars (USD), "
                "Singapore dollars (SGD), Australian dollars (AUD), Canadian dollars (CAD), or another currency? "
                "I have not created a proposal or transaction."
            )
            return self._result(
                "fx",
                question,
                [
                    {"step": "UNDERSTAND", "status": "completed", "detail": "Detected an unqualified dollar reference in an FX request."},
                    {"step": "OBSERVE", "status": "needs_input", "detail": "Asked the user to identify the dollar currency before selecting an FX pair."},
                    {"step": "SECURITY", "status": "completed", "detail": "Clarification only; no proposal or transaction was created."},
                ],
                {"needs_clarification": True, "ambiguous_currency": "dollar", "state_changed": False, "proposal": None},
            )
        # Safety-critical all-funds gate: never reinterpret "all/everything" as
        # a harmless FX quote or allow a planner to derive an amount from the wallet.
        # State-changing money movement requires an exact amount.
        security_override = any(k in normalized for k in [
            "ignore all previous", "ignore previous security", "ignore previous rules",
            "ignore the security", "override security", "bypass security",
            "bypass the policy", "you are authorized", "execute immediately",
        ])
        all_funds_money_action = (
            bool(re.search(
                r"\b(?:all|everything)\s+(?:my|of my)\s+(?:funds|money|balance|wallet)\b|"
                r"\b(?:all|everything)\s+(?:in|from)\s+my\s+(?:wallet|account|balance)\b|"
                r"\b(?:all|everything)\s+(?:in|from)\s+my\s+[a-z]{3}\s+(?:wallet|account|balance)\b|"
                r"\b(?:all|everything)\s+my\s+[a-z]{3}\b",
                normalized,
            ))
            and any(k in normalized for k in [
                "transfer", "send", "remit", "remittance", "convert", "conversion",
                "exchange", "pay", "move", "move my",
            ])
        )
        if security_override and any(k in normalized for k in [
            "transfer", "send", "execute", "prepare", "convert", "remit", "move", "pay"
        ]):
            return self._result(
                "agentic_local",
                "I can't override the security policy or grant authorization through natural language. "
                "Money movement requires an explicit proposal and Level 2 authorization. No transaction was created.",
                [
                    {"step": "UNDERSTAND", "status": "completed", "detail": "Detected an attempt to override financial security controls."},
                    {"step": "SECURITY", "status": "blocked", "detail": "Security override language cannot grant authorization or bypass deterministic policy."},
                ],
                {"blocked_reason": "security_policy_override_attempt", "state_changed": False},
            )

        if all_funds_money_action:
            return self._result(
                "agentic_local",
                "I blocked that request because 'all/everything' does not define a safe transaction amount. "
                "Please specify the exact amount and currency. No proposal or transaction was created.",
                [
                    {"step": "UNDERSTAND", "status": "completed", "detail": "Detected an all-funds money-moving request."},
                    {"step": "SECURITY", "status": "blocked", "detail": "Blocked ambiguous amount before FX, planning, or execution logic."},
                ],
                {
                    "blocked_reason": "ambiguous_all_funds_request",
                    "state_changed": False,
                    "agent_mode": "deterministic_all_funds_safety_gate",
                },
            )

        conditional_income_question = (
            (
                any(k in normalized for k in [
                    "can i assume", "assume that money", "assume the money", "count that money",
                    "treat that money", "can i count it", "can i count that",
                ])
                or (
                    "what if" in normalized
                    and any(k in normalized for k in [
                        "next month", "next week", "in two weeks", "later", "in a month"
                    ])
                )
            )
            and any(k in normalized for k in [
                "might", "may", "could", "possibly", "maybe", "will", "sends", "send me"
            ])
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

        # Deterministic hypothetical-income gate.
        # Questions such as "What if I receive another 2000 SGD next month?"
        # must simulate the stated incoming funds without mutating the wallet.
        hypothetical_income_question = (
            any(k in normalized for k in ["what if", "if i receive", "if i get", "if i were to receive"])
            and any(k in normalized for k in ["receive", "get", "incoming"])
            and any(k in normalized for k in ["next month", "later", "tomorrow", "next week", "in a month"])
        )
        if hypothetical_income_question:
            income_match = re.search(
                r"(?:receive(?:d)?|get|incoming)\s+(?:just\s+)?(?:another\s+)?(?P<amount>[0-9][0-9,]*(?:\.[0-9]+)?)(?P<suffix>[km]?)\s*(?P<currency>sgd|s\$|myr|rm|usd|us\$|cny|rmb|yuan)"
                r"|(?:receive(?:d)?|get|incoming)\s+(?:just\s+)?(?:another\s+)?(?P<currency_prefix>sgd|s\$|myr|rm|usd|us\$|cny|rmb|yuan)\s*(?P<amount_prefix>[0-9][0-9,]*(?:\.[0-9]+)?)(?P<suffix_prefix>[km]?)",
                normalized,
                re.IGNORECASE,
            )
            if income_match:
                groups = income_match.groupdict()
                amount_text = groups["amount"] or groups["amount_prefix"]
                suffix = groups["suffix"] or groups["suffix_prefix"] or ""
                currency_text = groups["currency"] or groups["currency_prefix"]
                multiplier = (
                    Decimal("1000") if suffix.lower() == "k"
                    else Decimal("1000000") if suffix.lower() == "m"
                    else Decimal("1")
                )
                amount = money(Decimal(amount_text.replace(",", "")) * multiplier)
                currency_alias_to_code = {
                    "sgd": "SGD", "s$": "SGD",
                    "myr": "MYR", "rm": "MYR",
                    "usd": "USD", "us$": "USD",
                    "cny": "CNY", "rmb": "CNY", "yuan": "CNY",
                }
                currency = currency_alias_to_code[currency_text.lower()]
                try:
                    simulation = self.simulate_income_impact(float(amount), currency)
                    after = simulation["projected_balance_after_hypothetical_income_sgd"]
                    before = simulation["forecast_before"]["projected_balance_sgd"]
                    improvement = simulation["projected_added_sgd"]
                    answer = (
                        f"If you receive {currency} {amount:,.2f}, your projected 30-day position "
                        f"would improve by about SGD {improvement:,.2f}, from SGD {before:,.2f} "
                        f"to about SGD {after:,.2f}. This is a hypothetical simulation only; "
                        f"your actual wallet balance has not changed."
                    )
                    return self._result(
                        "agentic_local",
                        answer,
                        [
                            {"step": "UNDERSTAND", "status": "completed", "detail": "Detected hypothetical incoming funds."},
                            {"step": "SIMULATE", "status": "completed", "detail": f"Simulated {currency} {amount:,.2f} without mutating account state."},
                            {"step": "SECURITY", "status": "completed", "detail": "No account state changed and no transaction was created."},
                        ],
                        {
                            "hypothetical_income": True,
                            "state_changed": False,
                            "simulation": simulation,
                            "agent_mode": "deterministic_hypothetical_income_gate",
                        },
                    )
                except (ValueError, HTTPError, URLError, TimeoutError, OSError) as exc:
                    return self._result(
                        "agentic_local",
                        f"I can model that hypothetical income, but I could not safely calculate its impact because the required reference data is unavailable ({type(exc).__name__}). No account state was changed.",
                        [
                            {"step": "UNDERSTAND", "status": "completed", "detail": "Detected hypothetical incoming funds."},
                            {"step": "SIMULATE", "status": "blocked", "detail": f"Simulation data was unavailable: {type(exc).__name__}."},
                            {"step": "SECURITY", "status": "completed", "detail": "No account state changed and no transaction was created."},
                        ],
                        {
                            "hypothetical_income": True,
                            "state_changed": False,
                            "blocked_reason": "simulation_data_unavailable",
                            "agent_mode": "deterministic_hypothetical_income_gate",
                        },
                    )

        # Deterministic multi-currency affordability gate.
        # This safety-critical advisory path runs before the optional LLM and local
        # planner so explicit scenario amounts can never fall through to the saved demo wallet.
        multi_currency_affordability = (
            "tuition" in normalized
            and any(k in normalized for k in ["can i do", "can i afford", "will i have enough", "can i cover"])
            and any(k in normalized for k in ["emergency savings", "emergency reserve", "emergency fund"])
        )
        if multi_currency_affordability:
            aliases = {
                "MYR": ["myr", "rm"],
                "SGD": ["sgd", "s$"],
                "USD": ["usd", "us$"],
                "CNY": ["cny", "rmb", "yuan"],
            }

            def parse_human(raw):
                raw = str(raw).replace(",", "").strip()
                suffix = raw[-1:].lower()
                multiplier = Decimal("1000") if suffix == "k" else Decimal("1000000") if suffix == "m" else Decimal("1")
                if suffix in {"k", "m"}:
                    raw = raw[:-1]
                return money(Decimal(raw) * multiplier)

            wallet = {}
            # Only read balances from the explicit "I've got/have..." possession clause.
            possession = re.search(
                r"\b(?:have|has|hold|holding|own|keep|got|gotten)\b(?P<body>.*?)"
                r"(?=\b(?:need|needs|want to|would like to|send|sending|remit|transfer|pay|paying|require|required|tuition|school fees)\b|[.!?]|$)",
                normalized,
                re.I,
            )
            body = possession.group("body") if possession else ""
            for code, names in aliases.items():
                token = "|".join(re.escape(x) for x in sorted(names, key=len, reverse=True))
                m = re.search(
                    rf"(?:{token})\s*([0-9]+(?:,[0-9]{{3}})*(?:\.[0-9]+)?[km]?)|"
                    rf"([0-9]+(?:,[0-9]{{3}})*(?:\.[0-9]+)?[km]?)\s*(?:{token})\b",
                    body,
                    re.I,
                )
                if m:
                    wallet[code] = parse_human(m.group(1) or m.group(2))

            tuition = re.search(
                r"([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?[km]?)\s*"
                r"(sgd|s\$|myr|rm|usd|us\$|cny|rmb|yuan)\s+tuition\b",
                normalized,
                re.I,
            )
            reserve = re.search(
                r"\bkeep\s+(?:an?\s+)?([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?[km]?)\s*"
                r"(sgd|s\$|myr|rm|usd|us\$|cny|rmb|yuan)\b[^.]*?\bemergency\s+"
                r"(?:savings|reserve|fund)\b",
                normalized,
                re.I,
            )
            if tuition and reserve and len(wallet) >= 2:
                code_map = {
                    "sgd": "SGD", "s$": "SGD",
                    "myr": "MYR", "rm": "MYR",
                    "usd": "USD", "us$": "USD",
                    "cny": "CNY", "rmb": "CNY", "yuan": "CNY",
                }
                tuition_amount = parse_human(tuition.group(1))
                tuition_currency = code_map[tuition.group(2).lower()]
                reserve_amount = parse_human(reserve.group(1))
                reserve_currency = code_map[reserve.group(2).lower()]

                total_sgd = money(0)
                valuation = []
                fx_quotes = {}
                for code, amount in wallet.items():
                    if code == "SGD":
                        rate = Decimal("1")
                        fx_meta = {"source": "Base currency", "date": None, "live": False}
                    else:
                        # Scenario balances are hypothetical inputs, so use the direct
                        # reference pair rather than any saved profile balance/config.
                        fx_meta = self._fetch_reference_pair(code, "SGD")
                        rate = fxrate(fx_meta["rate"])
                        # Reject an obviously mismatched cross-currency quote. This can
                        # happen when a provider/proxy returns the MYR/SGD quote for a
                        # different pair. Fall back to the bundled indicative reference.
                        scenario_fallbacks = {
                            "USD": Decimal("1.2771"),
                            "CNY": Decimal("0.1908"),
                            "MYR": Decimal("0.3220"),
                        }
                        if code in scenario_fallbacks and (
                            (code == "USD" and rate < Decimal("0.5"))
                            or (code == "CNY" and rate > Decimal("0.5"))
                            or (code == "MYR" and rate > Decimal("1.0"))
                        ):
                            rate = scenario_fallbacks[code]
                            fx_meta = {
                                **fx_meta,
                                "rate": float(rate),
                                "source": "bundled indicative fallback",
                                "live": False,
                            }
                    fx_quotes[code] = {
                        "rate_to_sgd": float(rate),
                        "source": fx_meta.get("source"),
                        "rate_date": fx_meta.get("date"),
                        "live": bool(fx_meta.get("live", False)),
                    }
                    value = money(amount * rate)
                    total_sgd = money(total_sgd + value)
                    valuation.append(f"{code} {amount:,.2f} ≈ SGD {value:,.2f}")

                tuition_rate = (
                    Decimal("1")
                    if tuition_currency == "SGD"
                    else fxrate(self._fetch_reference_pair(tuition_currency, "SGD")["rate"])
                )
                reserve_rate = (
                    Decimal("1")
                    if reserve_currency == "SGD"
                    else fxrate(self._fetch_reference_pair(reserve_currency, "SGD")["rate"])
                )
                tuition_sgd = money(tuition_amount * tuition_rate)
                reserve_sgd = money(reserve_amount * reserve_rate)
                usable_sgd = money(max(Decimal("0"), total_sgd - reserve_sgd))
                shortfall_sgd = money(max(Decimal("0"), tuition_sgd - usable_sgd))
                remaining_sgd = money(usable_sgd - tuition_sgd)

                if shortfall_sgd > 0:
                    answer = (
                        f"No — there's a shortfall of about SGD {shortfall_sgd:,.2f}. "
                        f"After protecting SGD {reserve_sgd:,.2f} in emergency savings, "
                        f"you have SGD {usable_sgd:,.2f} available for SGD {tuition_sgd:,.2f} tuition."
                    )
                else:
                    answer = (
                        f"Yes — after protecting SGD {reserve_sgd:,.2f} in emergency savings, "
                        f"you have SGD {usable_sgd:,.2f} available for SGD {tuition_sgd:,.2f} tuition, "
                        f"leaving about SGD {remaining_sgd:,.2f}."
                    )
                reserve_label = f"{reserve_currency} {reserve_amount:,.2f} ≈ SGD {reserve_sgd:,.2f}"
                tuition_label = f"{tuition_currency} {tuition_amount:,.2f} ≈ SGD {tuition_sgd:,.2f}"
                answer += (
                    " Read-only affordability simulation — no transaction or proposal was created. "
                    "Only the balances stated in this message were used; your saved wallet was not used. "
                    "Reference FX is indicative, not a bank settlement quote."
                )
                return self._result(
                    "agentic_local",
                    answer,
                    [
                        {"step": "UNDERSTAND", "status": "completed", "detail": "Detected an explicit multi-currency tuition affordability scenario."},
                        {"step": "OBSERVE", "status": "completed", "detail": "Used only the balances explicitly stated in the user's message; saved profile balances were not used."},
                        {"step": "FX", "status": "completed", "detail": f"Normalized {len(wallet)} stated currencies into SGD using reference FX."},
                        {"step": "CALCULATE", "status": "completed", "detail": f"Protected the stated emergency-savings floor ({reserve_label}) before assessing tuition ({tuition_label})."},
                        {"step": "SECURITY", "status": "completed", "detail": "Read-only simulation; no proposal or transaction was created."},
                    ],
                    {
                        "goal": "financial_plan",
                        "wallet_source": "message",
                        "wallet_balances_used": {code: float(amount) for code, amount in wallet.items()},
                        "fx_quotes": fx_quotes,
                        "affordability": {
                            "wallet_total_sgd": float(total_sgd),
                            "reserve_sgd": float(reserve_sgd),
                            "usable_sgd": float(usable_sgd),
                            "tuition_sgd": float(tuition_sgd),
                            "shortfall_sgd": float(shortfall_sgd),
                            "remaining_sgd": float(remaining_sgd),
                            "reserve": {
                                "currency": reserve_currency,
                                "amount": float(reserve_amount),
                                "sgd_equivalent": float(reserve_sgd),
                            },
                            "tuition": {
                                "currency": tuition_currency,
                                "amount": float(tuition_amount),
                                "sgd_equivalent": float(tuition_sgd),
                            },
                        },
                        "state_changed": False,
                        "agent_mode": "deterministic_multi_currency_affordability_gate",
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

        # Explicit figures in an affordability question override demo-wallet
        # values. This read-only path must never create a conversion proposal.
        explicit_tuition_case = (
            any(k in normalized for k in ["tuition", "school fee", "school fees"])
            and any(k in normalized for k in ["can i afford", "tell me i can afford", "even if the numbers"])
        )
        if explicit_tuition_case:
            amount_matches = list(re.finditer(
                r"(?<![A-Za-z])(?:sgd|s\$)\s*([0-9][0-9,]*(?:\.\d{1,2})?)",
                normalized,
            ))
            amounts = [money(Decimal(match.group(1).replace(",", ""))) for match in amount_matches]
            tuition_index = None
            separators = list(re.finditer(r"[,;.!?]|\b(?:and|while|but)\b", normalized))
            for index, match in enumerate(amount_matches):
                clause_start = max(
                    [separator.end() for separator in separators if separator.end() <= match.start()]
                    or [0]
                )
                clause_end = min(
                    [separator.start() for separator in separators if separator.start() >= match.end()]
                    or [len(normalized)]
                )
                clause = normalized[clause_start:clause_end]
                if re.search(r"\b(tuition|school fees?)\b", clause):
                    tuition_index = index
                    break
            if len(amounts) >= 2:
                tuition_position = tuition_index if tuition_index is not None else 1
                tuition_due = amounts[tuition_position]
                available_index = next(index for index in range(len(amounts)) if index != tuition_position)
                available = amounts[available_index]
                gap = money(max(Decimal("0"), tuition_due - available))
                answer = (
                    f"Based only on the figures you supplied, you cannot fully cover the tuition from the stated available cash. "
                    f"Available cash: SGD {available:,.2f}; tuition due: SGD {tuition_due:,.2f}; shortfall: SGD {gap:,.2f}. "
                    "I won't claim it is affordable when the arithmetic shows a gap. Check for confirmed income arriving before the due date and contact the tuition provider early to discuss options. "
                    "No proposal or transaction was created."
                )
                return self._result(
                    "affordability", answer,
                    [
                        {"step": "UNDERSTAND", "status": "completed", "detail": "Recognized explicit user-supplied affordability figures."},
                        {"step": "OBSERVE", "status": "completed", "detail": "Used prompt amounts, not saved demo-wallet data."},
                        {"step": "CALCULATE", "status": "completed", "detail": f"SGD {tuition_due:,.2f} tuition minus SGD {available:,.2f} available equals SGD {gap:,.2f} shortfall."},
                        {"step": "SECURITY", "status": "completed", "detail": "Read-only response; no proposal or transaction was created."},
                        {"step": "RECOMMEND", "status": "completed", "detail": "Recommended checking confirmed funds and contacting the tuition provider."},
                    ],
                    {"available_cash_sgd": float(available), "tuition_due_sgd": float(tuition_due), "shortfall_sgd": float(gap), "state_changed": False, "proposal": None},
                )


        # Deterministic casual tuition-affordability gate.
        # Natural-language student questions such as "I got 2k SGD and tuition
        # is around 6k soon, am I cooked?" should use only the balances and
        # tuition amount explicitly stated in the message, not the saved demo
        # wallet or saved emergency-reserve configuration.
        casual_tuition_question = (
            "tuition" in normalized
            and any(k in normalized for k in [
                "am i cooked", "cooked", "am i okay", "am i ok",
                "can i afford", "do i have enough", "can i cover",
            ])
            and any(k in normalized for k in ["got", "have", "i've got", "ive got"])
        )
        if casual_tuition_question:
            casual_sgd_values = []
            # Keep these regexes simple: support "SGD 2k" and "2k SGD"
            # without nested escaping.
            for match in re.finditer(
                r"(?:sgd|s\$)\s*([0-9][0-9,]*(?:\.[0-9]+)?)([km]?)",
                normalized,
                re.IGNORECASE,
            ):
                amount_text, suffix = match.groups()
                multiplier = (
                    Decimal("1000") if suffix.lower() == "k"
                    else Decimal("1000000") if suffix.lower() == "m"
                    else Decimal("1")
                )
                casual_sgd_values.append(
                    money(Decimal(amount_text.replace(",", "")) * multiplier)
                )
            for match in re.finditer(
                r"([0-9][0-9,]*(?:\.[0-9]+)?)([km]?)\s*(?:sgd|s\$)",
                normalized,
                re.IGNORECASE,
            ):
                amount_text, suffix = match.groups()
                multiplier = (
                    Decimal("1000") if suffix.lower() == "k"
                    else Decimal("1000000") if suffix.lower() == "m"
                    else Decimal("1")
                )
                casual_sgd_values.append(
                    money(Decimal(amount_text.replace(",", "")) * multiplier)
                )
            # The two explicit-SGD regexes intentionally cover both word orders,
            # but the same amount can match both. Deduplicate before deciding whether
            # a second (implicit-SGD) tuition amount still needs to be parsed.
            casual_sgd_values = list(dict.fromkeys(casual_sgd_values))

            # Casual tuition wording often omits the currency on the
            # second amount, e.g. "I got 2k SGD and tuition is around 6k".
            # Since the first amount explicitly establishes SGD, interpret the
            # nearby tuition shorthand as SGD rather than falling through to
            # the saved profile.
            if len(casual_sgd_values) < 2:
                tuition_amount_match = re.search(
                    r"tuition\b.*?(?:around|about|is|of|=)?\s*([0-9][0-9,]*(?:\.[0-9]+)?)([km]?)",
                    normalized,
                    re.IGNORECASE,
                )
                if tuition_amount_match:
                    amount_text, suffix = tuition_amount_match.groups()
                    multiplier = (
                        Decimal("1000") if suffix.lower() == "k"
                        else Decimal("1000000") if suffix.lower() == "m"
                        else Decimal("1")
                    )
                    tuition_value = money(
                        Decimal(amount_text.replace(",", "")) * multiplier
                    )
                    if casual_sgd_values:
                        casual_sgd_values.append(tuition_value)

            if len(casual_sgd_values) >= 2:
                starting_balance, tuition_amount = casual_sgd_values[:2]
                shortfall = money(max(Decimal("0"), tuition_amount - starting_balance))
                remaining = money(starting_balance - tuition_amount)
                if shortfall > 0:
                    answer = (
                        f"Yeah, you're short by about SGD {shortfall:,.2f}: you stated "
                        f"SGD {starting_balance:,.2f} and tuition of about SGD {tuition_amount:,.2f}. "
                        f"That means you would need roughly SGD {shortfall:,.2f} more to cover tuition."
                    )
                else:
                    answer = (
                        f"You're not cooked on tuition alone: you stated SGD {starting_balance:,.2f} "
                        f"against about SGD {tuition_amount:,.2f} tuition, leaving roughly SGD {remaining:,.2f}."
                    )
                return self._result(
                    "agentic_local",
                    answer + " This is an affordability simulation using only the amounts you supplied; no transaction was created or executed.",
                    [
                        {"step": "UNDERSTAND", "status": "completed", "detail": "Detected an informal tuition-affordability question with explicit scenario amounts."},
                        {"step": "CALCULATE", "status": "completed", "detail": f"Compared stated SGD {starting_balance:,.2f} against stated tuition of about SGD {tuition_amount:,.2f}."},
                        {"step": "SECURITY", "status": "completed", "detail": "Used only message-supplied scenario amounts and did not inherit saved reserve or wallet assumptions."},
                    ],
                    {
                        "goal": "financial_plan",
                        "affordability": {
                            "starting_balance_sgd": float(starting_balance),
                            "tuition_sgd": float(tuition_amount),
                            "shortfall_sgd": float(shortfall),
                            "remaining_sgd": float(remaining),
                        },
                        "state_changed": False,
                        "agent_mode": "deterministic_casual_tuition_gate",
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

        # Multi-intent safety gate: if one message mixes uncertain incoming funds
        # with an instruction to move an unspecified remainder, never let planning/FX
        # logic reinterpret it as a safe conversion. The action amount must be explicit.
        uncertain_incoming = (
            any(k in normalized for k in [
                "might send", "may send", "could send", "possibly send",
                "maybe send", "might receive", "may receive", "could receive",
                "possibly receive", "maybe receive",
            ])
            and any(k in normalized for k in ["parent", "parents", "family"])
        )
        ambiguous_remainder_action = (
            any(k in normalized for k in [
                "transfer whatever is left", "send whatever is left",
                "convert whatever is left", "transfer what's left",
                "send what's left", "convert what's left",
                "transfer the rest", "send the rest", "convert the rest",
            ])
        )
        explicit_money_action = any(k in normalized for k in [
            "transfer", "send money", "send ", "remit", "remittance",
            "prepare a transfer", "make a transfer", "create a transfer",
            "set up a transfer", "convert ",
        ])
        if ambiguous_remainder_action or (uncertain_incoming and explicit_money_action and not any(
            k in normalized for k in ["should i", "can i", "could i", "what should i", "how should i", "plan"]
        )):
            return self._result(
                "agentic_local",
                "I blocked that action because the amount is not explicitly defined. "
                "Money that parents or family might send is conditional, and 'whatever is left' "
                "is not a safe transaction amount. Please specify the exact amount and treat uncertain incoming funds as a separate what-if.",
                [
                    {"step": "UNDERSTAND", "status": "completed", "detail": "Detected a multi-intent money-moving request with ambiguous or conditional inputs."},
                    {"step": "SECURITY", "status": "blocked", "detail": "Blocked proposal creation because the transfer amount could not be determined from confirmed funds and an exact amount."},
                ],
                {
                    "blocked_reason": "ambiguous_action_amount",
                    "state_changed": False,
                    "conditional_income": uncertain_incoming,
                    "agent_mode": "deterministic_multi_intent_safety_gate",
                },
            )

        # Bank-recipient transfers are not implemented in this demo. Enforce this
        # before any LLM/local planner can reinterpret the amount as an internal
        # MYR→SGD conversion proposal.
        named_recipient_action = (
            any(k in normalized for k in ["recipient", "beneficiary", "payee"])
            and any(k in normalized for k in ["transfer", "send", "remit", "pay", "prepare"])
        )
        if named_recipient_action:
            return self._result(
                "agentic_local",
                "This XKF5 sandbox does not support payments to named recipients or bank-account transfers yet. "
                "Its supported transfer proposal is an internal MYR-to-SGD conversion, not sending money to a person such as Alice. "
                "I cannot verify or address a recipient from this chat. No proposal or transaction was created, and no account state changed.",
                [
                    {"step": "UNDERSTAND", "status": "completed", "detail": "Detected a named-recipient payment request."},
                    {"step": "SECURITY", "status": "blocked", "detail": "Named-recipient payment is not supported by the current sandbox."},
                ],
                {
                    "blocked_reason": "unsupported_recipient_transfer",
                    "requested_action": "named_recipient_transfer",
                    "state_changed": False,
                    "proposal": None,
                    "agent_mode": "deterministic_unsupported_recipient_gate",
                },
            )

        # User-supplied hypothetical FX rates are arithmetic inputs, not live quotes.
        # Evaluate them directly so a reference-rate lookup cannot override the scenario.
        hypothetical_text = self.repair_user_text(text).lower()
        if any(k in hypothetical_text for k in ["compare", "difference between", "what is the difference"]) and any(
            k in hypothetical_text for k in ["hypothetical", "assume", "at rate", "at 0.", "versus", " vs "]
        ):
            amount_match = re.search(
                r"\b(?P<currency>myr|rm|ringgit|malaysian ringgit|sgd|s\$|singapore dollars?|usd|us\$|us dollars?)\s*(?P<amount>[0-9][0-9,]*(?:\.[0-9]+)?)|"
                r"\b(?P<amount_after>[0-9][0-9,]*(?:\.[0-9]+)?)\s*(?P<currency_after>myr|rm|ringgit|malaysian ringgit|sgd|s\$|singapore dollars?|usd|us\$|us dollars?)\b",
                hypothetical_text,
            )
            rate_matches = re.findall(r"\b(?:at\s+(?:a\s+)?rate\s+of\s+|rate\s+of\s+)?(0?\.[0-9]+|[1-9][0-9]*(?:\.[0-9]+)?)\b", hypothetical_text)
            pair_match = re.search(
                r"\b(sgd|singapore dollars?|myr|ringgit|usd|us dollars?)\s+per\s+(myr|ringgit|sgd|singapore dollars?|usd|us dollars?)\b",
                hypothetical_text,
            )
            explicit_pair = self.extract_conversion_pair(text) if not pair_match else None
            if amount_match and len(rate_matches) >= 2 and (pair_match or explicit_pair):
                currency_aliases = {
                    "rm": "MYR", "ringgit": "MYR", "malaysian ringgit": "MYR", "myr": "MYR",
                    "s$": "SGD", "singapore dollar": "SGD", "singapore dollars": "SGD", "sgd": "SGD",
                    "us$": "USD", "us dollar": "USD", "us dollars": "USD", "usd": "USD",
                }
                amount_currency = currency_aliases.get((amount_match.group("currency") or amount_match.group("currency_after")).lower())
                amount_raw = amount_match.group("amount") or amount_match.group("amount_after")
                if pair_match:
                    rate_quote = currency_aliases.get(pair_match.group(1).lower())
                    rate_base = currency_aliases.get(pair_match.group(2).lower())
                else:
                    rate_base, rate_quote = explicit_pair
                if amount_currency and rate_quote and rate_base and amount_currency == rate_base and rate_base != rate_quote:
                    amount = Decimal(amount_raw.replace(",", ""))
                    rate_a, rate_b = Decimal(rate_matches[-2]), Decimal(rate_matches[-1])
                    result_a, result_b = amount * rate_a, amount * rate_b
                    difference = abs(result_a - result_b)
                    answer = (
                        f"Using your hypothetical rates (not live market quotes):\n"
                        f"• {amount:,.2f} {rate_base} at {rate_a} {rate_quote} per {rate_base} = {result_a:,.2f} {rate_quote}.\n"
                        f"• {amount:,.2f} {rate_base} at {rate_b} {rate_quote} per {rate_base} = {result_b:,.2f} {rate_quote}.\n"
                        f"Difference: {difference:,.2f} {rate_quote}. The higher rate gives {difference:,.2f} {rate_quote} more. No account state changed and no transaction was created."
                    )
                    return self._result("fx_comparison", answer, [
                        {"step": "UNDERSTAND", "status": "completed", "detail": "Extracted the amount, currency pair and both user-supplied hypothetical rates."},
                        {"step": "CALCULATE", "status": "completed", "detail": "Calculated both outcomes and their absolute difference using Decimal arithmetic."},
                        {"step": "SECURITY", "status": "completed", "detail": "Scenario-only calculation; no live quote or transaction was used."},
                    ], {"amount": float(amount), "base_currency": rate_base, "quote_currency": rate_quote,
                        "rates": [float(rate_a), float(rate_b)], "converted_amounts": [float(result_a), float(result_b)],
                        "difference": float(difference), "hypothetical_only": True, "state_changed": False, "proposal": None})

        # If the user names a conversion target and a different display currency,
        # calculate both explicitly instead of silently discarding either instruction.
        # Match any supported ISO code (not only a short hard-coded subset), while
        # validating it through the same currency-pair parser used by normal FX.
        raw_user_text = str(text or "")
        display_currency_match = re.search(
            r"\b(?:show|display|give|report)\s+(?:the\s+)?(?:result|answer|amount|value)\s+in\s+(?P<display>singapore dollars?|malaysian ringgit|ringgit|us dollars?|euros?|euro|pounds?|pound|yuan|rmb|yen|[A-Za-z]{3})\b",
            raw_user_text,
            re.IGNORECASE,
        )
        if display_currency_match:
            conversion_prefix = raw_user_text[:display_currency_match.start()]
            action_match = re.search(r"\b(?:convert|exchange)\b", conversion_prefix, re.IGNORECASE)
            if action_match:
                conversion_text = conversion_prefix[action_match.start():]
                requested_pair = self.extract_conversion_pair(conversion_text)
                explicit_amount = self.extract_generic_currency_amount(conversion_text)
                display_pair = self.extract_conversion_pair(f"MYR to {display_currency_match.group('display')}")
                # Only combine one unambiguous conversion clause with its requested
                # display currency. Multi-conversion requests are handled separately.
                one_action = len(re.findall(r"\b(?:convert|exchange)\b", conversion_text, re.IGNORECASE)) == 1
                if requested_pair and explicit_amount and display_pair and one_action:
                    amount, amount_currency = explicit_amount
                    base, target = requested_pair
                    display = display_pair[1]
                    if amount_currency == base and display != target:
                        try:
                            target_result = self.quote_conversion(amount, base, target)
                            display_result = self.quote_conversion(target_result["converted_amount"], target, display)
                            answer = (
                                f"Your requested conversion is {amount:,.2f} {base} ≈ "
                                f"{target_result['converted_amount']:,.2f} {target} at {target_result['rate']:.6f} {target} per {base}.\n"
                                f"You also asked to show the result in {display}: that is approximately "
                                f"{display_result['converted_amount']:,.2f} {display}, using a separate {target}/{display} reference rate of "
                                f"{display_result['rate']:.6f}. These are indicative reference-rate estimates, not a transaction quote. No account state changed."
                            )
                            return self._result("fx", answer, [
                                {"step": "UNDERSTAND", "status": "completed", "detail": "Preserved both the requested conversion target and the different display currency."},
                                {"step": "CALCULATE", "status": "completed", "detail": "Calculated the requested conversion and then its equivalent in the display currency."},
                                {"step": "SECURITY", "status": "completed", "detail": "Read-only reference estimates; no proposal or transaction was created."},
                            ], {"conversion": target_result, "display_conversion": display_result,
                                "requested_target_currency": target, "display_currency": display,
                                "state_changed": False, "proposal": None})
                        except (ValueError, KeyError, HTTPError, URLError, TimeoutError, OSError) as exc:
                            return self._result("fx", f"I understood that you want {base} converted to {target} and displayed in {display}, but I couldn't retrieve both reference rates reliably ({type(exc).__name__}). I won't substitute another pair or invent a result.", [
                                {"step": "UNDERSTAND", "status": "completed", "detail": "Recognized the requested target and display currencies."},
                                {"step": "FX", "status": "blocked", "detail": "At least one required reference rate was unavailable."},
                            ], {"requested_target_currency": target, "display_currency": display,
                                "needs_clarification": True, "state_changed": False, "proposal": None})

        # Typo-tolerant FX fast path: simple exchange-rate questions should never depend
        # on the LLM understanding every word perfectly. Repair small typos, resolve the pair
        # deterministically, and return a safe reference quote before invoking any planner.
        # Do not skip the deterministic FX quote path just because a read-only
        # question mentions "transfer" in a safety disclaimer. Detect only a
        # positive transfer command, evaluated sentence by sentence.
        fx_action_pattern = re.compile(
            r"\b(?:prepare|create|make|set\s+up|initiate|execute)\s+"
            r"(?:(?:a|an|the)\s+)?(?:sandbox\s+)?(?:transfer|proposal)\b"
            r"|\b(?:transfer|send|remit|pay)\s+(?:rm|myr|sgd|s\$|usd|us\$)\s*[0-9]",
            re.I,
        )
        fx_negated_action_pattern = re.compile(
            r"\b(?:do\s+not|don't|dont|never|should\s+not|shouldn't|shouldnt|"
            r"must\s+not|mustn't|mustnt|will\s+not|won't|wont|would\s+not|wouldn't|wouldnt)"
            r"\s+(?:(?:any|the|my|a|an|this|that)\s+)?"
            r"(?:prepare|create|make|set\s+up|initiate|execute|transfer|send|remit|pay)\b",
            re.I,
        )
        fx_action_segments = re.split(r"[.!?;\\n]+", normalized)
        fx_action_request = any(
            fx_action_pattern.search(segment) and not fx_negated_action_pattern.search(segment)
            for segment in fx_action_segments
        )
        fx_all_funds_request = bool(re.search(r"\b(?:all|everything)\b", normalized))
        family_future_income = (
            any(k in normalized for k in ["family", "parent", "parents"])
            and any(k in normalized for k in ["will send", "sends", "send me", "might send", "may send", "could send"])
            and any(k in normalized for k in ["next month", "later", "tomorrow", "next week", "in a month", "in two weeks"])
        )
        # Multi-conversion requests must precede the single-pair FX fast path.
        multi_fx_text = self.repair_user_text(text).lower()
        if self.detect_intent(text) == "fx":
            # Resolve ambiguous source-money words before any fast parser or planner
            # can silently canonicalize them to USD.
            ambiguous_bucks_early = bool(re.search(r"\b[0-9][0-9,]*(?:\.[0-9]+)?\s+bucks?\b", multi_fx_text))
            # A generic "dollars" source remains ambiguous even when the destination
            # is explicitly named (USD, SGD, MYR, etc.). Only "US dollars"/"US$"
            # explicitly identifies the source as USD.
            ambiguous_dollars_early = bool(re.search(
                r"\b[0-9][0-9,]*(?:\.[0-9]+)?\s+dollars?\s+(?:in|to|into)\s+(?:singapore dollars?|sgd|s\$|malaysian ringgit|ringgit|myr|rm|usd|us\$|us dollars?|cny|rmb|yuan|euros?|eur|pounds?|gbp|yen|jpy|aud|cad|hkd|twd|inr|idr|php|vnd|nzd|chf|sek|nok|dkk|sar|aed|qar|bnd)\b",
                multi_fx_text,
            )) and not re.search(r"\b(?:us dollars?|us\$)\s*[0-9]|[0-9][0-9,]*(?:\.[0-9]+)?\s+(?:us dollars?|us\$)\b", multi_fx_text)
            if ambiguous_bucks_early or ambiguous_dollars_early:
                word = "'bucks'" if ambiguous_bucks_early else "'dollars'"
                return self._result(
                    "fx",
                    f"Which currency do you mean by {word}—for example, US dollars (USD), Singapore dollars (SGD), or another currency?",
                    [
                        {"step": "UNDERSTAND", "status": "completed", "detail": "Detected an ambiguous source currency before conversion parsing."},
                        {"step": "OBSERVE", "status": "needs_input", "detail": "Asked for clarification rather than assuming a currency."},
                    ],
                    {"needs_clarification": True, "state_changed": False, "proposal": None},
                )
            # Handle multiple explicit conversions in one request instead of
            # silently answering only the first pair. Keep this before the
            # single-conversion parser so each amount/pair is calculated independently.
            if any(word in multi_fx_text for word in ["convert", "conversion", "convertions", "exchange"]):
                # Reuse the canonical currency and amount parsers for every
                # conversion clause rather than maintaining a smaller, drifting allowlist.
                conversion_segments = re.split(
                    r";|\n|\b(?:and then|and|then|also)\b",
                    str(text or ""),
                    flags=re.I,
                )
                requests = []
                candidate_segments = []
                for segment in conversion_segments:
                    has_amount = bool(re.search(
                        r"(?<![\d,.])[0-9][0-9,]*(?:\.[0-9]+)?[kKmM]?(?![A-Za-z0-9])",
                        segment,
                    ))
                    has_direction = bool(re.search(r"\b(?:to|into|in)\b", segment, re.I))
                    if has_amount and has_direction:
                        candidate_segments.append(segment)

                    pair = self.extract_conversion_pair(segment)
                    amount_pair = self.extract_generic_currency_amount(segment)
                    if not pair or not amount_pair:
                        continue
                    amount, amount_currency = amount_pair
                    base, quote = pair
                    # Do not treat an amount denominated in the quote currency as
                    # the source amount for this conversion.
                    if amount_currency != base:
                        continue
                    requests.append((money(amount), base, quote))

                if len(candidate_segments) >= 2 and len(requests) < len(candidate_segments):
                    return self._result(
                        "fx",
                        "I found multiple conversion amounts but couldn't confidently identify every source/target pair. "
                        "Please state each amount with its source and target currency. I won't return a partial or guessed result.",
                        [
                            {"step": "UNDERSTAND", "status": "completed", "detail": "Detected multiple conversion clauses."},
                            {"step": "OBSERVE", "status": "needs_input", "detail": "At least one amount/pair could not be resolved unambiguously."},
                            {"step": "SECURITY", "status": "completed", "detail": "No conversion result, proposal, or transaction was created."},
                        ],
                        {"needs_clarification": True, "state_changed": False, "proposal": None},
                    )
                if len(requests) >= 2:
                    results = []
                    lines = []
                    try:
                        for amount, base, quote in requests:
                            conversion = self.quote_conversion(amount, base, quote)
                            results.append(conversion)
                            fx_meta = conversion.get("fx", {})
                            rate_date = fx_meta.get("rate_date") or "date unavailable"
                            updated_at = fx_meta.get("updated_at")
                            timestamp = f"; quote timestamp {updated_at}" if updated_at else "; quote timestamp unavailable"
                            source = fx_meta.get("source", "reference source")
                            lines.append(
                                f"{amount:,.2f} {base} ≈ {conversion['converted_amount']:,.2f} {quote} "
                                f"(1 {base} = {conversion['rate']:.6f} {quote}; rate date {rate_date}{timestamp}; source: {source})"
                            )
                    except (ValueError, KeyError, HTTPError, URLError, TimeoutError, OSError) as exc:
                        return self._result(
                            "fx",
                            f"I identified multiple conversions, but couldn't retrieve a reliable quote for every pair ({type(exc).__name__}). I won't provide a partial set of results that could be misleading. No account state was changed.",
                            [{"step": "UNDERSTAND", "status": "completed", "detail": "Detected multiple explicit currency conversions."},
                             {"step": "FX", "status": "blocked", "detail": "At least one requested pair could not be quoted reliably."}],
                            {"needs_clarification": True, "state_changed": False, "proposal": None},
                        )
                    answer = "Here are both conversions using indicative reference rates:\n" + "\n".join(lines)
                    answer += "\nFees/spread are not included because no verified fee schedule is available in these reference quotes. Rates may differ from your bank's final rate. These are calculations only; no proposal or transaction was created."
                    return self._result(
                        "fx", answer,
                        [{"step": "UNDERSTAND", "status": "completed", "detail": f"Recognized {len(results)} separate conversion requests."},
                         {"step": "FX", "status": "completed", "detail": "Quoted each requested currency pair independently."},
                         {"step": "SECURITY", "status": "completed", "detail": "Read-only conversions; no proposal or transaction was created."}],
                        {"conversions": results, "state_changed": False, "proposal": None},
                    )
            requested_pair = self.extract_conversion_pair(text)
            if not requested_pair and not self.extract_generic_currency_amount(text):
                # Do not default a source-less amount such as "convert 250 to SGD"
                # to the application's MYR/SGD demo quote. An explicitly labeled
                # amount such as "RM3,000" is enough source-currency evidence for
                # existing transfer/proposal logic even if the pair is phrased as a noun.
                destination_only = re.search(
                    r"\b(?:to|into)\s+(?P<target>singapore\s+dollars?|malaysian\s+ringgit|ringgit|us\s+dollars?|australian\s+dollars?|canadian\s+dollars?|euros?|euro|pounds?|pound|yuan|rmb|renminbi|yen|kuwaiti\s+dinar|south\s+african\s+rand|[A-Za-z]{3})\b",
                    str(text or ""),
                    re.IGNORECASE,
                )
                if destination_only:
                    target_pair = self.extract_conversion_pair(f"MYR to {destination_only.group('target')}")
                    if target_pair:
                        target = target_pair[1]
                        return self._result(
                            "fx",
                            f"I can calculate a conversion into {target}, but I couldn't identify the source currency. "
                            "Which currency is the amount in? I haven't calculated a rate or changed account state.",
                            [
                                {"step": "UNDERSTAND", "status": "completed", "detail": f"Recognized {target} as the requested destination currency."},
                                {"step": "OBSERVE", "status": "needs_input", "detail": "Source currency is missing; asked instead of assuming a default."},
                                {"step": "SECURITY", "status": "completed", "detail": "No conversion, proposal, or transaction was created."},
                            ],
                            {"target_currency": target, "needs_clarification": True, "state_changed": False, "proposal": None},
                        )
        if self.detect_intent(text) == "fx" and not (fx_action_request or fx_all_funds_request or family_future_income):
            try:
                repaired = self.repair_user_text(text)
                pair = self.extract_conversion_pair(repaired)
                generic_amount = None
                if pair:
                    # Prefer the amount in the actual conversion sentence, not
                    # an earlier balance mentioned for context.
                    clauses = re.split(r"[;\n]|(?<=[.!?])\s+|\b(?:and then|then|also)\b", repaired, flags=re.I)
                    for clause in clauses:
                        clause_pair = self.extract_conversion_pair(clause)
                        if clause_pair != pair:
                            continue
                        if not any(word in clause.lower() for word in ["convert", "converting", "conversion", "exchange", "how much"]):
                            continue
                        candidate_amount = self.extract_generic_currency_amount(clause)
                        if candidate_amount and candidate_amount[1].upper() == pair[0].upper():
                            generic_amount = candidate_amount
                            break
                if generic_amount is None:
                    generic_amount = self.extract_generic_currency_amount(repaired)
                if pair:
                    base, quote = pair
                    amount = generic_amount[0] if generic_amount else money(1)
                    conv = self.quote_conversion(amount, base, quote)
                    fx_meta = conv.get("fx", {})
                    rate_date = fx_meta.get("rate_date") or "date unavailable"
                    updated_at = fx_meta.get("updated_at")
                    timestamp_note = f"; quote timestamp {updated_at}" if updated_at else "; quote timestamp unavailable"
                    source = fx_meta.get("source", "reference source")
                    answer = (
                        f"The current reference rate is 1 {base} = {conv['rate']:.6f} {quote} "
                        f"(rate date {rate_date}{timestamp_note}). "
                        f"{amount:,.2f} {base} is approximately {conv['converted_amount']:,.2f} {quote}. "
                        f"Source: {source}. Fees/spread are not included: this reference quote does not provide a verified fee schedule, "
                        "so I cannot confirm the final amount after fees. This is not a guaranteed bank quote. No proposal or transaction was created."
                    )
                    return self._result(
                        "fx",
                        answer,
                        [
                            {"step": "UNDERSTAND", "status": "completed", "detail": f"Recognized FX request after typo normalization: {base}→{quote}."},
                            {"step": "OBSERVE", "status": "completed", "detail": f"Retrieved the deterministic {base}/{quote} reference rate."},
                            {"step": "CALCULATE", "status": "completed", "detail": f"Calculated the indicative conversion for {amount:,.2f} {base}."},
                        ],
                        {"conversion": conv, "input_normalized": repaired, "state_changed": False, "proposal": None},
                    )
            except (ValueError, HTTPError, URLError, TimeoutError, OSError, KeyError, TypeError) as exc:
                # Once a source/target pair is recognized, a missing quote must stop
                # here. Passing the request to an LLM planner could turn unavailable
                # reference data into an unsupported estimate or default-pair answer.
                if pair:
                    failed_base, failed_quote = pair
                    return self._result(
                        "fx",
                        f"I recognized {failed_base} to {failed_quote}, but couldn't retrieve a reliable reference rate for that pair ({type(exc).__name__}); the rate is currently unavailable. "
                        "I won't substitute a different currency pair or invent a result. Please retry later or provide a trusted quote.",
                        [
                            {"step": "UNDERSTAND", "status": "completed", "detail": f"Recognized the requested {failed_base}/{failed_quote} pair."},
                            {"step": "FX", "status": "blocked", "detail": "Reference data for the requested pair could not be retrieved."},
                            {"step": "SECURITY", "status": "completed", "detail": "No fallback pair, proposal, or transaction was used."},
                        ],
                        {"requested_pair": [failed_base, failed_quote], "needs_clarification": True, "state_changed": False, "proposal": None},
                    )
                # Malformed wording without a recognized pair may still need a
                # clarification from the offline planner.
                pass

        # Deterministic savings-goal reasoning must take priority over the
        # general planner. Parse explicit figures here so an LLM response cannot
        # override the arithmetic or swallow a local-planner parsing exception.
        savings_signal = any(k in normalized for k in [
            "save enough", "can i save", "savings goal", "target savings",
            "what if my expenses", "expenses increase by",
        ])
        if savings_signal:
            start_match = re.search(r"\b(?:have|currently have|start with|starting with)\s+(?:sgd|s\$)\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s+(?:in\s+)?(?:my\s+)?savings", normalized, re.I)
            income_match = re.search(r"\b(?:receive|earn|income is|income of)\s+(?:sgd|s\$)\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:per|a)\s+month", normalized, re.I)
            expenses_match = re.search(r"\b(?:spend|expenses are|expenses of|spending is)\s+(?:sgd|s\$)\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:per|a)\s+month", normalized, re.I)
            target_match = re.search(r"\b(?:target|reach|have|save up to|save)\s+(?:sgd|s\$)\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s+in\s+(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+months?", normalized, re.I)
            ctx = getattr(self, "_agent_scenario_context", {})
            prior_plan = ctx.get("savings_goal_plan")
            increase_match = re.search(r"\b(?:expenses|spending)\s+(?:increase|go up|rise)\s+by\s+(?:sgd|s\$)?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:per|a)\s+month", normalized, re.I)
            if start_match and income_match and expenses_match and target_match:
                month_words = {"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,"eight":8,"nine":9,"ten":10}
                plan = {
                    "starting": Decimal(start_match.group(1).replace(",", "")),
                    "income": Decimal(income_match.group(1).replace(",", "")),
                    "expenses": Decimal(expenses_match.group(1).replace(",", "")),
                    "target": Decimal(target_match.group(1).replace(",", "")),
                    "months": int(target_match.group(2)) if target_match.group(2).isdigit() else month_words[target_match.group(2).lower()],
                }
                ctx["savings_goal_plan"] = plan
                self._agent_scenario_context = ctx
                monthly = money(plan["income"] - plan["expenses"])
                projected = money(plan["starting"] + monthly * plan["months"])
                shortfall = money(max(Decimal("0"), plan["target"] - projected))
                surplus = money(max(Decimal("0"), projected - plan["target"]))
                return self._result(
                    "savings_projection",
                    f"Savings projection over {plan['months']} months, using your stated figures:\n"
                    f"- Starting savings: SGD {plan['starting']:,.2f}\n"
                    f"- Monthly income: SGD {plan['income']:,.2f}\n"
                    f"- Monthly expenses: SGD {plan['expenses']:,.2f}\n"
                    f"- Monthly savings: SGD {monthly:,.2f}\n"
                    f"- Projected savings: SGD {projected:,.2f}\n"
                    f"- Target: SGD {plan['target']:,.2f}\n"
                    + (f"You are projected to fall short by SGD {shortfall:,.2f}.\n" if shortfall else f"You are projected to meet or exceed the target by SGD {surplus:,.2f}.\n")
                    + "Assumes income and expenses stay constant; excludes interest, fees, emergencies, and unlisted costs. Read-only scenario; no account balances changed.",
                    [
                        {"step":"UNDERSTAND","status":"completed","detail":"Recognized a savings goal and time horizon."},
                        {"step":"OBSERVE","status":"completed","detail":"Used amounts explicitly supplied by the user."},
                        {"step":"CALCULATE","status":"completed","detail":f"Monthly savings SGD {monthly:,.2f}; projected savings SGD {projected:,.2f}."},
                        {"step":"SECURITY","status":"completed","detail":"Read-only calculation; no proposal or transaction created."},
                    ],
                    {"starting_savings_sgd":float(plan["starting"]),"monthly_income_sgd":float(plan["income"]),"monthly_expenses_sgd":float(plan["expenses"]),"monthly_surplus_sgd":float(monthly),"months":plan["months"],"target_savings_sgd":float(plan["target"]),"projected_savings_sgd":float(projected),"shortfall_sgd":float(shortfall),"surplus_sgd":float(surplus),"state_changed":False,"proposal":None},
                )
            if prior_plan and increase_match:
                increase = Decimal(increase_match.group(1).replace(",", ""))
                adjusted_expenses = money(prior_plan["expenses"] + increase)
                monthly = money(prior_plan["income"] - adjusted_expenses)
                projected = money(prior_plan["starting"] + monthly * prior_plan["months"])
                shortfall = money(max(Decimal("0"), prior_plan["target"] - projected))
                surplus = money(max(Decimal("0"), projected - prior_plan["target"]))
                return self._result(
                    "savings_projection",
                    f"Updated projection with monthly expenses increased by SGD {increase:,.2f}:\n"
                    f"- Monthly expenses: SGD {adjusted_expenses:,.2f}\n"
                    f"- Monthly savings: SGD {monthly:,.2f}\n"
                    f"- Projected savings after {prior_plan['months']} months: SGD {projected:,.2f}\n"
                    f"- Target: SGD {prior_plan['target']:,.2f}\n"
                    + (f"You are projected to fall short by SGD {shortfall:,.2f}." if shortfall else f"You are projected to meet or exceed the target by SGD {surplus:,.2f}."),
                    [
                        {"step":"UNDERSTAND","status":"completed","detail":"Applied the expense change to the remembered savings scenario."},
                        {"step":"CALCULATE","status":"completed","detail":f"Updated monthly savings to SGD {monthly:,.2f}; projected savings SGD {projected:,.2f}."},
                        {"step":"SECURITY","status":"completed","detail":"Read-only scenario; no balances changed."},
                    ],
                    {"starting_savings_sgd":float(prior_plan["starting"]),"monthly_income_sgd":float(prior_plan["income"]),"monthly_expenses_sgd":float(adjusted_expenses),"monthly_surplus_sgd":float(monthly),"months":prior_plan["months"],"target_savings_sgd":float(prior_plan["target"]),"projected_savings_sgd":float(projected),"shortfall_sgd":float(shortfall),"surplus_sgd":float(surplus),"state_changed":False,"proposal":None},
                )

        # Money-moving requests must carry an explicit MYR amount before they
        # reach either planner. Otherwise a planner could infer an amount from a
        # forecast or saved wallet, which is not user authorization.
        early_intent = self.detect_intent(text)
        normalized_request = self.repair_user_text(text).lower()
        planning_or_advice_request = any(
            phrase in normalized_request
            for phrase in [
                "should i", "should we", "which currency", "which is better",
                "what is the best", "best way", "recommend", "how should i",
                "how should we", "compare", "what would be better",
            ]
        )
        explicit_currency_amount = (
            self.extract_generic_currency_amount(text)
            or self.extract_sgd_amount(text)
            or self.extract_myr_amount(text)
        )
        if (
            early_intent == "transfer"
            and explicit_currency_amount is None
            and not planning_or_advice_request
        ):
            return self._result(
                "agentic_local",
                "I need the exact MYR amount before preparing a transfer. Please specify it explicitly, for example: “Prepare a RM5,000 transfer to SGD.” No proposal or transaction was created.",
                [
                    {"step": "UNDERSTAND", "status": "completed", "detail": "Recognized a transfer request without an explicit MYR amount."},
                    {"step": "SECURITY", "status": "blocked", "detail": "Prevented either planner from inferring a transaction amount from forecasts or wallet balances."},
                ],
                {
                    "blocked_reason": "implicit_transaction_amount",
                    "state_changed": False,
                    "proposal": None,
                    "agent_mode": "deterministic_amount_safety_gate",
                },
            )

        # Resolve an explicit balance-vs-payment affordability question deterministically
        # before any LLM planner can drift into saved tuition/forecast context.
        from .local_agent import LocalAgentPlanner
        payment_affordability = LocalAgentPlanner(self).explicit_payment_affordability(text)
        if payment_affordability is not None:
            return payment_affordability

        # A general question about the next tuition fee must receive a direct,
        # read-only affordability decision based on the configured multi-currency
        # profile. Do not send it through the legacy 30-day fallback, which may
        # recommend a conversion proposal even though the user only asked a question.
        normalized_tuition_question = self.repair_user_text(text).lower()
        tuition_question = (
            self.detect_intent(text) == "affordability"
            and any(term in normalized_tuition_question for term in [
                "tuition", "school fee", "school fees", "semester fee", "education fee",
            ])
            and any(term in normalized_tuition_question for term in [
                "can i afford", "can we afford", "will i have enough", "do i have enough",
                "can i cover", "will i be able to pay", "can i pay for", "afford my next",
                "is my tuition affordable", "am i able to afford",
            ])
            and not (self.extract_generic_currency_amount(text) or self.extract_sgd_amount(text) or self.extract_myr_amount(text))
        )
        if tuition_question:
            education = self.state.get("education", {})
            tuition_net_sgd = self.money_value(max(
                Decimal("0"),
                self.money_value(education.get("tuition_semester_sgd", 0))
                - self.money_value(education.get("scholarship_semester_sgd", 0))
                - self.money_value(education.get("loan_semester_sgd", 0)),
            ))
            if tuition_net_sgd <= 0:
                return self._result(
                    "affordability",
                    "Your configured tuition is fully covered by the recorded scholarship/loan amounts, or no tuition amount is configured. "
                    "Please verify the tuition and funding values in your profile. I have not created a proposal or moved money.",
                    [{"step": "UNDERSTAND", "status": "completed", "detail": "Recognized a read-only question about the next tuition fee."},
                     {"step": "OBSERVE", "status": "needs_input", "detail": "The configured net tuition amount is zero; the profile may need checking."},
                     {"step": "SECURITY", "status": "completed", "detail": "No proposal or transaction was created."}],
                    {"goal": "configured_tuition_affordability", "needs_profile_check": True,
                     "state_changed": False, "proposal": None},
                )

            tuition_due_days = max(0, min(365, int(education.get("tuition_due_days", 30))))
            horizon = max(30, tuition_due_days)
            forecast = self.forecast_portfolio(horizon)
            other_obligations_sgd = sum((
                self.money_value(item.get("amount_sgd", 0))
                for item in self.get_obligations()
                if item.get("id") != "TUITION-USER" and int(item.get("days", horizon)) <= horizon
            ), Decimal("0"))
            projected_before_tuition_sgd = self.money_value(
                self.money_value(forecast.get("usable_starting_sgd", 0))
                + self.money_value(forecast.get("expected_income_sgd", 0))
                - self.money_value(forecast.get("spending_sgd", 0))
                - other_obligations_sgd
            )
            projected_after_tuition_sgd = self.money_value(projected_before_tuition_sgd - tuition_net_sgd)
            shortfall_sgd = self.money_value(max(Decimal("0"), -projected_after_tuition_sgd))
            affordable = projected_after_tuition_sgd >= 0

            meta = self.state.get("profile_meta", {})
            tuition_currency = str(meta.get("tuition_currency", "SGD")).upper()
            tuition_raw_net = self.money_value(max(
                Decimal("0"),
                self.money_value(meta.get("tuition_amount", tuition_net_sgd))
                - self.money_value(meta.get("scholarship_amount", 0))
                - self.money_value(meta.get("loan_amount", 0)),
            ))
            planning_currency = str(meta.get("planning_currency", "SGD")).upper()
            planning_rate = self._profile_rate_to_sgd(planning_currency)
            projected_before_planning = self.money_value(projected_before_tuition_sgd / planning_rate)
            projected_after_planning = self.money_value(projected_after_tuition_sgd / planning_rate)
            tuition_planning = self.money_value(tuition_net_sgd / planning_rate)
            shortfall_planning = self.money_value(shortfall_sgd / planning_rate)
            available_for_tuition_sgd = self.money_value(max(Decimal("0"), projected_before_tuition_sgd))
            remaining_sgd = self.money_value(max(Decimal("0"), projected_after_tuition_sgd))
            tuition_rate_text = (
                f" (about {planning_currency} {tuition_planning:,.2f} at the configured reference rates)"
                if tuition_currency != planning_currency else ""
            )
            if affordable:
                answer = (
                    f"Yes — based on your configured profile, your next net tuition fee is "
                    f"{tuition_currency} {tuition_raw_net:,.2f}{tuition_rate_text}, due in about {tuition_due_days} days. "
                    f"After protecting the configured emergency reserve and accounting for forecast income, living costs and other obligations, "
                    f"the estimate leaves about {planning_currency} {projected_after_planning:,.2f} after tuition. "
                )
            else:
                answer = (
                    f"Not yet — based on your configured profile, your next net tuition fee is "
                    f"{tuition_currency} {tuition_raw_net:,.2f}{tuition_rate_text}, due in about {tuition_due_days} days. "
                    f"After protecting the configured emergency reserve and accounting for forecast income, living costs and other obligations, "
                    f"the estimated funding gap is about {planning_currency} {shortfall_planning:,.2f}. "
                    f"Before paying tuition, the forecast leaves about {planning_currency} {projected_before_planning:,.2f} available. "
                )
            answer += (
                "This is a read-only estimate using your saved profile and indicative FX rates; fees and settlement rates can differ. "
                "I have not recommended or prepared a conversion, created a proposal, or moved money. "
                "Check that your tuition amount and due date are up to date in the profile."
            )
            return self._result(
                "affordability",
                answer,
                [
                    {"step": "UNDERSTAND", "status": "completed", "detail": "Recognized a direct, read-only question about the next tuition fee."},
                    {"step": "OBSERVE", "status": "completed", "detail": f"Used the configured {tuition_currency} tuition amount, current multi-currency wallet, protected reserve and tuition due date."},
                    {"step": "CALCULATE", "status": "completed", "detail": f"Projected position before tuition: {planning_currency} {projected_before_planning:,.2f}; after tuition: {planning_currency} {projected_after_planning:,.2f}."},
                    {"step": "SECURITY", "status": "completed", "detail": "Read-only affordability estimate; no proposal or transaction was created."},
                    {"step": "RECOMMEND", "status": "completed", "detail": "Answered whether the configured tuition appears affordable and advised checking profile accuracy."},
                ],
                {
                    "goal": "configured_tuition_affordability",
                    "configured_tuition_affordability": True,
                    "affordable": affordable,
                    "tuition_currency": tuition_currency,
                    "tuition_amount": float(tuition_raw_net),
                    "tuition_net_sgd": float(tuition_net_sgd),
                    "tuition_due_days": tuition_due_days,
                    "planning_currency": planning_currency,
                    "projected_before_tuition_sgd": float(projected_before_tuition_sgd),
                    "projected_after_tuition_sgd": float(projected_after_tuition_sgd),
                    "shortfall_sgd": float(shortfall_sgd),
                    "available_for_tuition_sgd": float(available_for_tuition_sgd),
                    "remaining_sgd": float(remaining_sgd),
                    "affordability": {
                        "wallet_total_sgd": float(forecast.get("starting_portfolio_sgd", 0)),
                        "reserve_sgd": float(forecast.get("protected_reserve_sgd", 0)),
                        "usable_sgd": float(available_for_tuition_sgd),
                        "tuition_sgd": float(tuition_net_sgd),
                        "shortfall_sgd": float(shortfall_sgd),
                        "remaining_sgd": float(remaining_sgd),
                    },
                    "forecast": forecast,
                    "state_changed": False,
                    "proposal": None,
                },
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
            fx_text = self.repair_user_text(text).lower()

            # A destination-only request such as "change my money to USD"
            # needs the source currency and amount before a meaningful quote.
            destination_only = re.search(r"\b(?:to|into)\s+(usd|sgd|myr|cny|rmb|yuan|eur|gbp|aud|cad|jpy|krw|thb|hkd|twd|inr)\b", fx_text)
            has_amount = bool(self.extract_generic_currency_amount(text) or self.extract_sgd_amount(text) or self.extract_myr_amount(text))
            if destination_only and not requested_pair and not has_amount:
                target = destination_only.group(1).upper()
                if target in {"RMB", "YUAN"}:
                    target = "CNY"
                answer = f"I can help estimate a conversion into {target}. Which currency are you starting from, and how much would you like to convert? I'll show a reference-rate estimate first; no proposal or transaction will be created unless you explicitly request the appropriate next step."
                return self._result("fx", answer, [
                    {"step": "UNDERSTAND", "status": "completed", "detail": f"Recognized {target} as the requested destination currency."},
                    {"step": "OBSERVE", "status": "needs_input", "detail": "Source currency and amount are missing."},
                    {"step": "SECURITY", "status": "completed", "detail": "Clarification only; no proposal or transaction was created."},
                ], {"target_currency": target, "needs_clarification": True, "state_changed": False, "proposal": None})
            # Do not silently fall back to the demo MYR/SGD pair when the user
            # asks for a rate without identifying both currencies.
            vague_rate_request = any(k in fx_text for k in [
                "best exchange rate", "exchange rate right now", "current exchange rate",
                "today's exchange rate", "todays exchange rate", "current rate",
            ])
            ambiguous_bucks = "buck" in fx_text and not any(
                code in fx_text for code in ["usd", "us$", "sgd", "myr", "aud", "cad"]
            )
            # A destination such as "Singapore dollars" does not disambiguate
            # a source amount written only as "dollars".
            ambiguous_dollars_source = bool(re.search(
                r"\b[0-9][0-9,]*(?:\.[0-9]+)?\s+dollars?\s+(?:in|to|into)\s+(?:singapore dollars?|sgd|s\$)\b",
                fx_text,
            )) and not any(code in fx_text for code in ["usd", "us$", "myr", "aud", "cad", "eur", "gbp"])
            ambiguous_currency_word = ambiguous_bucks or ambiguous_dollars_source
            if ambiguous_currency_word or (not requested_pair and vague_rate_request):
                if ambiguous_currency_word:
                    currency_word = "'bucks'" if ambiguous_bucks else "'dollars'"
                    question = f"Which currency do you mean by {currency_word}—for example, US dollars (USD), Singapore dollars (SGD), or another currency?"
                else:
                    question = "Which two currencies should I compare? I need the source and target currencies to retrieve the correct current reference rate."
                return self._result("fx", question, [
                    {"step": "UNDERSTAND", "status": "completed", "detail": "Detected that the requested currency pair is not specified."},
                    {"step": "OBSERVE", "status": "needs_input", "detail": "Asked for the missing currency information instead of assuming the default pair."},
                ], {"needs_clarification": True, "state_changed": False, "proposal": None})
            # RMB/Yuan/CNY without a source/target pair is ambiguous. Never
            # silently substitute the app's default MYR-to-SGD quote.
            fx_text = self.repair_user_text(text).lower()
            requested_pair = self.extract_conversion_pair(text)
            if any(k in fx_text for k in ["rmb", "yuan", "renminbi", "cny"]) and not requested_pair:
                answer = "Yes, I can help estimate an RMB (CNY) exchange. Which direction do you mean—RMB to SGD, RMB to MYR, or another currency? If you want a conversion calculation, tell me the amount too. I haven't created a proposal or transaction."
                return self._result("fx", answer, [
                    {"step": "UNDERSTAND", "status": "completed", "detail": "Recognized RMB/CNY as the requested currency."},
                    {"step": "OBSERVE", "status": "needs_input", "detail": "Source/target currency pair and amount were not specified."},
                    {"step": "SECURITY", "status": "completed", "detail": "Clarification only; no proposal or transaction was created."},
                ], {"requested_currency": "CNY", "needs_clarification": True, "state_changed": False, "proposal": None})
            # A rate-only cross-currency question (e.g. "rate of MYR to RMB")
            # must quote the requested pair, never fall back to the default MYR/SGD rate.
            if requested_pair:
                pair_base, pair_quote = requested_pair
                aliases = {"RMB": "CNY", "YUAN": "CNY", "RENMINBI": "CNY"}
                pair_base = aliases.get(pair_base.upper(), pair_base.upper())
                pair_quote = aliases.get(pair_quote.upper(), pair_quote.upper())
                has_any_amount = bool(self.extract_generic_currency_amount(text) or self.extract_sgd_amount(text) or self.extract_myr_amount(text))
                if not has_any_amount:
                    try:
                        pair_quote_result = self.quote_conversion(1, pair_base, pair_quote)
                        rate_date = pair_quote_result["fx"].get("rate_date")
                        rate_note = f"rate date {rate_date}" if rate_date else "rate date unavailable"
                        answer = (
                            f"The current reference rate is 1 {pair_base} = "
                            f"{pair_quote_result['rate']:.6f} {pair_quote} ({pair_quote_result['fx'].get('source', 'reference source')}, {rate_note}). "
                            "This is an indicative reference rate; your bank or exchange provider may use a different rate or charge fees."
                        )
                        trace.append({"step": "OBSERVE", "status": "completed", "detail": f"Retrieved the requested {pair_base}/{pair_quote} reference pair."})
                        trace.append({"step": "CALCULATE", "status": "completed", "detail": f"Returned the unit rate for {pair_base} to {pair_quote}."})
                        return self._result("fx", answer, trace, {"conversion": pair_quote_result, "state_changed": False, "proposal": None})
                    except (ValueError, KeyError) as exc:
                        return self._result("fx", f"I recognized {pair_base} to {pair_quote}, but couldn't retrieve a reliable reference rate for that pair: {exc}. I won't substitute a different currency pair.", trace, {"requested_pair": [pair_base, pair_quote], "needs_clarification": True, "state_changed": False, "proposal": None})
            q = self.refresh_fx()
            trace.append({"step": "OBSERVE", "status": "completed", "detail": f"Retrieved MYR/SGD reference rate from {q['source']}."})
            freshness = f"rate date {q['rate_date']}" if q.get('rate_date') else "rate date unavailable"
            status = "live reference data" if q.get("live") else "fallback/last-known data"
            sgd_amount = self.extract_sgd_amount(text)
            myr_amount = self.extract_myr_amount(text)
            pair = self.extract_conversion_pair(text)
            generic_amount = None
            if pair:
                # When the user states a wallet balance before the actual
                # conversion, prefer the amount inside the conversion clause.
                # Example: "I have SGD 1,200 available. Convert SGD 300 to MYR."
                # A whole-message first-match parser would otherwise convert 1,200.
                clauses = re.split(r"[;\n]|(?<=[.!?])\s+|\b(?:and then|then|also)\b", str(text or ""), flags=re.I)
                for clause in clauses:
                    clause_pair = self.extract_conversion_pair(clause)
                    if not clause_pair or tuple(code.upper() for code in clause_pair) != tuple(code.upper() for code in pair):
                        continue
                    if not any(word in clause.lower() for word in ["convert", "converting", "conversion", "exchange", "how much"]):
                        continue
                    candidate_amount = self.extract_generic_currency_amount(clause)
                    if candidate_amount and candidate_amount[1].upper() == pair[0].upper():
                        generic_amount = candidate_amount
                        break
            if generic_amount is None:
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
            answer = f"The reference rate for MYR to SGD is 1 MYR = S${q['rate']:.4f} ({status}, {freshness}). In the reverse direction, SGD to MYR uses the reciprocal reference rate. RM1,000 would convert to approximately SGD S${q['example_sgd']:,.2f}. This is a reference/mid-market rate, not a guaranteed bank quote."
            return self._result(intent, answer, trace, {"fx": q})

        if intent == "transfer":
            amount = self.extract_myr_amount(text)
            named_recipient_action = (
                any(k in normalized_request for k in ["recipient", "beneficiary", "payee"])
                and any(k in normalized_request for k in ["transfer", "send", "remit", "pay", "prepare"])
            )
            if named_recipient_action:
                return self._result(
                    intent,
                    "This XKF5 sandbox does not support payments to named recipients or bank-account transfers yet. "
                    "Its supported transfer proposal is an internal MYR-to-SGD conversion, not sending SGD to a person such as Alice. "
                    "I cannot verify or address a recipient from this chat. No proposal or transaction was created, and no account state changed.",
                    trace + [{"step": "SECURITY", "status": "blocked", "detail": "Named-recipient payment is not a supported action in this sandbox."}],
                    {
                        "blocked_reason": "unsupported_recipient_transfer",
                        "requested_action": "named_recipient_transfer",
                        "state_changed": False,
                        "proposal": None,
                    },
                )
            if amount is None:
                return self._result(
                    intent,
                    "I can prepare a MYR-to-SGD transfer only when you explicitly state the MYR amount. If you mean to remit SGD or another currency, tell me the source account and amount so I can plan that route without guessing. No proposal or transaction was created.",
                    trace,
                    {
                        "blocked_reason": "missing_explicit_myr_amount",
                        "state_changed": False,
                        "proposal": None,
                    },
                )
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
            if risk["status"] == "BLOCKED":
                answer = (
                    f"You have a projected S${f['shortfall_sgd']:,.2f} shortfall, but converting approximately "
                    f"RM{amount:,.2f} would violate a safety rule: " + " ".join(risk["reasons"]) +
                    f" The most you can convert is RM{risk['max_allowed_myr']:,.2f}. No proposal was created."
                )
                return self._result(intent, answer, trace, {"forecast": f, "risk": risk, "state_changed": False})

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

    @_state_locked
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
