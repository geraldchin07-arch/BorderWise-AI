    e = FinanceEngine()
    e.update_profile_general({
        "planning_currency": "SGD",
        "balances": {"SGD": 9000, "MYR": 8000},
        # The hypothetical CNY/USD balances below are expected to use these
        # deterministic scenario quotes; otherwise the autouse fake provider returns
        # the MYR/SGD test rate (0.322) for every pair and the expected 5490 SGD
        # starting valuation would be impossible to reproduce.
        "balance_fx_modes": {"CNY": "custom", "USD": "custom", "MYR": "custom"},
        "custom_fx_rates_to_sgd": {"CNY": 0.19, "USD": 1.28, "MYR": 0.31},
        "monthly_income_amount": 5000,
        "monthly_income_currency": "SGD",
        "emergency_reserve_amount": 5000,
        "emergency_reserve_currency": "MYR",
        "tuition_amount": 1000,
        "tuition_currency": "SGD",
        "scholarship_amount": 0,
        "loan_amount": 0,
        "tuition_due_days": 60,
        "accommodation_amount": 3000,
        "accommodation_currency": "SGD",
        "other_obligations_amount": 1000,
        "other_obligations_currency": "SGD",
        "monthly_spending_currency": "SGD",
        "monthly_spending": {"Food & dining": 3000},
        "spending_classifications": {"Food & dining": "Core"},
    })