"""User-editable assumptions: qualification rules, the sales model, risk thresholds, fees.

All criteria live here — the evaluator, the Settings page, the Excel "Assumptions"
sheet and the README describe the same list, so they cannot drift apart.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, fields

from ..numbers import parse_bool, parse_number, parse_whole

VAT_IGNORE = "ignore"
VAT_NOT_REGISTERED = "not_registered"
VAT_REGISTERED = "registered"
VAT_MODE_LABELS = {
    VAT_IGNORE: "Ignore VAT (simple formula)",
    VAT_NOT_REGISTERED: "Not VAT registered — pay VAT on Amazon fees",
    VAT_REGISTERED: "VAT registered — deduct output VAT from each sale",
}


@dataclass
class Settings:
    # Qualification rules
    min_total_sellers: int = 3
    min_fba_sellers: int = 1
    max_bsr: int = 25_000
    min_monthly_sales: int = 50
    min_net_profit: float = 0.0
    min_roi: float = 0.0
    # Target
    monthly_profit_target: float = 1000.0
    include_needs_verification_in_plan: bool = False
    # Conservative sales model (ESTIMATED)
    capture_rate_low: float = 20.0
    competition_medium_from: int = 5
    capture_rate_medium: float = 10.0
    competition_high_from: int = 10
    capture_rate_high: float = 5.0
    amazon_sells_capture_pct: float = 50.0
    # Risk and verification
    low_roi_threshold: float = 15.0
    thin_margin_threshold: float = 10.0
    stale_data_days: int = 30
    require_restriction_check: bool = False
    # Fees and VAT (ESTIMATED)
    vat_mode: str = VAT_IGNORE
    apply_digital_services_fee: bool = True
    apply_fuel_surcharge: bool = True
    apply_low_price_fba: bool = True
    apply_peak_fees: bool = True
    # Brand research (automated collection)
    research_max_pages: int = 5
    research_delay_seconds: float = 6.0
    research_refresh_hours: int = 24
    research_cache_hours: int = 12
    research_postcode: str = "SW1A 1AA"
    research_show_browser: bool = False

    @classmethod
    def defaults(cls) -> "Settings":
        return cls()

    @classmethod
    def from_dict(cls, data: dict | None) -> "Settings":
        """Build from stored data, ignoring unknown keys and falling back to defaults
        for anything missing or malformed (a hand-edited database never crashes the app)."""
        base = cls()
        if not data:
            return base
        candidate, errors = validate_settings({**base.to_dict(), **data}, partial_ok=True)
        return candidate if not errors else _merge_valid(base, data)

    def to_dict(self) -> dict:
        return asdict(self)

    def fingerprint(self) -> str:
        """Everything that can change an evaluation. Collection-only settings are left out so changing the
        browser pace does not re-evaluate every product."""
        data = {k: v for k, v in self.to_dict().items() if not k.startswith("research_")}
        return hashlib.sha1(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]

    def criteria(self) -> dict:
        """The qualification rules only — stored with each rejection so a later rule change can be spotted."""
        return {k: getattr(self, k) for k in CRITERIA_FIELDS}

    def criteria_fingerprint(self) -> str:
        return hashlib.sha1(json.dumps(self.criteria(), sort_keys=True).encode()).hexdigest()[:16]

    @property
    def vat_on_fees(self) -> bool:
        return self.vat_mode == VAT_NOT_REGISTERED


# --------------------------------------------------------------------------
# Field specs drive the Settings form, its validation and the Assumptions sheet.
# kind: int | money | pct | bool | choice
SETTING_GROUPS = [
    {
        "key": "rules",
        "title": "Qualification rules",
        "lead": "A product is only Qualified when it passes every rule below. Missing values are never guessed.",
        "fields": [
            {"name": "min_total_sellers", "label": "Minimum total sellers", "kind": "int", "min": 0, "max": 1000,
             "help": "Total sellers must be at least this. Very few sellers can mean a private-label or restricted listing."},
            {"name": "min_fba_sellers", "label": "Minimum FBA sellers", "kind": "int", "min": 0, "max": 1000,
             "help": "At least this many FBA sellers shows the listing works for FBA."},
            {"name": "max_bsr", "label": "Maximum Best Sellers Rank", "kind": "int", "min": 1, "max": 50_000_000,
             "help": "BSR must be below this number (a lower rank sells more)."},
            {"name": "min_monthly_sales", "label": "Minimum estimated monthly sales", "kind": "int", "min": 0, "max": 10_000_000,
             "help": "Estimated units the whole listing sells per month must be at least this."},
            {"name": "min_net_profit", "label": "Minimum net profit per unit", "kind": "money", "min": -10_000, "max": 100_000,
             "help": "Net profit per unit must be above this amount."},
            {"name": "min_roi", "label": "Minimum ROI", "kind": "pct", "min": -100, "max": 10_000,
             "help": "ROI must be at least this percentage. 0 means any positive-profit product can pass."},
        ],
    },
    {
        "key": "target",
        "title": "Monthly profit target",
        "lead": "The target plan walks through ranked opportunities until their conservative profit reaches this figure.",
        "fields": [
            {"name": "monthly_profit_target", "label": "Monthly profit target", "kind": "money", "min": 1, "max": 10_000_000,
             "help": "Conservative (ESTIMATED) monthly profit you are aiming for."},
            {"name": "include_needs_verification_in_plan", "label": "Include “Needs Verification” products in the target plan", "kind": "bool",
             "help": "Off by default: those products still have something to check before buying."},
        ],
    },
    {
        "key": "capture",
        "title": "Conservative sales model",
        "estimated": True,
        "lead": "You will not win every sale on a listing. These capture rates turn market sales into conservative units for you.",
        "fields": [
            {"name": "capture_rate_low", "label": "Default capture rate (low competition)", "kind": "pct", "min": 0, "max": 100,
             "help": "Share of the listing's monthly sales you might win when FBA competition is low."},
            {"name": "competition_medium_from", "label": "Medium competition starts at (FBA sellers)", "kind": "int", "min": 1, "max": 1000,
             "help": "From this many FBA sellers the medium capture rate is used."},
            {"name": "capture_rate_medium", "label": "Capture rate (medium competition)", "kind": "pct", "min": 0, "max": 100,
             "help": "Used when FBA sellers are between the medium and high thresholds."},
            {"name": "competition_high_from", "label": "High competition starts at (FBA sellers)", "kind": "int", "min": 2, "max": 1000,
             "help": "From this many FBA sellers the high-competition capture rate is used."},
            {"name": "capture_rate_high", "label": "Capture rate (high competition)", "kind": "pct", "min": 0, "max": 100,
             "help": "Used when FBA sellers reach the high-competition threshold."},
            {"name": "amazon_sells_capture_pct", "label": "When Amazon sells the listing, keep this % of the capture rate", "kind": "pct", "min": 0, "max": 100,
             "help": "Amazon usually wins most Buy Box share on its own listings. 50 halves your capture rate; 100 ignores it."},
        ],
    },
    {
        "key": "risk",
        "title": "Risk and verification",
        "lead": "Thresholds used by the risk engine and the Needs Verification checks.",
        "fields": [
            {"name": "low_roi_threshold", "label": "Flag ROI below", "kind": "pct", "min": -100, "max": 10_000,
             "help": "ROI under this adds a Low ROI risk reason."},
            {"name": "thin_margin_threshold", "label": "Flag net margin below", "kind": "pct", "min": -100, "max": 100,
             "help": "Net profit as a share of the selling price. Under this adds a Thin margin risk reason."},
            {"name": "stale_data_days", "label": "Amazon data is stale after (days)", "kind": "int", "min": 1, "max": 3650,
             "help": "Products whose Amazon data was last checked longer ago than this need verification."},
            {"name": "require_restriction_check", "label": "Require a manual restriction check before Qualified", "kind": "bool",
             "help": "When on, products with restriction status Unknown or Check Seller Central become Needs Verification."},
        ],
    },
    {
        "key": "fees",
        "title": "Fees and VAT",
        "estimated": True,
        "lead": "Fee estimates use the UK fee table shipped with the app. Confirm exact fees in Seller Central.",
        "fields": [
            {"name": "vat_mode", "label": "VAT treatment", "kind": "choice", "choices": VAT_MODE_LABELS,
             "help": "Ignore VAT follows the plain formula. Pick your real VAT position for a more realistic estimate."},
            {"name": "apply_digital_services_fee", "label": "Add Amazon's 2% digital services fee (UK-established sellers)", "kind": "bool",
             "help": "Amazon charges UK-established sellers 2% on selling and FBA fees."},
            {"name": "apply_fuel_surcharge", "label": "Add the 1.5% fuel and logistics surcharge to FBA fees", "kind": "bool",
             "help": "Applies to FBA fulfilment fees from 17 April 2026."},
            {"name": "apply_low_price_fba", "label": "Use Low-Price FBA rates when a product is eligible", "kind": "bool",
             "help": "Cheaper fulfilment for small, light items priced £20 or less (£10 in some categories)."},
            {"name": "apply_peak_fees", "label": "Use festive peak fees between 15 October and 14 January", "kind": "bool",
             "help": "Amazon raises some parcel fees during the festive peak."},
        ],
    },
]

SETTING_GROUPS.append({
    "key": "research",
    "title": "Brand research",
    "lead": "How the brand search collects public Amazon UK pages. Slower is gentler and less likely to be blocked.",
    "fields": [
        {"name": "research_max_pages", "label": "Search result pages to scan per brand", "kind": "int", "min": 1, "max": 20,
         "help": "Each page lists up to about 48 products. Scanning stops early when results stop matching the brand."},
        {"name": "research_delay_seconds", "label": "Pause between page loads", "kind": "number", "min": 3, "max": 120, "unit": "sec",
         "help": "At least 3 seconds, plus a random extra. A brand of 40 products takes roughly 40 × 2 × this pause."},
        {"name": "research_refresh_hours", "label": "Re-collect a known product after", "kind": "int", "min": 1, "max": 2160, "unit": "hours",
         "help": "Products checked more recently than this reuse their stored Amazon data instead of loading the pages again."},
        {"name": "research_cache_hours", "label": "Keep downloaded pages for", "kind": "int", "min": 0, "max": 168, "unit": "hours",
         "help": "Lets an interrupted search resume without loading pages again. 0 turns the cache off."},
        {"name": "research_postcode", "label": "UK delivery postcode used for prices", "kind": "text", "maxlength": 10,
         "pattern": r"^[A-Za-z]{1,2}\d[A-Za-z\d]?\s*\d[A-Za-z]{2}$",
         "help": "Amazon shows UK prices, stock and sellers only for a UK delivery address. Any valid UK postcode works."},
        {"name": "research_show_browser", "label": "Show the browser window while collecting", "kind": "bool",
         "help": "Off by default. Turn on to watch what the collector sees if something looks wrong."},
    ],
})

CRITERIA_FIELDS = ("min_total_sellers", "min_fba_sellers", "max_bsr", "min_monthly_sales", "min_net_profit", "min_roi")

FIELD_SPECS = {f["name"]: f for group in SETTING_GROUPS for f in group["fields"]}


def validate_settings(form: dict, partial_ok: bool = False) -> tuple[Settings, dict]:
    """Validate submitted settings. Returns (settings, errors-by-field).

    Checkbox fields that are absent from an HTML form mean "off"."""
    errors: dict[str, str] = {}
    values: dict = {}
    defaults = Settings()
    for f in fields(Settings):
        spec = FIELD_SPECS[f.name]
        raw = form.get(f.name)
        kind = spec["kind"]
        label = spec["label"]
        if kind == "bool":
            value, err = parse_bool(raw)
        elif kind == "int":
            value, err = parse_whole(raw, label, minimum=spec.get("min"), maximum=spec.get("max"))
        elif kind == "choice":
            value, err = (raw, None) if raw in spec["choices"] else (None, f"Choose a valid option for {label}.")
        elif kind == "text":
            value = re.sub(r"\s+", " ", str(raw or "")).strip().upper() or None
            err = None
            if value and spec.get("pattern") and not re.fullmatch(spec["pattern"], value):
                err = f"{label}: enter a valid UK postcode, for example SW1A 1AA."
        else:  # money / pct
            value, err = parse_number(raw, label, minimum=spec.get("min"), maximum=spec.get("max"), allow_negative=True)
        if err is None and value is None and kind != "bool":
            if partial_ok:
                value = getattr(defaults, f.name)
            else:
                err = f"{label} is required."
        if err:
            errors[f.name] = err
            values[f.name] = getattr(defaults, f.name)
        else:
            values[f.name] = value

    s = Settings(**values)
    if "competition_medium_from" not in errors and "competition_high_from" not in errors:
        if s.competition_medium_from >= s.competition_high_from:
            errors["competition_high_from"] = "High competition must start at more FBA sellers than medium competition."
    if not errors.keys() & {"capture_rate_low", "capture_rate_medium", "capture_rate_high"}:
        if s.capture_rate_medium > s.capture_rate_low:
            errors["capture_rate_medium"] = "The medium-competition capture rate cannot be higher than the default (low-competition) rate."
        elif s.capture_rate_high > s.capture_rate_medium:
            errors["capture_rate_high"] = "The high-competition capture rate cannot be higher than the medium-competition rate."
    return s, errors


def _merge_valid(base: Settings, data: dict) -> Settings:
    """Keep each stored value that validates on its own; default the rest."""
    merged = base.to_dict()
    for name in merged:
        if name not in data:
            continue
        trial = {**base.to_dict(), name: data[name]}
        candidate, errors = validate_settings(trial, partial_ok=True)
        if name not in errors:
            merged[name] = getattr(candidate, name)
    return Settings(**merged)
