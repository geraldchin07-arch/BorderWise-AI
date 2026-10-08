# Exact Demo Script

## Setup
Click Reset judge demo.

## Prompt 1
"Can I afford my tuition?"

Expected:

  * SGD 5,000 balance
  * 30-day obligations and monthly spending plan
  * The current 30-day projected shortfall
  * A MYR → SGD conversion recommendation calculated from the displayed reference FX rate
  * RM5,000 emergency reserve remains protected
  * Level 2 authorization is required before execution

Authorize it.

## Prompt 2
"What are my biggest expenses?"

Expected:
Spending categories and ranking.

## Prompt 3
"Will I run out of SGD?"

Expected:
30-day projection.

## Prompt 4
"Prepare a RM26,000 transfer."

Expected:
BLOCKED due to emergency reserve policy.

## Prompt 5
"Show my recent transactions."

Expected:
Recent transaction history.

## Closing line
"BorderWise does not let the model move money. It separates reasoning from financial execution and requires explicit authorization at the action boundary."


### v5 FX moment
Ask: “What is the current MYR to SGD rate?”
Point to the FX card: BorderWise shows the current reference rate, rate date, source, and whether live reference data or fallback data is being used. Then ask “Can I afford my tuition?” and show that the conversion recommendation is recalculated from that rate.
