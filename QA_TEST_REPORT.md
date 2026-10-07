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

```bash
python -m pytest -q

