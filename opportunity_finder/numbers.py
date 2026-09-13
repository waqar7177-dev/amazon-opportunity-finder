"""Money rounding and forgiving-but-strict number parsing.

Parsing accepts what people actually type or paste ("£1,299.99", " 12 ", "1,234")
and rejects everything else with a message a seller can act on.
"""
from __future__ import annotations

import math
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

_CURRENCY_NOISE = re.compile(r"[£,\s]|GBP", re.IGNORECASE)


def money(value: float | None) -> float | None:
    """Round to pence, half-up (the way a person rounds, not banker's rounding)."""
    if value is None:
        return None
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def round_to(value: float | None, places: int = 1) -> float | None:
    if value is None:
        return None
    quant = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))


def is_blank(raw) -> bool:
    return raw is None or (isinstance(raw, str) and raw.strip() == "")


def _clean(raw) -> str:
    text = str(raw).strip()
    return _CURRENCY_NOISE.sub("", text)


def parse_number(raw, label: str, *, minimum: float | None = None, maximum: float | None = None,
                 allow_negative: bool = False) -> tuple[float | None, str | None]:
    """Parse a decimal number. Blank -> (None, None)."""
    if is_blank(raw):
        return None, None
    if isinstance(raw, bool):
        return None, f"{label} must be a number."
    if isinstance(raw, (int, float)):
        value = float(raw)
    else:
        cleaned = _clean(raw)
        if cleaned in {"", "-", "."}:
            return None, f"{label} must be a number."
        try:
            value = float(Decimal(cleaned))
        except (InvalidOperation, ValueError):
            return None, f"{label} must be a number (for example 12.99)."
    if math.isnan(value) or math.isinf(value):
        return None, f"{label} must be a real number."
    if not allow_negative and value < 0:
        return None, f"{label} cannot be negative."
    if minimum is not None and value < minimum:
        return None, f"{label} must be at least {_fmt(minimum)}."
    if maximum is not None and value > maximum:
        return None, f"{label} must be no more than {_fmt(maximum)}."
    return value, None


def parse_whole(raw, label: str, *, minimum: int | None = None,
                maximum: int | None = None) -> tuple[int | None, str | None]:
    """Parse a whole number. "1,234" is fine, "12.5" is not."""
    if is_blank(raw):
        return None, None
    if isinstance(raw, bool):
        return None, f"{label} must be a whole number."
    if isinstance(raw, float):
        if not raw.is_integer():
            return None, f"{label} must be a whole number."
        value = int(raw)
    elif isinstance(raw, int):
        value = raw
    else:
        cleaned = _clean(raw)
        if re.fullmatch(r"[+-]?\d+(\.0+)?", cleaned):
            value = int(Decimal(cleaned))
        elif re.fullmatch(r"[+-]?\d*\.\d+", cleaned):
            return None, f"{label} must be a whole number."
        else:
            return None, f"{label} must be a whole number (for example 12)."
    if value < 0 and (minimum is None or minimum >= 0):
        return None, f"{label} cannot be negative."
    if minimum is not None and value < minimum:
        return None, f"{label} must be at least {minimum:,}."
    if maximum is not None and value > maximum:
        return None, f"{label} must be no more than {maximum:,}."
    return value, None


TRUE_WORDS = {"1", "true", "yes", "y", "on", "x", "✓", "✔", "checked"}
FALSE_WORDS = {"0", "false", "no", "n", "off", "", "-"}


def parse_bool(raw) -> tuple[bool | None, str | None]:
    if raw is None:
        return False, None
    if isinstance(raw, bool):
        return raw, None
    if isinstance(raw, (int, float)):
        return bool(raw), None
    text = str(raw).strip().lower()
    if text in TRUE_WORDS:
        return True, None
    if text in FALSE_WORDS:
        return False, None
    return None, f'"{raw}" is not a yes/no value.'


def _fmt(value: float) -> str:
    return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"
