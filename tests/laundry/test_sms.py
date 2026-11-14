"""SMS notification (UniSMS): consent, trigger, duplicate prevention, provider handling, refresh, retry, UI.
Every HTTP call is mocked; a fixture blocks the real network so a test can never send an SMS."""
import itertools
import logging
from datetime import timezone

import pytest
import requests

from app.extensions import db
from app.models import Order, OrderStatus, SMSNotification, SMSStatus
from app.orders import services as order_services
from app.sms import services as sms
from config import TestingConfig
from tests.laundry.conftest import _login, _make_app, svc

SECRET = "SECRET-KEY-VALUE-987"
_n = itertools.count(1)


# ----------------------------------------------------------------------------- fakes + fixtures
class FakeResponse:
    def __init__(self, code=201, body=None, bad_json=False):
        self.status_code, self._body, self._bad = code, body, bad_json

    def json(self):
        if self._bad:
            raise ValueError("not json")
        return self._body


def accepted(status="pending", ref="msg_test_1", reason=None):
    return FakeResponse(201, {"message": {"status": status, "reference_id": ref, "recipient": "+639171234567",
                                          "sender_id": "Unisoft", "fail_reason": reason}})


def status_reply(status="pending", ref="msg_test_1", reason=None):
    """What GET /sms/{reference_id} returns (HTTP 200, unlike the 201 of a send)."""
    return FakeResponse(200, {"message": {"status": status, "reference_id": ref, "fail_reason": reason}})


class HTTP:
    """Records every provider call; replies are scripted per test."""
    def __init__(self):
        self.calls, self.post_reply, self.get_reply = [], accepted(), status_reply()
        self.post_exc = self.get_exc = None
        self.on_post = None

    def post(self, url, json=None, auth=None, timeout=None):
        self.calls.append({"method": "POST", "url": url, "json": json, "auth": auth, "timeout": timeout})
        if self.on_post:
            self.on_post()
        if self.post_exc:
            raise self.post_exc
        return self.post_reply

    def get(self, url, auth=None, timeout=None):
        self.calls.append({"method": "GET", "url": url, "auth": auth, "timeout": timeout})
        if self.get_exc:
            raise self.get_exc
        return self.get_reply

    @property
    def posts(self):
        return [c for c in self.calls if c["method"] == "POST"]

    @property
    def gets(self):
        return [c for c in self.calls if c["method"] == "GET"]


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("A real HTTP request was attempted during a test.")
    monkeypatch.setattr("requests.sessions.Session.request", blocked)


@pytest.fixture()
def http(monkeypatch):
    h = HTTP()
    monkeypatch.setattr("requests.post", h.post)
    monkeypatch.setattr("requests.get", h.get)
    return h


@pytest.fixture()
def sms_on(app):
    # Explicit values so the tests do not depend on whatever a developer's .env contains.
    app.config.update(SMS_ENABLED=True, UNISMS_API_SECRET_KEY=SECRET, UNISMS_API_BASE_URL="https://unismsapi.com/api",
                      UNISMS_SENDER_ID="Unisoft", SMS_CONNECT_TIMEOUT=3.05, SMS_READ_TIMEOUT=10.0)


# ----------------------------------------------------------------------------- helpers
def make_order(client, consent=None, contact=None, name="Ana Cruz", customer=None):
    n = next(_n)
    body = {"items": [{"kind": "service", "id": svc("wash").id, "quantity": "2"}], "extras": [],
            "customer": customer or {"new": {"full_name": name, "contact_number": contact or f"0917{n:07d}"}}}
    if consent is not None:
        body["sms_consent"] = consent
    r = client.post("/orders/new/confirm", json=body)
    assert r.status_code == 200, r.get_json()
    ref = r.get_json()["redirect"].split("/")[2]
    return db.session.execute(db.select(Order).filter_by(reference=ref)).scalar_one()


def move(client, order, *statuses, note=None):
    for s in statuses:
        data = {"status": s}
        if note:
            data["note"] = note
        client.post(f"/orders/{order.reference}/status", data=data)
    db.session.expire_all()
    return db.session.get(Order, order.id)


READY_PATH = (OrderStatus.PENDING, OrderStatus.PROCESSING, OrderStatus.READY)


def ready_order(client, **kw):
    return move(client, make_order(client, **kw), *READY_PATH)


