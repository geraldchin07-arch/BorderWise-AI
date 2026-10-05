# BorderWise AI v7.1

- Additional currencies default to automatic reference FX instead of requiring manual rates.
- Users can switch any additional currency to a custom bank/money-changer quote.
- Auto reference rates are batch-fetched via Frankfurter, normalized to SGD, cached for 15 minutes, and shown with source/date.
- Cross-currency conversions refresh selected auto rates when needed.
- Sandbox execution remains explicit and protected by the deterministic policy layer.
- Existing API callers that omit a mode remain backward-compatible as custom-rate entries; the new UI explicitly sends auto mode.
