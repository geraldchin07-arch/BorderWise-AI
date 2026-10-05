# BorderWise AI v5.4 changelog

## v5.4.0
- Fixed natural-language authorization routing.
- `I authorize the RM3,141.94 conversion.` now matches the pending proposal.
- Explicit authorization records Level 2 approval, executes only in the sandbox, verifies the transaction, and writes audit events.
- Authorization without an unambiguous pending proposal is blocked.
- Added regression tests; 17/17 pass.

# BorderWise AI v5.3

## Security/action boundary fixes
- Explicit transfer/conversion requests now take priority over generic FX responses.
- A request such as `Prepare the RM3,141.94 conversion to SGD` creates a sandbox proposal and requires Level-2 authorization.
- The agent never infers a transfer amount from a forecast when the user did not provide an amount.
- `transfer all my MYR` / `everything` is now BLOCKED and requires an exact amount.
- Requests to skip confirmation cannot bypass Level-2 authorization.
- High-value transfers remain subject to the deterministic policy engine.
