"""Stages 4-6: the payment step in the order wizard, preview, stub, receipt step, order page panel,
payments pages, settings, tracking page and the complete shop workflow."""
import io
import re
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import Order, PaymentMethod, PaymentSettings, PaymentStatus
from app.payments.seed import seed_payments
from tests.laundry.conftest import svc
from tests.laundry.test_payments_backend import FULL_CASH, count, new_customer, order_from, place, png, record

PARTIAL_GCASH = {"arrangement": "partial", "entries": [{"method": "gcash", "amount": "60", "reference": "GC-SECRET-1"}]}
PARTIAL_CASH = {"arrangement": "partial", "entries": [{"method": "cash", "amount": "60"}]}
PAY_LATER = {"arrangement": "pay_later", "entries": []}


@pytest.fixture()
def pay(catalog):
    seed_payments()


def page(client, url):
    r = client.get(url)
    assert r.status_code == 200, (url, r.status_code)
    return r.get_data(as_text=True)


def pay_settings():
    return db.session.get(PaymentSettings, 1)


# ----------------------------------------------------------------------------- wizard payment step
def test_wizard_contains_the_payment_step_driven_by_the_database(staff_client, pay):
    html = page(staff_client, "/orders/new")
    for text in ("Full Payment", "Partial Payment", "Pay Later", "Cash", "GCash", "Confirm and generate stub", "Amount due"):
        assert text in html
    assert 'data-step="5"' in html and 'data-step="6"' in html and "style=" not in html
    t1 = re.search(r'data-token="([^"]+)"', html).group(1)
    t2 = re.search(r'data-token="([^"]+)"', page(staff_client, "/orders/new")).group(1)
    assert len(t1) >= 16 and t1 != t2                                  # a fresh one-time token per page load


def test_wizard_follows_admin_settings(staff_client, pay):
    s = pay_settings()
    s.partial_enabled = False
    s.pay_later_enabled = False
    s.gcash_account_name = "Shop GCash Name"
    s.gcash_account_number = "0917 555 0000"
    s.payment_notice = "Balances are due on pickup."
    db.session.commit()
    html = page(staff_client, "/orders/new")
    assert "Partial Payment" not in html and "Pay Later" not in html and "Full Payment" in html
    assert "Shop GCash Name" in html and "0917 555 0000" in html and "Balances are due on pickup." in html
    assert "/payments/qr" in html                                       # placeholder or uploaded QR, never invented


def test_wizard_warns_when_no_methods_are_configured(staff_client, catalog):
    assert "No payment methods are configured" in page(staff_client, "/orders/new")


# ----------------------------------------------------------------------------- server-side preview
def quote(client, payment=None, **over):
    body = {"items": [{"kind": "service", "id": svc("wash").id, "quantity": "2"}], "extras": [], **over}
    if payment is not None:
        body["payment"] = payment
    return client.post("/orders/new/quote", json=body).get_json()


def test_quote_previews_payment_using_the_server_total(staff_client, pay):
    j = quote(staff_client, PARTIAL_CASH)
    assert j["ok"] and j["total_raw"] == "160.00"
    p = j["payment"]
    assert (p["arrangement_label"], p["received"], p["balance"], p["status"]) == ("Partial Payment", "\u20b160.00", "\u20b1100.00", "partial")
    assert quote(staff_client, FULL_CASH)["payment"]["status"] == "paid"
    assert quote(staff_client, PAY_LATER)["payment"]["status"] == "unpaid"
    assert quote(staff_client)["payment"] is None                       # no payment block, no preview


def test_quote_rejects_invalid_payments_and_ignores_browser_totals(staff_client, pay):
    bad = quote(staff_client, {"arrangement": "full", "entries": [{"method": "cash", "amount": "100"}]}, total="100")
    assert not bad["ok"] and bad["payment"] is None and "payment" in bad["errors"]
    assert not quote(staff_client, {"arrangement": "partial", "entries": [{"method": "cash", "amount": "999"}]})["ok"]
    assert quote(staff_client, PARTIAL_CASH, total="1")["total"] == "\u20b1160.00"


