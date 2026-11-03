"""Stage 3 tests: payment models, validation, ledger rules, permissions, settings and QR upload.
No external service is involved; every amount is local test data."""
import io
import itertools
import re
from decimal import Decimal

import pytest
from PIL import Image

from app.extensions import db
from app.models import (
    Order, OrderStatus, Payment, PaymentEvent, PaymentMethod, PaymentSettings, PaymentStatus, Role, User,
)
from app.payments import services as pay_services
from app.payments.seed import seed_payments
from config import TestingConfig
from tests.laundry.conftest import _login, _make_app, svc

_n = itertools.count(1)


def new_customer():
    n = next(_n)
    return {"new": {"full_name": f"Customer {n}", "contact_number": f"0917{n:07d}"}}


FULL_CASH = {"arrangement": "full", "entries": [{"method": "cash", "amount": "160"}]}   # 2 loads of Wash = 160


@pytest.fixture()
def pay(catalog):
    seed_payments()


def place(client, payment="__none__", token=None, **over):
    body = {"items": [{"kind": "service", "id": svc("wash").id, "quantity": "2"}],
            "extras": [], "customer": new_customer()}
    if payment != "__none__":
        body["payment"] = payment
    if token:
        body["submission_token"] = token
    body.update(over)
    return client.post("/orders/new/confirm", json=body)


def order_from(resp):
    assert resp.status_code == 200, resp.get_json()
    ref = resp.get_json()["redirect"].split("/")[2]
    return db.session.execute(db.select(Order).filter_by(reference=ref)).scalar_one()


def count(model):
    return db.session.scalar(db.select(db.func.count(model.id)))


def record(client, order, entries, key=None):
    body = {"entries": entries}
    if key:
        body["idempotency_key"] = key
    return client.post(f"/orders/{order.reference}/payments", json=body)


# ----------------------------------------------------------------------------- seed / derivation
def test_seed_is_idempotent_and_invents_no_account_details(app):
    assert seed_payments() == (2, 1)
    assert seed_payments() == (0, 0)
    assert {m.code for m in db.session.scalars(db.select(PaymentMethod))} == {"cash", "gcash"}
    s = db.session.get(PaymentSettings, 1)
    assert s.gcash_account_name is None and s.gcash_account_number is None and s.qr_filename is None


def test_status_is_derived_from_amounts():
    d = pay_services.derive_status
    assert d("500", "0") == PaymentStatus.UNPAID
    assert d("500", "200") == PaymentStatus.PARTIAL
    assert d("500", "500") == PaymentStatus.PAID
    assert d("500", "0", tracked=False) == PaymentStatus.NOT_TRACKED


# ----------------------------------------------------------------------------- arrangements at order time
def test_full_payment_in_cash(staff_client, staff, pay):
    order = order_from(place(staff_client, FULL_CASH))
    assert order.payment_arrangement == "full"
    assert order.amount_paid == Decimal("160.00") and order.balance_due == 0
    assert order.payment_status == PaymentStatus.PAID
    row = order.payments[0]
    assert (row.kind, row.method_code, row.amount, row.recorded_by_id) == ("payment", "cash", Decimal("160.00"), staff.id)
    assert order.status == OrderStatus.RECEIVED          # payment does not touch order status
    assert order.received_at is None                     # ...and is not the same as "received"


def test_full_payment_in_gcash(staff_client, pay):
    order = order_from(place(staff_client, {"arrangement": "full", "entries": [
        {"method": "gcash", "amount": "160", "reference": "GC-0001"}]}))
    assert order.payments[0].method_code == "gcash" and order.payments[0].reference == "GC-0001"
    assert order.payment_status == PaymentStatus.PAID


def test_partial_payment_keeps_balance_outstanding(staff_client, pay):
    order = order_from(place(staff_client, {"arrangement": "partial", "entries": [{"method": "cash", "amount": "60"}]}))
    assert order.payment_status == PaymentStatus.PARTIAL
    assert order.amount_paid == Decimal("60.00") and order.balance_due == Decimal("100.00")