def notification(order):
    db.session.expire_all()
    return db.session.scalar(db.select(SMSNotification).filter_by(order_id=order.id))


def count_notifications():
    return db.session.scalar(db.select(db.func.count(SMSNotification.id)))


def retry(client, order):
    return client.post(f"/orders/{order.reference}/sms/retry", follow_redirects=True)


def refresh(client, order):
    return client.post(f"/orders/{order.reference}/sms/refresh", follow_redirects=True)


# ----------------------------------------------------------------------------- consent
def test_consent_unchecked_is_stored_as_false(staff_client, catalog):
    absent = make_order(staff_client)
    explicit = make_order(staff_client, consent=False)
    for order in (absent, explicit):
        assert order.sms_consent is False and order.sms_consent_at is None


def test_consent_checked_is_stored_with_a_timestamp(staff_client, catalog):
    order = make_order(staff_client, consent=True)
    assert order.sms_consent is True and order.sms_consent_at is not None
    age = order.sms_consent_at.replace(tzinfo=timezone.utc) - order.created_at.replace(tzinfo=timezone.utc)
    assert abs(age.total_seconds()) < 60


@pytest.mark.parametrize("bad", ["yes", "true", 1, 0, "on", [], {}])
def test_consent_must_be_a_real_boolean(staff_client, catalog, bad):
    r = staff_client.post("/orders/new/confirm", json={
        "items": [{"kind": "service", "id": svc("wash").id, "quantity": "1"}], "extras": [],
        "customer": {"new": {"full_name": "Ana", "contact_number": "09170000001"}}, "sms_consent": bad})
    assert r.status_code == 422 and "sms_consent" in r.get_json()["errors"]
    assert db.session.scalar(db.select(db.func.count(Order.id))) == 0


def test_an_existing_customers_earlier_consent_does_not_carry_over(staff_client, catalog):
    first = make_order(staff_client, consent=True, contact="09171110000")
    second = make_order(staff_client, customer={"id": first.customer_id})           # same customer, no checkbox
    third = make_order(staff_client, consent=True, customer={"id": first.customer_id})
    assert (first.sms_consent, second.sms_consent, third.sms_consent) == (True, False, True)
    assert second.customer_id == first.customer_id


def test_consent_works_for_new_and_existing_customers(staff_client, catalog):
    new = make_order(staff_client, consent=True, contact="09172220000")
    existing = make_order(staff_client, consent=True, customer={"id": new.customer_id})
    assert new.sms_consent and existing.sms_consent


# ----------------------------------------------------------------------------- trigger + duplicate prevention
def test_ready_for_pickup_creates_exactly_one_notification(staff_client, catalog):
    order = ready_order(staff_client, consent=True, contact="0917 123 4567")
    n = notification(order)
    assert count_notifications() == 1 and n.order_id == order.id
    assert (n.status, n.recipient, n.attempt_count, n.provider) == (SMSStatus.PENDING, "+639171234567", 0, "unisms")


def test_other_statuses_never_create_a_notification(staff_client, catalog):
    order = make_order(staff_client, consent=True)
    assert count_notifications() == 0
    move(staff_client, order, OrderStatus.PENDING)
    assert count_notifications() == 0
    move(staff_client, order, OrderStatus.PROCESSING)
    assert count_notifications() == 0
    move(staff_client, order, OrderStatus.READY)
    assert count_notifications() == 1
    move(staff_client, order, OrderStatus.RELEASED, OrderStatus.COMPLETED)
    assert count_notifications() == 1


def test_returning_to_ready_does_not_create_or_send_a_second_sms(staff_client, admin_client, catalog, sms_on, http):
    order = ready_order(staff_client, consent=True)
    assert len(http.posts) == 1
    move(admin_client, order, OrderStatus.PROCESSING, note="marked ready by mistake")      # admin may step back
    assert db.session.get(Order, order.id).status == OrderStatus.PROCESSING
    move(staff_client, order, OrderStatus.READY)
    assert db.session.get(Order, order.id).status == OrderStatus.READY
    assert count_notifications() == 1 and len(http.posts) == 1


def test_repeating_the_ready_request_cannot_duplicate(staff_client, catalog, sms_on, http):
    order = ready_order(staff_client, consent=True)
    for _ in range(3):
        staff_client.post(f"/orders/{order.reference}/status", data={"status": OrderStatus.READY})
    updated, error = order_services.change_status(order.id, OrderStatus.READY, order.created_by, None)
    assert error                                                                  # Ready -> Ready is not a transition
    assert count_notifications() == 1 and len(http.posts) == 1