# ----------------------------------------------------------------------------- stub + receipt step
def test_confirmation_page_guides_print_then_receipt(staff_client, pay):
    order = order_from(place(staff_client, PARTIAL_CASH))
    html = page(staff_client, f"/orders/{order.reference}/confirmation")
    for text in ("1. Print the order stub", "2. Confirm laundry received", "Partially Paid", "Open printable stub"):
        assert text in html
    assert f"/orders/{order.reference}/confirm-received" in html
    r = staff_client.post(f"/orders/{order.reference}/confirm-received", follow_redirects=True)
    assert b"Laundry confirmed as received." in r.data
    db.session.expire_all()
    assert db.session.get(Order, order.id).received_at is not None
    assert "Received" in page(staff_client, f"/orders/{order.reference}/confirmation")
    assert b"already confirmed" in staff_client.post(f"/orders/{order.reference}/confirm-received", follow_redirects=True).data


def test_stub_shows_payment_but_nothing_internal(staff_client, pay):
    s = pay_settings()
    s.payment_instructions = "Pay the balance at pickup."
    s.stub_footer = "Thank you, come again"
    db.session.commit()
    order = order_from(place(staff_client, PARTIAL_GCASH, notes="Fold neatly"))
    stub = page(staff_client, f"/orders/{order.reference}/stub")
    for text in ("Amount received", "\u20b160.00", "Remaining balance", "\u20b1100.00", "Partially Paid", "Paid by GCash",
                 "Served by", "Staff", "Pay the balance at pickup.", "Thank you, come again", "Fold neatly", "Scan to Track"):
        assert text in stub, text
    for secret in ("GC-SECRET-1", "staff@example.com"):      # references and staff accounts are never printed
        assert secret not in stub, secret
    assert "/payments/qr" not in stub                                   # QR on stub is off by default


def test_stub_prints_payment_qr_only_when_enabled_and_balance_remains(staff_client, pay):
    s = pay_settings()
    s.show_qr_on_stub = True
    s.qr_filename = "qr-" + "a" * 32 + ".png"
    db.session.commit()
    owing = order_from(place(staff_client, PAY_LATER))
    paid = order_from(place(staff_client, FULL_CASH))
    assert "/payments/qr" in page(staff_client, f"/orders/{owing.reference}/stub")
    stub_paid = page(staff_client, f"/orders/{paid.reference}/stub")
    assert "/payments/qr" not in stub_paid and "Pay the balance" not in stub_paid and "Paid" in stub_paid


def test_untracked_legacy_orders_still_print(staff_client, pay):
    order = order_from(place(staff_client))
    order.payment_arrangement = None
    db.session.commit()
    assert "not recorded on this stub" in page(staff_client, f"/orders/{order.reference}/stub")


# ----------------------------------------------------------------------------- order page
def test_order_page_shows_payment_panel_and_history(staff_client, admin_client, pay):
    order = order_from(place(staff_client, PARTIAL_GCASH))
    html = page(staff_client, f"/orders/{order.reference}")
    for text in ("Payment history", "Record a payment", "Balance due", "Partially Paid", "Ref: GC-SECRET-1", "Awaiting confirmation"):
        assert text in html
    assert "Reverse payment" not in html                                # staff cannot correct payments
    assert "Reverse payment" in page(admin_client, f"/orders/{order.reference}")
    assert "Confirm that the laundry was received before changing the order status." in html


