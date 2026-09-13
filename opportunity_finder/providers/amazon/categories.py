"""Map Amazon UK's category breadcrumb to a referral-fee category key in uk_fee_table.json.

The mapping is approximate (Amazon's fee categories do not match its browse tree one-to-one), so a
mapped category is recorded as ESTIMATED and an unmapped one falls back to "Everything else" (15%)
with a note asking the user to check.
"""
from __future__ import annotations

import re

# (pattern on the top-level category, optional pattern on the second level, fee key)
RULES = [
    (r"grocery", None, "grocery_gourmet"),
    (r"beauty|health|personal care|luxury beauty", None, "beauty_health_personal_care"),
    (r"baby", None, "baby_products"),
    (r"home & kitchen|home and kitchen", r"kitchen|dining|cookware|bakeware", "kitchen"),
    (r"home & kitchen|home and kitchen", r"bedding|linen|rugs|curtains", "home_linen_rugs"),
    (r"home & kitchen|home and kitchen", r"furniture", "furniture"),
    (r"home & kitchen|home and kitchen", None, "home_products"),
    (r"toys|games", None, "toys_games"),
    (r"sports|outdoors", None, "sports_outdoors"),
    (r"pet supplies", None, "pet_supplies"),
    (r"stationery|office", None, "office_products"),
    (r"computers", None, "computers"),
    (r"electronics|camera|photo", None, "consumer_electronics"),
    (r"diy|tools", None, "tools_home_improvement"),
    (r"garden", None, "lawn_garden"),
    (r"automotive|car & motorbike", None, "automotive_powersports"),
    (r"fashion|clothing", r"shoes", "footwear"),
    (r"fashion|clothing", r"jewellery", "jewellery"),
    (r"fashion|clothing", r"watches", "watches"),
    (r"fashion|clothing", r"luggage|bags", "backpacks_handbags"),
    (r"fashion|clothing", None, "clothing_accessories"),
    (r"shoes", None, "footwear"),
    (r"jewellery", None, "jewellery"),
    (r"watches", None, "watches"),
    (r"luggage", None, "luggage"),
    (r"^books", None, "books"),
    (r"music|dvd|blu-ray", None, "music_video_dvd"),
    (r"video games|pc & video games", None, "video_games_accessories"),
    (r"musical instruments", None, "musical_instruments_av"),
    (r"large appliances", None, "full_size_appliances"),
    (r"business|industry|science", None, "business_industrial_scientific"),
    (r"handmade", None, "handmade"),
    (r"beer|wine|spirits", None, "beer_wine_spirits"),
]


def fee_category_for(breadcrumbs: list[str] | None, bsr_category: str | None = None) -> tuple[str, bool]:
    """Return (fee_category_key, mapped?). mapped=False means the 15% default was used."""
    crumbs = [c for c in (breadcrumbs or []) if c]
    top = (crumbs[0] if crumbs else bsr_category or "").lower()
    second = crumbs[1].lower() if len(crumbs) > 1 else ""
    if not top:
        return "everything_else", False
    for top_rx, second_rx, key in RULES:
        if re.search(top_rx, top) and (second_rx is None or re.search(second_rx, second)):
            return key, True
    return "everything_else", False