def test_the_database_itself_refuses_a_second_notification_for_an_order(staff_client, catalog):
    from sqlalchemy.exc import IntegrityError
    order = ready_order(staff_client, consent=True)
    db.session.add(SMSNotification(order_id=order.id, status=SMSStatus.PENDING))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
    assert count_notifications() == 1


def test_no_consent_is_recorded_and_the_provider_is_never_called(staff_client, catalog, sms_on, http):
    order = ready_order(staff_client, consent=False)
    n = notification(order)
    assert n.status == SMSStatus.SKIPPED_NO_CONSENT and n.recipient is None and n.attempt_count == 0
    assert http.calls == []


def test_an_invalid_saved_number_is_recorded_and_the_provider_is_never_called(staff_client, catalog, sms_on, http):
    order = ready_order(staff_client, consent=True, contact="0281234567")          # a landline: fine for the order, not for SMS
    n = notification(order)
    assert n.status == SMSStatus.SKIPPED_INVALID_RECIPIENT and n.recipient is None
    assert http.calls == []


def test_sms_disabled_keeps_a_pending_record_and_sends_nothing(staff_client, catalog, http):
    order = ready_order(staff_client, consent=True)
    assert notification(order).status == SMSStatus.PENDING and http.calls == []
    assert order.status == OrderStatus.READY


def test_a_provider_outage_never_undoes_the_status_change(staff_client, catalog, sms_on, http):
    http.post_exc = requests.exceptions.ConnectionError("boom")
    order = ready_order(staff_client, consent=True)
    assert order.status == OrderStatus.READY                                       # the order change survives
    n = notification(order)
    assert n.status == SMSStatus.UNKNOWN and n.attempt_count == 1
    assert [h.to_status for h in order.history][-1] == OrderStatus.READY


def test_the_provider_is_contacted_only_after_the_order_change_is_committed(staff_client, catalog, sms_on, http):
    seen = {}

    def during_call():
        seen["clean_session"] = not db.session.new and not db.session.dirty
        seen["status"] = db.session.execute(db.select(Order.status)).scalar_one()
        n = db.session.scalar(db.select(SMSNotification))
        seen["claim"] = (n.status, n.attempt_count)
    http.on_post = during_call
    ready_order(staff_client, consent=True)
    assert seen == {"clean_session": True, "status": OrderStatus.READY, "claim": (SMSStatus.UNKNOWN, 1)}


# ----------------------------------------------------------------------------- the provider request
def test_the_unisms_request_is_exactly_as_documented(app, staff_client, catalog, sms_on, http):
    order = ready_order(staff_client, consent=True, contact="09171234567", name="Ana Cruz")
    (call,) = http.posts
    assert call["url"] == "https://unismsapi.com/api/sms"
    assert (call["auth"].username, call["auth"].password) == (SECRET, "")          # Basic auth, empty password
    assert call["timeout"] == (3.05, 10.0)                                       # (connect, read) from configuration
    assert call["json"] == {
        "recipient": "+639171234567", "sender_id": "Unisoft",
        "content": f"Wash Up! Laundry Shop: Hi Ana Cruz, your laundry order {order.reference} is ready for pickup. "
                   "Please present your order stub when claiming. Thank you.",
        "metadata": {"order_id": str(order.id), "template": "ready_for_pickup"},
    }
    assert set(call["json"]) == {"recipient", "content", "sender_id", "metadata"}      # no undocumented fields


def test_the_message_uses_the_order_time_snapshot_not_the_current_customer(staff_client, catalog, sms_on, http):
    order = make_order(staff_client, consent=True, contact="09171234567", name="Ana Cruz")
    order.customer.contact_number, order.customer.contact_normalized, order.customer.full_name = "09990000000", "09990000000", "Someone Else"
    db.session.commit()
    move(staff_client, order, *READY_PATH)
    (call,) = http.posts
    assert call["json"]["recipient"] == "+639171234567" and "Ana Cruz" in call["json"]["content"]
    assert "Someone Else" not in call["json"]["content"]