def test_pay_later_records_zero_and_is_unpaid(staff_client, pay):
    order = order_from(place(staff_client, {"arrangement": "pay_later", "entries": []}))
    assert order.payment_arrangement == "pay_later" and count(Payment) == 0
    assert order.payment_status == PaymentStatus.UNPAID and order.balance_due == Decimal("160.00")


def test_cash_plus_gcash_records_two_allocations(staff_client, pay):
    order = order_from(place(staff_client, {"arrangement": "full", "entries": [
        {"method": "cash", "amount": "100"}, {"method": "gcash", "amount": "60"}]}))
    assert sorted((p.method_code, p.amount) for p in order.payments) == [("cash", Decimal("100.00")), ("gcash", Decimal("60.00"))]
    assert order.payment_status == PaymentStatus.PAID


@pytest.mark.parametrize("payment", [
    {"arrangement": "full", "entries": [{"method": "cash", "amount": "150"}]},            # short
    {"arrangement": "full", "entries": [{"method": "cash", "amount": "170"}]},            # over
    {"arrangement": "full", "entries": []},
    {"arrangement": "partial", "entries": [{"method": "cash", "amount": "160"}]},         # not partial
    {"arrangement": "partial", "entries": []},
    {"arrangement": "pay_later", "entries": [{"method": "cash", "amount": "10"}]},
    {"arrangement": "partial", "entries": [{"method": "cash", "amount": "100"}, {"method": "gcash", "amount": "100"}]},  # overpay
    {"arrangement": "full", "entries": [{"method": "cash", "amount": "-5"}]},
    {"arrangement": "full", "entries": [{"method": "cash", "amount": "0"}]},
    {"arrangement": "full", "entries": [{"method": "cash", "amount": "abc"}]},
    {"arrangement": "full", "entries": [{"method": "cash", "amount": "NaN"}]},
    {"arrangement": "full", "entries": [{"method": "cash", "amount": "160.005"}]},
    {"arrangement": "full", "entries": [{"method": "cash", "amount": "1" * 15}]},
    {"arrangement": "full", "entries": [{"method": "paypal", "amount": "160"}]},
    {"arrangement": "full", "entries": [{"method": "cash", "amount": "80"}, {"method": "cash", "amount": "80"}]},
    {"arrangement": "bogus", "entries": []},
    {"entries": []},
    "cash",
    None,
    {"arrangement": "partial", "entries": [{"method": "cash", "amount": "1"}] * 5},
])
def test_invalid_payment_input_creates_nothing(staff_client, pay, payment):
    r = place(staff_client, payment)
    assert r.status_code == 422 and not r.get_json()["ok"] and any(k.startswith("payment") for k in r.get_json()["errors"])
    assert count(Order) == 0 and count(Payment) == 0


def test_inactive_method_and_disabled_arrangements_are_rejected(staff_client, pay):
    db.session.execute(db.select(PaymentMethod).filter_by(code="gcash")).scalar_one().is_active = False
    db.session.commit()
    assert place(staff_client, {"arrangement": "full", "entries": [{"method": "gcash", "amount": "160"}]}).status_code == 422
    s = db.session.get(PaymentSettings, 1)
    s.partial_enabled = False
    s.pay_later_enabled = False
    db.session.commit()
    assert place(staff_client, {"arrangement": "partial", "entries": [{"method": "cash", "amount": "10"}]}).status_code == 422
    assert place(staff_client, {"arrangement": "pay_later", "entries": []}).status_code == 422
    assert count(Order) == 0


def test_reference_rules(staff_client, pay):
    db.session.execute(db.select(PaymentMethod).filter_by(code="gcash")).scalar_one().requires_reference = True
    db.session.commit()
    pay_g = lambda ref: {"arrangement": "full", "entries": [{"method": "gcash", "amount": "160", "reference": ref}]}  # noqa: E731
    assert place(staff_client, pay_g("")).status_code == 422
    assert place(staff_client, pay_g("<script>alert(1)</script>")).status_code == 422
    assert place(staff_client, pay_g("x" * 65)).status_code == 422
    assert place(staff_client, pay_g("GC 123/45-A")).status_code == 200


