from decimal import Decimal

import pytest

from app.extensions import db
from app.models import ServiceAddon, ServicePackage
from app.orders.pricing import build_quote
from tests.laundry.conftest import svc


def pkg(category, description):
    return db.session.execute(db.select(ServicePackage).filter_by(category=category, description=description)).scalar_one()


def addon(code):
    return db.session.execute(db.select(ServiceAddon).filter_by(code=code)).scalar_one()


def service_item(code, qty, **kw):
    return {"kind": "service", "id": svc(code).id, "quantity": qty, **kw}


def test_service_uses_configured_price_and_unit(catalog):
    q = build_quote({"items": [service_item("wash", "2"), service_item("fold", "2.5")]})
    assert q.ok
    assert [l.line_total for l in q.lines] == [Decimal("160.00"), Decimal("50.00")]
    assert q.lines[0].unit == "load" and q.lines[1].unit == "kg"
    assert q.total == Decimal("210.00")


def test_browser_supplied_prices_are_ignored(catalog):
    q = build_quote({"items": [service_item("wash", "1", price="1.00", unit_price="1", total="1")], "total": "1"})
    assert q.total == Decimal("80.00")


@pytest.mark.parametrize("bad", ["0", "-1", "abc", "", "NaN", "Infinity", "1.5", "999", "1e2"])
def test_invalid_load_quantities_rejected(catalog, bad):
    q = build_quote({"items": [service_item("wash", bad)]})
    assert not q.ok and q.total == 0 and not q.lines


@pytest.mark.parametrize("bad", ["0", "0.05", "2.555", "1000"])
def test_invalid_weights_rejected(catalog, bad):
    assert not build_quote({"items": [service_item("fold", bad)]}).ok


def test_unconfigured_unit_cannot_be_ordered(app):
    from app.catalog.seed import seed_catalog
    seed_catalog()  # units deliberately unset
    q = build_quote({"items": [service_item("wash", "1")]})
    assert not q.ok and any("pricing unit" in m for ms in q.errors.values() for m in ms)


def test_inactive_and_unknown_items_rejected(catalog):
    svc("wash").is_active = False
    db.session.commit()
    assert not build_quote({"items": [service_item("wash", "1")]}).ok
    assert not build_quote({"items": [{"kind": "service", "id": 99999, "quantity": "1"}]}).ok
    assert not build_quote({"items": [{"kind": "nope", "id": 1}]}).ok
    assert not build_quote("garbage").ok
    assert not build_quote({"items": "x", "extras": 5}).ok


def test_nothing_selected_rejected(catalog):
    assert not build_quote({"items": [], "extras": []}).ok


def test_duplicate_selection_rejected(catalog):
    assert not build_quote({"items": [service_item("wash", "1"), service_item("wash", "1")]}).ok


def test_package_uses_configured_price_and_range(catalog):
    p = pkg("Clothes", "3KG\u20135KG")
    q = build_quote({"items": [{"kind": "package", "id": p.id, "measurement": "4.5", "quantity": "2"}]})
    assert q.ok and q.total == Decimal("370.00")
    assert q.lines[0].measurement == Decimal("4.5") and q.lines[0].unit == "package"
    for bad in ("2.9", "5.01", "abc", "0"):
        assert not build_quote({"items": [{"kind": "package", "id": p.id, "measurement": bad, "quantity": "1"}]}).ok
    assert not build_quote({"items": [{"kind": "package", "id": p.id, "measurement": "4", "quantity": "21"}]}).ok


def test_piece_package_requires_whole_pieces(catalog):
    p = pkg("Comforter", "2\u20133 pieces (small)")
    ok = build_quote({"items": [{"kind": "package", "id": p.id, "measurement": "3"}]})
    assert ok.ok and ok.total == Decimal("205.00")
    assert not build_quote({"items": [{"kind": "package", "id": p.id, "measurement": "2.5"}]}).ok
    assert not build_quote({"items": [{"kind": "package", "id": p.id, "measurement": "4"}]}).ok


def test_no_double_charging_package_with_included_services(catalog):
    p = pkg("Clothes", "6KG\u20138KG")
    package = {"kind": "package", "id": p.id, "measurement": "7"}
    for code in ("wash", "dry", "fold"):
        q = build_quote({"items": [package, service_item(code, "1")]})
        assert not q.ok, code
    # Spin is not part of Wash, Dry & Fold, so it stays chargeable (open business question, see README).
    q = build_quote({"items": [package, service_item("spin", "1")]})
    assert q.ok and q.total == Decimal("205.00") + Decimal("25.00")


def test_extras_charged_only_when_selected_and_chargeable(catalog):
    base = [service_item("wash", "1")]
    assert build_quote({"items": base}).total == Decimal("80.00")           # not selected -> not charged
    paid = build_quote({"items": base, "extras": [{"id": addon("fabcon").id, "mode": "paid", "quantity": "2"}]})
    assert paid.total == Decimal("110.00")
    addon("fabcon").is_chargeable = False
    db.session.commit()
    assert not build_quote({"items": base, "extras": [{"id": addon("fabcon").id, "mode": "paid"}]}).ok


def test_customer_supplied_extras_are_free(catalog):
    q = build_quote({"items": [service_item("wash", "1")],
                     "extras": [{"id": addon("liquid_soap").id, "mode": "customer_supplied", "quantity": "3"}]})
    assert q.ok and q.total == Decimal("80.00")
    line = q.lines[-1]
    assert line.customer_supplied and line.unit_price == 0 and line.line_total == 0
    addon("liquid_soap").allow_customer_supplied = False
    db.session.commit()
    assert not build_quote({"items": [service_item("wash", "1")],
                            "extras": [{"id": addon("liquid_soap").id, "mode": "customer_supplied"}]}).ok


def test_invalid_extra_mode_and_quantity(catalog):
    base = [service_item("wash", "1")]
    a = addon("fabcon").id
    assert not build_quote({"items": base, "extras": [{"id": a, "mode": "free"}]}).ok
    assert not build_quote({"items": base, "extras": [{"id": a, "mode": "paid", "quantity": "0"}]}).ok
    assert not build_quote({"items": base, "extras": [{"id": a, "mode": "paid", "quantity": "-2"}]}).ok
    assert not build_quote({"items": base, "extras": [{"id": a, "mode": "paid"}, {"id": a, "mode": "paid"}]}).ok
    assert not build_quote({"items": [], "extras": [{"id": a, "mode": "paid"}]}).ok  # extras alone are not an order