def test_the_message_carries_no_private_details(staff_client, catalog, sms_on, http):
    ready_order(staff_client, consent=True)
    content = http.posts[0]["json"]["content"]
    for private in ("\u20b1", "PHP", "total", "paid", "balance", "payment", "@"):
        assert private.lower() not in content.lower(), private


def test_http_201_pending_means_queued_not_delivered(staff_client, catalog, sms_on, http):
    http.post_reply = accepted("pending", "msg_abc123")
    order = ready_order(staff_client, consent=True)
    n = notification(order)
    assert (n.status, n.provider_message_id, n.attempt_count, n.last_error) == (SMSStatus.QUEUED, "msg_abc123", 1, None)
    assert n.accepted_at is not None and n.provider_sent_at is None


@pytest.mark.parametrize("provider_status,internal", [("retrying", SMSStatus.RETRYING), ("sent", SMSStatus.SENT), ("failed", SMSStatus.FAILED)])
def test_other_statuses_in_the_send_reply_are_mapped(staff_client, catalog, sms_on, http, provider_status, internal):
    http.post_reply = accepted(provider_status, "msg_x", reason="Carrier rejected +639171234567")
    n = notification(ready_order(staff_client, consent=True))
    assert n.status == internal and n.provider_message_id == "msg_x"
    if internal == SMSStatus.FAILED:
        assert "639171234567" not in n.last_error                                  # numbers are scrubbed from stored errors


@pytest.mark.parametrize("reply,exc,expected", [
    (FakeResponse(401, {"message": "Unauthorized"}), None, SMSStatus.FAILED),
    (FakeResponse(403, {}), None, SMSStatus.FAILED),
    (FakeResponse(402, {}), None, SMSStatus.FAILED),
    (FakeResponse(422, {"message": "Invalid recipient"}), None, SMSStatus.FAILED),
    (FakeResponse(429, {}), None, SMSStatus.FAILED),
    (FakeResponse(500, {}), None, SMSStatus.UNKNOWN),
    (FakeResponse(503, {}), None, SMSStatus.UNKNOWN),
    (FakeResponse(201, None, bad_json=True), None, SMSStatus.UNKNOWN),
    (FakeResponse(201, {"unexpected": True}), None, SMSStatus.UNKNOWN),
    (None, requests.exceptions.ReadTimeout(), SMSStatus.UNKNOWN),
    (None, requests.exceptions.ConnectTimeout(), SMSStatus.UNKNOWN),
    (None, requests.exceptions.ConnectionError(), SMSStatus.UNKNOWN),
])
def test_provider_errors_are_classified_safely(staff_client, catalog, sms_on, http, reply, exc, expected):
    http.post_reply, http.post_exc = reply, exc
    order = ready_order(staff_client, consent=True)
    n = notification(order)
    assert n.status == expected and n.attempt_count == 1 and n.last_error
    assert order.status == OrderStatus.READY
    assert len(http.posts) == 1                                                     # never retried automatically


def test_the_secret_never_appears_in_logs_pages_or_stored_errors(staff_client, admin_client, catalog, sms_on, http, caplog):
    http.post_reply = FakeResponse(422, {"message": f"bad key {SECRET} for +639171234567"})
    with caplog.at_level(logging.DEBUG):
        order = ready_order(staff_client, consent=True, contact="09171234567")
        page = admin_client.get(f"/orders/{order.reference}").get_data(as_text=True)
    n = notification(order)
    assert SECRET not in caplog.text and SECRET not in page and SECRET not in (n.last_error or "")
    assert "+639171234567" not in caplog.text and "Wash Up! Laundry Shop" not in caplog.text    # no numbers or message bodies
    http.post_exc = requests.exceptions.ConnectionError(SECRET)
    n.status, n.attempt_count = SMSStatus.FAILED, 1
    db.session.commit()
    retry(admin_client, order)
    assert SECRET not in caplog.text and SECRET not in (notification(order).last_error or "")


# ----------------------------------------------------------------------------- status refresh
@pytest.mark.parametrize("provider_status,internal", [("pending", SMSStatus.QUEUED), ("retrying", SMSStatus.RETRYING),
                                                      ("sent", SMSStatus.SENT), ("failed", SMSStatus.FAILED)])