def test_payload_without_payment_block_stays_backward_compatible(staff_client, pay):
    order = order_from(place(staff_client))                       # what the older code/tests send
    assert order.payment_arrangement == "pay_later" and count(Payment) == 0
    assert order.received_at is not None                         # counted as received, as before
    assert order.payment_status == PaymentStatus.UNPAID


def test_browser_supplied_totals_and_status_are_ignored(staff_client, pay):
    order = order_from(place(staff_client, {"arrangement": "partial", "payment_status": "paid", "total": "1",
                                            "entries": [{"method": "cash", "amount": "60"}]},
                             total="1.00", payment_status="paid"))
    assert order.total == Decimal("160.00") and order.payment_status == PaymentStatus.PARTIAL


# ----------------------------------------------------------------------------- duplicate submissions
def test_same_submission_token_creates_one_order_and_one_payment(staff_client, pay):
    token = "tok-abcdef123456-xyz"
    customer = new_customer()
    first = place(staff_client, FULL_CASH, token=token, customer=customer)
    again = place(staff_client, FULL_CASH, token=token, customer=customer)
    assert first.status_code == again.status_code == 200
    assert first.get_json()["redirect"] == again.get_json()["redirect"]
    assert count(Order) == 1 and count(Payment) == 1


def test_submission_token_cannot_be_reused_by_another_user(staff_client, admin_client, pay):
    token = "tok-abcdef123456-xyz"
    assert place(staff_client, FULL_CASH, token=token).status_code == 200
    assert place(admin_client, FULL_CASH, token=token).status_code == 422
    assert place(staff_client, FULL_CASH, token="bad token!").status_code == 422
    assert count(Order) == 1


# ----------------------------------------------------------------------------- later payments / history
def test_subsequent_payments_preserve_history_and_settle_the_balance(staff_client, admin_client, pay):
    order = order_from(place(staff_client, {"arrangement": "partial", "entries": [{"method": "cash", "amount": "60"}]}))
    first_id = order.payments[0].id
    r = record(admin_client, order, [{"method": "gcash", "amount": "100", "reference": "GC-9"}])
    assert r.status_code == 200 and r.get_json()["balance"] == "\u20b10.00" and r.get_json()["payment_status"] == "paid"
    db.session.expire_all()
    order = db.session.get(Order, order.id)
    assert [(p.method_code, p.amount) for p in order.payments] == [("cash", Decimal("60.00")), ("gcash", Decimal("100.00"))]
    assert order.payments[0].id == first_id and order.payments[0].amount == Decimal("60.00")   # untouched
    assert order.payment_status == PaymentStatus.PAID


def test_settlement_rejects_overpayment_and_paid_orders(staff_client, pay):
    order = order_from(place(staff_client, {"arrangement": "partial", "entries": [{"method": "cash", "amount": "60"}]}))
    assert record(staff_client, order, [{"method": "cash", "amount": "100.01"}]).status_code == 422
    assert record(staff_client, order, [{"method": "cash", "amount": "-1"}]).status_code == 422
    assert record(staff_client, order, [{"method": "cash", "amount": "0"}]).status_code == 422
    assert record(staff_client, order, []).status_code == 422
    assert count(Payment) == 1
    assert record(staff_client, order, [{"method": "cash", "amount": "100"}]).status_code == 200
    r = record(staff_client, order, [{"method": "cash", "amount": "1"}])
    assert r.status_code == 422 and "fully paid" in r.get_json()["errors"]["payment"][0]
    assert count(Payment) == 2


def test_settlement_can_be_split_across_methods(staff_client, pay):
    order = order_from(place(staff_client, {"arrangement": "pay_later", "entries": []}))
    assert record(staff_client, order, [{"method": "cash", "amount": "40"}, {"method": "gcash", "amount": "120"}]).status_code == 200
    db.session.expire_all()
    assert db.session.get(Order, order.id).payment_status == PaymentStatus.PAID and count(Payment) == 2


