import sys
from datetime import date, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from opportunity_finder.domain.product import Product  # noqa: E402
from opportunity_finder.domain.settings import Settings  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
TODAY = date(2026, 9, 13)  # outside the festive peak, after the fuel surcharge start


def good_product(**overrides) -> Product:
    """A complete product that qualifies with default settings.

    Hand-worked expectations (13 Sep 2026, default settings):
      referral 15% of £24.99 = £3.75; 20x15x8 cm, 400 g -> dimensional weight 480 g -> Small parcel <=900 g £3.04;
      fuel 1.5% = £0.05; digital services fee 2% of £6.84 = £0.14; total fees £6.98
      net profit = 24.99 - 6.98 - 0.50 - 8.00 = £9.51; ROI 118.9%; 3 FBA sellers -> 20% capture
      300 sales -> 60 conservative units -> £570.60 conservative profit; theoretical £2,853.00
    """
    data = dict(
        id=1, asin="B0TEST0001", title="Stackable storage box", brand="Brightnest", category="Home & Kitchen",
        fee_category="everything_else", amazon_url="https://www.amazon.co.uk/dp/B0TEST0001",
        selling_price=24.99, bsr=5000, monthly_sales=300, total_sellers=6, fba_sellers=3,
        sourcing_price=8.00, supplier="Wholesale Ltd", shipping_prep=0.50, other_costs=0.0,
        weight_g=400, length_cm=20, width_cm=15, height_cm=8,
        restriction_status="ungated", amazon_checked_at=datetime(2026, 9, 12, 10, 0).isoformat(),
    )
    data.update(overrides)
    return Product(**data)


@pytest.fixture
def settings() -> Settings:
    return Settings()


@pytest.fixture
def today() -> date:
    return TODAY


@pytest.fixture
def fixture_text():
    def _read(name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")
    return _read
