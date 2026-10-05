# BorderWise AI v7.2.0

- Added user-directed any-currency pair conversion (e.g. CNY → MYR).
- Added automatic current reference FX lookup for arbitrary currency pairs using Frankfurter.
- Added a dashboard conversion studio with Auto current reference / My quoted rate modes.
- Shows the actual fetched FX rate, source and rate date instead of placeholder text.
- Additional wallet currencies continue to use SGD as a normalization base only for indicative portfolio valuation.
- Added generic natural-language conversion parsing for 3-letter codes and RMB/Renminbi → CNY aliases.
- Preserved proposal/authorization/execution safety boundaries; the conversion studio is quote-only.
- 33 automated tests pass.
