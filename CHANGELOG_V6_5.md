# BorderWise AI v6.5

## Student-controlled spending assumptions and transparent health score

- Added user-controlled Essential/Core vs Adjustable classification for monthly spending categories.
- Accommodation remains Essential/Core because it is treated as a housing commitment in the model.
- Spending analysis now reports whether each category classification came from the user or the default.
- Replaced the old generous health formula with a transparent liquidity indicator based on:
  - projected cash buffer in months,
  - emergency-reserve target,
  - near-term obligation pressure.
- The health indicator explicitly states that it is not a credit score.
- Added regression tests for classification and score behavior.
- Preserved v6.4 tuition timing, profile inputs, dynamic FX, authorization, anti-replay, sandbox execution and audit controls.
