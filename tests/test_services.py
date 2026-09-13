"""Database, settings persistence, product lifecycle, history, duplicates and backups."""
import sqlite3
from datetime import date

import pytest

from conftest import TODAY, good_product
from opportunity_finder.constants import QUALIFIED, REJECTED
from opportunity_finder.database.db import connect, init_db, looks_like_our_database, schema_version
from opportunity_finder.database.repositories import SettingsRepository
from opportunity_finder.domain.product import Product
from opportunity_finder.domain.settings import Settings, validate_settings
from opportunity_finder.services.backup import create_backup, restore_backup
from opportunity_finder.services.duplicates import find_duplicates, identity_key
from opportunity_finder.services.product_service import ProductNotFound, ProductService


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "data" / "test.db"
    init_db(path)
    return path


@pytest.fixture
def service(db_path):
    conn = connect(db_path)
    yield ProductService(conn, today=lambda: TODAY)
    conn.close()


def new(**kw) -> Product:
    p = good_product(**kw)
    p.id = None
    return p


# ---------------------------------------------------------------- database
def test_init_db_creates_schema_and_is_idempotent(db_path):
    init_db(db_path)
    conn = connect(db_path)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"products", "settings", "product_snapshots", "evaluations", "meta"} <= names
    assert schema_version(conn) == 2
    conn.close()


def test_database_rejects_negative_price(service):
    with pytest.raises(sqlite3.IntegrityError):
        service.conn.execute("INSERT INTO products (title, selling_price, created_at, updated_at) VALUES ('x', -1, 'a', 'a')")


# ---------------------------------------------------------------- settings
def test_settings_persist_across_connections(db_path):
    conn = connect(db_path)
    assert SettingsRepository(conn).load() == Settings()
    ProductService(conn).save_settings(Settings(max_bsr=40_000, monthly_profit_target=2500, vat_mode="registered"))
    conn.close()

    conn2 = connect(db_path)
    loaded = SettingsRepository(conn2).load()
    assert loaded.max_bsr == 40_000 and loaded.monthly_profit_target == 2500 and loaded.vat_mode == "registered"
    ProductService(conn2).reset_settings()
    assert SettingsRepository(conn2).load() == Settings()
    conn2.close()


def test_corrupt_stored_settings_fall_back_per_field():
    s = Settings.from_dict({"max_bsr": "not a number", "min_total_sellers": 7, "vat_mode": "bogus", "unknown": 1})
    assert s.max_bsr == 25_000 and s.min_total_sellers == 7 and s.vat_mode == "ignore"


def test_settings_validation_messages():
    form = {**{k: str(v) for k, v in Settings().to_dict().items()}}
    form.update(max_bsr="-5", capture_rate_low="150", competition_medium_from="10", competition_high_from="10",
                monthly_profit_target="")
    form = {k: v for k, v in form.items() if v not in ("True", "False")}
    _, errors = validate_settings(form)
    assert "max_bsr" in errors and "capture_rate_low" in errors and "monthly_profit_target" in errors
    assert "competition_high_from" in errors
    _, errors = validate_settings({**{k: str(v) for k, v in Settings().to_dict().items()}, "capture_rate_high": "15"})
    assert "capture_rate_high" in errors


# ---------------------------------------------------------------- lifecycle
def test_create_evaluates_and_records_history(service):
    pid = service.create(new())
    product = service.get(pid)
    assert product.evaluation["status"] == QUALIFIED
    history = service.history(pid)
    assert len(history["snapshots"]) == 1 and history["snapshots"][0]["selling_price"] == 24.99
    assert history["evaluations"][0]["trigger"] == "created"
    assert product.created_at and product.updated_at and product.evaluated_at


def test_update_market_value_refreshes_checked_date_and_snapshots(service):
    pid = service.create(new(amazon_checked_at="2026-01-01T09:00:00"))
    before = service.get(pid)
    incoming = Product.from_mapping({**before.__dict__, "bsr": 7000})
    after = service.update(pid, incoming)
    assert after.amazon_checked_at != "2026-01-01T09:00:00"
    assert len(service.history(pid)["snapshots"]) == 2


def test_update_notes_only_keeps_checked_date_and_snapshot(service):
    pid = service.create(new(amazon_checked_at="2026-09-10T09:00:00"))
    before = service.get(pid)
    after = service.update(pid, Product.from_mapping({**before.__dict__, "notes": "call supplier"}))
    assert after.amazon_checked_at == "2026-09-10T09:00:00"
    assert len(service.history(pid)["snapshots"]) == 1
    assert after.notes == "call supplier"


def test_mark_checked_without_changes(service):
    pid = service.create(new(amazon_checked_at="2026-09-01T09:00:00"))
    p = service.get(pid)
    after = service.update(pid, Product.from_mapping(p.__dict__), mark_checked=True)
    assert after.amazon_checked_at > "2026-09-01T09:00:00"


def test_settings_change_reevaluates(service):
    pid = service.create(new(bsr=42_831))
    assert service.get(pid).evaluation["status"] == REJECTED
    service.save_settings(Settings(max_bsr=50_000))
    item = next(i for i in service.items() if i["product"].id == pid)
    assert item["evaluation"]["status"] == QUALIFIED