def test_refresh_maps_every_documented_provider_status(staff_client, catalog, sms_on, http, provider_status, internal):
    order = ready_order(staff_client, consent=True)
    http.get_reply = status_reply(provider_status, "msg_test_1", reason="Number unreachable")
    r = refresh(staff_client, order)
    n = notification(order)
    assert r.status_code == 200 and n.status == internal and n.provider_message_id == "msg_test_1"
    assert len(http.posts) == 1                                                      # a refresh never sends another SMS
    (get,) = http.gets
    assert get["url"] == "https://unismsapi.com/api/sms/msg_test_1" and (get["auth"].username, get["auth"].password) == (SECRET, "")
    assert (n.provider_sent_at is not None) == (internal == SMSStatus.SENT)


def test_a_refresh_can_resolve_an_unknown_outcome_when_a_reference_exists(staff_client, catalog, sms_on, http):
    order = ready_order(staff_client, consent=True)
    n = notification(order)
    n.status, n.last_error = SMSStatus.UNKNOWN, "unclear"
    db.session.commit()
    http.get_reply = status_reply("sent", "msg_test_1")
    refresh(staff_client, order)
    assert notification(order).status == SMSStatus.SENT


def test_refresh_without_a_reference_does_nothing(staff_client, catalog, sms_on, http):
    http.post_exc = requests.exceptions.ReadTimeout()
    order = ready_order(staff_client, consent=True)
    assert notification(order).provider_message_id is None
    r = refresh(staff_client, order)
    assert b"nothing to refresh" in r.data and http.gets == [] and len(http.posts) == 1


@pytest.mark.parametrize("reply,exc", [(FakeResponse(500, {}), None), (FakeResponse(404, {}), None),
                                       (FakeResponse(401, {}), None), (None, requests.exceptions.ConnectionError())])
def test_refresh_survives_provider_downtime_without_changing_anything(staff_client, catalog, sms_on, http, reply, exc):
    order = ready_order(staff_client, consent=True)
    http.get_reply, http.get_exc = reply, exc
    r = refresh(staff_client, order)
    assert r.status_code == 200 and notification(order).status == SMSStatus.QUEUED
    assert staff_client.get(f"/orders/{order.reference}").status_code == 200       # the page itself never calls the provider


def test_final_statuses_are_not_refreshed(staff_client, catalog, sms_on, http):
    http.post_reply = accepted("sent", "msg_done")
    order = ready_order(staff_client, consent=True)
    r = refresh(staff_client, order)
    assert b"final" in r.data and http.gets == []


def test_viewing_pages_never_polls_the_provider(staff_client, admin_client, catalog, sms_on, http):
    order = ready_order(staff_client, consent=True)
    for _ in range(3):
        staff_client.get(f"/orders/{order.reference}")
        admin_client.get("/orders/")
    assert http.gets == [] and len(http.posts) == 1


# ----------------------------------------------------------------------------- manual retry
def failed_order(staff_client, http, **kw):
    http.post_reply = FakeResponse(401, {"message": "Unauthorized"})
    order = ready_order(staff_client, consent=True, **kw)
    assert notification(order).status == SMSStatus.FAILED
    return order


def test_staff_can_retry_a_definite_failure_once_fixed(staff_client, catalog, sms_on, http):
    order = failed_order(staff_client, http)
    http.post_reply = accepted("pending", "msg_retry")
    r = retry(staff_client, order)
    n = notification(order)
    assert r.status_code == 200 and (n.status, n.attempt_count, n.provider_message_id) == (SMSStatus.QUEUED, 2, "msg_retry")
    assert count_notifications() == 1 and len(http.posts) == 2


def test_admins_can_retry_too(admin_client, staff_client, catalog, sms_on, http):
    order = failed_order(staff_client, http)
    http.post_reply = accepted()
    retry(admin_client, order)
    assert notification(order).status == SMSStatus.QUEUED


def test_anonymous_visitors_cannot_trigger_or_refresh_anything(anon_client, staff_client, catalog, sms_on, http):
    order = failed_order(staff_client, http)
    assert anon_client.post(f"/orders/{order.reference}/sms/retry").status_code == 302
    assert anon_client.post(f"/orders/{order.reference}/sms/refresh").status_code == 302
    assert len(http.posts) == 1 and http.gets == [] and notification(order).attempt_count == 1


def test_public_tracking_pages_expose_no_sms_actions(anon_client, staff_client, catalog, sms_on, http):
    order = ready_order(staff_client, consent=True)
    page = anon_client.get(f"/track/{order.tracking_token}").get_data(as_text=True)
    assert "sms" not in page.lower() and "msg_test_1" not in page