def test_recording_a_later_payment_through_the_form(staff_client, pay):
    order = order_from(place(staff_client, PARTIAL_CASH))
    form = {"method": ["gcash", ""], "amount": ["100", ""], "reference": ["GC-77", ""],
            "notes": "settled at pickup", "idempotency_key": "form-key-123456"}
    first = staff_client.post(f"/orders/{order.reference}/payments", data=form, follow_redirects=True)
    assert b"Payment recorded." in first.data
    again = staff_client.post(f"/orders/{order.reference}/payments", data=form, follow_redirects=True)
    assert b"already recorded" in again.data
    db.session.expire_all()
    order = db.session.get(Order, order.id)
    assert order.payment_status == PaymentStatus.PAID and len(order.payments) == 2
    assert "This order is fully paid." in page(staff_client, f"/orders/{order.reference}")
    over = staff_client.post(f"/orders/{order.reference}/payments", data={"method": "cash", "amount": "5"}, follow_redirects=True)
    assert b"fully paid" in over.data


def test_admin_can_correct_a_payment_from_the_order_page(admin_client, staff_client, pay):
    order = order_from(place(staff_client, FULL_CASH))
    pid = order.payments[0].id
    assert b"Enter a reason" in admin_client.post(f"/payments/{pid}/reverse", data={"reason": ""}, follow_redirects=True).data
    ok = admin_client.post(f"/payments/{pid}/reverse", data={"reason": "Wrong amount keyed"}, follow_redirects=True)
    assert b"Payment reversed." in ok.data and b"Reversed" in ok.data and b"Reversal" in ok.data
    db.session.expire_all()
    assert db.session.get(Order, order.id).payment_status == PaymentStatus.UNPAID
    assert staff_client.post(f"/payments/{pid}/reverse", data={"reason": "x y z"}).status_code == 403


def test_legacy_order_page_explains_untracked_payments(staff_client, pay):
    order = order_from(place(staff_client))
    order.payment_arrangement = None
    db.session.commit()
    html = page(staff_client, f"/orders/{order.reference}")
    assert "Payment not tracked" in html and "payments are not tracked" in html and "Record a payment" not in html


def test_orders_list_shows_payment_and_receipt_state(staff_client, pay):
    order_from(place(staff_client, PARTIAL_CASH))
    html = page(staff_client, "/orders/")
    assert "Partially Paid" in html and "Balance \u20b1100.00" in html and "Awaiting receipt" in html


# ----------------------------------------------------------------------------- payments pages
def three_orders(staff_client):
    return (order_from(place(staff_client, FULL_CASH)), order_from(place(staff_client, PARTIAL_GCASH)),
            order_from(place(staff_client, PAY_LATER)))


def test_outstanding_balances_for_staff_and_admin(staff_client, admin_client, pay):
    paid, partial, later = three_orders(staff_client)
    html = page(staff_client, "/payments/outstanding")
    assert partial.reference in html and later.reference in html and paid.reference not in html
    assert "\u20b1260.00" in html                                       # 100 + 160 still due
    only_unpaid = page(staff_client, "/payments/outstanding?status=unpaid")
    assert later.reference in only_unpaid and partial.reference not in only_unpaid
    only_partial = page(staff_client, "/payments/outstanding?status=partial")
    assert partial.reference in only_partial and later.reference not in only_partial
    assert staff_client.get("/payments/outstanding?status=paid").status_code == 403
    assert paid.reference in page(admin_client, "/payments/outstanding?status=paid")
    assert page(staff_client, "/payments/outstanding?status=bogus") and staff_client.get("/payments/outstanding?page=99").status_code == 200


def test_legacy_orders_never_count_as_owing(staff_client, pay):
    order = order_from(place(staff_client, PAY_LATER))
    order.payment_arrangement = None
    db.session.commit()
    html = page(staff_client, "/payments/outstanding")
    assert order.reference not in html and "No orders owe a balance." in html


