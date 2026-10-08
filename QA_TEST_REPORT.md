# BorderWise AI — QA Test Report

## 1. QA Scope

This QA work focuses on validating the core financial engine, with particular attention to:

- Multi-currency wallet support
- Currency conversion
- FX configuration and fallback behavior
- Planning-currency handling
- Financial calculations
- Agent-related finance workflows
- Transaction safety and authorization
- Regression stability

The goal is to verify that financial calculations remain deterministic and that transaction execution remains protected by explicit authorization and sandbox controls.

---

## 2. Test Environment

- Operating System: macOS
- Python: 3.14.7
- Test Framework: Pytest
- Branch: `docs-qa`

---


## 3. Test Command

The full regression suite was executed with:

`python -m pytest -q`

---

## 15. Manual UI Finding — Safe Conversion

### Test Scenario

The "Convert any currency" UI was tested using:

- Amount: `1000`
- From currency: `MYR`
- To currency: `SGD`
- FX mode: `Auto current reference`

### Expected Result

Clicking **Calculate** should display:

- Current/reference FX rate
- Converted amount
- Currency pair information

### Actual Result

Clicking **Calculate** produced no visible conversion result.

The UI remained on:

> Enter a pair and calculate

No converted amount or reference-rate result was displayed.

### QA Assessment

**FAIL — Frontend integration defect**

The backend conversion functionality is covered by automated tests and passes.

The current frontend conversion control calls:

`calculateFXPair()`

but the current `static/index.html` does not provide a corresponding function definition.

The page also references `fxCurrencyHint()` and `toggleStudioRate()` from the conversion controls without those functions being present in the current frontend source.

### Impact

The deterministic conversion engine remains testable, but the browser-based "Convert any currency" control is currently not functional.

This prevents the manual UI flow from displaying a conversion result even though the underlying conversion functionality is covered by automated tests.

### Recommended Fix

Implement the missing frontend handlers and connect the conversion form to the existing FX conversion API.

No financial-engine logic was changed as part of this QA finding.

---

## 16. Manual QA Finding — Multi-Currency Forecast Limitation

### Test Scenario

The multi-currency wallet was tested with:

- Planning currency: `SGD`
- CNY balance: `10,000`
- SGD balance: `500`
- CNY → SGD rate: `0.18`
- SGD → SGD rate: `1.00`
- Required amount: `SGD 3,000`

### Expected Result

The starting planning liquidity should include all wallet balances after FX normalization:

- CNY 10,000 → SGD 1,800
- SGD 500 → SGD 500
- Total indicative value → SGD 2,300
- Expected shortfall against SGD 3,000 → SGD 700

### Actual Result

The multi-currency wallet valuation correctly reports the combined indicative value as `SGD 2,300`.

However, the 30-day forecast currently uses only the balance held in the selected planning currency as its starting planning balance.

For this scenario, the forecast therefore starts from `SGD 500` instead of the combined indicative value of `SGD 2,300`.

### QA Assessment

**FAIL — Multi-currency forecast integration limitation**

The underlying multi-currency valuation is working, but non-planning-currency balances are not currently aggregated into forecast starting liquidity.

### Impact

Users holding funds in non-planning currencies may see an inaccurate starting liquidity position and an overstated projected shortfall.

### Tracking

Tracked as GitHub Issue **#27**:

**Multi-currency forecast ignores non-planning-currency wallet balances**

### Regression Status

The full automated test suite remains green:

`45 passed`

No backend logic was changed as part of this QA finding.