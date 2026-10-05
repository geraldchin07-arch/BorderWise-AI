# BorderWise AI v7.3.0

## Currency-first onboarding
- Removed the assumption that every user starts with MYR and SGD as their core currencies.
- Added a user-selected primary planning currency.
- Added dynamic multi-currency balance rows with auto reference FX or user-entered quotes.
- Profile monetary inputs can specify their own currency and are normalized internally for deterministic calculations.
- Forecasts, spending analysis, obligations and wallet valuation are shown in the selected planning currency.
- Emergency reserves are currency-aware and assessed against the balance held in the selected reserve currency.
- Any-currency conversion remains available with exact user-selected direction.

## Safety
- Existing proposal, authorization, execute-once, verification and audit controls remain in place.
- Changing the planning currency does not grant additional transaction permissions.
