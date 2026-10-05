# BorderWise AI v6.2

## Personal financial profile
- Added a manual sandbox profile form for current MYR/SGD balances.
- Added monthly SGD income, 30-day living expenses and MYR emergency-reserve inputs so recommendations use the user’s own assumptions.
- Added `POST /api/profile` and `profile` data to `/api/state`.
- Profile updates are recorded in the audit trail.

## Spending analysis
- Reworked the spending dashboard so percentages are always based on the full 30-day recorded SGD total.
- Added total, daily average, core spending and adjustable spending summaries.
- Added clear Core/Adjustable labels for budgeting context instead of presenting every large expense as discretionary.

## Safety / UX
- Emergency-reserve health calculation now uses the user-entered reserve instead of a hard-coded RM5,000.
- Manual profile is clearly labeled as sandbox input; no bank account is connected.