def test_csrf_is_enforced_on_the_new_sms_routes():
    class CsrfOn(TestingConfig):
        WTF_CSRF_ENABLED = True
    app = _make_app(CsrfOn)
    with app.app_context():
        db.create_all()
        from app.models import Role, User
        user = User(email="s@example.com", role=Role.STAFF, is_active=True)
        db.session.add(user)
        db.session.commit()
        c = app.test_client()
        _login(c, user)
        assert c.post("/orders/LX-X/sms/retry").status_code == 400
        assert c.post("/orders/LX-X/sms/refresh").status_code == 400
        db.session.remove()
        db.drop_all()


def test_an_unknown_outcome_is_never_blindly_retried(staff_client, catalog, sms_on, http):
    http.post_exc = requests.exceptions.ReadTimeout()
    order = ready_order(staff_client, consent=True)
    assert notification(order).status == SMSStatus.UNKNOWN
    http.post_exc, http.post_reply = None, accepted()
    r = retry(staff_client, order)
    assert b"never retried automatically" in r.data
    assert len(http.posts) == 1 and notification(order).attempt_count == 1 and notification(order).status == SMSStatus.UNKNOWN


@pytest.mark.parametrize("status", [SMSStatus.SENT, SMSStatus.QUEUED, SMSStatus.RETRYING,
                                    SMSStatus.SKIPPED_NO_CONSENT, SMSStatus.SKIPPED_INVALID_RECIPIENT])
def test_only_failed_or_never_submitted_notifications_can_be_retried(staff_client, catalog, sms_on, http, status):
    order = ready_order(staff_client, consent=True)
    http.calls.clear()
    n = notification(order)
    n.status = status
    db.session.commit()
    retry(staff_client, order)
    assert http.posts == [] and notification(order).status == status


def test_retry_needs_consent_a_valid_number_and_an_enabled_service(app, staff_client, catalog, sms_on, http):
    order = failed_order(staff_client, http)
    http.post_reply = accepted()
    order.sms_consent = False
    db.session.commit()
    assert b"did not consent" in retry(staff_client, order).data
    order.sms_consent, order.customer_contact = True, "12345"
    db.session.commit()
    assert b"not a valid Philippine mobile number" in retry(staff_client, order).data
    order.customer_contact = "09171234567"
    db.session.commit()
    app.config["SMS_ENABLED"] = False
    assert b"disabled" in retry(staff_client, order).data
    assert len(http.posts) == 1                                                      # none of the refusals reached the provider
    app.config["SMS_ENABLED"] = True
    retry(staff_client, order)
    assert len(http.posts) == 2 and notification(order).status == SMSStatus.QUEUED


def test_a_pending_notification_can_be_sent_manually_once_sms_is_enabled(app, staff_client, catalog, http):
    order = ready_order(staff_client, consent=True)                                  # SMS still disabled
    assert notification(order).status == SMSStatus.PENDING and http.calls == []
    app.config.update(SMS_ENABLED=True, UNISMS_API_SECRET_KEY=SECRET)
    retry(staff_client, order)
    n = notification(order)
    assert n.status == SMSStatus.QUEUED and n.attempt_count == 1 and count_notifications() == 1


def test_a_retry_only_acts_on_the_order_in_the_url(staff_client, catalog, sms_on, http):
    a = failed_order(staff_client, http)
    b = failed_order(staff_client, http)
    http.post_reply = accepted("pending", "msg_for_a")
    retry(staff_client, a)
    assert (notification(a).status, notification(b).status) == (SMSStatus.QUEUED, SMSStatus.FAILED)
    assert staff_client.post("/orders/LX-NOPE/sms/retry").status_code == 404
    assert staff_client.post("/orders/LX-NOPE/sms/refresh").status_code == 404


def test_a_second_submission_during_the_first_is_refused(staff_client, catalog, sms_on, http):
    order = make_order(staff_client, consent=True)
    inner = {}

    def concurrent_attempt():
        n = db.session.scalar(db.select(SMSNotification))
        inner["result"] = sms.submit_notification(n.id)
    http.on_post = concurrent_attempt
    move(staff_client, order, *READY_PATH)
    assert len(http.posts) == 1 and inner["result"].ok is False
    assert "unknown" in inner["result"].message.lower()
    assert notification(order).attempt_count == 1