def test_products_persist_after_restart(db_path):
    conn = connect(db_path)
    pid = ProductService(conn, today=lambda: TODAY).create(new(title="Persistent"))
    conn.close()
    conn = connect(db_path)
    items = ProductService(conn, today=lambda: TODAY).items()
    assert [(i["product"].id, i["product"].title, i["evaluation"]["status"]) for i in items] == [(pid, "Persistent", QUALIFIED)]
    conn.close()


def test_new_day_refreshes_stale_data_check(db_path):
    conn = connect(db_path)
    pid = ProductService(conn, today=lambda: TODAY).create(new())
    later = ProductService(conn, today=lambda: date(2026, 12, 1))
    assert later.get(pid).evaluation["status"] == "needs_verification"
    conn.close()


def test_duplicate_archive_delete(service):
    pid = service.create(new())
    copy_id = service.duplicate(pid)
    assert copy_id != pid and service.get(copy_id).title.endswith("(copy)")

    service.set_archived(copy_id, True)
    assert [i["product"].id for i in service.items()] == [pid]
    assert len(service.items(include_archived=True)) == 2
    service.set_archived(copy_id, False)
    assert len(service.items()) == 2

    assert service.delete(pid) is True
    with pytest.raises(ProductNotFound):
        service.get(pid)
    assert service.conn.execute("SELECT COUNT(*) FROM product_snapshots WHERE product_id = ?", (pid,)).fetchone()[0] == 0
    assert service.conn.execute("SELECT COUNT(*) FROM evaluations WHERE product_id = ?", (pid,)).fetchone()[0] == 0
    assert service.delete(pid) is False


def test_merge_keeps_existing_values_for_blanks(service):
    pid = service.create(new(sourcing_price=8.0, supplier="Old Supplier"))
    incoming = Product(asin="B0TEST0001", selling_price=26.50, sourcing_price=None, supplier=None)
    merged = service.merge(pid, incoming, provided={"selling_price"}, source="import")
    assert merged.selling_price == 26.50
    assert merged.sourcing_price == 8.0 and merged.supplier == "Old Supplier"
    assert merged.flag_hazmat is False


def test_reevaluate_records_manual_trigger(service):
    pid = service.create(new())
    service.reevaluate(pid)
    assert service.history(pid)["evaluations"][0]["trigger"] == "manual"
    assert service.reevaluate_all() == 1


# ---------------------------------------------------------------- duplicates
def test_duplicate_detection_order(service):
    a = service.create(new(asin="B0DUPE0001", amazon_url="https://www.amazon.co.uk/dp/B0DUPE0001"))
    b = service.create(new(asin=None, amazon_url="https://www.amazon.co.uk/dp/B0URLONLY1", title="Url item"))
    c = service.create(new(asin=None, amazon_url=None, title="Blue Mug", brand="Acme"))

    m = find_duplicates(service.repo, Product(asin="b0dupe0001"))
    assert [(d.product.id, d.matched_on) for d in m] == [(a, "asin")]
    m = find_duplicates(service.repo, Product(amazon_url="https://www.amazon.co.uk/dp/B0URLONLY1/"))
    assert [(d.product.id, d.matched_on) for d in m] == [(b, "url")]
    m = find_duplicates(service.repo, Product(title="  blue mug ", brand="ACME"))
    assert [(d.product.id, d.matched_on) for d in m] == [(c, "title_brand")]
    assert find_duplicates(service.repo, Product(title="Blue Mug", brand="Other")) == []
    assert find_duplicates(service.repo, Product(asin="B0DUPE0001"), exclude_id=a) == []
    assert find_duplicates(service.repo, Product(asin="B0NOTHERE1")) == []


def test_identity_key():
    assert identity_key(Product(asin="b0x")) == "asin:B0X"
    assert identity_key(Product(title="A", brand="B")) == "tb:a|b"
    assert identity_key(Product()) is None


# ---------------------------------------------------------------- backups
def test_backup_and_restore(service, db_path, tmp_path):
    pid = service.create(new(title="Keep me"))
    backup = create_backup(db_path, tmp_path / "backups")
    service.delete(pid)
    assert service.items() == []

    ok, message, safety = restore_backup(backup.read_bytes(), db_path, tmp_path / "backups")
    assert ok, message
    assert safety is not None and safety.exists()
    conn = connect(db_path)
    assert [p.title for p in ProductService(conn, today=lambda: TODAY).repo.all()] == ["Keep me"]
    conn.close()


def test_restore_rejects_other_files(db_path, tmp_path):
    ok, message, _ = restore_backup(b"hello world", db_path, tmp_path)
    assert not ok and "not an Opportunity Finder backup" in message
    other = tmp_path / "other.db"
    c = sqlite3.connect(other)
    c.execute("CREATE TABLE x (id INTEGER)")
    c.commit()
    c.close()
    assert looks_like_our_database(other)[0] is False
    ok, message, _ = restore_backup(other.read_bytes(), db_path, tmp_path)
    assert not ok and "required tables" in message
