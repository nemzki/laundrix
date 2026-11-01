from decimal import Decimal

from app.catalog.seed import seed_catalog
from app.extensions import db
from app.models import Service, ServiceAddon, ServicePackage
from tests.laundry.conftest import svc

SERVICE_FORM = {
    "name": "Iron", "code": "iron", "category": "Laundry service", "price": "30.00",
    "pricing_unit": "piece", "icon_key": "generic", "is_active": "on",
}


def test_anonymous_is_redirected_to_login(anon_client):
    r = anon_client.get("/admin/services/")
    assert r.status_code == 302 and "/auth/login" in r.headers["Location"]


def test_admin_can_view_catalog_tabs(admin_client, catalog):
    for tab in ("services", "packages", "addons"):
        assert admin_client.get(f"/admin/services/?tab={tab}").status_code == 200
    html = admin_client.get("/admin/services/").get_data(as_text=True)
    assert "Wash" in html and "Spin" in html


def test_staff_cannot_open_or_modify_catalog(staff_client, catalog):
    assert staff_client.get("/admin/services/").status_code == 403
    assert staff_client.get("/admin/services/services/new").status_code == 403
    before = svc("wash").price
    assert staff_client.post(f"/admin/services/services/{svc('wash').id}/edit",
                             data={**SERVICE_FORM, "name": "Wash", "price": "1.00"}).status_code == 403
    assert staff_client.post("/admin/services/services/new", data=SERVICE_FORM).status_code == 403
    assert staff_client.post(f"/admin/services/services/{svc('wash').id}/toggle").status_code == 403
    db.session.expire_all()
    assert svc("wash").price == before
    assert db.session.execute(db.select(Service).filter_by(code="iron")).scalar_one_or_none() is None


def test_admin_creates_edits_prices_and_deactivates_service(admin_client, app):
    r = admin_client.post("/admin/services/services/new", data=SERVICE_FORM)
    assert r.status_code == 302
    iron = svc("iron")
    assert iron.price == Decimal("30.00") and iron.pricing_unit == "piece"

    r = admin_client.post(f"/admin/services/services/{iron.id}/edit",
                          data={**SERVICE_FORM, "price": "35.50", "pricing_unit": "load"})
    assert r.status_code == 302
    db.session.expire_all()
    assert svc("iron").price == Decimal("35.50") and svc("iron").pricing_unit == "load"

    admin_client.post(f"/admin/services/services/{iron.id}/toggle")
    db.session.expire_all()
    assert svc("iron").is_active is False


def test_invalid_catalog_input_is_rejected(admin_client, app):
    for bad in ({"price": "-5"}, {"price": "abc"}, {"price": "10.123"}, {"pricing_unit": "per_galaxy"},
                {"code": "Bad Code!"}, {"name": ""}, {"image_url": "https://evil.example/x.png"}):
        r = admin_client.post("/admin/services/services/new", data={**SERVICE_FORM, **bad})
        assert r.status_code == 422, bad
    assert db.session.execute(db.select(Service).filter_by(code="iron")).scalar_one_or_none() is None


def test_admin_manages_packages_and_addons(admin_client, catalog):
    pkg = {"name": "Wash, Dry & Fold", "category": "Rugs", "description": "1 piece", "measure_type": "pieces",
           "min_value": "1", "max_value": "1", "price": "300", "covers_codes": ["wash", "dry", "fold"],
           "icon_key": "package", "is_active": "on"}
    assert admin_client.post("/admin/services/packages/new", data=pkg).status_code == 302
    assert admin_client.post("/admin/services/packages/new", data=pkg).status_code == 422  # duplicate
    assert admin_client.post("/admin/services/packages/new", data={**pkg, "description": "x", "max_value": "0"}).status_code == 422
    addon = {"name": "Bleach", "code": "bleach", "price": "10", "is_chargeable": "on", "icon_key": "soap", "is_active": "on"}
    assert admin_client.post("/admin/services/addons/new", data=addon).status_code == 302
    bad = {**addon, "code": "nothing", "is_chargeable": ""}
    assert admin_client.post("/admin/services/addons/new", data=bad).status_code == 422


def test_seed_is_idempotent_and_never_overwrites(app):
    assert seed_catalog() == (4, 2, 6)
    wash = svc("wash")
    wash.price = Decimal("90.00")
    db.session.commit()
    assert seed_catalog() == (0, 0, 0)
    db.session.expire_all()
    assert svc("wash").price == Decimal("90.00")
    assert len(db.session.scalars(db.select(ServicePackage)).all()) == 6


def test_seed_matches_confirmed_catalog_and_leaves_units_unset(app):
    seed_catalog()
    prices = {s.code: s.price for s in db.session.scalars(db.select(Service))}
    assert prices == {"wash": Decimal("80.00"), "dry": Decimal("75.00"), "fold": Decimal("20.00"), "spin": Decimal("25.00")}
    assert all(s.pricing_unit is None for s in db.session.scalars(db.select(Service)))
    assert {a.code: a.price for a in db.session.scalars(db.select(ServiceAddon))} == {
        "fabcon": Decimal("15.00"), "liquid_soap": Decimal("15.00")}
    pk = {(p.category, p.description): p.price for p in db.session.scalars(db.select(ServicePackage))}
    assert pk[("Clothes", "3KG\u20135KG")] == Decimal("185.00")
    assert pk[("Clothes", "6KG\u20138KG")] == Decimal("205.00")
    assert pk[("Comforter", "2\u20133 pieces (small)")] == Decimal("205.00")
    assert pk[("Comforter", "1 piece (big)")] == Decimal("205.00")
    assert pk[("Curtains", "3KG\u20135KG")] == Decimal("205.00")
    assert pk[("Linens", "3KG\u20135KG")] == Decimal("205.00")
