"""TSP Predictor: educational decision support for Thrift Savings Plan fund choices.

Not financial advice. The package reports historical, out-of-sample evidence.
"""

__version__ = "0.1.0"

NOT_ADVICE = (
    "TSP Predictor is educational decision support, not financial advice. "
    "It reports historical evidence and estimated probabilities. "
    "It does not access a TSP account, place trades, or promise an outcome."
)

SCHEMA_VERSION = 1
DATA_AS_OF_BUNDLED = "2026-10-05"
I_FUND_BREAK = "2024-10-30"
FUNDS = ("G", "F", "C", "S", "I")
