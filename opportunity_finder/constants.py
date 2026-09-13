"""Shared vocabulary: statuses, risk levels, restriction states and risk flags.

Every label the UI, the Excel export and the tests show comes from here, so a
status can never be spelled two different ways in two places.
"""

APP_NAME = "Amazon UK Opportunity Finder"
APP_VERSION = "1.0.0"

# Bump when a change to the calculation, qualification, risk or scoring logic
# should force every stored evaluation to be recomputed.
ENGINE_VERSION = "2026.09.1"

# ---------------------------------------------------------------- statuses
QUALIFIED = "qualified"
REJECTED = "rejected"
INCOMPLETE = "incomplete"
NEEDS_VERIFICATION = "needs_verification"
HIGH_RISK = "high_risk"

STATUSES = [QUALIFIED, NEEDS_VERIFICATION, HIGH_RISK, INCOMPLETE, REJECTED]

STATUS_LABELS = {
    QUALIFIED: "Qualified",
    REJECTED: "Rejected",
    INCOMPLETE: "Incomplete Data",
    NEEDS_VERIFICATION: "Needs Verification",
    HIGH_RISK: "High Risk",
}

# Tone drives colour; the symbol makes the meaning readable without colour.
STATUS_STYLE = {
    QUALIFIED: {"tone": "ok", "symbol": "✓"},
    REJECTED: {"tone": "bad", "symbol": "✕"},
    INCOMPLETE: {"tone": "mute", "symbol": "?"},
    NEEDS_VERIFICATION: {"tone": "warn", "symbol": "!"},
    HIGH_RISK: {"tone": "bad", "symbol": "▲"},
}

STATUS_HELP = {
    QUALIFIED: "Passes every qualification rule, risk is not high and nothing needs re-checking.",
    REJECTED: "At least one qualification rule fails with the data entered.",
    INCOMPLETE: "A value needed for a rule is missing. Nothing is guessed — add the data to evaluate it.",
    NEEDS_VERIFICATION: "Passes the rules, but something must be checked before buying stock.",
    HIGH_RISK: "Passes the rules, but the risk engine scored it HIGH.",
}

# ------------------------------------------------------------- risk levels
RISK_LOW = "LOW"
RISK_MEDIUM = "MEDIUM"
RISK_HIGH = "HIGH"
RISK_LEVELS = [RISK_LOW, RISK_MEDIUM, RISK_HIGH]
RISK_TONE = {RISK_LOW: "ok", RISK_MEDIUM: "warn", RISK_HIGH: "bad"}

# ------------------------------------------------------- restriction status
RESTRICTION_UNKNOWN = "unknown"
RESTRICTION_CHECK = "check"
RESTRICTION_RESTRICTED = "restricted"
RESTRICTION_UNGATED = "ungated"

RESTRICTION_LABELS = {
    RESTRICTION_UNKNOWN: "Unknown",
    RESTRICTION_CHECK: "Check Seller Central",
    RESTRICTION_RESTRICTED: "Restricted",
    RESTRICTION_UNGATED: "Ungated / verified manually",
}

# ---------------------------------------------------------------- flags
RISK_FLAGS = [
    ("flag_hazmat", "Hazmat / dangerous goods"),
    ("flag_battery", "Contains a battery"),
    ("flag_liquid", "Liquid"),
    ("flag_fragile", "Fragile"),
    ("flag_seasonal", "Seasonal"),
    ("flag_amazon_sells", "Amazon itself sells this listing"),
    ("flag_ip_concern", "Possible IP / trademark concern"),
]
FLAG_KEYS = [key for key, _ in RISK_FLAGS]

# -------------------------------------------------------------- fulfilment
FBA = "FBA"
FBM = "FBM"
FULFILMENT_LABELS = {FBA: "FBA — Fulfilled by Amazon", FBM: "FBM — Fulfilled by merchant"}

# ------------------------------------------------------------ data sources
SOURCE_MANUAL = "manual"
SOURCE_SMART_PASTE = "smart_paste"
SOURCE_IMPORT = "import"
SOURCE_KEEPA = "keepa"
SOURCE_LABELS = {
    SOURCE_MANUAL: "Manual entry",
    SOURCE_SMART_PASTE: "Smart paste",
    SOURCE_IMPORT: "Bulk import",
    SOURCE_KEEPA: "Keepa",
}

FEE_DISCLAIMER = (
    "Confirm exact fees in Amazon Seller Central Revenue Calculator before purchasing stock."
)
ESTIMATE_DISCLAIMER = (
    "Estimates are assumptions, not guaranteed forecasts or income."
)
