    assert "emergency reserve" in r["answer"].lower()
    assert e.get_balance() == before
    assert e.state["proposals"] == {}


def test_local_agent_returns_structured_decision_summary():
    e = FinanceEngine()
    e.update_profile_general({
        "planning_currency": "SGD",
        "balances": {"SGD": 500, "CNY": 10000, "USD": 500, "MYR": 5000},
        "balance_fx_modes": {"CNY": "custom", "USD": "custom", "MYR": "custom"},
        "custom_fx_rates_to_sgd": {"CNY": 0.19, "USD": 1.28, "MYR": 0.31},
        "monthly_income_amount": 1000,
        "monthly_income_currency": "SGD",
        "emergency_reserve_amount": 1000,
        "emergency_reserve_currency": "MYR",
        "tuition_amount": 3000,
        "tuition_currency": "SGD",
        "scholarship_amount": 0,
        "loan_amount": 0,
        "accommodation_amount": 400,
        "accommodation_currency": "SGD",
        "other_obligations_amount": 0,
        "other_obligations_currency": "SGD",
        "monthly_spending_currency": "SGD",
        "monthly_spending": {"Food & dining": 300, "Transport": 100},
        "spending_classifications": {"Food & dining": "Adjustable", "Transport": "Core"},
    })
    r = e.agent(
        "I have CNY 10,000, USD 500, MYR 5,000 and SGD 500. "
        "I need SGD 3,000 for tuition. What should I do?"
    )
    decision = r["data"]["decision"]
    assert decision["action"] in {"FUND_TARGET", "FUND_PARTIAL"}
    assert decision["target"] == {"currency": "SGD", "amount": 3000.0}
    assert decision["conversion_count"] >= 1
    assert decision["reserve_protected"]["protected"] is True
    assert decision["state_changed"] is False


def test_local_agent_structured_decision_can_be_no_fx():
    e = FinanceEngine()
    r = e.agent(
        "I have SGD 4,000 and MYR 5,000. "
        "I need SGD 3,000 for tuition. What should I do?"
    )
    decision = r["data"]["decision"]