def test_repeated_settlement_submission_is_recorded_once(staff_client, pay):
    order = order_from(place(staff_client, {"arrangement": "pay_later", "entries": []}))
    key = "settle-0001-abcdef"
    first = record(staff_client, order, [{"method": "cash", "amount": "50"}], key)
    second = record(staff_client, order, [{"method": "cash", "amount": "50"}], key)
    assert first.status_code == second.status_code == 200
    assert not first.get_json()["duplicate"] and second.get_json()["duplicate"]
    assert count(Payment) == 1
    assert record(staff_client, order, [{"method": "cash", "amount": "5"}], "short").status_code == 422


def test_payments_cannot_be_recorded_on_untracked_legacy_orders(staff_client, pay):
    order = order_from(place(staff_client))
    order.payment_arrangement = None            # an order created before payment recording
    db.session.commit()
    assert order.payment_status == PaymentStatus.NOT_TRACKED
    r = record(staff_client, order, [{"method": "cash", "amount": "10"}])
    assert r.status_code == 422 and "not tracked" in r.get_json()["errors"]["payment"][0]


def test_payment_endpoints_require_login_and_a_real_order(anon_client, staff_client, pay):
    assert anon_client.post("/orders/LX-X/payments", json={}).status_code == 302
    assert anon_client.post("/orders/LX-X/confirm-received").status_code == 302
    assert staff_client.post("/orders/LX-NOPE/payments", json={"entries": []}).status_code == 404


# ----------------------------------------------------------------------------- corrections (admin only, append-only)
def test_admin_reverses_a_payment_without_losing_history(admin_client, staff_client, pay):
    order = order_from(place(staff_client, FULL_CASH))
    original = order.payments[0]
    r = admin_client.post(f"/payments/{original.id}/reverse", json={"reason": "Keyed the wrong amount"})
    assert r.status_code == 200
    db.session.expire_all()
    order = db.session.get(Order, order.id)
    assert len(order.payments) == 2 and order.payments[0].amount == Decimal("160.00")        # original intact
    rev = order.payments[1]
    assert rev.kind == "reversal" and rev.reverses_payment_id == original.id and rev.notes == "Keyed the wrong amount"
    assert order.amount_paid == 0 and order.payment_status == PaymentStatus.UNPAID
    assert db.session.scalar(db.select(db.func.count(PaymentEvent.id)).filter_by(action="payment_reversed")) == 1
    # the correction can now be re-entered correctly
    assert record(staff_client, order, [{"method": "gcash", "amount": "160"}]).status_code == 200


def test_reversal_rules(admin_client, staff_client, pay):
    order = order_from(place(staff_client, FULL_CASH))
    pid = order.payments[0].id
    assert staff_client.post(f"/payments/{pid}/reverse", json={"reason": "nope nope"}).status_code == 403
    assert admin_client.post(f"/payments/{pid}/reverse", json={"reason": ""}).status_code == 422
    assert admin_client.post(f"/payments/{pid}/reverse", json={"reason": "ok reason"}).status_code == 200
    assert admin_client.post(f"/payments/{pid}/reverse", json={"reason": "again"}).status_code == 422   # once only
    db.session.expire_all()
    rev_id = db.session.get(Order, order.id).payments[1].id
    assert admin_client.post(f"/payments/{rev_id}/reverse", json={"reason": "undo the undo"}).status_code == 422
    assert admin_client.post("/payments/99999/reverse", json={"reason": "missing"}).status_code == 422
    assert count(Payment) == 2


# ----------------------------------------------------------------------------- received vs paid are independent
def test_order_received_and_payment_status_are_independent(staff_client, pay):
    order = order_from(place(staff_client, {"arrangement": "pay_later", "entries": []}))
    assert order.received_at is None
    staff_client.post(f"/orders/{order.reference}/status", data={"status": OrderStatus.PENDING})
    db.session.expire_all()
    assert db.session.get(Order, order.id).status == OrderStatus.RECEIVED          # blocked until receipt confirmed
    r = staff_client.post(f"/orders/{order.reference}/confirm-received", json={})
    assert r.status_code == 200 and not r.get_json()["already"]
    db.session.expire_all()
    order = db.session.get(Order, order.id)
    assert order.received_at is not None and order.received_by_id is not None
    assert order.payment_status == PaymentStatus.UNPAID                              # receipt did not mark it paid
    assert order.history[-1].note == "Laundry received by the shop" and order.status == OrderStatus.RECEIVED
    assert staff_client.post(f"/orders/{order.reference}/confirm-received", json={}).get_json()["already"] is True
    staff_client.post(f"/orders/{order.reference}/status", data={"status": OrderStatus.PENDING})
    db.session.expire_all()
    order = db.session.get(Order, order.id)
    assert order.status == OrderStatus.PENDING and order.payment_status == PaymentStatus.UNPAID
    record(staff_client, order, [{"method": "cash", "amount": "160"}])
    db.session.expire_all()
    order = db.session.get(Order, order.id)
    assert order.payment_status == PaymentStatus.PAID and order.status == OrderStatus.PENDING   # paying did not move the order


