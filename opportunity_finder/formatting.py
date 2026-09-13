"""Human-readable formatting shared by messages, templates and exports."""
from __future__ import annotations

from datetime import datetime


def fmt_money(value, dash: str = "—") -> str:
    if value is None:
        return dash
    sign = "−" if value < 0 else ""
    return f"{sign}£{abs(value):,.2f}"


def fmt_pct(value, places: int = 1, dash: str = "—") -> str:
    if value is None:
        return dash
    text = f"{value:,.{places}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return f"{text.replace('-', '−')}%"


def fmt_int(value, dash: str = "—") -> str:
    if value is None:
        return dash
    return f"{int(value):,}".replace("-", "−")


def fmt_number(value, dash: str = "—") -> str:
    if value is None:
        return dash
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def fmt_weight(grams, dash: str = "—") -> str:
    if grams is None:
        return dash
    if grams >= 1000:
        return f"{grams / 1000:,.2f}".rstrip("0").rstrip(".") + " kg"
    return f"{grams:,.0f} g"


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def fmt_datetime(value: str | None, dash: str = "—") -> str:
    dt = parse_iso(value)
    return dt.strftime("%d %b %Y, %H:%M") if dt else dash


def fmt_date(value: str | None, dash: str = "—") -> str:
    dt = parse_iso(value)
    return dt.strftime("%d %b %Y") if dt else dash


def fmt_ago(value: str | None, now: datetime | None = None, dash: str = "never") -> str:
    dt = parse_iso(value)
    if not dt:
        return dash
    now = now or datetime.now()
    seconds = max(0, (now - dt).total_seconds())
    if seconds < 90:
        return "just now"
    minutes = seconds / 60
    if minutes < 60:
        return f"{int(minutes)} min ago"
    hours = minutes / 60
    if hours < 24:
        return f"{int(hours)} h ago"
    days = int(hours / 24)
    return "yesterday" if days == 1 else f"{days} days ago"
