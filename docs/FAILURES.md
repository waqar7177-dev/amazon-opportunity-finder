# Failures log

**Hard rule:** every fault goes in this file *as part of fixing it*, in the same commit as the fix —
not later, not when asked. Each entry has four parts: what broke, the measurement, why nothing
caught it, and the checklist line it becomes.

## Pre-commit checklist

Ask these before committing. Each line came from a real fault below.

1. Can every input that may legitimately be missing actually be *omitted* when the object is built — not just set to `None` by callers who happen to know? *(F1)*

---

## F1 — Fee engine could not represent "no selling price"

- **What broke:** `FeeInputs` declared `selling_price` without a default, so building fee inputs for
  a product whose Amazon price is unknown raised a `TypeError` instead of producing a
  "selling price missing" result. The app's core promise — missing values are reported, never
  guessed — had no way to express the most important missing value at the fee layer.
- **Measurement:** 2026-09-13, first run of the test suite: 99 of 100 tests passed;
  `test_missing_price_means_no_referral_fee` failed with
  `TypeError: FeeInputs.__init__() missing 1 required positional argument: 'selling_price'`.
  The evaluator path hid it because `fee_inputs_for()` always passes the attribute (as `None`).
- **Why nothing caught it:** the only earlier check was a smoke run with a complete product, and
  every internal caller passes all fields by keyword. The gap only shows when the dataclass is
  used the way a future provider (e.g. Keepa) would use it — with just the fields it knows.
- **Fix:** `selling_price: float | None = None`.
- **Checklist line:** 1.
