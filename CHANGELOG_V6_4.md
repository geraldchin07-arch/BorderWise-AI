# BorderWise AI v6.4

## Cash-flow model clarification
- Dashboard now shows **30-day cash position** rather than always calling it a shortfall.
- Tuition is included in the 30-day calculation only when its user-entered due date is within 30 days.
- Forecast explicitly reports surplus vs funding gap.
- Forecast exposes the calculation basis for judge transparency.
- Added regression test for tuition due after the 30-day horizon.

No real money moves; all transaction execution remains sandboxed behind Level 2 authorization.