def test_admin_payment_records_with_filters(admin_client, staff_client, staff, pay):
    paid, partial, _ = three_orders(staff_client)
    html = page(admin_client, "/payments/")
    assert paid.reference in html and partial.reference in html
    gcash_only = page(admin_client, "/payments/?method=gcash")
    assert partial.reference in gcash_only and paid.reference not in gcash_only and "GC-SECRET-1" in gcash_only
    assert "No payments found" in page(admin_client, "/payments/?kind=reversal")
    assert paid.reference in page(admin_client, "/payments/?from=2000-01-01&to=2100-01-01")
    assert "No payments found" in page(admin_client, "/payments/?from=2100-01-01")
    assert paid.reference in page(admin_client, "/payments/?from=not-a-date")          # bad dates are ignored
    assert paid.reference in page(admin_client, f"/payments/?staff={staff.id}")
    assert staff_client.get("/payments/").status_code == 403


def test_admin_payment_summaries(admin_client, staff_client, pay):
    paid, _, _ = three_orders(staff_client)
    html = page(admin_client, "/payments/summary")
    assert "\u20b1220.00" in html and "\u20b1160.00" in html and "\u20b160.00" in html and "Cash" in html and "GCash" in html
    for period in ("weekly", "monthly", "bogus"):
        assert page(admin_client, f"/payments/summary?period={period}")
    admin_client.post(f"/payments/{paid.payments[0].id}/reverse", json={"reason": "refund of mistake"})
    assert "\u20b160.00" in page(admin_client, "/payments/summary") and "\u20b1220.00" not in page(admin_client, "/payments/summary")
    assert staff_client.get("/payments/summary").status_code == 403


def test_dashboards_show_payment_figures(admin_client, staff_client, pay):
    assert "\u20b10.00" in page(admin_client, "/dashboard/admin")
    order_from(place(staff_client, PARTIAL_CASH))
    admin_html = page(admin_client, "/dashboard/admin")
    assert "Outstanding Balance" in admin_html and "\u20b1100.00" in admin_html and "Collected Today" in admin_html and "\u20b160.00" in admin_html
    staff_html = page(staff_client, "/dashboard/staff")
    assert "Awaiting receipt confirmation" in staff_html and "Collected today" not in staff_html


def test_navigation_is_role_aware(admin_client, staff_client, pay):
    staff_html = page(staff_client, "/orders/")
    assert "Outstanding Balances" in staff_html and 'href="/payments/"' not in staff_html
    assert 'href="/payments/"' in page(admin_client, "/orders/")


# ----------------------------------------------------------------------------- settings page
def ui_upload(client, data, name="qr.png"):
    return client.post("/payments/settings/qr", data={"ui": "1", "image": (io.BytesIO(data), name)},
                       content_type="multipart/form-data", follow_redirects=True)


def test_settings_page_saves_through_the_form(admin_client, staff_client, pay):
    html = page(admin_client, "/payments/settings")
    for text in ("Payment QR Code", "Payment Methods", "Add Method", "Save Settings", "No QR uploaded yet"):
        assert text in html
    assert staff_client.get("/payments/settings").status_code == 403
    r = admin_client.post("/payments/settings", data={"ui": "1", "partial_enabled": "on", "gcash_account_name": "My Shop"},
                          follow_redirects=True)
    assert b"Payment settings saved." in r.data
    db.session.expire_all()
    s = pay_settings()
    assert (s.partial_enabled, s.pay_later_enabled, s.gcash_account_name) == (True, False, "My Shop")
    bad = admin_client.post("/payments/settings", data={"ui": "1", "gcash_account_name": "x" * 130})
    assert bad.status_code == 422 and b"Must be 120 characters or fewer." in bad.data


def test_methods_can_be_managed_from_the_page(admin_client, pay):
    r = admin_client.post("/payments/methods", data={"ui": "1", "label": "Bank Transfer", "requires_reference": "on"}, follow_redirects=True)
    assert b"Added Bank Transfer." in r.data
    assert b"already exists" in admin_client.post("/payments/methods", data={"ui": "1", "label": "bank transfer"}, follow_redirects=True).data
    ids = {m.code: m.id for m in db.session.scalars(db.select(PaymentMethod))}
    for code in ("gcash", "bank_transfer"):
        assert b"disabled." in admin_client.post(f"/payments/methods/{ids[code]}/toggle", data={"ui": "1"}, follow_redirects=True).data
    last = admin_client.post(f"/payments/methods/{ids['cash']}/toggle", data={"ui": "1"}, follow_redirects=True)
    assert b"At least one payment method must stay active." in last.data


