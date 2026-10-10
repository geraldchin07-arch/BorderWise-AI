# XKF5 AI v7.4.0

## Currency intelligence
- Expanded the wallet selector and deterministic parser to 150+ ISO currency codes.
- Added names for additional active currencies, including Afghan afghani, Angolan kwanza, Barbadian dollar, Bhutanese ngultrum, Cuban peso, Guinean franc, Mauritanian ouguiya, and Zimbabwe Gold.
- Unified currency aliases in the offline planner to reduce inconsistent parsing across balance, obligation, and amount extraction.
- Added support for explicit shorthand amounts such as 2k and 1.5m, while rejecting malformed thousands separators.
- Prevented false MYR extraction from ordinary words such as "from".
- Disambiguated ordinary words that overlap currency codes, and stopped guessing whether the yen symbol means CNY or JPY.
- Clarified in the UI that automatic FX coverage depends on the reference-rate provider and that unsupported quotes need a custom rate or retry.

## Transfer and profile safety
- Required LLM-generated proposals to match an explicit transfer instruction and exact user-stated MYR amount.
- Blocked proposal creation and execution when either the MYR source or SGD destination wallet row is missing.
- Preserved wallet state when an unsupported automatic FX quote prevents profile validation.

## Verification
- Added red-team tests for multi-currency wallet parsing, ambiguous codes, shorthand amounts, malformed separators, unsupported FX, proposal authorization, and transfer mutation boundaries.