# ----------------------------------------------------------------------------- permissions
def test_payments_blueprint_is_default_deny_for_staff(app, staff_client, anon_client, pay):
    seen = 0
    for rule in app.url_map.iter_rules():
        if not rule.endpoint.startswith("payments."):
            continue
        seen += 1
        url = re.sub(r"<[^>]+>", "1", rule.rule)
        method = "get" if "GET" in rule.methods else "post"
        assert getattr(anon_client, method)(url).status_code == 302, rule.endpoint
        status = getattr(staff_client, method)(url).status_code
        staff_ok = rule.endpoint in ("payments.qr", "payments.outstanding")   # the only staff-allowed views
        assert status == (200 if staff_ok else 403), (rule.endpoint, status)
    assert seen >= 7


# ----------------------------------------------------------------------------- settings and methods
def test_admin_updates_settings_and_it_is_audited(admin_client, staff_client, pay):
    body = {"partial_enabled": True, "pay_later_enabled": False, "gcash_account_name": "WASH UP Laundry",
            "gcash_account_number": "0917 000 0000", "payment_instructions": "Show the reference number.",
            "payment_notice": "Pay within 7 days", "stub_footer": "Thank you", "show_qr_on_stub": True}
    assert admin_client.post("/payments/settings", json=body).status_code == 200
    db.session.expire_all()
    s = db.session.get(PaymentSettings, 1)
    assert (s.pay_later_enabled, s.gcash_account_name, s.show_qr_on_stub) == (False, "WASH UP Laundry", True)
    assert db.session.scalar(db.select(db.func.count(PaymentEvent.id)).filter_by(action="settings_updated")) == 1
    assert staff_client.post("/payments/settings", json=body).status_code == 403


def test_invalid_settings_are_rejected_and_nothing_changes(admin_client, pay):
    for bad in ({"gcash_account_name": "x" * 121}, {"gcash_account_number": "abc"}, {"payment_notice": "y" * 256}):
        assert admin_client.post("/payments/settings", json=bad).status_code == 422
    db.session.expire_all()
    assert db.session.get(PaymentSettings, 1).gcash_account_name is None


def test_payment_methods_can_be_added_and_toggled(admin_client, pay):
    r = admin_client.post("/payments/methods", json={"label": "Bank Transfer", "requires_reference": True})
    assert r.status_code == 200 and r.get_json()["code"] == "bank_transfer"
    assert admin_client.post("/payments/methods", json={"label": "bank transfer"}).status_code == 422
    assert admin_client.post("/payments/methods", json={"label": "x"}).status_code == 422
    ids = {m.code: m.id for m in db.session.scalars(db.select(PaymentMethod))}
    assert admin_client.post(f"/payments/methods/{ids['gcash']}/toggle").status_code == 200
    assert admin_client.post(f"/payments/methods/{ids['bank_transfer']}/toggle").status_code == 200
    assert admin_client.post(f"/payments/methods/{ids['cash']}/toggle").status_code == 422   # last active one