def test_qr_upload_from_the_settings_page(admin_client, staff_client, app, tmp_path, pay):
    app.config["PAYMENT_UPLOAD_DIR"] = str(tmp_path)
    assert b"Payment QR image replaced." in ui_upload(admin_client, png()).data
    assert len(list(tmp_path.iterdir())) == 1
    assert b"No QR uploaded yet" not in admin_client.get("/payments/settings").data
    assert staff_client.get("/payments/qr").mimetype == "image/png"
    assert b"not a valid image" in ui_upload(admin_client, b"definitely not an image").data
    assert b"Payment QR image removed." in admin_client.post("/payments/settings/qr/remove", data={"ui": "1"}, follow_redirects=True).data
    assert list(tmp_path.iterdir()) == []


# ----------------------------------------------------------------------------- customer tracking page
def test_tracking_page_shows_payment_status_and_balance_only(staff_client, anon_client, pay):
    order = order_from(place(staff_client, PARTIAL_GCASH))
    html = page(anon_client, f"/track/{order.tracking_token}")
    assert "Partially Paid" in html and "Balance due" in html and "\u20b1100.00" in html
    for private in ("GCash", "GC-SECRET-1", "\u20b160.00", "Staff", "staff@example.com"):
        assert private not in html, private


def test_tracking_page_for_paid_and_untracked_orders(staff_client, anon_client, pay):
    paid = order_from(place(staff_client, FULL_CASH))
    html = page(anon_client, f"/track/{paid.tracking_token}")
    assert "Paid" in html and "Balance due" not in html
    legacy = order_from(place(staff_client))
    legacy.payment_arrangement = None
    db.session.commit()
    untracked = page(anon_client, f"/track/{legacy.tracking_token}")
    assert "<span>Payment</span>" not in untracked and "Balance due" not in untracked
    assert "<span>Payment</span>" in html


# ----------------------------------------------------------------------------- the whole shop workflow
def test_complete_workflow_from_order_to_final_payment(staff_client, admin_client, pay):
    # 1-2. staff records the order and the payment arrangement; the server prices it
    preview = quote(staff_client, {"arrangement": "partial", "entries": [{"method": "cash", "amount": "60"}]})
    assert preview["ok"] and preview["payment"]["balance"] == "\u20b1100.00"
    # 3-4. confirm -> order exists with its payment; printable stub is available
    resp = place(staff_client, PARTIAL_CASH, token="workflow-token-abcdef12", customer=new_customer())
    order = order_from(resp)
    assert order.payment_status == PaymentStatus.PARTIAL and order.received_at is None
    assert order.reference in page(staff_client, f"/orders/{order.reference}/stub")
    # 5. staff confirms the physical laundry was received: payment is untouched
    staff_client.post(f"/orders/{order.reference}/confirm-received")
    db.session.expire_all()
    order = db.session.get(Order, order.id)
    assert order.received_at is not None and order.payment_status == PaymentStatus.PARTIAL
    # later: customer settles the balance with GCash; history keeps both entries
    assert record(staff_client, order, [{"method": "gcash", "amount": "100", "reference": "GC-FINAL"}]).status_code == 200
    db.session.expire_all()
    order = db.session.get(Order, order.id)
    assert [(p.method_code, p.amount) for p in order.payments] == [("cash", Decimal("60.00")), ("gcash", Decimal("100.00"))]
    assert order.payment_status == PaymentStatus.PAID and order.status == "order_received"
    assert count(Order) == 1
    assert order.reference not in page(admin_client, "/payments/outstanding")      # settled: no longer outstanding