def test_nothing_is_ever_retried_automatically(staff_client, admin_client, catalog, sms_on, http):
    order = failed_order(staff_client, http)
    for _ in range(3):
        staff_client.get(f"/orders/{order.reference}")
        refresh(staff_client, order)
        move(staff_client, order, OrderStatus.RELEASED)
        admin_client.get("/payments/outstanding")
    assert len(http.posts) == 1 and notification(order).attempt_count == 1


# ----------------------------------------------------------------------------- the order page
def test_the_order_page_shows_the_sms_card_without_the_full_number(staff_client, admin_client, catalog, sms_on, http):
    http.post_reply = accepted("pending", "msg_card_1")
    order = ready_order(staff_client, consent=True, contact="09171234567")
    for client in (staff_client, admin_client):
        page = client.get(f"/orders/{order.reference}").get_data(as_text=True)
        for text in ("SMS Notification", "Queued", "+63917\u2022\u2022\u20224567", "msg_card_1", "Customer consent", "Refresh status"):
            assert text in page, text
        assert "+639171234567" not in page                                           # the full E.164 number is never shown
        assert "Retry SMS" not in page and "Delivered" not in page


@pytest.mark.parametrize("status,label", [
    (SMSStatus.PENDING, "Pending"), (SMSStatus.QUEUED, "Queued"), (SMSStatus.RETRYING, "Retrying"),
    (SMSStatus.SENT, "Sent by provider"), (SMSStatus.FAILED, "Failed"), (SMSStatus.UNKNOWN, "Outcome unknown"),
    (SMSStatus.SKIPPED_NO_CONSENT, "Skipped \u2014 no consent"), (SMSStatus.SKIPPED_INVALID_RECIPIENT, "Skipped \u2014 invalid number"),
])
def test_every_status_has_an_accurate_label(staff_client, catalog, sms_on, http, status, label):
    order = ready_order(staff_client, consent=True)
    n = notification(order)
    n.status = status
    db.session.commit()
    page = staff_client.get(f"/orders/{order.reference}").get_data(as_text=True)
    assert label in page
    if status == SMSStatus.SENT:
        assert "does not confirm" in page and "delivered" not in page.lower()


def test_action_buttons_appear_only_when_they_are_allowed(staff_client, catalog, sms_on, http):
    order = failed_order(staff_client, http)
    page = staff_client.get(f"/orders/{order.reference}").get_data(as_text=True)
    assert "Retry SMS" in page and "Refresh status" not in page                      # failed, no reference: retry only
    n = notification(order)
    n.status, n.provider_message_id = SMSStatus.UNKNOWN, "msg_u1"
    db.session.commit()
    page = staff_client.get(f"/orders/{order.reference}").get_data(as_text=True)
    assert "Retry SMS" not in page and "Send SMS" not in page and "Refresh status" in page and "never retried automatically" in page


def test_the_card_before_ready_explains_what_will_happen(staff_client, catalog):
    yes = make_order(staff_client, consent=True)
    no = make_order(staff_client)
    assert "will be prepared when this order is first marked Ready" in staff_client.get(f"/orders/{yes.reference}").get_data(as_text=True)
    assert "did not ask for an SMS" in staff_client.get(f"/orders/{no.reference}").get_data(as_text=True)


def test_the_wizard_has_an_unchecked_optional_consent_checkbox_wired_to_the_payload(staff_client, catalog):
    page = staff_client.get("/orders/new").get_data(as_text=True)
    assert "I agree to receive an SMS notification when this laundry order is ready for pickup." in page
    box = page[page.index('id="sms-consent"') - 40: page.index('id="sms-consent"') + 80]
    assert "checked" not in box and "required" not in box
    js = staff_client.get("/orders/assets/js/order_wizard.js").get_data(as_text=True)
    assert "sms_consent" in js and "sms-consent" in js


# ----------------------------------------------------------------------------- regression
def test_existing_order_flow_totals_history_and_tracking_are_unchanged(staff_client, anon_client, catalog):
    order = ready_order(staff_client)                                                # no consent: nothing is sent
    assert str(order.total) == "160.00" and order.status == OrderStatus.READY
    assert [h.to_status for h in order.history] == [OrderStatus.RECEIVED, *READY_PATH]
    assert anon_client.get(f"/track/{order.tracking_token}").status_code == 200