# ----------------------------------------------------------------------------- QR upload
def png(size=(200, 200)):
    img = Image.new("RGB", size, (20, 40, 160))
    for i in range(0, size[0], 7):
        img.putpixel((i, i % size[1]), (255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def upload(client, data, name="qr.png"):
    return client.post("/payments/settings/qr", data={"image": (io.BytesIO(data), name)},
                       content_type="multipart/form-data")


@pytest.fixture()
def qr_dir(app, tmp_path):
    app.config["PAYMENT_UPLOAD_DIR"] = str(tmp_path)
    return tmp_path


def test_placeholder_is_served_until_a_qr_is_uploaded(staff_client, qr_dir, pay):
    r = staff_client.get("/payments/qr")
    assert r.status_code == 200 and r.mimetype == "image/svg+xml" and b"not uploaded" in r.data


def test_admin_can_upload_and_replace_the_qr(admin_client, staff_client, qr_dir, pay):
    assert upload(admin_client, png()).status_code == 200
    files = list(qr_dir.iterdir())
    assert len(files) == 1 and re.fullmatch(r"qr-[0-9a-f]{32}\.png", files[0].name)
    served = staff_client.get("/payments/qr")
    assert served.mimetype == "image/png" and served.headers["Cache-Control"] == "private, no-cache"
    assert upload(admin_client, png((300, 300)), "../../evil name.PNG").status_code == 200
    names = [f.name for f in qr_dir.iterdir()]
    assert len(names) == 1 and names[0] != files[0].name            # old file removed, new random name
    assert admin_client.post("/payments/settings/qr/remove").status_code == 200
    assert list(qr_dir.iterdir()) == [] and staff_client.get("/payments/qr").mimetype == "image/svg+xml"


@pytest.mark.parametrize("name,data", [
    ("qr.png", b"not an image at all"),
    ("qr.svg", b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"),
    ("qr.exe", png()),
    ("qr.php", png()),
    ("qr", png()),
    ("qr.png", b""),
    ("qr.png", png((10, 10))),
    ("qr.png", png((2500, 100))),
])
def test_unsafe_or_invalid_uploads_are_rejected(admin_client, qr_dir, pay, name, data):
    assert upload(admin_client, data, name).status_code == 422
    assert list(qr_dir.iterdir()) == []


def test_oversized_upload_is_rejected(admin_client, qr_dir, pay):
    assert upload(admin_client, png() + b"0" * (3 * 1024 * 1024)).status_code in (413, 422)
    assert list(qr_dir.iterdir()) == []


def test_uploaded_images_are_reencoded_so_hidden_payloads_are_dropped(admin_client, qr_dir, pay):
    polyglot = png() + b"<script>alert('x')</script><?php system($_GET[1]); ?>"
    assert upload(admin_client, polyglot).status_code == 200
    stored = next(qr_dir.iterdir()).read_bytes()
    assert b"<script" not in stored and b"<?php" not in stored
    Image.open(io.BytesIO(stored)).verify()


def test_qr_route_never_follows_a_tampered_filename(staff_client, qr_dir, pay):
    s = db.session.get(PaymentSettings, 1)
    s.qr_filename = "../../etc/passwd"
    db.session.commit()
    assert staff_client.get("/payments/qr").mimetype == "image/svg+xml"


def test_only_admins_can_change_the_qr(staff_client, anon_client, qr_dir, pay):
    assert upload(staff_client, png()).status_code == 403
    assert staff_client.post("/payments/settings/qr/remove").status_code == 403
    assert upload(anon_client, png()).status_code == 302


# ----------------------------------------------------------------------------- CSRF still on
class CsrfOn(TestingConfig):
    WTF_CSRF_ENABLED = True


def test_csrf_protection_covers_the_new_endpoints():
    app = _make_app(CsrfOn)
    with app.app_context():
        db.create_all()
        staff = User(email="s@example.com", role=Role.STAFF, is_active=True)
        admin = User(email="a@example.com", role=Role.ADMIN, is_active=True)
        db.session.add_all([staff, admin])
        db.session.commit()
        s, a = app.test_client(), app.test_client()
        _login(s, staff)
        _login(a, admin)
        assert s.post("/orders/LX-X/payments", json={}).status_code == 400
        assert s.post("/orders/LX-X/confirm-received").status_code == 400
        assert a.post("/payments/1/reverse", json={"reason": "abc"}).status_code == 400
        assert a.post("/payments/settings", json={}).status_code == 400
        assert a.post("/payments/settings/qr").status_code == 400
        assert a.post("/payments/methods", json={"label": "Bank"}).status_code == 400
        db.session.remove()
        db.drop_all()
