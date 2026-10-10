from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from .engine import FinanceEngine
from .security import SecurityHeadersMiddleware, SimpleRateLimiter

load_dotenv()

BASE = Path(__file__).resolve().parent.parent
engine = FinanceEngine()

app = FastAPI(title="XKF5 AI v7.4.0 — Currency-First", version="7.4.0")
app.add_middleware(SecurityHeadersMiddleware)
rate_limiter = SimpleRateLimiter()

@app.middleware("http")
async def enforce_rate_limit(request, call_next):
    client_ip = request.client.host if request.client else "127.0.0.1"
    rate_limiter.check_rate_limit(client_ip)
    return await call_next(request)

app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")

@app.middleware("http")
async def no_cache_dev(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=2000)
    # This is only a contextual reference. The engine must validate the ID against
    # its own proposal store and current status before any authorization.
    proposal_id: str | None = Field(default=None, max_length=64)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    # Keep a bounded history of up to 25 user/assistant exchanges. Proposal IDs
    # remain contextual hints only and are always checked against server-side state.
    history: list[ChatTurn] = Field(default_factory=list, max_length=50)


class AuthRequest(BaseModel):
    proposal_id: str = Field(min_length=1, max_length=64)
    approved: bool
    acknowledge_review: bool = False


class ExecuteRequest(BaseModel):
    proposal_id: str = Field(min_length=1, max_length=64)


class TransferRequest(BaseModel):
    amount_myr: float = Field(gt=0, allow_inf_nan=False)
    purpose: str = Field(default="student finance transfer", min_length=1, max_length=200)


class FXConversionRequest(BaseModel):
    amount: float = Field(gt=0, allow_inf_nan=False)
    from_currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$")
    to_currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$")
    custom_rate: float | None = Field(default=None, gt=0, allow_inf_nan=False)


class ProfileRequest(BaseModel):
    general_profile: dict[str, Any] | None = None
    myr_balance: float = Field(default=0, ge=0, allow_inf_nan=False)
    sgd_balance: float = Field(default=0, ge=0, allow_inf_nan=False)
    monthly_income_sgd: float = Field(default=0, ge=0, allow_inf_nan=False)
    emergency_reserve_myr: float = Field(default=0, ge=0, allow_inf_nan=False)
    tuition_semester_sgd: float = Field(default=0, ge=0, allow_inf_nan=False)
    scholarship_semester_sgd: float = Field(default=0, ge=0, allow_inf_nan=False)
    loan_semester_sgd: float = Field(default=0, ge=0, allow_inf_nan=False)
    tuition_due_days: int = Field(default=30, ge=0, le=365)
    accommodation_monthly_sgd: float = Field(default=0, ge=0, allow_inf_nan=False)
    other_monthly_obligations_sgd: float = Field(default=0, ge=0, allow_inf_nan=False)
    monthly_spending_sgd: dict[str, float] = Field(default_factory=dict)
    spending_classifications: dict[str, str] = Field(default_factory=dict)
    additional_currencies: dict[str, float] = Field(default_factory=dict)
    myr_mode: str = "live"
    custom_myrsgd: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    custom_fx_rates_to_sgd: dict[str, float] = Field(default_factory=dict)
    custom_fx_sources: dict[str, str] = Field(default_factory=dict)
    custom_fx_dates: dict[str, str] = Field(default_factory=dict)
    additional_fx_rate_modes: dict[str, str] = Field(default_factory=dict)


class TraceStep(BaseModel):
    step: str
    status: str
    detail: str


class ChatResponse(BaseModel):
    intent: str
    answer: str
    trace: list[TraceStep]
    data: dict[str, Any]
    state: dict[str, Any]


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True, "version": "7.4.0", "python_compatible": "3.14+", "llm_enabled": bool(os.getenv("OPENAI_API_KEY")), "auto_fx_supported": True}


@app.get("/api/state")
def state():
    return engine.snapshot()


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    history = [turn.model_dump() for turn in req.history]
    return engine.agent(req.message, conversation_history=history)


@app.post("/api/profile")
def update_profile(req: ProfileRequest):
    try:
        if req.general_profile is not None:
            return engine.update_profile_general(req.general_profile)
        return engine.update_profile(
            req.myr_balance, req.sgd_balance, req.monthly_income_sgd,
            req.emergency_reserve_myr, req.tuition_semester_sgd,
            req.scholarship_semester_sgd, req.loan_semester_sgd,
            req.tuition_due_days, req.accommodation_monthly_sgd,
            req.other_monthly_obligations_sgd, req.monthly_spending_sgd,
            req.spending_classifications, req.additional_currencies, req.myr_mode,
            req.custom_myrsgd, req.custom_fx_rates_to_sgd, req.custom_fx_sources, req.custom_fx_dates,
            req.additional_fx_rate_modes,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/proposals")
def list_proposals():
    return {"proposals": engine.list_proposals()}


@app.post("/api/proposals")
def proposal(req: TransferRequest):
    try:
        return engine.create_proposal(__import__("decimal").Decimal(str(req.amount_myr)), req.purpose)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/authorize")
def authorize(req: AuthRequest):
    try:
        return engine.authorize(req.proposal_id, req.approved, acknowledge_review=req.acknowledge_review)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/execute")
def execute(req: ExecuteRequest):
    try:
        return engine.execute(req.proposal_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/reset")
def reset():
    engine.reset()
    engine.audit("DEMO_RESET", {"reason": "judge demo reset"})
    return engine.snapshot()


@app.get("/api/audit")
def audit():
    return {"audit": engine.audit_log()}


@app.post("/api/fx/refresh")
def refresh_fx():
    return engine.refresh_fx(force=True)


@app.post("/api/fx/refresh-all")
def refresh_all_fx():
    return engine.refresh_auto_fx(force=True)


@app.get("/api/fx/quote")
def fx_quote_pair(from_currency: str, to_currency: str, amount: float = 1.0, custom_rate: float | None = None):
    try:
        return engine.quote_conversion(amount, from_currency, to_currency, custom_rate=custom_rate)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/fx/convert")
def fx_convert(req: FXConversionRequest):
    try:
        return engine.quote_conversion(req.amount, req.from_currency, req.to_currency, custom_rate=req.custom_rate)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/capabilities")
def capabilities():
    return {
        "capabilities": [
            "balance analysis",
            "transaction history",
            "spending analysis",
            "30-day cash-flow forecast",
            "multi-currency wallet valuation",
            "user-entered FX rates normalized to SGD",
            "automatic live reference FX for additional currencies",
            "any-currency pair conversion with automatic reference quotes",
            "live or custom MYR/SGD reference FX rates",
            "FX freshness and source attribution",
            "transfer preparation",
            "risk policy enforcement",
            "Level 2 authorization",
            "sandbox execution",
            "post-transaction verification",
            "immutable-style audit events",
            "LLM tool-calling agent with deterministic tool authority",
            "hypothetical income-impact simulation without state mutation",
        ]
    }
